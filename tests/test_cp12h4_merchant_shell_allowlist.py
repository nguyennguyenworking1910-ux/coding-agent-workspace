"""CP12H.4B: merchant-manager may run exactly one direct agent_cli.py call.

The shell policy is an allowlist, not a substring denylist. It is defense
in depth: the privileged write APIs independently require durable
reservations and spent user authority (see test_cp12h4_write_boundary).
"""

from __future__ import annotations

import io
import json
import sys

import pytest

from claude.hooks import policy_gate


CLI = ".claude/agents/tools/merchant/agent_cli.py"


def _decision(command, *, tool="Bash", agent="merchant-manager"):
    return policy_gate.merchant_runtime_bypass_decision(
        {
            "agent_type": agent,
            "tool_name": tool,
            "tool_input": {"command": command},
        }
    )


def _denied(decision):
    return (
        decision is not None
        and decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    )


BYPASSES = {
    "importlib": (
        "python -c \"import importlib;m=importlib.import_module("
        "'claude.system.'+'merchant_runtime'+'_handoff')\""
    ),
    "direct-handoff-import": (
        'python -c "from claude.hooks.merchant_direct_handoff '
        'import invoke_direct_merchant_execute"'
    ),
    "runtime-repository": (
        "python -c \"from claude.clients.merchant.repository import "
        "MerchantRepository; MerchantRepository(role='runtime')\""
    ),
    "forged-hook-pipe": (
        "echo {} | .venv/Scripts/python.exe .claude/hooks/team_result_hook.py"
    ),
    "forged-hook-redirect": (
        "python .claude/hooks/team_result_hook.py < forged.json"
    ),
    "python-module": "python -m claude.system.merchant_runtime_handoff",
    "interpreter-flag": f"python -X importtime {CLI} project list",
    "isolated-flag": f"python -I {CLI} project list",
    "chained-semicolon": f"python {CLI} project list; python -c 'x'",
    "chained-and": f"python {CLI} project list && python -c 'x'",
    "chained-or": f"python {CLI} project list || python -c 'x'",
    "pipe": f"python {CLI} project list | python -c 'x'",
    "background": f"python {CLI} project list & python -c 'x'",
    "substitution": f"python {CLI} project list $(python -c 'x')",
    "backtick": f"python {CLI} project list `python -c x`",
    "dq-substitution": f'python {CLI} project list --name "$(id)"',
    "newline": f"python {CLI} project list\npython -c 'x'",
    "redirect-out": f"python {CLI} project list > out.json",
    "env-assignment": f"PYTHONSTARTUP=evil.py python {CLI} project list",
    "env-command": f"env PYTHONPATH=evil python {CLI} project list",
    "other-script": "python ./evil/agent_cli.py project list",
    "path-traversal": (
        "python .claude/agents/tools/merchant/../../../hooks/"
        "team_result_hook.py"
    ),
    "encoded-powershell": "powershell -EncodedCommand SQBFAFgA",
    "pwsh": "pwsh -c 'Get-ChildItem'",
    "bash-c": f"bash -c 'python {CLI} project list'",
    "node": "node -e 'require(\"child_process\")'",
    "perl": "perl -e 'system(1)'",
    "cd": "cd /tmp",
    "cat-env": "cat .claude/clients/.env",
    "glob": f"python {CLI} project list *",
    "brace": f"python {CLI} project {{list,show}}",
    "backslash-escape": f"python {CLI} project list \\; id",
    "empty": "",
}


@pytest.mark.parametrize("command", BYPASSES.values(), ids=BYPASSES.keys())
def test_merchant_manager_bypass_commands_are_denied(command):
    assert _denied(_decision(command))


@pytest.mark.parametrize(
    "tool",
    ["PowerShell", "BashOutput", "Write", "Edit", "MultiEdit", "NotebookEdit"],
)
def test_merchant_manager_non_bash_execution_tools_are_denied(tool):
    assert _denied(_decision(f"python {CLI} project list", tool=tool))


ALLOWED = {
    "project-list": f"python {CLI} project list",
    "venv-interpreter": (
        f".venv/Scripts/python.exe {CLI} merchant resolve --name 'Acme Co'"
    ),
    "quoted-script": f'python "{CLI}" project show '
    "00000000-0000-0000-0000-000000000001",
    "completeness": (
        f'python {CLI} completeness check --command "merchant create" '
        "--payload-json '{\"code\": \"X\", \"name\": \"Y $1\"}'"
    ),
}


@pytest.mark.parametrize("command", ALLOWED.values(), ids=ALLOWED.keys())
def test_exact_agent_cli_invocations_remain_allowed(command):
    assert _decision(command) is None


@pytest.mark.parametrize("tool", ["Read", "SendMessage", "TaskUpdate"])
def test_non_execution_tools_are_not_shell_policed(tool):
    assert _decision("anything", tool=tool) is None


def test_other_roles_are_not_restricted_by_merchant_allowlist():
    assert _decision("python -c 'print(1)'", agent="coder") is None
    assert _decision("python -c 'print(1)'", agent="") is None


def test_policy_hook_entrypoint_denies_merchant_bypass(monkeypatch, tmp_path):
    """The real PreToolUse entry point applies the allowlist."""

    monkeypatch.setenv("CLAUDE_TEAM_STATE_DIR", str(tmp_path / "team"))
    monkeypatch.setenv("CLAUDE_RUNTIME_STATE_DIR", str(tmp_path / "rt"))

    payload = {
        "hook_event_name": "PreToolUse",
        "agent_type": "merchant-manager",
        "session_id": "pane-x",
        "tool_name": "Bash",
        "tool_input": {"command": BYPASSES["direct-handoff-import"]},
    }

    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, "stdout", out)

    assert policy_gate.main() == 0

    decision = json.loads(out.getvalue())
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_registered_rag_search_is_allowed_exactly():
    assert _decision(
        'python .claude/rag_search.py "merchant onboarding" --top-k 5'
    ) is None
    assert _denied(_decision("python -I .claude/rag_search.py q"))
    assert _denied(_decision("python .claude/rag_search.py"))
    assert _denied(_decision("python .claude/rag_search.py q; id"))
