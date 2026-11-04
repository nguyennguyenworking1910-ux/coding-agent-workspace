"""CP12H.NL2F on the Merchant test database: cross-run confirmation end to end.

Every teammate message goes through the real PreToolUse policy gate first and
reaches the PostToolUse staging hook only when allowed, the order the harness
uses. Run A is the read-only preview; Run B is a fresh confirmed run that has
no preview evidence of its own.
"""

from __future__ import annotations

import json

import pytest

from claude.hooks.merchant_runtime_handoff_gate import HANDOFF_STATE_KEY
from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    TEST_DB_CONFIGURED,
    dispatch,
    idle,
    isolated,
    record,
    run_state,
    submit,
)
from tests.merchant.test_nl1_project_preview_postgres import snapshot
from tests.merchant.test_nl2_project_create_postgres import (  # noqa: F401
    claims,
    merchant,
    preview,
    projects,
    pytest_operation_keys,
    request_for,
)
from tests.merchant.test_nl2f_execute_delivery import deliver, execute_body

pytestmark = pytest.mark.skipif(
    not TEST_DB_CONFIGURED, reason="Merchant test database not configured"
)


def run_b(argv, short):
    submit(request_for(short), argv=argv, target="test")
    assert run_state()["operations"] == ["merchant_execute"]
    assert dispatch() is None
    assert "project_preview_evidence" not in record()


def terminal(outcome):
    return "TEAM_RESULT_JSON:\n" + json.dumps(
        {
            "contract_version": 1,
            "outcome": outcome,
            "operation": "merchant_execute",
            "database_target": "test",
            "proposal_emitted": False,
            "command": "project create",
        }
    )


def test_cross_run_confirmation_creates_exactly_one_project(merchant, capsys):
    repository, merchant_id, short = merchant
    op = preview(repository, short)["requested_operation"]  # Run A

    run_b(op["argv"], short)
    assert deliver(execute_body(op["argv"]), capsys, "execute-request") is None

    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    (created,) = projects(repository, merchant_id)
    assert str(created["id"]) == op["project_id"]
    assert created["title"] == f"{short} Nguyễn Văn Cừ"
    assert created["workflow_variant"] == "OPENING_NEW_CINEMA_STANDARD"
    assert [row["claim_status"] for row in claims(repository)] == ["COMPLETED"]

    assert deliver(terminal("EXECUTE_SUCCESS"), capsys) is None
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"


def test_stale_merchant_state_after_run_a_is_refused_before_spend(merchant, capsys):
    repository, merchant_id, short = merchant
    op = preview(repository, short)["requested_operation"]

    with repository.connection() as connection:
        with connection.transaction():
            connection.execute(
                "UPDATE merchant_ops.merchants SET name = name || ' (renamed)',"
                " version = version + 1 WHERE id = %s::uuid",
                (merchant_id,),
            )

    run_b(op["argv"], short)
    before = snapshot(repository)
    assert deliver(execute_body(op["argv"]), capsys, "execute-request") is None

    assert snapshot(repository) == before
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"].startswith("PREFLIGHT:")
    assert run_state().get("merchant_runtime_authorization_issued") is not True
    assert projects(repository, merchant_id) == []


def test_runtime_target_request_for_a_test_scope_writes_nothing(merchant, capsys):
    repository, merchant_id, short = merchant
    op = preview(repository, short)["requested_operation"]

    run_b(op["argv"], short)
    before = snapshot(repository)
    assert deliver(
        execute_body(op["argv"], target="runtime"), capsys, "execute-request"
    ) is None

    assert snapshot(repository) == before
    assert projects(repository, merchant_id) == []
    assert claims(repository) == []
