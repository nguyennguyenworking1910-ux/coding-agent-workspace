"""Tests for trusted Document Revision resolver receipt consumption."""

from __future__ import annotations

from copy import deepcopy

from claude.hooks.document_revision_resolution_gate import (
    BOUND,
    REJECTED,
    REQUIRES_CLARIFICATION,
    bind_document_revision_resolution_receipt,
)


MERCHANT_A = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
)

MERCHANT_B = (
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
)

PROJECT_A = (
    "11111111-1111-4111-8111-111111111111"
)

PROJECT_A2 = (
    "22222222-2222-4222-8222-222222222222"
)

REVISION_A1 = (
    "41111111-1111-4111-8111-111111111111"
)

REVISION_A2 = (
    "42222222-2222-4222-8222-222222222222"
)


def candidate(
    revision_id: str,
    *,
    project_id: str = PROJECT_A,
    merchant_id: str = MERCHANT_A,
    document_type: str = "CONTRACT",
    revision_number: int = 1,
    signed: bool = True,
    superseded_by=None,
):
    return {
        "revision_id": revision_id,
        "project_id": project_id,
        "merchant_id": merchant_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "signed": signed,
        "superseded_by": superseded_by,
    }


def project_resolved():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "CONTRACT#1",
        "scope": "PROJECT",
        "merchant_id": MERCHANT_A,
        "project_id": PROJECT_A,
        "status": "RESOLVED",
        "match_kind": "REVISION_KEY",
        "resolved": True,
        "revision_id": REVISION_A1,
        "source_project_id": PROJECT_A,
        "document_type": "CONTRACT",
        "revision_number": 1,
        "signed": True,
        "superseded_by": None,
        "candidates": [
            candidate(
                REVISION_A1
            ),
        ],
    }


def merchant_resolved():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "MEDIA_APPENDIX#1",
        "scope": "MERCHANT",
        "merchant_id": MERCHANT_A,
        "project_id": None,
        "status": "RESOLVED",
        "match_kind": "REVISION_KEY",
        "resolved": True,
        "revision_id": REVISION_A2,
        "source_project_id": PROJECT_A2,
        "document_type": "MEDIA_APPENDIX",
        "revision_number": 1,
        "signed": False,
        "superseded_by": None,
        "candidates": [
            candidate(
                REVISION_A2,
                project_id=PROJECT_A2,
                document_type="MEDIA_APPENDIX",
                revision_number=1,
                signed=False,
            ),
        ],
    }


def project_ambiguous():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "CONTRACT",
        "scope": "PROJECT",
        "merchant_id": MERCHANT_A,
        "project_id": PROJECT_A,
        "status": "AMBIGUOUS",
        "match_kind": "DOCUMENT_TYPE",
        "resolved": False,
        "revision_id": None,
        "source_project_id": None,
        "document_type": None,
        "revision_number": None,
        "signed": None,
        "superseded_by": None,
        "candidates": [
            candidate(
                REVISION_A1,
                revision_number=1,
            ),
            candidate(
                REVISION_A2,
                revision_number=2,
            ),
        ],
    }


def merchant_ambiguous():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "CONTRACT",
        "scope": "MERCHANT",
        "merchant_id": MERCHANT_A,
        "project_id": None,
        "status": "AMBIGUOUS",
        "match_kind": "DOCUMENT_TYPE",
        "resolved": False,
        "revision_id": None,
        "source_project_id": None,
        "document_type": None,
        "revision_number": None,
        "signed": None,
        "superseded_by": None,
        "candidates": [
            candidate(
                REVISION_A1,
                project_id=PROJECT_A,
                revision_number=1,
            ),
            candidate(
                REVISION_A2,
                project_id=PROJECT_A2,
                revision_number=2,
            ),
        ],
    }


def project_not_found():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "UNKNOWN#1",
        "scope": "PROJECT",
        "merchant_id": MERCHANT_A,
        "project_id": PROJECT_A,
        "status": "NOT_FOUND",
        "match_kind": "NONE",
        "resolved": False,
        "revision_id": None,
        "source_project_id": None,
        "document_type": None,
        "revision_number": None,
        "signed": None,
        "superseded_by": None,
        "candidates": [],
    }


def merchant_not_found():
    return {
        "success": True,
        "mode": "DOCUMENT_REVISION_RESOLUTION",
        "query": "UNKNOWN#1",
        "scope": "MERCHANT",
        "merchant_id": MERCHANT_A,
        "project_id": None,
        "status": "NOT_FOUND",
        "match_kind": "NONE",
        "resolved": False,
        "revision_id": None,
        "source_project_id": None,
        "document_type": None,
        "revision_number": None,
        "signed": None,
        "superseded_by": None,
        "candidates": [],
    }


def receipt(
    resolution=None,
):
    value = (
        project_resolved()
        if resolution is None
        else resolution
    )

    return {
        "pane_session_id": "pane-1",
        "owner_session_id": "lead-1",
        "teammate_name": "merchant-manager",
        "run_id": "run-1",
        "task_id": "task-1",
        "merchant_id": value[
            "merchant_id"
        ],
        "project_id": value[
            "project_id"
        ],
        "scope": value[
            "scope"
        ],
        "tool_use_id": "tool-1",
        "resolution": value,
        "created_at": 1.0,
    }


def bind_project(
    value,
    *,
    query="CONTRACT#1",
    merchant_id=MERCHANT_A,
    project_id=PROJECT_A,
    pane_session_id="pane-1",
    owner_session_id="lead-1",
    teammate_name="merchant-manager",
    run_id="run-1",
    task_id="task-1",
):
    return bind_document_revision_resolution_receipt(
        value,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        trusted_merchant_id=merchant_id,
        trusted_project_id=project_id,
        expected_scope="PROJECT",
        expected_query=query,
    )


def bind_merchant(
    value,
    *,
    query="MEDIA_APPENDIX#1",
    merchant_id=MERCHANT_A,
    project_id=None,
    pane_session_id="pane-1",
    owner_session_id="lead-1",
    teammate_name="merchant-manager",
    run_id="run-1",
    task_id="task-1",
):
    return bind_document_revision_resolution_receipt(
        value,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        trusted_merchant_id=merchant_id,
        trusted_project_id=project_id,
        expected_scope="MERCHANT",
        expected_query=query,
    )


def test_exact_project_resolved_receipt_binds_revision():
    decision = bind_project(
        receipt()
    )

    assert decision.accepted is True
    assert decision.outcome == BOUND
    assert decision.query == "CONTRACT#1"
    assert decision.scope == "PROJECT"
    assert decision.merchant_id == MERCHANT_A
    assert decision.project_id == PROJECT_A
    assert decision.revision_id == REVISION_A1
    assert decision.source_project_id == PROJECT_A
    assert decision.document_type == "CONTRACT"
    assert decision.revision_number == 1
    assert decision.signed is True
    assert decision.superseded_by is None
    assert decision.match_kind == "REVISION_KEY"
    assert decision.question is None
    assert len(decision.candidates) == 1


def test_exact_merchant_resolved_receipt_binds_cross_project_revision():
    decision = bind_merchant(
        receipt(
            merchant_resolved()
        )
    )

    assert decision.accepted is True
    assert decision.outcome == BOUND
    assert decision.scope == "MERCHANT"
    assert decision.merchant_id == MERCHANT_A
    assert decision.project_id is None
    assert decision.revision_id == REVISION_A2
    assert decision.source_project_id == PROJECT_A2
    assert decision.document_type == "MEDIA_APPENDIX"
    assert decision.revision_number == 1
    assert decision.signed is False


def test_wrong_pane_is_rejected():
    decision = bind_project(
        receipt(),
        pane_session_id="pane-wrong",
    )

    assert decision.accepted is False
    assert decision.outcome == REJECTED


def test_wrong_owner_is_rejected():
    decision = bind_project(
        receipt(),
        owner_session_id="lead-wrong",
    )

    assert decision.outcome == REJECTED


def test_wrong_teammate_is_rejected():
    decision = bind_project(
        receipt(),
        teammate_name="reviewer",
    )

    assert decision.outcome == REJECTED


def test_wrong_run_is_rejected():
    decision = bind_project(
        receipt(),
        run_id="run-wrong",
    )

    assert decision.outcome == REJECTED


def test_wrong_task_is_rejected():
    decision = bind_project(
        receipt(),
        task_id="task-wrong",
    )

    assert decision.outcome == REJECTED


def test_wrong_trusted_merchant_is_rejected():
    decision = bind_project(
        receipt(),
        merchant_id=MERCHANT_B,
    )

    assert decision.outcome == REJECTED
    assert decision.revision_id is None


def test_wrong_trusted_project_is_rejected():
    decision = bind_project(
        receipt(),
        project_id=PROJECT_A2,
    )

    assert decision.outcome == REJECTED
    assert decision.revision_id is None


def test_project_receipt_cannot_be_consumed_as_merchant_scope():
    decision = bind_merchant(
        receipt(),
        query="CONTRACT#1",
    )

    assert decision.outcome == REJECTED


def test_merchant_receipt_cannot_be_consumed_as_project_scope():
    decision = bind_project(
        receipt(
            merchant_resolved()
        ),
        query="MEDIA_APPENDIX#1",
    )

    assert decision.outcome == REJECTED


def test_merchant_scope_rejects_trusted_project_parent():
    decision = bind_merchant(
        receipt(
            merchant_resolved()
        ),
        project_id=PROJECT_A2,
    )

    assert decision.outcome == REJECTED


def test_project_scope_requires_trusted_project():
    decision = bind_document_revision_resolution_receipt(
        receipt(),
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        trusted_merchant_id=MERCHANT_A,
        trusted_project_id=None,
        expected_scope="PROJECT",
        expected_query="CONTRACT#1",
    )

    assert decision.outcome == REJECTED


def test_invalid_scope_is_rejected():
    decision = bind_document_revision_resolution_receipt(
        receipt(),
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        trusted_merchant_id=MERCHANT_A,
        trusted_project_id=PROJECT_A,
        expected_scope="UNKNOWN",
        expected_query="CONTRACT#1",
    )

    assert decision.outcome == REJECTED


def test_query_mismatch_is_rejected():
    decision = bind_project(
        receipt(),
        query="CONTRACT#2",
    )

    assert decision.outcome == REJECTED
    assert decision.question is None


def test_nfkc_equivalent_query_is_accepted():
    value = receipt()

    value["resolution"] = deepcopy(
        project_resolved()
    )

    value["resolution"][
        "query"
    ] = "ＣＯＮＴＲＡＣＴ#1"

    value["resolution"][
        "candidates"
    ] = deepcopy(
        project_resolved()[
            "candidates"
        ]
    )

    decision = bind_project(
        value,
        query="CONTRACT#1",
    )

    # Receipt validation is based on the nested deterministic resolution.
    # NFKC query binding accepts the equivalent full-width form.
    assert decision.outcome == BOUND


def test_missing_receipt_is_rejected():
    decision = bind_project(
        None
    )

    assert decision.outcome == REJECTED


def test_empty_expected_query_is_rejected():
    decision = bind_project(
        receipt(),
        query="",
    )

    assert decision.outcome == REJECTED


def test_malformed_resolution_is_rejected():
    value = receipt()

    value["resolution"] = deepcopy(
        project_resolved()
    )

    value["resolution"][
        "revision_id"
    ] = "not-a-uuid"

    decision = bind_project(
        value
    )

    assert decision.outcome == REJECTED


def test_resolution_scope_mismatch_is_rejected():
    value = receipt()

    value["resolution"] = deepcopy(
        project_resolved()
    )

    value["resolution"][
        "scope"
    ] = "MERCHANT"

    decision = bind_project(
        value
    )

    assert decision.outcome == REJECTED


def test_resolution_merchant_mismatch_is_rejected():
    value = receipt()

    value["resolution"] = deepcopy(
        project_resolved()
    )

    value["resolution"][
        "merchant_id"
    ] = MERCHANT_B

    value["resolution"][
        "candidates"
    ][0][
        "merchant_id"
    ] = MERCHANT_B

    decision = bind_project(
        value
    )

    assert decision.outcome == REJECTED


def test_resolution_project_mismatch_is_rejected():
    value = receipt()

    value["resolution"] = deepcopy(
        project_resolved()
    )

    value["resolution"][
        "project_id"
    ] = PROJECT_A2

    value["resolution"][
        "source_project_id"
    ] = PROJECT_A2

    value["resolution"][
        "candidates"
    ][0][
        "project_id"
    ] = PROJECT_A2

    decision = bind_project(
        value
    )

    assert decision.outcome == REJECTED


def test_project_ambiguous_requires_clarification():
    decision = bind_project(
        receipt(
            project_ambiguous()
        ),
        query="CONTRACT",
    )

    assert decision.accepted is False
    assert decision.outcome == REQUIRES_CLARIFICATION
    assert decision.scope == "PROJECT"
    assert decision.merchant_id == MERCHANT_A
    assert decision.project_id == PROJECT_A
    assert decision.revision_id is None
    assert decision.match_kind == "DOCUMENT_TYPE"

    assert [
        item.revision_id
        for item in decision.candidates
    ] == [
        REVISION_A1,
        REVISION_A2,
    ]


def test_project_ambiguous_question_is_deterministic():
    decision = bind_project(
        receipt(
            project_ambiguous()
        ),
        query="CONTRACT",
    )

    assert decision.question == (
        'Multiple document revisions match "CONTRACT" '
        f"for project {PROJECT_A} "
        f"under merchant {MERCHANT_A}: "
        f'"CONTRACT#1" ({REVISION_A1}; '
        f"source project {PROJECT_A}), "
        f'"CONTRACT#2" ({REVISION_A2}; '
        f"source project {PROJECT_A}). "
        "Please specify one revision by exact UUID "
        "or DOCUMENT_TYPE#REVISION_NUMBER."
    )


def test_merchant_ambiguous_requires_clarification():
    decision = bind_merchant(
        receipt(
            merchant_ambiguous()
        ),
        query="CONTRACT",
    )

    assert decision.accepted is False
    assert decision.outcome == REQUIRES_CLARIFICATION
    assert decision.scope == "MERCHANT"
    assert decision.merchant_id == MERCHANT_A
    assert decision.project_id is None
    assert len(decision.candidates) == 2


def test_merchant_ambiguous_question_preserves_source_projects():
    decision = bind_merchant(
        receipt(
            merchant_ambiguous()
        ),
        query="CONTRACT",
    )

    assert (
        f"source project {PROJECT_A}"
        in decision.question
    )

    assert (
        f"source project {PROJECT_A2}"
        in decision.question
    )


def test_project_not_found_requires_clarification():
    decision = bind_project(
        receipt(
            project_not_found()
        ),
        query="UNKNOWN#1",
    )

    assert decision.accepted is False
    assert decision.outcome == REQUIRES_CLARIFICATION
    assert decision.scope == "PROJECT"
    assert decision.merchant_id == MERCHANT_A
    assert decision.project_id == PROJECT_A
    assert decision.revision_id is None
    assert decision.candidates == ()

    assert decision.question == (
        'No document revision matched "UNKNOWN#1" '
        f"for project {PROJECT_A} "
        f"under merchant {MERCHANT_A}. "
        "Please provide an exact revision UUID "
        "or DOCUMENT_TYPE#REVISION_NUMBER."
    )


def test_merchant_not_found_requires_clarification():
    decision = bind_merchant(
        receipt(
            merchant_not_found()
        ),
        query="UNKNOWN#1",
    )

    assert decision.accepted is False
    assert decision.outcome == REQUIRES_CLARIFICATION
    assert decision.scope == "MERCHANT"
    assert decision.merchant_id == MERCHANT_A
    assert decision.project_id is None

    assert decision.question == (
        'No document revision matched "UNKNOWN#1" '
        f"for merchant {MERCHANT_A}. "
        "Please provide an exact revision UUID "
        "or DOCUMENT_TYPE#REVISION_NUMBER."
    )


def test_resolved_preserves_superseded_metadata():
    value = project_resolved()

    value[
        "superseded_by"
    ] = REVISION_A2

    value[
        "candidates"
    ][0][
        "superseded_by"
    ] = REVISION_A2

    decision = bind_project(
        receipt(
            value
        )
    )

    assert decision.outcome == BOUND
    assert decision.superseded_by == REVISION_A2


def test_resolved_preserves_unsigned_metadata():
    decision = bind_merchant(
        receipt(
            merchant_resolved()
        )
    )

    assert decision.outcome == BOUND
    assert decision.signed is False


def test_rejected_decision_clears_identity_fields():
    decision = bind_project(
        receipt(),
        query="WRONG"
    )

    assert decision.outcome == REJECTED
    assert decision.scope is None
    assert decision.merchant_id is None
    assert decision.project_id is None
    assert decision.revision_id is None
    assert decision.source_project_id is None
    assert decision.document_type is None
    assert decision.revision_number is None
    assert decision.signed is None
    assert decision.superseded_by is None
    assert decision.match_kind is None
    assert decision.candidates == ()
    assert decision.question is None
