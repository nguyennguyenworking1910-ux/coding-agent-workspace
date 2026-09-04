"""Tests for Merchant approval and signing gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from claude.agents.tools.merchant.gates import (
    GateValidationError,
    evaluate_approval_gate,
    evaluate_signing_gate,
    latest_document_revision,
)


APPROVED_AT = datetime(
    2026,
    9,
    3,
    12,
    0,
    tzinfo=timezone.utc,
)


def project(
    project_id="project-1",
    *,
    requires_procurement=False,
):
    return {
        "id": project_id,
        "requires_procurement": requires_procurement,
    }


def revision(
    revision_id,
    *,
    project_id="project-1",
    document_type="CONTRACT",
    revision_number=1,
    signed=False,
    superseded_by=None,
):
    return {
        "id": revision_id,
        "project_id": project_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "signed": signed,
        "signed_at": (
            APPROVED_AT
            if signed
            else None
        ),
        "superseded_by": superseded_by,
    }


def approval(
    role,
    *,
    revision_id="revision-1",
    status="APPROVED",
    approved_at=APPROVED_AT,
):
    return {
        "document_revision_id": revision_id,
        "approver_role": role,
        "approval_status": status,
        "approved_at": approved_at,
    }


def purchase_request(
    *,
    project_id="project-1",
    external_id="PR-12345",
):
    return {
        "project_id": project_id,
        "procurement_type": "PURCHASE_REQUEST",
        "external_id": external_id,
    }


def all_approvals(revision_id="revision-1"):
    return [
        approval(
            role,
            revision_id=revision_id,
        )
        for role in (
            "LEGAL",
            "ACCOUNTING",
            "PARTNER",
        )
    ]


def test_latest_revision_ignores_superseded_revision():
    revisions = [
        revision(
            "revision-1",
            revision_number=1,
            superseded_by="revision-2",
        ),
        revision(
            "revision-2",
            revision_number=2,
        ),
    ]

    selected = latest_document_revision(
        "project-1",
        revisions,
    )

    assert selected is not None
    assert selected["id"] == "revision-2"


def test_latest_revision_ignores_other_projects():
    revisions = [
        revision(
            "other-revision",
            project_id="other-project",
            revision_number=99,
        ),
        revision(
            "expected-revision",
            revision_number=1,
        ),
    ]

    selected = latest_document_revision(
        "project-1",
        revisions,
    )

    assert selected is not None
    assert selected["id"] == "expected-revision"


def test_document_type_selects_correct_revision():
    revisions = [
        revision(
            "contract",
            document_type="CONTRACT",
        ),
        revision(
            "appendix",
            document_type="APPENDIX",
        ),
    ]

    selected = latest_document_revision(
        "project-1",
        revisions,
        document_type=" appendix ",
    )

    assert selected is not None
    assert selected["id"] == "appendix"


def test_multiple_document_types_require_selection():
    revisions = [
        revision(
            "contract",
            document_type="CONTRACT",
        ),
        revision(
            "appendix",
            document_type="APPENDIX",
        ),
    ]

    with pytest.raises(
        GateValidationError,
        match="document_type is required",
    ):
        latest_document_revision(
            "project-1",
            revisions,
        )


def test_no_revision_returns_none():
    assert latest_document_revision(
        "project-1",
        [],
    ) is None


def test_invalid_revision_number_is_rejected():
    with pytest.raises(
        GateValidationError,
        match="positive integer",
    ):
        latest_document_revision(
            "project-1",
            [
                revision(
                    "revision-1",
                    revision_number=0,
                )
            ],
        )


def test_missing_revision_blocks_approval_gate():
    result = evaluate_approval_gate(
        "project-1",
        [],
        [],
        required_roles=("LEGAL", "ACCOUNTING"),
    )

    assert not result.all_met
    assert result.document_revision_id is None
    assert result.blocking_codes == (
        "MISSING_DOCUMENT_REVISION",
    )
    assert result.missing_roles == (
        "LEGAL",
        "ACCOUNTING",
    )


def test_requested_approval_roles_can_pass():
    revisions = [revision("revision-1")]
    approvals = [
        approval("LEGAL"),
        approval("ACCOUNTING"),
    ]

    result = evaluate_approval_gate(
        "project-1",
        revisions,
        approvals,
        required_roles=("LEGAL", "ACCOUNTING"),
    )

    assert result.all_met
    assert result.approved_roles == (
        "LEGAL",
        "ACCOUNTING",
    )
    assert result.missing_roles == ()


@pytest.mark.parametrize(
    "status",
    (
        "PENDING",
        "REJECTED",
    ),
)
def test_non_approved_status_blocks_gate(status):
    revisions = [revision("revision-1")]
    approvals = [
        approval(
            "LEGAL",
            status=status,
            approved_at=None,
        )
    ]

    result = evaluate_approval_gate(
        "project-1",
        revisions,
        approvals,
        required_roles=("LEGAL",),
    )

    assert not result.all_met
    assert result.approved_roles == ()
    assert result.missing_roles == ("LEGAL",)
    assert result.blocking_codes == (
        "MISSING_REQUIRED_APPROVALS",
    )


def test_approval_without_timestamp_is_incomplete():
    result = evaluate_approval_gate(
        "project-1",
        [revision("revision-1")],
        [
            approval(
                "LEGAL",
                status="APPROVED",
                approved_at=None,
            )
        ],
        required_roles=("LEGAL",),
    )

    assert not result.all_met
    assert result.missing_roles == ("LEGAL",)


def test_approvals_on_old_revision_do_not_carry_forward():
    revisions = [
        revision(
            "revision-1",
            revision_number=1,
            superseded_by="revision-2",
        ),
        revision(
            "revision-2",
            revision_number=2,
        ),
    ]

    result = evaluate_approval_gate(
        "project-1",
        revisions,
        all_approvals("revision-1"),
        required_roles=(
            "LEGAL",
            "ACCOUNTING",
            "PARTNER",
        ),
    )

    assert not result.all_met
    assert result.document_revision_id == "revision-2"
    assert result.approved_roles == ()
    assert result.missing_roles == (
        "LEGAL",
        "ACCOUNTING",
        "PARTNER",
    )


def test_duplicate_approval_role_is_rejected():
    revisions = [revision("revision-1")]
    approvals = [
        approval("LEGAL"),
        approval("LEGAL"),
    ]

    with pytest.raises(
        GateValidationError,
        match="Duplicate approval role",
    ):
        evaluate_approval_gate(
            "project-1",
            revisions,
            approvals,
            required_roles=("LEGAL",),
        )


def test_unsupported_approval_role_is_rejected():
    with pytest.raises(
        GateValidationError,
        match="Unsupported approver role",
    ):
        evaluate_approval_gate(
            "project-1",
            [revision("revision-1")],
            [approval("UNKNOWN")],
            required_roles=("LEGAL",),
        )


def test_unsupported_approval_status_is_rejected():
    with pytest.raises(
        GateValidationError,
        match="Unsupported approval status",
    ):
        evaluate_approval_gate(
            "project-1",
            [revision("revision-1")],
            [
                approval(
                    "LEGAL",
                    status="UNKNOWN",
                )
            ],
            required_roles=("LEGAL",),
        )


def test_required_roles_must_not_be_empty():
    with pytest.raises(
        GateValidationError,
        match="At least one approval role",
    ):
        evaluate_approval_gate(
            "project-1",
            [revision("revision-1")],
            [],
            required_roles=(),
        )


def test_required_roles_must_be_unique():
    with pytest.raises(
        GateValidationError,
        match="must be unique",
    ):
        evaluate_approval_gate(
            "project-1",
            [revision("revision-1")],
            [],
            required_roles=("LEGAL", "LEGAL"),
        )


def test_unsupported_required_role_is_rejected():
    with pytest.raises(
        GateValidationError,
        match="Unsupported required approval roles",
    ):
        evaluate_approval_gate(
            "project-1",
            [revision("revision-1")],
            [],
            required_roles=("SECURITY",),
        )


def test_signing_gate_passes_without_procurement_when_optional():
    result = evaluate_signing_gate(
        project(requires_procurement=False),
        [revision("revision-1")],
        all_approvals(),
        [],
    )

    assert result.all_met
    assert not result.requires_procurement
    assert not result.purchase_request_present
    assert result.blocking_codes == ()


def test_required_purchase_request_allows_signing():
    result = evaluate_signing_gate(
        project(requires_procurement=True),
        [revision("revision-1")],
        all_approvals(),
        [purchase_request()],
    )

    assert result.all_met
    assert result.requires_procurement
    assert result.purchase_request_present


def test_missing_required_purchase_request_blocks_signing():
    result = evaluate_signing_gate(
        project(requires_procurement=True),
        [revision("revision-1")],
        all_approvals(),
        [],
    )

    assert not result.all_met
    assert result.blocking_codes == (
        "MISSING_PURCHASE_REQUEST",
    )


@pytest.mark.parametrize(
    "procurement_records",
    (
        [
            {
                "project_id": "project-1",
                "procurement_type": "PURCHASE_ORDER",
                "external_id": "PO-123",
            }
        ],
        [
            {
                "project_id": "project-1",
                "procurement_type": "PURCHASE_REQUEST",
                "external_id": "",
            }
        ],
        [
            {
                "project_id": "other-project",
                "procurement_type": "PURCHASE_REQUEST",
                "external_id": "PR-OTHER",
            }
        ],
    ),
)
def test_invalid_purchase_request_does_not_open_gate(
    procurement_records,
):
    result = evaluate_signing_gate(
        project(requires_procurement=True),
        [revision("revision-1")],
        all_approvals(),
        procurement_records,
    )

    assert not result.all_met
    assert not result.purchase_request_present
    assert "MISSING_PURCHASE_REQUEST" in (
        result.blocking_codes
    )


def test_already_signed_revision_cannot_be_signed_again():
    result = evaluate_signing_gate(
        project(),
        [
            revision(
                "revision-1",
                signed=True,
            )
        ],
        all_approvals(),
        [],
    )

    assert not result.all_met
    assert result.already_signed
    assert result.blocking_codes == (
        "DOCUMENT_ALREADY_SIGNED",
    )


def test_signing_reports_multiple_blockers():
    result = evaluate_signing_gate(
        project(requires_procurement=True),
        [revision("revision-1")],
        [],
        [],
    )

    assert not result.all_met
    assert result.blocking_codes == (
        "MISSING_REQUIRED_APPROVALS",
        "MISSING_PURCHASE_REQUEST",
    )
    assert result.missing_roles == (
        "LEGAL",
        "ACCOUNTING",
        "PARTNER",
    )


def test_approval_values_are_normalized():
    result = evaluate_approval_gate(
        "project-1",
        [revision("revision-1")],
        [
            approval(
                " legal ",
                status=" approved ",
            )
        ],
        required_roles=(" legal ",),
    )

    assert result.all_met
    assert result.approved_roles == ("LEGAL",)


def test_result_is_json_compatible_and_redacted():
    sensitive_external_id = "JRA-SENSITIVE-12345"

    result = evaluate_signing_gate(
        project(requires_procurement=True),
        [revision("revision-1")],
        all_approvals(),
        [
            purchase_request(
                external_id=sensitive_external_id
            )
        ],
    )

    encoded = json.dumps(result.to_dict())
    decoded = json.loads(encoded)

    assert decoded["all_met"] is True
    assert decoded["purchase_request_present"] is True
    assert sensitive_external_id not in encoded