from pathlib import Path

import re


ROOT = Path(__file__).resolve().parents[2]

SOLVE = (
    ROOT
    / ".claude"
    / "commands"
    / "solve.md"
)

MERCHANT_MANAGER = (
    ROOT
    / ".claude"
    / "agents"
    / "merchant-manager.md"
)

CANONICAL_MARKER = (
    "MERCHANT_APPLY_HANDOFF_REQUEST_JSON:"
)


def _read(path: Path) -> str:
    return path.read_text(
        encoding="utf-8",
    )


def test_solve_uses_canonical_runtime_handoff_marker():
    text = _read(SOLVE)

    assert CANONICAL_MARKER in text

    bad = list(
        re.finditer(
            r"MERCHANT_APPLY_HANDOFF_REQUEST_JSON(?!:)",
            text,
        )
    )

    assert bad == []


def test_merchant_manager_uses_canonical_runtime_handoff_marker():
    text = _read(
        MERCHANT_MANAGER
    )

    assert CANONICAL_MARKER in text

    bad = list(
        re.finditer(
            r"MERCHANT_APPLY_HANDOFF_REQUEST_JSON(?!:)",
            text,
        )
    )

    assert bad == []


def test_solve_forbids_model_authored_apply_receipt():
    text = _read(SOLVE)

    assert (
        "Do not model-author"
        in text
    )

    assert (
        "`MERCHANT_APPLY_RECEIPT_JSON`"
        in text
    )

def test_merchant_manager_forbids_model_authored_apply_receipt():
    text = _read(
        MERCHANT_MANAGER
    )

    assert (
        "Do not model-author"
        in text
    )

    assert (
        "`MERCHANT_APPLY_RECEIPT_JSON`"
        in text
    )

def test_solve_requires_exactly_one_handoff_sendmessage():
    text = _read(SOLVE)

    assert (
        "exactly one"
        in text.lower()
    )

    assert (
        "non-terminal"
        in text
    )

    assert (
        "`SendMessage`"
        in text
    )


def test_merchant_manager_requires_exactly_one_handoff_sendmessage():
    text = _read(
        MERCHANT_MANAGER
    )

    assert (
        "exactly one"
        in text.lower()
    )

    assert (
        "non-terminal"
        in text
    )

    assert (
        "`SendMessage`"
        in text
    )


def test_merchant_manager_terminal_apply_sendmessage_is_machine_only():
    text = _read(
        MERCHANT_MANAGER
    )

    assert (
        "`SendMessage` must consist only of exactly one "
        "`TEAM_RESULT_JSON` block."
        in text
    )

    assert (
        "the first non-whitespace content must be "
        "`TEAM_RESULT_JSON:`"
        in text
    )

    assert (
        "after the closing `}` of the JSON object, "
        "the message must end"
        in text
    )

    assert (
        "do not write prose, Markdown, headings, explanations, "
        "failure reports, CLI"
        in text
    )


def test_general_reporting_does_not_override_terminal_apply_contract():
    text = _read(
        MERCHANT_MANAGER
    )

    assert (
        "They do not override the strict terminal"
        in text
    )

    assert re.search(
        r"For terminal `merchant_apply`, send\s+"
        r"only the required `TEAM_RESULT_JSON` block\.",
        text,
    )

def _normalized_document_text(path: Path) -> str:
    return " ".join(
        _read(path).split()
    )


def test_confirmed_merchant_create_assignment_preserves_exact_business_fields():
    solve = _normalized_document_text(SOLVE)
    manager = _normalized_document_text(MERCHANT_MANAGER)

    for field in (
        "`code`",
        "`name`",
        "`region_code`",
    ):
        assert field in solve
        assert field in manager

    assert (
        "Do not reduce the assignment to only a merchant code, "
        "label, proposal hash, or generic instruction"
        in solve
    )

    assert (
        "copy the exact proposed `code`, `name`, and `region_code`"
        in solve
    )

    assert (
        "the confirmed-apply assignment must preserve the exact "
        "proposed `code`, `name`, and `region_code`"
        in manager
    )


def test_missing_confirmed_apply_business_context_blocks_before_gate_7_4():
    solve = _normalized_document_text(SOLVE)
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert (
        "If the exact required business context is unavailable, "
        "do not dispatch an incomplete apply assignment."
        in solve
    )

    assert (
        "fail closed with a terminal `BLOCKED` result before sending"
        in manager
    )

    assert (
        "`MERCHANT_APPLY_HANDOFF_REQUEST_JSON:`"
        in manager
    )

    assert (
        "Never guess, reconstruct, substitute, or silently change "
        "missing business values"
        in manager
    )


def test_business_fields_do_not_become_runtime_authority():
    solve = _normalized_document_text(SOLVE)

    assert (
        "These values are execution context only; they do not grant "
        "runtime write authority."
        in solve
    )

    assert (
        "MERCHANT_DISPATCH_AUTHORIZATION_JSON"
        in solve
    )


def test_confirmed_project_create_assignment_preserves_exact_business_fields():
    solve = _normalized_document_text(SOLVE)
    manager = _normalized_document_text(MERCHANT_MANAGER)

    for field in (
        "`merchant_id`",
        "`project_id`",
        "`project_type`",
        "`workflow_variant`",
        "`requires_procurement`",
        "`payment_period_number`",
        "`reused_document_revision_id`",
        "`title`",
        "`created_by`",
    ):
        assert field in solve
        assert field in manager


def test_project_create_confirmed_apply_uses_proposal_hash_not_expected_version():
    solve = _normalized_document_text(SOLVE)
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert "`project create` is a new-entity write" in solve
    assert "`project create` is a new-entity write" in manager

    assert "`proposal_hash`" in solve
    assert "`proposal_hash`" in manager


def test_merchant_manager_treats_registered_cli_contract_as_authoritative():
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert (
        "The actual CLI parser and registered Merchant command contract are authoritative"
        in manager
    )

    assert (
        "Descriptive documentation must never be used to remove or reject a business field"
        in manager
    )


def test_project_create_false_requires_procurement_maps_to_absent_cli_flag():
    solve = _normalized_document_text(SOLVE)
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert (
        "confirmed `requires_procurement: false` is represented by "
        "omitting the `--requires-procurement` flag"
        in solve
    )

    assert (
        "boolean `requires_procurement: false` is represented by "
        "the absence of the `--requires-procurement` flag"
        in manager
    )

    assert (
        "must not be treated as missing, changed, or ambiguous "
        "business context"
        in manager
    )


def test_project_create_true_requires_procurement_maps_to_present_cli_flag():
    solve = _normalized_document_text(SOLVE)
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert (
        "Confirmed `requires_procurement: true` requires that flag."
        in solve
    )

    assert (
        "`requires_procurement: true` requires the "
        "`--requires-procurement` flag."
        in manager
    )


def test_merchant_apply_pre_gate_7_4_blocked_has_bounded_diagnostic_contract():
    solve = _normalized_document_text(SOLVE)
    manager = _normalized_document_text(MERCHANT_MANAGER)

    for token in (
        "`blocked_stage`",
        "`reason_code`",
        "`missing_fields`",
        "`mismatched_fields`",
        "`PRE_GATE_7_4`",
    ):
        assert token in solve
        assert token in manager

    for reason in (
        "`MISSING_BUSINESS_CONTEXT`",
        "`MISMATCHED_BUSINESS_CONTEXT`",
        "`AMBIGUOUS_BUSINESS_CONTEXT`",
        "`INVALID_NORMALIZED_ARGV`",
        "`DISPATCH_PRECONDITION_FAILED`",
    ):
        assert reason in manager


def test_merchant_apply_blocked_diagnostics_never_expose_values_or_authority():
    solve = _normalized_document_text(SOLVE)
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert (
        "field names only"
        in solve
    )

    assert (
        "never include field values, hashes, tokens, credentials, raw proposal data"
        in manager
    )

    assert (
        "runtime authorization objects"
        in manager
    )


def test_merchant_apply_blocked_terminal_shape_is_distinct_from_apply_failed():
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert (
        '"outcome": "BLOCKED"'
        in manager
    )

    assert (
        '"blocked_stage": "PRE_GATE_7_4"'
        in manager
    )

    assert (
        '"outcome": "APPLY_FAILED"'
        in manager
    )


def test_project_create_null_optional_fields_map_to_absent_cli_flags():
    manager = _normalized_document_text(MERCHANT_MANAGER)
    solve = _normalized_document_text(SOLVE)

    for field in (
        "`payment_period_number`",
        "`reused_document_revision_id`",
        "`created_by`",
    ):
        assert field in manager
        assert field in solve

    for cli_flag in (
        "`--payment-period-number`",
        "`--reused-document-revision-id`",
        "`--created-by`",
    ):
        assert cli_flag in manager
        assert cli_flag in solve

    assert "literal string `null`" in manager
    assert "literal string `null`" in solve


def test_project_create_null_optional_values_are_not_invalid_normalized_argv():
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert (
        "must not be treated as missing, changed, ambiguous, or "
        "`INVALID_NORMALIZED_ARGV`"
        in manager
    )


def test_confirmed_apply_must_not_use_agent_cli_for_validation():
    manager = _normalized_document_text(MERCHANT_MANAGER)

    assert (
        "do not validate a confirmed apply vector through `agent_cli.py`"
        in manager.lower()
    )

    assert "`prepare_agent_cli_argv()`" in manager
    assert "`invoke_agent_cli()`" in manager

    assert (
        "those boundaries intentionally reject runtime `--apply`"
        in manager.lower()
    )

    assert (
        "merchant_runtime_handoff.py"
        in manager
    )


def test_agent_cli_apply_authority_rejection_is_not_invalid_argv():
    manager = _normalized_document_text(MERCHANT_MANAGER)
    solve = _normalized_document_text(SOLVE)

    assert (
        "authority restriction"
        in manager
    )

    assert (
        "must never by itself produce `INVALID_NORMALIZED_ARGV`"
        in manager
    )

    assert (
        "authority boundary, not evidence of invalid CLI syntax"
        in solve
    )

    assert (
        "`merchant_runtime_handoff.py`"
        in solve
    )
