"""Tests for pure Merchant procurement mutation planning."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from claude.agents.tools.merchant.procurement_engine import (
    ProcurementConflictError,
    ProcurementDependencyError,
    ProcurementEngineError,
    ProcurementLifecycleClosedError,
    ProcurementMutationPlan,
    propose_procurement_mutation,
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
PROCUREMENT_1_ID = (
    "00000000-0000-0000-0000-000000000006"
)
PROCUREMENT_2_ID = (
    "00000000-0000-0000-0000-000000000007"
)
TRIGGERED_BY = (
    "00000000-0000-0000-0000-000000000008"
)

SIGNED_AT = datetime(
    2026,
    9,
    5,
    9,
    0,
    tzinfo=timezone.utc,
)
SENSITIVE_EXTERNAL_ID = "JRA-SENSITIVE-12345"


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
    signed=True,
    signed_at=SIGNED_AT,
    superseded_by=None,
):
    return {
        "id": revision_id,
        "project_id": project_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "content_hash": "sensitive-document-hash",
        "signed": signed,
        "signed_at": signed_at,
        "superseded_by": superseded_by,
    }


def procurement_record(
    *,
    procurement_id=PROCUREMENT_1_ID,
    project_id=PROJECT_ID,
    procurement_type="PURCHASE_REQUEST",
    external_id=SENSITIVE_EXTERNAL_ID,
    status="CREATED",
    version=1,
):
    return {
        "id": procurement_id,
        "project_id": project_id,
        "procurement_type": procurement_type,
        "external_id": external_id,
        "status": status,
        "version": version,
    }


def snapshot(
    *,
    project=None,
    revisions=(),
    procurement_records=(),
):
    return {
        "project": (
            project
            if project is not None
            else project_record()
        ),
        "document_revisions": list(revisions),
        "procurement_records": list(
            procurement_records
        ),
    }


def propose(
    *,
    state=None,
    procurement_id=PROCUREMENT_1_ID,
    procurement_type="PURCHASE_REQUEST",
    external_id=SENSITIVE_EXTERNAL_ID,
    status="created",
    expected_version=None,
    document_type=None,
    triggered_by=TRIGGERED_BY,
):
    return propose_procurement_mutation(
        state if state is not None else snapshot(),
        procurement_id=procurement_id,
        procurement_type=procurement_type,
        external_id=external_id,
        status=status,
        expected_version=expected_version,
        document_type=document_type,
        triggered_by=triggered_by,
    )


class ProcurementEngineTests(unittest.TestCase):
    def test_new_purchase_request_is_version_one(self):
        plan = propose()

        self.assertIsInstance(
            plan,
            ProcurementMutationPlan,
        )
        self.assertEqual(plan.merchant_id, MERCHANT_ID)
        self.assertEqual(plan.project_id, PROJECT_ID)
        self.assertEqual(
            plan.procurement_id,
            PROCUREMENT_1_ID,
        )
        self.assertEqual(
            plan.procurement_type,
            "PURCHASE_REQUEST",
        )
        self.assertEqual(
            plan.external_id,
            SENSITIVE_EXTERNAL_ID,
        )
        self.assertEqual(plan.status, "CREATED")
        self.assertIsNone(plan.current_version)
        self.assertEqual(plan.new_version, 1)
        self.assertEqual(plan.operation, "INSERT")
        self.assertEqual(
            plan.event_type,
            "PROCUREMENT_CREATED",
        )

    def test_existing_record_update_increments_version(self):
        plan = propose(
            state=snapshot(
                procurement_records=[
                    procurement_record()
                ]
            ),
            procurement_id=PROCUREMENT_2_ID,
            external_id="JRA-UPDATED-456",
            status="APPROVED",
            expected_version=1,
        )

        self.assertEqual(plan.operation, "UPDATE")
        self.assertEqual(
            plan.procurement_id,
            PROCUREMENT_1_ID,
        )
        self.assertEqual(plan.current_version, 1)
        self.assertEqual(plan.new_version, 2)
        self.assertEqual(
            plan.current_external_id,
            SENSITIVE_EXTERNAL_ID,
        )
        self.assertEqual(plan.current_status, "CREATED")
        self.assertEqual(
            plan.event_type,
            "PROCUREMENT_UPDATED",
        )

    def test_new_record_requires_evidence(self):
        with self.assertRaisesRegex(
            ProcurementEngineError,
            "requires status or external_id",
        ):
            propose(external_id=None, status=None)

    def test_update_must_change_a_field(self):
        with self.assertRaisesRegex(
            ProcurementConflictError,
            "does not change",
        ):
            propose(
                state=snapshot(
                    procurement_records=[
                        procurement_record()
                    ]
                ),
                expected_version=1,
            )

    def test_update_requires_current_expected_version(self):
        record = procurement_record(version=3)

        for expected_version in (
            None,
            1,
            0,
            True,
        ):
            with self.subTest(
                expected_version=expected_version
            ):
                with self.assertRaises(
                    ProcurementEngineError
                ):
                    propose(
                        state=snapshot(
                            procurement_records=[record]
                        ),
                        external_id="JRA-CHANGED",
                        expected_version=(
                            expected_version
                        ),
                    )

    def test_missing_record_rejects_expected_version(self):
        with self.assertRaisesRegex(
            ProcurementConflictError,
            "does not exist",
        ):
            propose(expected_version=1)

    def test_terminal_project_rejects_mutation(self):
        for status in ("COMPLETED", "CANCELLED"):
            with self.subTest(status=status):
                with self.assertRaises(
                    ProcurementLifecycleClosedError
                ):
                    propose(
                        state=snapshot(
                            project=project_record(
                                status=status
                            )
                        )
                    )

    def test_procurement_type_is_validated(self):
        for value in (None, "", "INVOICE"):
            with self.subTest(value=value):
                with self.assertRaises(
                    ProcurementEngineError
                ):
                    propose(procurement_type=value)

    def test_status_is_normalized_and_validated(self):
        plan = propose(status="awaiting_finance")
        self.assertEqual(plan.status, "AWAITING_FINANCE")

        for value in ("", "contains space", "A" * 51, 123):
            with self.subTest(value=value):
                with self.assertRaises(
                    ProcurementEngineError
                ):
                    propose(status=value)

    def test_external_id_is_validated(self):
        for value in ("", "   ", "A" * 101, 123):
            with self.subTest(value=value):
                with self.assertRaises(
                    ProcurementEngineError
                ):
                    propose(external_id=value)

    def test_snapshot_consistency_is_validated(self):
        invalid_states = (
            snapshot(
                procurement_records=[
                    procurement_record(
                        project_id=OTHER_PROJECT_ID
                    )
                ]
            ),
            snapshot(
                procurement_records=[
                    procurement_record(),
                    procurement_record(
                        procurement_id=PROCUREMENT_2_ID
                    ),
                ]
            ),
            snapshot(
                procurement_records=[
                    procurement_record(),
                    procurement_record(
                        procurement_type=(
                            "PURCHASE_ORDER"
                        )
                    ),
                ]
            ),
        )

        for state in invalid_states:
            with self.subTest(state=state):
                with self.assertRaises(
                    ProcurementConflictError
                ):
                    propose(state=state)

    def test_new_procurement_id_must_be_unique(self):
        with self.assertRaisesRegex(
            ProcurementConflictError,
            "procurement id already exists",
        ):
            propose(
                state=snapshot(
                    procurement_records=[
                        procurement_record(
                            procurement_type=(
                                "PURCHASE_ORDER"
                            )
                        )
                    ]
                ),
                procurement_type="PURCHASE_REQUEST",
                procurement_id=PROCUREMENT_1_ID,
            )

    def test_purchase_order_requires_signed_document(self):
        invalid_revision_sets = (
            (),
            [
                revision_record(
                    signed=False,
                    signed_at=None,
                )
            ],
            [
                revision_record(
                    signed=True,
                    signed_at=None,
                )
            ],
        )

        for revisions in invalid_revision_sets:
            with self.subTest(revisions=revisions):
                with self.assertRaises(
                    ProcurementDependencyError
                ):
                    propose(
                        state=snapshot(
                            revisions=revisions
                        ),
                        procurement_type="PURCHASE_ORDER",
                    )

    def test_signed_document_allows_purchase_order(self):
        plan = propose(
            state=snapshot(
                revisions=[revision_record()]
            ),
            procurement_type="PURCHASE_ORDER",
        )

        self.assertEqual(
            plan.procurement_type,
            "PURCHASE_ORDER",
        )

    def test_required_procurement_needs_recorded_pr(self):
        project = project_record(
            requires_procurement=True
        )
        missing_pr_states = (
            snapshot(
                project=project,
                revisions=[revision_record()],
            ),
            snapshot(
                project=project,
                revisions=[revision_record()],
                procurement_records=[
                    procurement_record(
                        external_id=None,
                    )
                ],
            ),
        )

        for state in missing_pr_states:
            with self.subTest(state=state):
                with self.assertRaisesRegex(
                    ProcurementDependencyError,
                    "Purchase Request number",
                ):
                    propose(
                        state=state,
                        procurement_type="PURCHASE_ORDER",
                        procurement_id=PROCUREMENT_2_ID,
                    )

    def test_recorded_pr_allows_purchase_order(self):
        plan = propose(
            state=snapshot(
                project=project_record(
                    requires_procurement=True
                ),
                revisions=[revision_record()],
                procurement_records=[
                    procurement_record()
                ],
            ),
            procurement_id=PROCUREMENT_2_ID,
            procurement_type="PURCHASE_ORDER",
            external_id="PO-123",
        )

        self.assertEqual(plan.operation, "INSERT")
        self.assertEqual(
            plan.procurement_type,
            "PURCHASE_ORDER",
        )

    def test_payment_request_requires_recorded_po(self):
        with self.assertRaisesRegex(
            ProcurementDependencyError,
            "Purchase Order number",
        ):
            propose(
                state=snapshot(
                    revisions=[revision_record()]
                ),
                procurement_type="PAYMENT_REQUEST",
            )

    def test_recorded_po_allows_payment_request(self):
        plan = propose(
            state=snapshot(
                revisions=[revision_record()],
                procurement_records=[
                    procurement_record(
                        procurement_type="PURCHASE_ORDER",
                        external_id="PO-123",
                    )
                ],
            ),
            procurement_id=PROCUREMENT_2_ID,
            procurement_type="PAYMENT_REQUEST",
            external_id="PAY-123",
        )

        self.assertEqual(
            plan.procurement_type,
            "PAYMENT_REQUEST",
        )

    def test_superseded_signed_revision_is_not_sufficient(self):
        revisions = [
            revision_record(
                signed=True,
                superseded_by=REVISION_2_ID,
            ),
            revision_record(
                revision_id=REVISION_2_ID,
                revision_number=2,
                signed=False,
                signed_at=None,
            ),
        ]

        with self.assertRaisesRegex(
            ProcurementDependencyError,
            "signed active",
        ):
            propose(
                state=snapshot(revisions=revisions),
                procurement_type="PURCHASE_ORDER",
            )

    def test_active_document_must_be_latest_revision(self):
        revisions = [
            revision_record(),
            revision_record(
                revision_id=REVISION_2_ID,
                revision_number=2,
                superseded_by=REVISION_1_ID,
            ),
        ]

        with self.assertRaisesRegex(
            ProcurementConflictError,
            "not the latest revision number",
        ):
            propose(
                state=snapshot(revisions=revisions),
                procurement_type="PURCHASE_ORDER",
            )

    def test_multiple_document_types_require_selection(self):
        revisions = [
            revision_record(),
            revision_record(
                revision_id=REVISION_2_ID,
                document_type="DATA_PROCESSING_ADDENDUM",
            ),
        ]

        with self.assertRaisesRegex(
            ProcurementConflictError,
            "document_type is required",
        ):
            propose(
                state=snapshot(revisions=revisions),
                procurement_type="PURCHASE_ORDER",
            )

        plan = propose(
            state=snapshot(revisions=revisions),
            procurement_type="PURCHASE_ORDER",
            document_type="merchant_agreement",
        )
        self.assertEqual(plan.operation, "INSERT")

    def test_audit_payload_redacts_external_identifiers(self):
        plan = propose()
        encoded = json.dumps(
            {
                "change_summary": plan.change_summary,
                "old_values": plan.old_values,
                "new_values": plan.new_values,
            }
        )

        self.assertNotIn(SENSITIVE_EXTERNAL_ID, encoded)
        self.assertNotIn(TRIGGERED_BY, encoded)
        self.assertNotIn(PROCUREMENT_1_ID, encoded)
        self.assertEqual(
            set(plan.old_values),
            {
                "procurement_type",
                "status",
                "external_id_recorded",
                "version",
            },
        )
        self.assertEqual(
            set(plan.new_values),
            set(plan.old_values),
        )

    def test_plan_is_frozen_and_json_compatible(self):
        plan = propose()

        with self.assertRaises(FrozenInstanceError):
            plan.status = "APPROVED"

        payload = plan.to_dict()
        self.assertEqual(
            json.loads(json.dumps(payload)),
            payload,
        )


if __name__ == "__main__":
    unittest.main()
