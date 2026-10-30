"""Direct-only PostToolUse dispatch contract."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT / ".claude/hooks/post_tool_orchestrator.py"
)


def test_posttool_does_not_stage_legacy_merchant_proposals():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))

    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "handle_post_tool_use"
    ]
    assert len(functions) == 1

    entrypoint = functions[0]
    invoked = {
        node.func.id
        for node in ast.walk(entrypoint)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
    }

    assert "_stage_exact_tmux_merchant_proposal" not in invoked
    assert "merchant_proposal_from_tool_response" not in invoked

    # Direct observation must remain available.
    assert "merchant_execute_from_tool_response" in invoked
    assert "validated_merchant_execute_invocation" in invoked



def test_posttool_legacy_staging_branch_is_absent():
    """No Merchant proposal may be staged from PostToolUse."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))

    handlers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "handle_post_tool_use"
    ]

    assert len(handlers) == 1

    calls = [
        ast.unparse(node.func)
        for node in ast.walk(handlers[0])
        if isinstance(node, ast.Call)
    ]

    assert not any(
        "_stage_exact_tmux_merchant_proposal" in call
        for call in calls
    )

    assert not any(
        "merchant_proposal_from_tool_response" in call
        for call in calls
    )
