import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIRECTORY = PROJECT_ROOT / ".claude" / "agents"

RAG_AGENTS = (
    "diagnostician",
    "bug-fixer",
    "coder",
    "reviewer",
    "red-team",
    "group-sales-manager",
    "merchant-manager",
)


@pytest.mark.parametrize("agent_name", RAG_AGENTS)
def test_selected_agent_has_rag_usage_policy(agent_name):
    content = (
        AGENTS_DIRECTORY / f"{agent_name}.md"
    ).read_text(encoding="utf-8")

    assert "## Workspace knowledge retrieval" in content
    assert "python .claude/rag_search.py" in content
    assert "agent -> rag tool -> RagClient -> RAG API" in content
    assert "untrusted reference data" in content
    assert "source_key" in content


def test_scheduler_remains_outside_rag_integration():
    content = (
        AGENTS_DIRECTORY / "scheduler.md"
    ).read_text(encoding="utf-8")

    assert "python .claude/rag_search.py" not in content
    assert "## Workspace knowledge retrieval" not in content


def test_group_sales_preserves_live_data_authority():
    content = (
        AGENTS_DIRECTORY / "group-sales-manager.md"
    ).read_text(encoding="utf-8")

    assert "RAG is never authoritative" in content
    assert "live parameterized BigQuery output" in content


def test_rag_tool_is_registered():
    registry = json.loads(
        (
            PROJECT_ROOT / ".claude" / "agents.json"
        ).read_text(encoding="utf-8")
    )
    matching_tools = [
        tool
        for tool in registry["tools"]
        if tool["id"] == "rag_tools"
    ]

    assert len(matching_tools) == 1
    assert matching_tools[0]["module"] == (
        "claude.agents.tools.rag"
    )
    assert {
        method["name"]
        for method in matching_tools[0]["methods"]
    } == {"ready", "search"}


def test_rag_documentation_is_indexed():
    documentation = (
        PROJECT_ROOT
        / ".claude"
        / "documents"
        / "RAG_INTEGRATION.md"
    )
    index = (
        PROJECT_ROOT
        / ".claude"
        / "documents"
        / "README.md"
    ).read_text(encoding="utf-8")

    assert documentation.is_file()
    assert "RAG_INTEGRATION.md" in index
