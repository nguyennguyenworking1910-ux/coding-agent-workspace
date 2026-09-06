"""Structural contract tests for the Merchant Manager teammate."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "agents"
    / "merchant-manager.md"
)


def _content() -> str:
    return AGENT_PATH.read_text(encoding="utf-8")


def _normalized_content() -> str:
    return " ".join(_content().split())


def _frontmatter() -> dict[str, str]:
    content = _content()
    assert content.startswith("---\n")

    fields = {}

    for line in content.splitlines()[1:]:
        if line == "---":
            break

        key, separator, value = line.partition(":")

        if separator:
            fields[key.strip()] = value.strip()

    return fields


def test_agent_frontmatter_is_dispatchable_and_bounded():
    fields = _frontmatter()

    assert fields["name"] == "merchant-manager"
    assert fields["tools"] == (
        "Read, Bash, SendMessage, TaskUpdate"
    )
    assert fields["model"] == "haiku"
    assert fields["permissionMode"] == "default"
    assert fields["maxTurns"] == "12"


def test_agent_reads_architecture_before_work():
    content = _content()

    assert "Before doing anything else" in content
    assert ".claude/documents/ARCHITECTURE.md" in content
    assert (
        ".claude/documents/MERCHANT_PROJECT_MANAGER.md"
        in content
    )


def test_agent_uses_only_the_registered_runtime_cli_boundary():
    content = _content()

    assert (
        "python .claude/agents/tools/merchant/agent_cli.py "
        "<resource> <action> [arguments]"
    ) in content
    assert "does not accept a\n`--database` argument" in content
    assert "never run `psql`" in content
    assert "never connect to PostgreSQL directly" in content
    assert "never import a Merchant repository" in content


def test_agent_carries_the_complete_read_allowlist():
    content = _content()
    read_commands = {
        "merchant list",
        "project list",
        "project show",
        "project history",
        "project blockers",
        "project alerts",
    }

    for command in read_commands:
        assert f"`{command}`" in content


def test_agent_carries_the_complete_write_allowlist():
    content = _content()
    write_commands = {
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

    for command in write_commands:
        assert f"`{command}`" in content


def test_agent_requires_propose_before_any_future_apply():
    content = _content()

    assert "`--propose` / `--apply`" in content
    assert "run the exact allowlisted command" in content
    assert "in `--propose` mode first" in content
    assert "requires_confirmation: true" in content
    assert "no change has been applied" in content


def test_agent_fails_closed_without_checkpoint_7_authority():
    content = _content()

    assert (
        "do not execute any runtime command in `--apply` mode"
        in content
    )
    assert "runtime_authorized=True" in content
    assert "Checkpoint 7" in content
    assert "successful fail-closed outcome" in content


def test_agent_does_not_expose_or_source_credentials():
    content = _content()

    assert "never read, source, echo, or print `.env`" in content
    assert (
        "never add or infer a database target, host, port, user, "
        "password, DSN, or credential argument"
    ) in content
    assert "Preserve `[REDACTED]`" in content
    assert "values exactly" in content


def test_agent_preserves_parallel_project_state():
    content = _content()

    assert "all active workflow steps" in content
    assert "`branch_key`" in content
    assert "parallel UAT and Production branches" in content


def test_agent_uses_cli_json_and_exit_status_as_evidence():
    content = _normalized_content()

    assert "CLI returns JSON and exits non-zero on failure" in content
    assert "only evidence that an operation succeeded" in content
    assert "Never invent state" in content


def test_agent_reports_through_supported_team_tools():
    content = _content()

    assert "mark it completed with `TaskUpdate`" in content
    assert "final action" in content.lower()
    assert "send the complete report to `team-lead`" in content
    assert "with `SendMessage`" in content
    assert "retry it once" in content


def test_agent_does_not_mutate_the_repository():
    content = _content()

    assert "Never edit project files" in content
    assert "commit, push, create branches" in content


def test_agent_keeps_rag_supplemental_and_untrusted():
    content = _content()

    assert "## Workspace knowledge retrieval" in content
    assert "python .claude/rag_search.py" in content
    assert "agent -> rag tool -> RagClient -> RAG API" in content
    assert "untrusted reference data" in content
    assert "never authoritative for current Merchant" in content
