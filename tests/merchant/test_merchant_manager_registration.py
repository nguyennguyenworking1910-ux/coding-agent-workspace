"""Registration and /solve routing tests for Merchant Manager."""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / ".claude" / "agents.json"
AGENT_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "agents"
    / "merchant-manager.md"
)
SOLVE_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "commands"
    / "solve.md"
)


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _merchant_entry() -> dict:
    matches = [
        agent
        for agent in _registry()["agents"]
        if agent["id"] == "merchant-manager"
    ]

    assert len(matches) == 1
    return matches[0]


def _agent_frontmatter() -> dict[str, str]:
    content = AGENT_PATH.read_text(encoding="utf-8")
    fields = {}

    for line in content.splitlines()[1:]:
        if line == "---":
            break

        key, separator, value = line.partition(":")

        if separator:
            fields[key.strip()] = value.strip()

    return fields


def test_registry_contains_one_enabled_merchant_manager():
    entry = _merchant_entry()

    assert entry["enabled"] is True
    assert entry["name"] == "Merchant Manager"
    assert entry["type"] == "merchant_manager"
    assert entry["permissions"] == "write-confirming"
    assert entry["definition"] == (
        ".claude/agents/merchant-manager.md"
    )


def test_registry_runtime_matches_dispatch_frontmatter():
    entry = _merchant_entry()
    frontmatter = _agent_frontmatter()

    assert entry["runtime"]["model"] == frontmatter["model"]
    assert str(entry["runtime"]["max_turns"]) == (
        frontmatter["maxTurns"]
    )
    assert entry["tools"] == [
        item.strip()
        for item in frontmatter["tools"].split(",")
    ]


def test_registry_targets_only_the_runtime_cli_entry_point():
    access = _merchant_entry()["merchant_access"]

    assert access["enabled"] is True
    assert access["entry_point"] == (
        ".claude/agents/tools/merchant/agent_cli.py"
    )
    assert access["database_target"] == "runtime"
    assert "credential-free" not in access["entry_point"]
    assert "password" not in access["entry_point"].lower()
    assert access["runtime_handoff"] == (
        ".claude/system/merchant_runtime_handoff.py"
    )
    assert access["runtime_handoff_method"] == (
        "invoke_confirmed_merchant_session_apply"
    )


def test_credential_safe_merchant_cli_tool_is_registered():
    matching = [
        tool
        for tool in _registry()["tools"]
        if tool["id"] == "merchant_cli"
    ]

    assert len(matching) == 1
    tool = matching[0]
    assert tool["enabled"] is True
    assert tool["module"] == (
        "claude.agents.tools.merchant.agent_cli"
    )
    assert tool["entry_point"] == (
        ".claude/agents/tools/merchant/agent_cli.py"
    )
    assert tool["database_target"] == "runtime"
    assert tool["credential_arguments"] == "forbidden"
    assert tool["runtime_apply"] == (
        "denied_in_ordinary_agent_cli"
    )
    assert {
        method["name"]
        for method in tool["methods"]
    } == {"prepare_agent_cli_argv", "invoke_agent_cli"}


def test_registry_freezes_the_read_operation_allowlist():
    operations = set(
        _merchant_entry()["merchant_access"][
            "read_operations"
        ]
    )

    assert operations == {
        "merchant list",
        "project list",
        "project show",
        "project history",
        "project blockers",
        "project alerts",
    }


def test_registry_freezes_the_write_operation_allowlist():
    operations = set(
        _merchant_entry()["merchant_access"][
            "write_operations"
        ]
    )

    assert operations == {
        "merchant activate",
        "merchant activate-all",
        "merchant create",
        "contact import",
        "project create",
        "project update",
        "step update",
        "document revision-create",
        "document approve",
        "procurement update",
        "integration identifier-set",
    }


def test_registry_separates_ordinary_cli_from_trusted_handoff():
    access = _merchant_entry()["merchant_access"]

    assert access["checkpoint_6_write_mode"] == "propose_only"
    assert access["runtime_apply"] == (
        "trusted_in_process_handoff_only"
    )
    assert access["runtime_handoff"] == (
        ".claude/system/merchant_runtime_handoff.py"
    )
    assert access["runtime_handoff_method"] == (
        "invoke_confirmed_merchant_session_apply"
    )
    assert "without reading or passing database credentials" in (
        access["note"]
    )
    assert "ordinary CLI remains read/propose-only" in access["note"]
    assert "opaque in-process handoff" in access["note"]


def test_no_other_agent_claims_merchant_access():
    registry = _registry()
    owners = [
        agent["id"]
        for agent in registry["agents"]
        if agent.get("merchant_access", {}).get("enabled")
    ]

    assert owners == ["merchant-manager"]


def test_solve_command_dispatches_the_registered_agent():
    registry = _registry()
    solve = next(
        command
        for command in registry["commands"]
        if command["id"] == "solve"
    )

    assert solve["dispatches"].count("merchant-manager") == 1
    assert set(solve["dispatches"]) == {
        agent["id"]
        for agent in registry["agents"]
        if agent["enabled"]
    }


def test_solve_authorized_roster_documents_merchant_manager():
    content = SOLVE_PATH.read_text(encoding="utf-8")

    assert "| `merchant-manager` |" in content
    assert "Proposal only; runtime apply blocked" in content
    assert "### Merchant routing contract" in content


def test_solve_routes_operational_work_to_one_owner():
    content = SOLVE_PATH.read_text(encoding="utf-8")

    assert "Merchant operational work has one owner" in content
    assert "A Merchant-state read may be assigned only" in content
    assert "A Merchant write-intent proposal may be assigned only" in (
        content
    )
    assert "The lead must never run the Merchant CLI" in content


def test_solve_requires_selected_agent_authority():
    content = SOLVE_PATH.read_text(encoding="utf-8")

    assert (
        "`merchant-manager` is absent from\n"
        "  `selected_agents`, report the authorization mismatch and stop"
    ) in content
    assert "Do not add the teammate" in content
    assert "substitute another role" in content


def test_solve_does_not_treat_proposal_hash_as_authority():
    content = SOLVE_PATH.read_text(encoding="utf-8")

    assert "Runtime `--apply` remains unavailable in Checkpoint 6" in (
        content
    )
    assert "Checkpoint 7 intent/policy authorization handoff" in content
    assert "It is not permission" in content


def test_system_test_requires_the_registered_definition():
    content = (
        PROJECT_ROOT / ".claude" / "system_test.py"
    ).read_text(encoding="utf-8")

    assert (
        "'.claude/agents/merchant-manager.md'"
        in content
    )
