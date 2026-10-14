from __future__ import annotations

import ast
from pathlib import Path


DEPENDENCY_MODULES = (
    Path(
        ".claude/hooks/post_tool_orchestrator.py"
    ),
    Path(
        ".claude/hooks/merchant_runtime_orchestration.py"
    ),
    Path(
        ".claude/hooks/teammate_idle_orchestrator.py"
    ),
    Path(
        ".claude/hooks/merchant_resolution_tool_contract.py"
    ),
    Path(
        ".claude/hooks/team_result_dispatcher.py"
    ),
)


EXPECTED_TOTAL_FIELDS = 101

MINIMUM_PRECISE_FIELDS = 85


ALLOWED_LOOSE_FIELDS = {
    (
        "merchant_runtime_orchestration.py",
        "shlex",
        "Any",
    ),

    (
        "teammate_idle_orchestrator.py",
        "MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES",
        "Any",
    ),

    (
        "merchant_resolution_tool_contract.py",
        "json",
        "Any",
    ),

    (
        "merchant_resolution_tool_contract.py",
        "shlex",
        "Any",
    ),

    (
        "merchant_resolution_tool_contract.py",
        "unicodedata",
        "Any",
    ),

    (
        "team_result_dispatcher.py",
        "HOOK_EVENT_NAMES",
        "Any",
    ),

    (
        "team_result_dispatcher.py",
        "MerchantRuntimeHandoffStageError",
        "Any",
    ),

    (
        "team_result_dispatcher.py",
        "io",
        "Any",
    ),

    (
        "team_result_dispatcher.py",
        "json",
        "Any",
    ),

    (
        "team_result_dispatcher.py",
        "redirect_stderr",
        "Callable[..., Any]",
    ),

    (
        "team_result_dispatcher.py",
        "redirect_stdout",
        "Callable[..., Any]",
    ),

    (
        "team_result_dispatcher.py",
        "sys",
        "Any",
    ),
}


SECURITY_CRITICAL_FIELDS = {
    "find_unique_active_teammate_owner",
    "locked_state",
    "record_teammate_result",
    "release_reported_teammate_to_idle",
    "trusted_post_tool_sender",
    "trusted_teammate_pane_session_matches",
    "validate_merchant_resolution_result",
    "capture_proposal_receipt",
    "stage_runtime_handoff_attempt",
    "validate_completeness_receipt_for_outcome",
    "invoke_confirmed_merchant_session_apply",
    "contains_handoff_marker",
    "pending_merchant_completeness_matches",
    "pending_merchant_proposal_matches",
    "failed_runtime_handoff_matches",
    "successful_runtime_handoff_matches",
}


def _dependency_fields():
    fields = []

    for path in DEPENDENCY_MODULES:

        tree = ast.parse(
            path.read_text(
                encoding="utf-8-sig"
            )
        )

        contracts = [
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.ClassDef,
                )
                and node.name.endswith(
                    "Dependencies"
                )
            )
        ]

        assert (
            len(contracts) == 1
        ), (
            f"{path}: expected exactly one "
            f"dependency contract"
        )

        contract = contracts[0]

        for node in contract.body:

            if (
                not isinstance(
                    node,
                    ast.AnnAssign,
                )
                or not isinstance(
                    node.target,
                    ast.Name,
                )
            ):
                continue

            fields.append(
                (
                    path.name,
                    node.target.id,
                    ast.unparse(
                        node.annotation
                    ),
                )
            )

    return fields


def test_dependency_field_count_is_stable():
    fields = _dependency_fields()

    assert (
        len(fields)
        == EXPECTED_TOTAL_FIELDS
    ), (
        "Dependency field count changed. "
        f"Expected {EXPECTED_TOTAL_FIELDS}, "
        f"got {len(fields)}"
    )


def test_dependency_precision_does_not_regress():
    fields = _dependency_fields()

    loose = [
        item
        for item in fields
        if item[2] in {
            "Any",
            "Callable[..., Any]",
        }
    ]

    precise = (
        len(fields)
        - len(loose)
    )

    assert (
        precise
        >= MINIMUM_PRECISE_FIELDS
    ), (
        "Dependency type precision regressed: "
        f"{precise}/{len(fields)} precise, "
        f"minimum is {MINIMUM_PRECISE_FIELDS}"
    )


def test_only_explicitly_allowed_fields_may_remain_loose():
    fields = _dependency_fields()

    loose = {
        item
        for item in fields
        if item[2] in {
            "Any",
            "Callable[..., Any]",
        }
    }

    unexpected = (
        loose
        - ALLOWED_LOOSE_FIELDS
    )

    missing = (
        ALLOWED_LOOSE_FIELDS
        - loose
    )

    assert unexpected == set(), (
        "Unexpected loose dependency fields: "
        f"{sorted(unexpected)}"
    )

    assert missing == set(), (
        "Loose-field allowlist changed unexpectedly: "
        f"{sorted(missing)}"
    )


def test_security_critical_fields_are_never_loose():
    fields = _dependency_fields()

    violations = [
        (
            filename,
            field,
            annotation,
        )
        for (
            filename,
            field,
            annotation,
        ) in fields
        if (
            field
            in SECURITY_CRITICAL_FIELDS
            and annotation
            in {
                "Any",
                "Callable[..., Any]",
            }
        )
    ]

    assert violations == [], (
        "Security-critical dependency fields "
        f"must remain precisely typed: {violations}"
    )
