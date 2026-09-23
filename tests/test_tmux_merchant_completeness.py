import json

from claude.hooks.tmux_merchant_completeness import (
    clear_pending_merchant_completeness,
    load_pending_merchant_completeness,
    pending_merchant_completeness_matches,
    stage_pending_merchant_completeness,
    validate_completeness_result,
)


def clarification_result():
    return {
        "success": True,
        "mode": "COMPLETENESS",
        "command": (
            "document revision-create"
        ),
        "complete": False,
        "missing_fields": [
            "project_id",
            "document_type",
            "content_hash",
        ],
        "missing_one_of": [],
        "clarification": {
            "outcome": (
                "REQUIRES_CLARIFICATION"
            ),
            "missing_fields": [
                "project_id",
                "document_type",
                "content_hash",
            ],
            "missing_one_of": [],
            "question": (
                "Please provide project_id, "
                "document_type, and content_hash."
            ),
        },
    }


def complete_result():
    return {
        "success": True,
        "mode": "COMPLETENESS",
        "command": "merchant create",
        "complete": True,
        "missing_fields": [],
        "missing_one_of": [],
        "clarification": None,
    }


def test_valid_incomplete_result_is_accepted():
    result = clarification_result()

    assert (
        validate_completeness_result(
            result
        )
        == result
    )


def test_valid_complete_result_is_accepted():
    result = complete_result()

    assert (
        validate_completeness_result(
            result
        )
        == result
    )


def test_incomplete_result_requires_exact_clarification_evidence():
    result = clarification_result()

    result[
        "clarification"
    ][
        "missing_fields"
    ] = [
        "project_id"
    ]

    assert (
        validate_completeness_result(
            result
        )
        is None
    )


def test_complete_result_cannot_claim_missing_fields():
    result = complete_result()

    result[
        "missing_fields"
    ] = [
        "project_id"
    ]

    assert (
        validate_completeness_result(
            result
        )
        is None
    )


def test_receipt_is_bound_to_exact_run_and_task(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "CLAUDE_RUNTIME_DIR",
        str(tmp_path),
    )

    assert stage_pending_merchant_completeness(
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="run-1:merchant-manager",
        tool_use_id="tool-1",
        result=clarification_result(),
    )

    receipt = (
        load_pending_merchant_completeness(
            "pane-1"
        )
    )

    assert receipt is not None

    assert pending_merchant_completeness_matches(
        receipt,
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="run-1:merchant-manager",
    )

    assert not pending_merchant_completeness_matches(
        receipt,
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-2",
        task_id="run-2:merchant-manager",
    )


def test_clear_removes_transient_receipt(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "CLAUDE_RUNTIME_DIR",
        str(tmp_path),
    )

    assert stage_pending_merchant_completeness(
        pane_session_id="pane-1",
        owner_session_id="lead-1",
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="run-1:merchant-manager",
        tool_use_id="tool-1",
        result=complete_result(),
    )

    clear_pending_merchant_completeness(
        "pane-1"
    )

    assert (
        load_pending_merchant_completeness(
            "pane-1"
        )
        is None
    )