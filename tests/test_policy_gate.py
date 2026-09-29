"""Tests for policy_gate.py hook with real team lifecycle integration."""

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_DIR = PROJECT_ROOT / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"

sys.path.insert(0, str(HOOKS_DIR))

import team_lifecycle
import policy_gate
import pytest
from runtime_state import new_state

from team_lifecycle import (
    TEAM_STATE_DIR_ENV_VAR,
    TeammateAllocationDecision,
    TeammateLifecycleStatus,
    allocate_teammate,
    load_team_state,
    mark_bound_report_received,
    mark_teammate_idle_reusable,
    mark_teammate_running,
    release_reported_teammate_to_idle,
)

class PolicyGateAgentDispatchTests(unittest.TestCase):
    """Test policy_gate Agent dispatch with team lifecycle."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
        os.environ[TEAM_STATE_DIR_ENV_VAR] = self.temp_dir.name
        self.session_id = "test-session"

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(TEAM_STATE_DIR_ENV_VAR, None)
        else:
            os.environ[TEAM_STATE_DIR_ENV_VAR] = self.original_env
        self.temp_dir.cleanup()

    def test_apply_call_allows_create_decision(self):
        """Agent dispatch for new role is allowed (CREATE decision)."""
        state = {
            "run_id": "run-1",
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
            "members_used": [],
        }
        tool_input = {"subagent_type": "reviewer", "name": "reviewer"}

        result = policy_gate.apply_call(state, "Agent", tool_input, self.session_id)

        self.assertIsNone(result)
        self.assertEqual(state["members_used"], ["reviewer"])

        record = team_lifecycle.load_team_state(
            self.session_id
        )["teammates"]["reviewer"]
        self.assertEqual(record["status"], "RUNNING")
        self.assertEqual(record["current_run_id"], "run-1")
        self.assertEqual(record["current_task_id"], "run-1:reviewer")

    def test_create_without_run_id_fails_closed(self):
        """A teammate cannot be created without an exact run binding."""
        state = {
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
            "members_used": [],
        }

        result = policy_gate.apply_call(
            state,
            "Agent",
            {"subagent_type": "reviewer", "name": "reviewer"},
            self.session_id,
        )

        self.assertIsNotNone(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("requires the current run_id", reason)
        self.assertIsNone(
            team_lifecycle.load_team_state(self.session_id)
        )

    def test_member_limit_denial_does_not_create_team_state(self):
        """Budget validation runs before lifecycle state reservation."""
        state = {
            "run_id": "run-1",
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 0, "max_total_tool_calls": 10},
            "members_used": [],
        }

        result = policy_gate.apply_call(
            state,
            "Agent",
            {"subagent_type": "reviewer", "name": "reviewer"},
            self.session_id,
        )

        self.assertIsNotNone(result)
        self.assertIsNone(
            team_lifecycle.load_team_state(self.session_id)
        )

    def test_apply_call_denies_reuse_decision(self):
        """Agent dispatch for idle teammate is denied with SendMessage instruction."""
        decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
        mark_teammate_idle_reusable(self.session_id, "reviewer")

        state = {
            "run_id": "run-2",
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
            "members_used": ["reviewer"],
        }
        tool_input = {"subagent_type": "reviewer", "name": "reviewer"}

        result = policy_gate.apply_call(state, "Agent", tool_input, self.session_id)

        self.assertIsNotNone(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("SendMessage", reason)

    def test_apply_call_denies_busy_decision(self):
        """Agent dispatch for busy teammate is denied."""
        decision, name = allocate_teammate(self.session_id, "reviewer", "reviewer")
        mark_teammate_running(self.session_id, "reviewer", "run-1", "task-1")

        state = {
            "run_id": "run-2",
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
            "members_used": ["reviewer"],
        }
        tool_input = {"subagent_type": "reviewer", "name": "reviewer"}

        result = policy_gate.apply_call(state, "Agent", tool_input, self.session_id)

        self.assertIsNotNone(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("currently handling work", reason)

    def test_apply_call_denies_mismatched_name(self):
        """Agent dispatch with mismatched canonical name is denied."""
        state = {
            "selected_agents": ["reviewer"],
            "limits": {"max_members": 1, "max_total_tool_calls": 10},
        }
        tool_input = {"subagent_type": "reviewer", "name": "reviewer-2"}

        result = policy_gate.apply_call(state, "Agent", tool_input, self.session_id)

        self.assertIsNotNone(result)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("does not match the canonical name", reason)

    def test_canonical_names_for_all_roles(self):
        """All canonical roles are enforced."""
        roles = ["reviewer", "coder", "bug-fixer", "diagnostician", "red-team", "group-sales-manager", "merchant-manager", "scheduler"]

        for role in roles:
            state = {"selected_agents": [role], "limits": {"max_members": 1, "max_total_tool_calls": 10}, "members_used": []}
            result = policy_gate.apply_call(state, "Agent", {"subagent_type": role, "name": role}, None)
            self.assertIsNone(result, f"Canonical name should be allowed for {role}")


class PolicyGateHookTests(unittest.TestCase):
    """Test policy_gate.main() hook."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_env = os.environ.get(TEAM_STATE_DIR_ENV_VAR)
        os.environ[TEAM_STATE_DIR_ENV_VAR] = self.temp_dir.name
        self.session_id = "test-session"

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop(TEAM_STATE_DIR_ENV_VAR, None)
        else:
            os.environ[TEAM_STATE_DIR_ENV_VAR] = self.original_env
        self.temp_dir.cleanup()

    def run_hook(self, hook_input):
        """Run hook main with JSON input."""
        original_stdin = sys.stdin
        original_stdout = sys.stdout

        try:
            sys.stdin = StringIO(json.dumps(hook_input))
            sys.stdout = StringIO()
            policy_gate.main()
            output = sys.stdout.getvalue()
            return json.loads(output) if output else None
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

    def test_hook_ignores_request_without_run_state(self):
        """Hook ignores Agent dispatch when no run state exists (not a /solve run)."""
        output = self.run_hook({
            "session_id": self.session_id,
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "reviewer", "name": "reviewer"},
        })
        self.assertIsNone(output)


def test_delivered_teammate_cannot_use_more_tools(
    monkeypatch,
    tmp_path,
):
    lead_session = "lead-post-delivery-freeze"
    teammate = "merchant-manager"
    run_id = "run-post-delivery-freeze"
    task_id = f"{run_id}:{teammate}"

    # Isolate team lifecycle state for this test.
    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(tmp_path / "team_state"),
    )

    decision, name = allocate_teammate(
        lead_session,
        teammate,
        teammate,
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session,
        name,
        run_id,
        task_id,
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            teammate,
        ],
    )

    assert mark_bound_report_received(
        lead_session,
        teammate,
        run_id,
        task_id,
        "sendmessage",
    )

    decision = (
        policy_gate.completed_teammate_tool_decision(
            teammate
        )
    )

    assert decision is not None

    assert (
        decision[
            "hookSpecificOutput"
        ][
            "permissionDecision"
        ]
        == "deny"
    )

    reason = (
        decision[
            "hookSpecificOutput"
        ][
            "permissionDecisionReason"
        ]
    )

    assert "RESULT_DELIVERED" in reason


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        (
            "Bash",
            {
                "command": "echo should-not-run",
            },
        ),
        (
            "Read",
            {
                "file_path": "README.md",
            },
        ),
        (
            "SendMessage",
            {
                "recipient": "team-lead",
                "message": "duplicate result",
            },
        ),
        (
            "TaskUpdate",
            {
                "taskId": "task-1",
                "status": "completed",
            },
        ),
    ],
)
def test_policy_gate_main_freezes_teammate_after_delivery(
    monkeypatch,
    tmp_path,
    capsys,
    tool_name,
    tool_input,
):
    import json
    from io import StringIO

    lead_session = "lead-post-delivery-main"
    pane_session = "pane-post-delivery-main"
    teammate = "merchant-manager"
    run_id = "run-post-delivery-main"
    task_id = f"{run_id}:{teammate}"

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(tmp_path / "team_state"),
    )

    decision, name = allocate_teammate(
        lead_session,
        teammate,
        teammate,
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session,
        name,
        run_id,
        task_id,
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            teammate,
        ],
    )

    assert mark_bound_report_received(
        lead_session,
        teammate,
        run_id,
        task_id,
        "sendmessage",
    )

    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": pane_session,
        "agent_type": teammate,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }

    monkeypatch.setattr(
        policy_gate.sys,
        "stdin",
        StringIO(
            json.dumps(payload)
        ),
    )

    exit_code = policy_gate.main()

    assert exit_code == 0

    captured = capsys.readouterr()

    assert captured.out.strip()

    response = json.loads(
        captured.out
    )

    specific = response[
        "hookSpecificOutput"
    ]

    assert (
        specific["permissionDecision"]
        == "deny"
    )

    reason = specific[
        "permissionDecisionReason"
    ]

    assert "RESULT_DELIVERED" in reason
    assert "already been delivered" in reason


def test_lead_cannot_wake_completed_teammate_again_in_same_run(
    monkeypatch,
    tmp_path,
):
    lead_session = "lead-same-run-freeze"
    teammate = "merchant-manager"
    run_id = "run-same-run-freeze"
    task_id = f"{run_id}:{teammate}"

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(tmp_path / "team_state"),
    )

    state = new_state(
        request="merchant read",
        task_class="small_task",
        risk_level="read_only",
        selected_agents=[
            teammate,
        ],
        operations=[
            "merchant_read",
        ],
        limits={
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 10,
            "max_run_budget_usd": 1.0,
        },
        confirmed=False,
        run_id=run_id,
    )

    decision, name = allocate_teammate(
        lead_session,
        teammate,
        teammate,
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session,
        name,
        run_id,
        task_id,
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            teammate,
        ],
    )

    assert mark_bound_report_received(
        lead_session,
        teammate,
        run_id,
        task_id,
        "sendmessage",
    )

    released, _ = (
        release_reported_teammate_to_idle(
            lead_session,
            teammate,
        )
    )

    assert released is True

    decision = policy_gate._check_teammate_message(
        state,
        {
            "recipient": teammate,
            "message": "acknowledged, please remain idle",
        },
        lead_session,
        "",
    )

    assert decision is not None

    specific = decision[
        "hookSpecificOutput"
    ]

    assert (
        specific["permissionDecision"]
        == "deny"
    )

    assert (
        "already completed"
        in specific[
            "permissionDecisionReason"
        ]
    )


def test_new_run_can_reuse_previously_completed_teammate(
    monkeypatch,
    tmp_path,
):
    lead_session = "lead-new-run-reuse"
    teammate = "merchant-manager"

    monkeypatch.setenv(
        "CLAUDE_TEAM_STATE_DIR",
        str(tmp_path / "team_state"),
    )

    old_run = "run-old"
    old_task = f"{old_run}:{teammate}"

    decision, name = allocate_teammate(
        lead_session,
        teammate,
        teammate,
    )

    assert (
        decision
        == TeammateAllocationDecision.CREATE
    )

    assert mark_teammate_running(
        lead_session,
        name,
        old_run,
        old_task,
        operations=[
            "merchant_read",
        ],
        selected_agents=[
            teammate,
        ],
    )

    assert mark_bound_report_received(
        lead_session,
        teammate,
        old_run,
        old_task,
        "sendmessage",
    )

    released, _ = (
        release_reported_teammate_to_idle(
            lead_session,
            teammate,
        )
    )

    assert released is True

    new_run = "run-new"

    new_state_value = new_state(
        request="another merchant read",
        task_class="small_task",
        risk_level="read_only",
        selected_agents=[
            teammate,
        ],
        operations=[
            "merchant_read",
        ],
        limits={
            "max_members": 1,
            "max_tool_rounds": 1,
            "max_total_tool_calls": 10,
            "max_run_budget_usd": 1.0,
        },
        confirmed=False,
        run_id=new_run,
    )

    decision = policy_gate._check_teammate_message(
        new_state_value,
        {
            "recipient": teammate,
            "message": "new bounded assignment",
        },
        lead_session,
        "",
    )

    # None means policy allowed the message.
    assert decision is None

    team_state = load_team_state(
        lead_session
    )

    record = team_state[
        "teammates"
    ][
        teammate
    ]

    assert (
        record["status"]
        == TeammateLifecycleStatus.RUNNING.value
    )

    assert (
        record["current_run_id"]
        == new_run
    )


def test_merchant_propose_agent_assignment_rejects_concrete_cli():
    state = {
        "operations": ["merchant_propose"],
        "selected_agents": ["merchant-manager"],
        "merchant_confirmation": None,
    }

    decision = policy_gate._check_merchant_dispatch(
        state,
        "merchant-manager",
        "merchant-manager",
        {
            "prompt": (
                "Objective: create the requested cinema project.\n"
                "project create --project-type OPENING_NEW_CINEMA "
                "--workflow-variant OPENING_NEW_CINEMA_STANDARD "
                "--propose"
            )
        },
    )

    assert decision is not None

    output = decision["hookSpecificOutput"]

    assert output["permissionDecision"] == "deny"
    assert "semantic-only" in output[
        "permissionDecisionReason"
    ]


def test_merchant_propose_reuse_assignment_rejects_concrete_cli():
    state = {
        "operations": ["merchant_propose"],
        "selected_agents": ["merchant-manager"],
        "merchant_confirmation": None,
    }

    decision = policy_gate._check_merchant_dispatch(
        state,
        "merchant-manager",
        "merchant-manager",
        {
            "message": (
                "Resolve AEON Beta first.\n"
                "project resolve --merchant-id <id> "
                '--query "Mở rạp mới AEON Beta Hải Dương"'
            )
        },
    )

    assert decision is not None

    output = decision["hookSpecificOutput"]

    assert output["permissionDecision"] == "deny"
    assert "semantic-only" in output[
        "permissionDecisionReason"
    ]


def test_merchant_propose_semantic_assignment_is_allowed():
    state = {
        "operations": ["merchant_propose"],
        "selected_agents": ["merchant-manager"],
        "merchant_confirmation": None,
    }

    decision = policy_gate._check_merchant_dispatch(
        state,
        "merchant-manager",
        "merchant-manager",
        {
            "prompt": (
                "Objective: prepare a proposal to create a new "
                "cinema-opening project for AEON Beta.\n"
                "Operation: merchant_propose\n"
                "Database target: runtime\n"
                "Authorized mode: PROPOSE\n"
                "Resolve authoritative Merchant and Project state "
                "through registered reads.\n"
                "Resolve the normalized write command from the "
                "registered Merchant contract.\n"
                "Run deterministic completeness before proposing.\n"
                "Do not apply any mutation."
            )
        },
    )

    assert decision is None


def test_reuse_path_validates_before_lifecycle_reservation(
    monkeypatch,
):
    state = {
        "run_id": "run-command-authority",
        "operations": ["merchant_propose"],
        "selected_agents": ["merchant-manager"],
        "merchant_confirmation": None,
        "members_used": [],
        "limits": {
            "max_members": 1,
        },
    }

    reservation_called = False

    def fake_reserve(*args, **kwargs):
        nonlocal reservation_called
        reservation_called = True
        return True, "IDLE_REUSABLE"

    monkeypatch.setattr(
        policy_gate,
        "reserve_reusable_teammate",
        fake_reserve,
    )

    decision = policy_gate._check_teammate_message(
        state,
        {
            "recipient": "merchant-manager",
            "message": (
                "Objective: create project.\n"
                "project create --type OPENING_NEW_CINEMA "
                "--propose"
            ),
        },
        "lead-session",
        "",
    )

    assert decision is not None
    assert reservation_called is False

    output = decision["hookSpecificOutput"]

    assert output["permissionDecision"] == "deny"
    assert "semantic-only" in output[
        "permissionDecisionReason"
    ]

if __name__ == "__main__":
    unittest.main()
