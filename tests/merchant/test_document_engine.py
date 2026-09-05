"""Tests for pure Merchant document revision planning."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

from claude.agents.tools.merchant.document_engine import (
    DocumentEngineError,
    DocumentLifecycleClosedError,
    DocumentRevisionConflictError,
    DocumentRevisionPlan,
    propose_document_revision,
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
REVISION_3_ID = (
    "00000000-0000-0000-0000-000000000006"
)
CREATED_BY = "00000000-0000-0000-0000-000000000007"

EFFECTIVE_DATE = date(2026, 9, 4)
EXPIRY_DATE = date(2027, 9, 4)
CONTENT_HASH = "sha256:document-revision-one"


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
    content_hash=CONTENT_HASH,
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


def snapshot(*, project=None, revisions=()):
    return {
        "project": (
            project
            if project is not None
            else project_record()
        ),
        "revisions": list(revisions),
    }


def propose(
    *,
    state=None,
    revision_id=REVISION_1_ID,
    document_type="merchant_agreement",
    content_hash=CONTENT_HASH,
    effective_date=EFFECTIVE_DATE,
    expiry_date=EXPIRY_DATE,
    created_by=CREATED_BY,
):
    return propose_document_revision(
        state if state is not None else snapshot(),
        revision_id=revision_id,
        document_type=document_type,
        content_hash=content_hash,
        effective_date=effective_date,
        expiry_date=expiry_date,
        created_by=created_by,
    )


class DocumentEngineTests(unittest.TestCase):
    def test_initial_revision_is_number_one(self):
        plan = propose()

        self.assertIsInstance(
            plan,
            DocumentRevisionPlan,
        )
        self.assertEqual(plan.merchant_id, MERCHANT_ID)
        self.assertEqual(plan.project_id, PROJECT_ID)
        self.assertEqual(plan.revision_id, REVISION_1_ID)
        self.assertEqual(
            plan.document_type,
            "MERCHANT_AGREEMENT",
        )
        self.assertEqual(plan.revision_number, 1)
        self.assertEqual(plan.content_hash, CONTENT_HASH)
        self.assertEqual(
            plan.effective_date,
            EFFECTIVE_DATE,
        )
        self.assertEqual(plan.expiry_date, EXPIRY_DATE)
        self.assertEqual(plan.created_by, CREATED_BY)
        self.assertIsNone(plan.previous_revision_id)
        self.assertIsNone(
            plan.previous_revision_number
        )
        self.assertEqual(
            plan.event_type,
            "DOCUMENT_REVISION_CREATED",
        )

    def test_new_revision_supersedes_active_revision(self):
        plan = propose(
            state=snapshot(
                revisions=[revision_record()]
            ),
            revision_id=REVISION_2_ID,
            content_hash="sha256:revision-two",
        )

        self.assertEqual(plan.revision_number, 2)
        self.assertEqual(
            plan.previous_revision_id,
            REVISION_1_ID,
        )
        self.assertEqual(
            plan.previous_revision_number,
            1,
        )
        self.assertTrue(
            plan.new_values["superseded_previous"]
        )

    def test_historical_chain_increments_latest_number(self):
        plan = propose(
            state=snapshot(
                revisions=[
                    revision_record(
                        superseded_by=REVISION_2_ID,
                    ),
                    revision_record(
                        revision_id=REVISION_2_ID,
                        revision_number=2,
                        content_hash="sha256:revision-two",
                    ),
                ]
            ),
            revision_id=REVISION_3_ID,
            content_hash="sha256:revision-three",
        )

        self.assertEqual(plan.revision_number, 3)
        self.assertEqual(
            plan.previous_revision_id,
            REVISION_2_ID,
        )
        self.assertEqual(
            plan.previous_revision_number,
            2,
        )

    def test_document_types_have_independent_sequences(self):
        plan = propose(
            state=snapshot(
                revisions=[revision_record()]
            ),
            revision_id=REVISION_2_ID,
            document_type="DATA_PROCESSING_ADDENDUM",
        )

        self.assertEqual(plan.revision_number, 1)
        self.assertIsNone(plan.previous_revision_id)

    def test_signed_revision_can_be_superseded_safely(self):
        plan = propose(
            state=snapshot(
                revisions=[
                    revision_record(signed=True)
                ]
            ),
            revision_id=REVISION_2_ID,
        )

        self.assertTrue(
            plan.old_values["active_revision_signed"]
        )
        self.assertFalse(plan.new_values["signed"])

    def test_multiple_active_revisions_are_rejected(self):
        with self.assertRaisesRegex(
            DocumentRevisionConflictError,
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
                ),
                revision_id=REVISION_3_ID,
            )

    def test_duplicate_revision_numbers_are_rejected(self):
        with self.assertRaisesRegex(
            DocumentRevisionConflictError,
            "duplicate revision numbers",
        ):
            propose(
                state=snapshot(
                    revisions=[
                        revision_record(
                            superseded_by=REVISION_2_ID,
                        ),
                        revision_record(
                            revision_id=REVISION_2_ID,
                            revision_number=1,
                        ),
                    ]
                ),
                revision_id=REVISION_3_ID,
            )

    def test_active_revision_must_have_highest_number(self):
        with self.assertRaisesRegex(
            DocumentRevisionConflictError,
            "not the latest revision number",
        ):
            propose(
                state=snapshot(
                    revisions=[
                        revision_record(),
                        revision_record(
                            revision_id=REVISION_2_ID,
                            revision_number=2,
                            superseded_by=REVISION_3_ID,
                        ),
                    ]
                ),
                revision_id=REVISION_3_ID,
            )

    def test_existing_new_revision_id_is_rejected(self):
        with self.assertRaisesRegex(
            DocumentRevisionConflictError,
            "already exists",
        ):
            propose(
                state=snapshot(
                    revisions=[revision_record()]
                ),
                revision_id=REVISION_1_ID,
            )

    def test_foreign_project_revision_is_rejected(self):
        with self.assertRaisesRegex(
            DocumentRevisionConflictError,
            "another project",
        ):
            propose(
                state=snapshot(
                    revisions=[
                        revision_record(
                            project_id=OTHER_PROJECT_ID,
                        )
                    ]
                ),
                revision_id=REVISION_2_ID,
            )

    def test_terminal_project_rejects_new_revision(self):
        for status in ("COMPLETED", "CANCELLED"):
            with self.subTest(status=status):
                with self.assertRaises(
                    DocumentLifecycleClosedError
                ):
                    propose(
                        state=snapshot(
                            project=project_record(
                                status=status
                            )
                        )
                    )

    def test_document_type_is_strictly_validated(self):
        invalid_values = (
            None,
            "",
            "merchant agreement",
            "-MERCHANT",
            "A" * 101,
        )

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(
                    DocumentEngineError
                ):
                    propose(document_type=value)

    def test_content_hash_is_required(self):
        for value in (None, "", "   ", 123):
            with self.subTest(value=value):
                with self.assertRaises(
                    DocumentEngineError
                ):
                    propose(content_hash=value)

    def test_document_dates_are_validated(self):
        invalid_date_values = (
            "2026-09-04",
            datetime(
                2026,
                9,
                4,
                tzinfo=timezone.utc,
            ),
        )

        for value in invalid_date_values:
            with self.subTest(value=value):
                with self.assertRaises(
                    DocumentEngineError
                ):
                    propose(effective_date=value)

        for expiry in (
            EFFECTIVE_DATE,
            date(2026, 9, 3),
        ):
            with self.subTest(expiry=expiry):
                with self.assertRaisesRegex(
                    DocumentEngineError,
                    "later than effective_date",
                ):
                    propose(expiry_date=expiry)

    def test_identifiers_are_validated(self):
        invalid_project = project_record()
        invalid_project["id"] = "not-a-uuid"

        cases = (
            {
                "state": snapshot(
                    project=invalid_project
                )
            },
            {"revision_id": "not-a-uuid"},
            {"created_by": "not-a-uuid"},
        )

        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(
                    DocumentEngineError
                ):
                    propose(**case)

    def test_audit_values_exclude_hash_and_identifiers(self):
        plan = propose(
            state=snapshot(
                revisions=[revision_record()]
            ),
            revision_id=REVISION_2_ID,
            content_hash="sensitive-content-fingerprint",
        )

        encoded = json.dumps(
            {
                "old_values": plan.old_values,
                "new_values": plan.new_values,
            }
        )

        self.assertNotIn(
            "sensitive-content-fingerprint",
            encoded,
        )
        self.assertNotIn(REVISION_1_ID, encoded)
        self.assertNotIn(REVISION_2_ID, encoded)
        self.assertNotIn(
            "Sensitive project title",
            encoded,
        )

    def test_plan_is_frozen_and_json_compatible(self):
        plan = propose()

        with self.assertRaises(FrozenInstanceError):
            plan.revision_number = 2

        payload = plan.to_dict()
        self.assertEqual(
            json.loads(json.dumps(payload)),
            payload,
        )
        self.assertEqual(
            payload["effective_date"],
            EFFECTIVE_DATE.isoformat(),
        )
        self.assertEqual(
            payload["expiry_date"],
            EXPIRY_DATE.isoformat(),
        )


if __name__ == "__main__":
    unittest.main()
