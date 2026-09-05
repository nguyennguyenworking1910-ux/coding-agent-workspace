"""Tests for pure Merchant document signing planning."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from claude.agents.tools.merchant.signing_engine import (
    DocumentAlreadySignedError,
    DocumentSigningConflictError,
    DocumentSigningError,
    DocumentSigningGateError,
    DocumentSigningLifecycleClosedError,
    DocumentSigningPlan,
    propose_document_signing,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
OTHER_PROJECT_ID = (
    "00000000-0000-0000-0000-000000000003"
)
REVISION_1_ID = (
    "00000000-0000-0000-0000-000000000004"
)
REVISION_2_ID = (
    "00000000-0000-0000-0000-000000000005"
)
SIGNED_BY = "00000000-0000-0000-0000-000000000006"

SIGNED_AT = datetime(
    2026,
    9,
    5,
    11,
    0,
    tzinfo=timezone.utc,
)
SENSITIVE_CONTENT_HASH = "sensitive-document-hash"
SENSITIVE_PR_NUMBER = "JRA-SENSITIVE-12345"
SENSITIVE_APPROVAL_NOTES = "Private approval notes"


def project_record(
    *,
    status="IN_PROGRESS",
    requires_procurement=False,
):
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "status": status,
        "requires_procurement": requires_procurement,
        "title": "Sensitive project title",
    }


def revision_record(
    *,
    revision_id=REVISION_1_ID,
    project_id=PROJECT_ID,
    document_type="MERCHANT_AGREEMENT",
    revision_number=1,
    signed=False,
    signed_at=None,
    superseded_by=None,
):
    return {
        "id": revision_id,
        "project_id": project_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "content_hash": SENSITIVE_CONTENT_HASH,
        "signed": signed,
        "signed_at": signed_at,
        "superseded_by": superseded_by,
    }


def approval_record(
    role,
    *,
    revision_id=REVISION_1_ID,
    status="APPROVED",
    approved_at=SIGNED_AT,
):
    return {
        "id": f"approval-{role.lower()}",
        "document_revision_id": revision_id,
        "approver_role": role,
        "approval_status": status,
        "approved_at": approved_at,
        "notes": SENSITIVE_APPROVAL_NOTES,
    }


def all_approvals(*, revision_id=REVISION_1_ID):
    return [
        approval_record(
            role,
            revision_id=revision_id,
        )
        for role in ("LEGAL", "ACCOUNTING", "PARTNER")
    ]


def purchase_request(*, external_id=SENSITIVE_PR_NUMBER):
    return {
        "id": "purchase-request-1",
        "project_id": PROJECT_ID,
        "procurement_type": "PURCHASE_REQUEST",
        "external_id": external_id,
        "status": "CREATED",
        "version": 1,
    }


def snapshot(
    *,
    project=None,
    revisions=None,
    approvals=None,
    procurement_records=(),
):
    return {
        "project": (
            project
            if project is not None
            else project_record()
        ),
        "document_revisions": list(
            revisions
            if revisions is not None
            else [revision_record()]
        ),
        "document_approvals": list(
            approvals
            if approvals is not None
            else all_approvals()
        ),
        "procurement_records": list(
            procurement_records
        ),
    }


def propose(
    *,
    state=None,
    revision_id=REVISION_1_ID,
    occurred_at=SIGNED_AT,
    signed_by=SIGNED_BY,
):
    return propose_document_signing(
        state if state is not None else snapshot(),
        document_revision_id=revision_id,
        occurred_at=occurred_at,
        signed_by=signed_by,
    )


class SigningEngineTests(unittest.TestCase):
    def test_complete_evidence_allows_signing(self):
        plan = propose()

        self.assertIsInstance(
            plan,
            DocumentSigningPlan,
        )
        self.assertEqual(plan.merchant_id, MERCHANT_ID)
        self.assertEqual(plan.project_id, PROJECT_ID)
        self.assertEqual(
            plan.document_revision_id,
            REVISION_1_ID,
        )
        self.assertEqual(
            plan.document_type,
            "MERCHANT_AGREEMENT",
        )
        self.assertEqual(plan.revision_number, 1)
        self.assertEqual(plan.signed_at, SIGNED_AT)
        self.assertEqual(plan.signed_by, SIGNED_BY)
        self.assertEqual(plan.event_type, "DOCUMENT_SIGNED")

    def test_required_purchase_request_allows_signing(self):
        plan = propose(
            state=snapshot(
                project=project_record(
                    requires_procurement=True
                ),
                procurement_records=[
                    purchase_request()
                ],
            )
        )

        self.assertEqual(plan.event_type, "DOCUMENT_SIGNED")

    def test_missing_approvals_block_signing(self):
        approval_sets = (
            [],
            [approval_record("LEGAL")],
            [
                approval_record("LEGAL"),
                approval_record("ACCOUNTING"),
            ],
        )

        for approvals in approval_sets:
            with self.subTest(approvals=approvals):
                with self.assertRaises(
                    DocumentSigningGateError
                ) as context:
                    propose(
                        state=snapshot(
                            approvals=approvals
                        )
                    )

                self.assertIn(
                    "MISSING_REQUIRED_APPROVALS",
                    context.exception.gate_result
                    .blocking_codes,
                )

    def test_nonapproved_decision_blocks_signing(self):
        for status in ("PENDING", "REJECTED"):
            with self.subTest(status=status):
                approvals = all_approvals()
                approvals[0] = approval_record(
                    "LEGAL",
                    status=status,
                    approved_at=None,
                )

                with self.assertRaises(
                    DocumentSigningGateError
                ):
                    propose(
                        state=snapshot(
                            approvals=approvals
                        )
                    )

    def test_old_revision_approvals_do_not_allow_signing(self):
        revisions = [
            revision_record(
                superseded_by=REVISION_2_ID,
            ),
            revision_record(
                revision_id=REVISION_2_ID,
                revision_number=2,
            ),
        ]

        with self.assertRaises(
            DocumentSigningGateError
        ) as context:
            propose(
                state=snapshot(
                    revisions=revisions,
                    approvals=all_approvals(),
                ),
                revision_id=REVISION_2_ID,
            )

        self.assertEqual(
            context.exception.gate_result.missing_roles,
            ("LEGAL", "ACCOUNTING", "PARTNER"),
        )

    def test_missing_required_pr_blocks_signing(self):
        with self.assertRaises(
            DocumentSigningGateError
        ) as context:
            propose(
                state=snapshot(
                    project=project_record(
                        requires_procurement=True
                    ),
                )
            )

        self.assertIn(
            "MISSING_PURCHASE_REQUEST",
            context.exception.gate_result.blocking_codes,
        )

    def test_blank_pr_number_does_not_allow_signing(self):
        with self.assertRaises(
            DocumentSigningGateError
        ):
            propose(
                state=snapshot(
                    project=project_record(
                        requires_procurement=True
                    ),
                    procurement_records=[
                        purchase_request(external_id=" ")
                    ],
                )
            )

    def test_only_latest_active_revision_can_be_signed(self):
        revisions = [
            revision_record(
                superseded_by=REVISION_2_ID,
            ),
            revision_record(
                revision_id=REVISION_2_ID,
                revision_number=2,
            ),
        ]

        with self.assertRaises(
            DocumentSigningLifecycleClosedError
        ):
            propose(
                state=snapshot(revisions=revisions),
                revision_id=REVISION_1_ID,
            )

    def test_active_revision_must_have_highest_number(self):
        revisions = [
            revision_record(),
            revision_record(
                revision_id=REVISION_2_ID,
                revision_number=2,
                superseded_by=REVISION_1_ID,
            ),
        ]

        with self.assertRaisesRegex(
            DocumentSigningConflictError,
            "not the latest revision number",
        ):
            propose(
                state=snapshot(revisions=revisions)
            )

    def test_already_signed_revision_is_rejected(self):
        with self.assertRaises(
            DocumentAlreadySignedError
        ):
            propose(
                state=snapshot(
                    revisions=[
                        revision_record(
                            signed=True,
                            signed_at=SIGNED_AT,
                        )
                    ]
                )
            )

    def test_signing_state_consistency_is_validated(self):
        invalid_revisions = (
            revision_record(
                signed=True,
                signed_at=None,
            ),
            revision_record(
                signed=False,
                signed_at=SIGNED_AT,
            ),
            revision_record(
                signed=None,
                signed_at=None,
            ),
        )

        for revision in invalid_revisions:
            with self.subTest(revision=revision):
                with self.assertRaises(
                    DocumentSigningConflictError
                ):
                    propose(
                        state=snapshot(
                            revisions=[revision]
                        )
                    )

    def test_invalid_gate_evidence_is_a_signing_conflict(self):
        approvals = all_approvals()
        approvals.append(approval_record("LEGAL"))

        with self.assertRaisesRegex(
            DocumentSigningConflictError,
            "invalid gate evidence",
        ):
            propose(
                state=snapshot(approvals=approvals)
            )

    def test_terminal_project_rejects_signing(self):
        for status in ("COMPLETED", "CANCELLED"):
            with self.subTest(status=status):
                with self.assertRaises(
                    DocumentSigningLifecycleClosedError
                ):
                    propose(
                        state=snapshot(
                            project=project_record(
                                status=status
                            )
                        )
                    )

    def test_revision_snapshot_consistency_is_validated(self):
        invalid_revision_sets = (
            [
                revision_record(
                    project_id=OTHER_PROJECT_ID
                )
            ],
            [
                revision_record(),
                revision_record(),
            ],
            [
                revision_record(),
                revision_record(
                    revision_id=REVISION_2_ID,
                ),
            ],
        )

        for revisions in invalid_revision_sets:
            with self.subTest(revisions=revisions):
                with self.assertRaises(
                    DocumentSigningConflictError
                ):
                    propose(
                        state=snapshot(
                            revisions=revisions
                        )
                    )

    def test_multiple_document_types_are_targeted_safely(self):
        revisions = [
            revision_record(),
            revision_record(
                revision_id=REVISION_2_ID,
                document_type="DATA_PROCESSING_ADDENDUM",
            ),
        ]

        plan = propose(
            state=snapshot(revisions=revisions)
        )
        self.assertEqual(
            plan.document_type,
            "MERCHANT_AGREEMENT",
        )

    def test_identifiers_are_validated(self):
        invalid_calls = (
            {
                "revision_id": "not-a-uuid",
            },
            {
                "signed_by": "not-a-uuid",
            },
        )

        for arguments in invalid_calls:
            with self.subTest(arguments=arguments):
                with self.assertRaises(
                    DocumentSigningError
                ):
                    propose(**arguments)

    def test_signing_time_is_normalized_to_utc(self):
        offset = timezone(timedelta(hours=7))
        local_time = datetime(
            2026,
            9,
            5,
            18,
            0,
            tzinfo=offset,
        )
        naive_time = datetime(2026, 9, 5, 11, 0)

        offset_plan = propose(occurred_at=local_time)
        naive_plan = propose(occurred_at=naive_time)

        self.assertEqual(offset_plan.signed_at, SIGNED_AT)
        self.assertEqual(naive_plan.signed_at, SIGNED_AT)

        with self.assertRaisesRegex(
            DocumentSigningError,
            "occurred_at must be a datetime",
        ):
            propose(occurred_at="2026-09-05")

    def test_audit_payload_is_redacted(self):
        plan = propose()
        encoded = json.dumps(
            {
                "change_summary": plan.change_summary,
                "old_values": plan.old_values,
                "new_values": plan.new_values,
            }
        )

        sensitive_values = (
            SENSITIVE_CONTENT_HASH,
            SENSITIVE_PR_NUMBER,
            SENSITIVE_APPROVAL_NOTES,
            SIGNED_BY,
            REVISION_1_ID,
        )

        for sensitive_value in sensitive_values:
            self.assertNotIn(sensitive_value, encoded)

        self.assertEqual(
            set(plan.old_values),
            {
                "document_type",
                "revision_number",
                "signed",
                "signed_at_recorded",
            },
        )
        self.assertEqual(
            set(plan.new_values),
            set(plan.old_values),
        )

    def test_plan_is_frozen_and_json_compatible(self):
        plan = propose()

        with self.assertRaises(FrozenInstanceError):
            plan.signed_at = SIGNED_AT

        payload = plan.to_dict()
        self.assertEqual(
            payload["signed_at"],
            SIGNED_AT.isoformat(),
        )
        self.assertEqual(
            json.loads(json.dumps(payload)),
            payload,
        )


if __name__ == "__main__":
    unittest.main()
