"""CP12H.NL3 on the Merchant test database: preview, then "/solve Xác nhận tạo".

Run A is the unscoped read-only preview: the real PostToolUse(Bash) hook
captures the CLI output and creates the trusted pending record. The user's own
prompt then starts Run B, which executes through the unchanged Direct EXECUTE
pipeline (completeness, reservation, pane identity, preview-basis recheck and
committed evidence) and reuses the idle teammate.
"""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks.merchant_preview_delivery import PREVIEW_OPERATION_MARKER
from claude.hooks.merchant_runtime_handoff_gate import HANDOFF_STATE_KEY, HANDOFF_SUCCESS
from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    PANE,
    TEAMMATE,
    TEST_DB_CONFIGURED,
    Operation,
    dispatch,
    idle,
    intent_gate,
    isolated,
    policy_gate,
    record,
    run_hook,
    run_state,
    runtime_state,
    submit,
)
from tests.merchant.test_nl1_project_preview_postgres import snapshot
from tests.merchant.test_nl2_project_create_postgres import (  # noqa: F401
    claims,
    merchant,
    projects,
    pytest_operation_keys,
)
from tests.merchant.test_nl2f_execute_delivery import deliver, execute_body

pytestmark = pytest.mark.skipif(
    not TEST_DB_CONFIGURED, reason="Merchant test database not configured"
)

CLI = "python .claude/agents/tools/merchant/agent_cli.py"


def request_text(short):
    return (
        f"Create a cinema opening project for {short} Nguyễn Văn Cừ under "
        f"{short} Cinemas on the test database. No procurement."
    )


def run_a(repository, short, capsys):
    """The read-only preview run; returns the CLI's requested_operation."""

    text = request_text(short)
    submit(text, confirmed=False, operations=[Operation.MERCHANT_READ])
    assert run_state()["merchant_read_target"] == "test"
    assert dispatch(
        "operation: merchant_read\ndatabase_target: test\n"
        "Preview the Project the user described."
    ) is None

    output = MerchantReadCommands(MerchantReadRepository(repository)).project_preview(
        request=text, database_target="test"
    )
    assert output["outcome"] == "READY_FOR_CONFIRMATION", output["clarifications"]
    assert run_hook({
        "hook_event_name": "PostToolUse", "session_id": PANE,
        "agent_type": TEAMMATE, "tool_name": "Bash",
        "tool_input": {"command": f'{CLI} project preview --request "{text}" --test-database'},
        "tool_response": {"stdout": json.dumps(output, ensure_ascii=False, indent=2),
                          "stderr": ""},
    }) == 0

    operation = output["requested_operation"]
    exact = json.dumps(operation, ensure_ascii=False, separators=(",", ":"))
    assert deliver(
        f"Preview ready.\n{PREVIEW_OPERATION_MARKER}\n{exact}\n", capsys
    ) is None
    assert idle() == 0
    return operation


def user_says(prompt):
    def never_classified():
        raise AssertionError("a confirmation is never classified by the model")

    return intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD, "prompt": prompt},
        parser_factory=never_classified, env={},
    )


def reuse_teammate():
    assert dispatch() is not None  # an idle teammate is redirected to SendMessage
    with runtime_state.locked_state(LEAD) as state:
        assert policy_gate.apply_call(
            state, "SendMessage",
            {"to": TEAMMATE, "message": "Perform the user's Merchant request."},
            session_id=LEAD,
        ) is None


def terminal(outcome):
    return "TEAM_RESULT_JSON:\n" + json.dumps({
        "contract_version": 1, "outcome": outcome, "operation": "merchant_execute",
        "database_target": "test", "proposal_emitted": False, "command": "project create",
    })


def test_conversational_confirmation_creates_exactly_one_project(merchant, capsys):
    repository, merchant_id, short = merchant
    operation = run_a(repository, short, capsys)
    assert record()["status"] == "IDLE_REUSABLE"
    (live,) = pending.live_records(LEAD)
    assert live["operation"] == operation
    assert projects(repository, merchant_id) == []  # a preview creates nothing

    assert user_says("Xác nhận tạo.")["decision"] == "block"  # bare: guidance only
    assert projects(repository, merchant_id) == []

    output = user_says("/solve Xác nhận tạo.")
    assert "hookSpecificOutput" in output
    assert run_state()["merchant_scope"]["argv"] == operation["argv"]
    assert run_state()["merchant_scope"]["database_target"] == "test"

    reuse_teammate()
    assert deliver(execute_body(operation["argv"]), capsys, "execute-request") is None

    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert run_state()[HANDOFF_STATE_KEY]["status"] == HANDOFF_SUCCESS
    (created,) = projects(repository, merchant_id)
    assert str(created["id"]) == operation["project_id"]
    assert created["title"] == f"{short} Nguyễn Văn Cừ"
    assert created["workflow_variant"] == "OPENING_NEW_CINEMA_STANDARD"
    assert created["steps"] == 22
    assert [row["claim_status"] for row in claims(repository)] == ["COMPLETED"]

    assert deliver(terminal("EXECUTE_SUCCESS"), capsys) is None
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    # Replay: the pending record was spent by the confirmation.
    run_id = run_state()["run_id"]
    assert user_says("/solve Xác nhận tạo.")["decision"] == "block"
    assert run_state()["run_id"] == run_id
    assert len(projects(repository, merchant_id)) == 1


def test_merchant_changed_after_preview_is_refused_before_any_spend(merchant, capsys):
    repository, merchant_id, short = merchant
    operation = run_a(repository, short, capsys)

    with repository.connection() as connection:
        with connection.transaction():
            connection.execute(
                "UPDATE merchant_ops.merchants SET name = name || ' (renamed)',"
                " version = version + 1 WHERE id = %s::uuid",
                (merchant_id,),
            )

    assert "hookSpecificOutput" in user_says("/solve Xác nhận tạo.")
    reuse_teammate()
    before = snapshot(repository)
    assert deliver(execute_body(operation["argv"]), capsys, "execute-request") is None

    assert snapshot(repository) == before
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"].startswith("PREFLIGHT:")
    assert run_state().get("merchant_runtime_authorization_issued") is not True
    assert projects(repository, merchant_id) == []
    assert claims(repository) == []
