"""Tests for pure Merchant document approval planning."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from claude.agents.tools.merchant.approval_engine import (
    ApprovalConflictError,
    ApprovalEngineError,
    ApprovalFinalizedError,
    ApprovalLifecycleClosedError,
    ApprovalMutationPlan,
    ApprovalRevisionNotActiveError,
    propose_document_approval,
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
APPROVAL_1_ID = (
    "00000000-0000-0000-0000-000000000006"
)
APPROVAL_2_ID = (
    "00000000-0000-0000-0000-000000000007"
)
ACTED_BY = "00000000-0000-0000-0000-000000000008"

OCCURRED_AT = datetime(
    2026,
    9,
    4,
    11,
    30,
    tzinfo=timezone.utc,
)
SENSITIVE_NOTES = "Private legal review notes"


def project_record(*, status="IN_PROGRESS"):
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "status": status,
        "title": "Sensitive project title",
    }


def revision_record(
    *,
    revision_id=REVISION_1_ID,
    project_id=PROJECT_ID,
    document_type="MERCHANT_AGREEMENT",
    revision_number=1,
    content_hash="sensitive-document-hash",
    signed=False,
    superseded_by=None,
):
    return {
        "id": revision_id,
        "project_id": project_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "content_hash": content_hash,
        "signed": signed,
        "superseded_by": superseded_by,
    }


def approval_record(
    *,
    approval_id=APPROVAL_1_ID,
    revision_id=REVISION_1_ID,
    role="LEGAL",
    status="PENDING",
    approved_at=None,
    approved_by=None,
    notes=None,
):
    return {
        "id": approval_id,
        "document_revision_id": revision_id,
        "approver_role": role,
        "approval_status": status,
        "approved_at": approved_at,
        "approved_by": approved_by,
        "notes": notes,
    }


def snapshot(
    *,
    project=None,
    revisions=None,
    approvals=(),
):
    return {
        "project": (
            project
            if project is not None
            else project_record()
        ),
        "revisions": list(
            revisions
            if revisions is not None
            else [revision_record()]
        ),
        "approvals": list(approvals),
    }


def propose(
    *,
    state=None,
    document_revision_id=REVISION_1_ID,
    approval_id=APPROVAL_1_ID,
    role="legal",
    status="pending",
    expected_status=None,
    occurred_at=OCCURRED_AT,
    acted_by=ACTED_BY,
    notes=SENSITIVE_NOTES,
):
    return propose_document_approval(
        state if state is not None else snapshot(),
        document_revision_id=document_revision_id,
        approval_id=approval_id,
        approver_role=role,
        approval_status=status,
        expected_status=expected_status,
        occurred_at=occurred_at,
        acted_by=acted_by,
        notes=notes,
    )


class ApprovalEngineTests(unittest.TestCase):
    def test_new_pending_approval_is_planned(self):
        plan = propose()

        self.assertIsInstance(
            plan,
            ApprovalMutationPlan,
        )
        self.assertEqual(plan.merchant_id, MERCHANT_ID)
        self.assertEqual(plan.project_id, PROJECT_ID)
        self.assertEqual(
            plan.document_revision_id,
            REVISION_1_ID,
        )
        self.assertEqual(plan.approval_id, APPROVAL_1_ID)
        self.assertEqual(
            plan.document_type,
            "MERCHANT_AGREEMENT",
        )
        self.assertEqual(plan.revision_number, 1)
        self.assertEqual(plan.approver_role, "LEGAL")
        self.assertIsNone(plan.current_status)
        self.assertEqual(plan.target_status, "PENDING")
        self.assertEqual(plan.operation, "INSERT")
        self.assertIsNone(plan.approved_at)
        self.assertIsNone(plan.approved_by)
        self.assertEqual(plan.triggered_by, ACTED_BY)
        self.assertEqual(
            plan.event_type,
            "DOCUMENT_APPROVAL_REQUESTED",
        )

    def test_new_approval_may_be_directly_approved(self):
        plan = propose(status="approved")

        self.assertEqual(plan.target_status, "APPROVED")
        self.assertEqual(plan.approved_at, OCCURRED_AT)
        self.assertEqual(plan.approved_by, ACTED_BY)
        self.assertEqual(
            plan.event_type,
            "DOCUMENT_APPROVED",
        )

    def test_new_approval_may_be_directly_rejected(self):
        plan = propose(status="rejected")

        self.assertEqual(plan.target_status, "REJECTED")
        self.assertIsNone(plan.approved_at)
        self.assertIsNone(plan.approved_by)
        self.assertEqual(
            plan.event_type,
            "DOCUMENT_REJECTED",
        )

    def test_pending_approval_can_be_approved(self):
        plan = propose(
            state=snapshot(
                approvals=[approval_record()]
            ),
            approval_id=APPROVAL_2_ID,
            status="APPROVED",
            expected_status="PENDING",
        )

        self.assertEqual(plan.operation, "UPDATE")
        self.assertEqual(plan.approval_id, APPROVAL_1_ID)
        self.assertEqual(plan.current_status, "PENDING")
        self.assertEqual(plan.target_status, "APPROVED")

    def test_pending_approval_can_be_rejected(self):
        plan = propose(
            state=snapshot(
                approvals=[approval_record()]
            ),
            status="REJECTED",
            expected_status="PENDING",
        )

        self.assertEqual(plan.operation, "UPDATE")
        self.assertEqual(plan.current_status, "PENDING")
        self.assertEqual(plan.target_status, "REJECTED")
        self.assertIsNone(plan.approved_at)
        self.assertIsNone(plan.approved_by)

    def test_existing_approval_requires_expected_status(self):
        with self.assertRaisesRegex(
            ApprovalConflictError,
            "expected_status is required",
        ):
            propose(
                state=snapshot(
                    approvals=[approval_record()]
                ),
                status="APPROVED",
            )

    def test_stale_expected_status_is_rejected(self):
        with self.assertRaisesRegex(
            ApprovalConflictError,
            "status changed",
        ):
            propose(
                state=snapshot(
                    approvals=[approval_record()]
                ),
                status="APPROVED",
                expected_status="REJECTED",
            )

    def test_missing_approval_rejects_expected_status(self):
        with self.assertRaisesRegex(
            ApprovalConflictError,
            "does not exist",
        ):
            propose(expected_status="PENDING")

    def test_new_approval_id_must_be_unique(self):
        with self.assertRaisesRegex(
            ApprovalConflictError,
            "approval id already exists",
        ):
            propose(
                state=snapshot(
                    approvals=[
                        approval_record(role="ACCOUNTING")
                    ]
                ),
                approval_id=APPROVAL_1_ID,
                role="LEGAL",
            )

    def test_finalized_decisions_cannot_change(self):
        for status in ("APPROVED", "REJECTED"):
            with self.subTest(status=status):
                approved_at = (
                    OCCURRED_AT
                    if status == "APPROVED"
                    else None
                )

                with self.assertRaises(
                    ApprovalFinalizedError
                ):
                    propose(
                        state=snapshot(
                            approvals=[
                                approval_record(
                                    status=status,
                                    approved_at=approved_at,
                                )
                            ]
                        ),
                        status="PENDING",
                        expected_status=status,
                    )

    def test_pending_cannot_transition_to_pending(self):
        with self.assertRaises(
            ApprovalConflictError
        ):
            propose(
                state=snapshot(
                    approvals=[approval_record()]
                ),
                status="PENDING",
                expected_status="PENDING",
            )

    def test_only_latest_active_revision_can_be_approved(self):
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
            ApprovalRevisionNotActiveError
        ):
            propose(
                state=snapshot(revisions=revisions),
                document_revision_id=REVISION_1_ID,
            )

        latest = propose(
            state=snapshot(revisions=revisions),
            document_revision_id=REVISION_2_ID,
            approval_id=APPROVAL_2_ID,
        )
        self.assertEqual(
            latest.document_revision_id,
            REVISION_2_ID,
        )

    def test_old_revision_approvals_do_not_carry_forward(self):
        revisions = [
            revision_record(
                superseded_by=REVISION_2_ID,
            ),
            revision_record(
                revision_id=REVISION_2_ID,
                revision_number=2,
            ),
        ]
        old_approval = approval_record(
            status="APPROVED",
            approved_at=OCCURRED_AT,
        )

        plan = propose(
            state=snapshot(
                revisions=revisions,
                approvals=[old_approval],
            ),
            document_revision_id=REVISION_2_ID,
            approval_id=APPROVAL_2_ID,
        )

        self.assertEqual(plan.operation, "INSERT")
        self.assertIsNone(plan.current_status)

    def test_multiple_active_revisions_are_rejected(self):
        with self.assertRaisesRegex(
            ApprovalConflictError,
            "multiple active revisions",
        ):
            propose(
                state=snapshot(
                    revisions=[
                        revision_record(),
                        revision_record(
                            revision_id=REVISION_2_ID,
                            revision_number=2,
                        ),
                    ]
                )
            )

    def test_active_revision_must_have_highest_number(self):
        with self.assertRaisesRegex(
            ApprovalConflictError,
            "not the latest revision number",
        ):
            propose(
                state=snapshot(
                    revisions=[
                        revision_record(),
                        revision_record(
                            revision_id=REVISION_2_ID,
                            revision_number=2,
                            superseded_by=REVISION_1_ID,
                        ),
                    ]
                )
            )

    def test_signed_revision_rejects_approval_changes(self):
        with self.assertRaises(
            ApprovalLifecycleClosedError
        ):
            propose(
                state=snapshot(
                    revisions=[
                        revision_record(signed=True)
                    ]
                )
            )

    def test_terminal_project_rejects_approval_changes(self):
        for status in ("COMPLETED", "CANCELLED"):
            with self.subTest(status=status):
                with self.assertRaises(
                    ApprovalLifecycleClosedError
                ):
                    propose(
                        state=snapshot(
                            project=project_record(
                                status=status
                            )
                        )
                    )

    def test_roles_and_statuses_are_validated(self):
        for role in (None, "", "SECURITY"):
            with self.subTest(role=role):
                with self.assertRaises(
                    ApprovalEngineError
                ):
                    propose(role=role)

        for status in (None, "", "CANCELLED"):
            with self.subTest(status=status):
                with self.assertRaises(
                    ApprovalEngineError
                ):
                    propose(status=status)

    def test_snapshot_consistency_is_validated(self):
        invalid_states = (
            snapshot(
                revisions=[
                    revision_record(
                        project_id=OTHER_PROJECT_ID,
                    )
                ]
            ),
            snapshot(
                approvals=[
                    approval_record(),
                    approval_record(
                        approval_id=APPROVAL_2_ID,
                    ),
                ]
            ),
            snapshot(
                approvals=[
                    approval_record(
                        status="APPROVED",
                    )
                ]
            ),
        )

        for state in invalid_states:
            with self.subTest(state=state):
                with self.assertRaises(
                    ApprovalConflictError
                ):
                    propose(state=state)

    def test_identifiers_are_validated(self):
        invalid_calls = (
            {
                "document_revision_id": "not-a-uuid",
            },
            {
                "approval_id": "not-a-uuid",
            },
            {
                "acted_by": "not-a-uuid",
            },
        )

        for arguments in invalid_calls:
            with self.subTest(arguments=arguments):
                with self.assertRaises(
                    ApprovalEngineError
                ):
                    propose(**arguments)

    def test_approval_time_is_normalized_to_utc(self):
        offset = timezone(timedelta(hours=7))
        local_time = datetime(
            2026,
            9,
            4,
            18,
            30,
            tzinfo=offset,
        )
        naive_time = datetime(2026, 9, 4, 11, 30)

        offset_plan = propose(
            status="APPROVED",
            occurred_at=local_time,
        )
        naive_plan = propose(
            status="APPROVED",
            occurred_at=naive_time,
        )

        self.assertEqual(
            offset_plan.approved_at,
            OCCURRED_AT,
        )
        self.assertEqual(
            naive_plan.approved_at,
            OCCURRED_AT,
        )

        with self.assertRaisesRegex(
            ApprovalEngineError,
            "occurred_at must be a datetime",
        ):
            propose(occurred_at="2026-09-04")

    def test_audit_payload_excludes_sensitive_fields(self):
        plan = propose(status="APPROVED")
        encoded = json.dumps(
            {
                "change_summary": plan.change_summary,
                "old_values": plan.old_values,
                "new_values": plan.new_values,
            }
        )

        self.assertNotIn(SENSITIVE_NOTES, encoded)
        self.assertNotIn(
            "sensitive-document-hash",
            encoded,
        )
        self.assertNotIn(ACTED_BY, encoded)
        self.assertEqual(
            set(plan.old_values),
            {
                "document_type",
                "revision_number",
                "approver_role",
                "approval_status",
            },
        )
        self.assertEqual(
            set(plan.new_values),
            set(plan.old_values),
        )

    def test_plan_is_frozen_and_json_compatible(self):
        plan = propose(status="APPROVED")

        with self.assertRaises(FrozenInstanceError):
            plan.target_status = "REJECTED"

        payload = plan.to_dict()
        self.assertEqual(
            payload["approved_at"],
            OCCURRED_AT.isoformat(),
        )
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
