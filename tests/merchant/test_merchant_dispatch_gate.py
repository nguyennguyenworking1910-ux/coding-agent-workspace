"""Checkpoint 7.3 policy tests for exact Merchant Agent dispatch."""

import json
import sys
from pathlib import Path

import pytest

from claude.agents.tools.merchant.cli_contract import (
    build_confirmation_envelope,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = PROJECT_ROOT / ".claude" / "hooks"
SOLVE_PATH = PROJECT_ROOT / ".claude" / "commands" / "solve.md"
AGENT_PATH = PROJECT_ROOT / ".claude" / "agents" / "merchant-manager.md"

sys.path.insert(0, str(HOOKS_DIR))

import policy_gate  # noqa: E402
import runtime_state  # noqa: E402


PROJECT_ID = "00000000-0000-0000-0000-000000000001"


def _confirmation():
    return build_confirmation_envelope(
        "project update",
        "runtime",
        {
            "project_id": PROJECT_ID,
            "status": "IN_PROGRESS",
            "expected_version": 3,
        },
    ).to_dict()


def _state(
    *,
    operations=("merchant_apply",),
    selected_agents=("merchant-manager",),
    risk_level="external_write",
    confirmed=True,
    confirmation=None,
):
    state = {
        "request": "Apply the exact Merchant project update proposal",
        "task_class": "small_task",
        "risk_level": risk_level,
        "confirmed": confirmed,
        "operations": list(operations),
        "selected_agents": list(selected_agents),
        "limits": {
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 10,
            "max_run_budget_usd": 1.0,
        },
        "members_used": [],
        "total_tool_calls": 0,
        "total_tool_calls_regular": 0,
        "agent_rounds": 0,
    }

    if confirmation is not False:
        state["merchant_confirmation"] = (
            _confirmation()
            if confirmation is None
            else confirmation
        )

    return state


def _dispatch_payload(confirmation=None, **changes):
    payload = dict(confirmation or _confirmation())
    payload["authorized_mode"] = (
        policy_gate.MERCHANT_DISPATCH_MODE
    )
    payload.update(changes)
    return payload


def _prompt(payload=None):
    authorization = json.dumps(
        payload or _dispatch_payload(),
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    return (
        "Apply only the confirmed Merchant proposal. Runtime apply remains "
        "blocked until Gate 7.4.\n\n"
        f"{policy_gate.MERCHANT_DISPATCH_MARKER}\n"
        "```json\n"
        f"{authorization}\n"
        "```\n"
    )


def _tool_input(
    *,
    subagent_type="merchant-manager",
    name="merchant-manager",
    prompt=None,
):
    return {
        "subagent_type": subagent_type,
        "name": name,
        "prompt": _prompt() if prompt is None else prompt,
    }


def _decision(output):
    if output is None:
        return "allow"

    return output["hookSpecificOutput"]["permissionDecision"]


def _reason(output):
    return output["hookSpecificOutput"][
        "permissionDecisionReason"
    ]


def test_runtime_state_preserves_operations_without_token_or_payload():
    confirmation = _confirmation()
    state = runtime_state.new_state(
        request="Apply the exact Merchant project update proposal",
        task_class="small_task",
        risk_level="external_write",
        selected_agents=["merchant-manager"],
        limits={"max_members": 1},
        confirmed=True,
        operations=["merchant_apply"],
        merchant_confirmation=confirmation,
    )

    assert state["operations"] == ["merchant_apply"]
    assert state["merchant_confirmation"] == confirmation
    assert "confirmation_token" not in repr(state)
    assert "payload" not in state["merchant_confirmation"]


def test_exact_apply_dispatch_is_allowed_and_consumed_once():
    state = _state()

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(),
    )

    assert _decision(output) == "allow"
    assert state["members_used"] == ["merchant-manager"]
    assert state["merchant_dispatch_spent"] is True
    assert state["merchant_dispatch"] == {
        "operation": "merchant_apply",
        "subagent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
        "confirmation_hash": _confirmation()[
            "confirmation_hash"
        ],
    }
    assert "payload" not in state["merchant_dispatch"]


def test_second_apply_dispatch_with_same_confirmation_is_denied():
    state = _state()
    tool_input = _tool_input()

    assert policy_gate.apply_call(state, "Agent", tool_input) is None
    output = policy_gate.apply_call(state, "Agent", tool_input)

    assert _decision(output) == "deny"
    assert "already authorized one dispatch" in _reason(output)


@pytest.mark.parametrize(
    ("state_changes", "reason"),
    (
        ({"confirmation": False}, "missing or malformed"),
        ({"confirmed": False}, "exact confirmed state"),
        ({"risk_level": "write"}, "external_write or destructive"),
        (
            {"selected_agents": ("merchant-manager", "coder")},
            "exclusive merchant-manager",
        ),
    ),
)
def test_apply_dispatch_denies_missing_policy_authority(
    state_changes,
    reason,
):
    state = _state(**state_changes)

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(),
    )

    assert _decision(output) == "deny"
    assert reason in _reason(output)
    assert state["members_used"] == []
    assert "merchant_dispatch_spent" not in state


def test_apply_dispatch_denies_non_merchant_manager_even_if_selected():
    state = _state(selected_agents=("coder",))

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(subagent_type="coder", name="coder"),
    )

    assert _decision(output) == "deny"
    assert "exclusive merchant-manager" in _reason(output)
    assert state["members_used"] == []


def test_apply_dispatch_denies_mixed_operation_envelope():
    state = _state(operations=("merchant_apply", "schedule"))

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(),
    )

    assert _decision(output) == "deny"
    assert "cannot combine Merchant and non-Merchant" in _reason(output)


@pytest.mark.parametrize(
    "change",
    (
        {"contract_version": True},
        {"confirmation_version": True},
        {"command": "project show"},
        {"confirmation_hash": "0" * 64},
    ),
)
def test_apply_dispatch_revalidates_persisted_confirmation(change):
    confirmation = _confirmation()
    confirmation.update(change)
    state = _state(confirmation=confirmation)

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(prompt=_prompt(_dispatch_payload(confirmation))),
    )

    assert _decision(output) == "deny"
    assert "missing or malformed" in _reason(output)
    assert state["members_used"] == []


@pytest.mark.parametrize(
    "prompt",
    (
        "Apply the confirmed proposal without a binding block.",
        (
            "MERCHANT_DISPATCH_AUTHORIZATION_JSON\n"
            "```json\nnot-json\n```\n"
        ),
        (
            "MERCHANT_DISPATCH_AUTHORIZATION_JSON\n"
            "```json\n{}\n```\n"
        ),
    ),
)
def test_apply_dispatch_denies_missing_or_malformed_block(prompt):
    state = _state()

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(prompt=prompt),
    )

    assert _decision(output) == "deny"
    assert "exact dispatch binding" in _reason(output)
    assert state["members_used"] == []
    assert "merchant_dispatch_spent" not in state


def test_apply_dispatch_denies_duplicate_binding_block():
    state = _state()
    block = _prompt()

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(prompt=block + block),
    )

    assert _decision(output) == "deny"
    assert "exactly once" in _reason(output)


def test_apply_dispatch_denies_unexpected_binding_field():
    state = _state()
    payload = _dispatch_payload(password="never-accepted")

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(prompt=_prompt(payload)),
    )

    assert _decision(output) == "deny"
    assert "incomplete or unexpected" in _reason(output)
    assert "never-accepted" not in _reason(output)


@pytest.mark.parametrize(
    ("field", "changed_value"),
    (
        ("command", "step update"),
        ("database_target", "test"),
        ("expected_version", 4),
        ("payload_hash", "1" * 64),
        ("proposal_hash", "2" * 64),
        ("confirmation_hash", "3" * 64),
        ("authorized_mode", "APPLY"),
    ),
)
def test_apply_dispatch_denies_any_changed_binding(
    field,
    changed_value,
):
    state = _state()
    payload = _dispatch_payload(**{field: changed_value})

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(prompt=_prompt(payload)),
    )

    assert _decision(output) == "deny"
    assert "does not match the confirmed command" in _reason(output)
    assert state["members_used"] == []
    assert "merchant_dispatch_spent" not in state


@pytest.mark.parametrize(
    "operation",
    ("merchant_read", "merchant_propose"),
)
def test_non_apply_merchant_dispatch_rejects_apply_binding(operation):
    state = _state(operations=(operation,))

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(),
    )

    assert _decision(output) == "deny"
    assert "cannot carry Merchant apply confirmation" in _reason(output)


@pytest.mark.parametrize(
    "operation",
    ("merchant_read", "merchant_propose"),
)
def test_non_apply_merchant_dispatch_remains_available(operation):
    state = _state(
        operations=(operation,),
        risk_level=(
            "read_only" if operation == "merchant_read" else "write"
        ),
        confirmed=False,
        confirmation=False,
    )

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(prompt="Run the narrow Merchant operation only."),
    )

    assert _decision(output) == "allow"
    assert state["members_used"] == ["merchant-manager"]
    assert "merchant_dispatch_spent" not in state


def test_non_merchant_dispatch_rejects_injected_merchant_authority():
    state = _state(
        operations=("schedule",),
        selected_agents=("scheduler",),
        confirmation=False,
    )

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(
            subagent_type="scheduler",
            name="scheduler",
        ),
    )

    assert _decision(output) == "deny"
    assert "outside a classified Merchant operation" in _reason(output)


def test_ordinary_non_merchant_dispatch_is_unchanged():
    state = _state(
        operations=("schedule",),
        selected_agents=("scheduler",),
        confirmation=False,
    )

    output = policy_gate.apply_call(
        state,
        "Agent",
        _tool_input(
            subagent_type="scheduler",
            name="scheduler",
            prompt="Create the confirmed calendar event.",
        ),
    )

    assert _decision(output) == "allow"


def test_solve_and_agent_document_gate_7_3_boundary():
    solve = SOLVE_PATH.read_text(encoding="utf-8")
    agent = AGENT_PATH.read_text(encoding="utf-8")

    assert "Gate 7.3 permits one policy-validated" in solve
    assert "MERCHANT_DISPATCH_AUTHORIZATION_JSON" in solve
    assert policy_gate.MERCHANT_DISPATCH_MODE in solve
    assert "consumes the binding" in solve
    assert "Runtime `--apply` remains fail-closed" in solve
    assert "Gate 7.3 allows the policy hook" in agent
    assert "still does not provide the trusted runtime-write" in agent
    assert "Gate 7.4 trusted in-process authorization" in agent
