"""CP12H.NL2E-P4: a READY preview is actionable only with its verified operation.

Live run 2026-11-02 09:29Z (lead 3a21ef05, teammate 9019434c): the CLI printed
a complete, valid ``requested_operation`` (merchant_id, argv, Unicode title,
confirmation_command), but Claude Code's Bash tool merges stderr into stdout,
so a Python ``FutureWarning`` preceded the JSON. The exact-JSON capture failed,
no evidence was stored, the gate blocked the teammate's operation block as
"not captured", and the teammate then delivered READY_FOR_CONFIRMATION
without merchant_id, argv or confirmation_command, which the gate accepted.

Real hooks and team state; no database.
"""

from __future__ import annotations

import json

import pytest

from claude.hooks import merchant_preview_delivery
from claude.hooks.merchant_preview_delivery import (
    PREVIEW_DELIVERY_FAILED,
    PREVIEW_OPERATION_MARKER,
)
from claude.hooks.merchant_tool_result_contract import _exact_json_object
from claude.agents.tools.merchant.project_preview import validate_requested_operation
from tests.merchant.test_nl2e_p1_p2_p4 import (  # noqa: F401  (fixtures)
    PREVIEW_TEST,
    delivery,
    deny,
    evidence,
    exact,
    isolated,
    mutate,
    post_bash,
    preview,
    report,
    runtime_state,
    LEAD,
)

# What the live Bash tool_response.stdout looked like: stderr warning first,
# then the CLI's pretty JSON with CRLF line endings.
WARNING = (
    "C:\\Users\\u\\AppData\\Local\\Programs\\Python\\Python311\\Lib\\site-packages\\"
    "google\\api_core\\_python_version_support.py:254: FutureWarning: You are using "
    "a Python version (3.11.9) which Google will stop supporting in new releases of "
    "google.api_core once it reaches its end of life (2027-10-24).\n"
    "  warnings.warn(message, FutureWarning)\n"
)


def live_stdout(clean):
    return WARNING + clean.replace("\n", "\r\n")


def bash_result(stdout):
    return {"tool_name": "Bash", "tool_response": {"stdout": stdout, "stderr": ""}}


def decide(*blocks, body=None):
    payload = report(*blocks)
    if body is not None:
        payload["tool_input"]["message"] = body
    return merchant_preview_delivery.preview_delivery_decision(payload, deny)


# ---------------------------------------------------------------- capture


def test_live_stdout_with_a_stderr_warning_is_captured(delivery):
    op, stdout = delivery

    assert merchant_preview_delivery.record_preview_evidence(
        post_bash(PREVIEW_TEST, live_stdout(stdout))
    )
    assert evidence()["status"] == "VERIFIED"
    assert evidence()["requested_operation"] == op
    assert decide(exact(op)) is None


@pytest.mark.parametrize(
    "stdout",
    [
        "log output before JSON",
        WARNING + '{"a": 1}\ntrailing text',
        WARNING + '{"a": 1}\n{"b": 2}',
        WARNING + "{not json\n" + '{"a": 1}',  # first object line is not JSON
    ],
)
def test_noise_tolerance_never_accepts_trailing_or_second_objects(stdout):
    assert _exact_json_object(bash_result(stdout)) is None


def test_clean_and_prefixed_single_objects_parse_identically():
    clean = json.dumps({"mode": "PROJECT_PREVIEW", "title": "Beta Nguyễn Văn Cừ"},
                       ensure_ascii=False, indent=2)
    assert _exact_json_object(bash_result(clean)) == _exact_json_object(
        bash_result(live_stdout(clean))
    )


# ---------------------------------------------------------------- completeness of the block


REQUIRED = (
    "merchant_id", "merchant_code", "project_id", "project_type",
    "workflow_variant", "title", "requires_procurement", "expected_basis",
    "database_target", "argv", "confirmation_command",
)


@pytest.mark.parametrize("field", REQUIRED)
def test_operation_missing_any_required_field_is_invalid(field):
    op = preview()["requested_operation"]
    del op[field]

    with pytest.raises((ValueError, KeyError)):
        validate_requested_operation(op)


@pytest.mark.parametrize(
    "broken",
    [
        lambda op: {k: v for k, v in op.items() if k != "merchant_id"},
        lambda op: {k: v for k, v in op.items() if k != "argv"},
        lambda op: {k: v for k, v in op.items() if k != "confirmation_command"},
        lambda op: mutate(op, argv=op["argv"][:-1]),                             # truncated
        lambda op: mutate(op, argv=op["argv"][:2] + op["argv"][4:6]
                          + op["argv"][2:4] + op["argv"][6:]),                   # reordered
        lambda op: mutate(op, title="Beta Nguyen Van Cu"),                       # Unicode lost
        lambda op: mutate(op, title="Beta Nguy?n V?n C?"),                       # mojibake
        lambda op: mutate(op, confirmation_command=op["confirmation_command"]
                          .replace("Nguyễn Văn Cừ", "Nguy\\u1ec5n V\\u0103n C\\u1eeb")),
    ],
)
def test_incomplete_or_corrupted_block_is_refused(delivery, broken):
    op, stdout = delivery
    merchant_preview_delivery.record_preview_evidence(post_bash(PREVIEW_TEST, live_stdout(stdout)))

    assert decide(exact(broken(op))) is not None


def test_valid_exact_block_with_unicode_is_delivered(delivery):
    op, stdout = delivery
    merchant_preview_delivery.record_preview_evidence(post_bash(PREVIEW_TEST, live_stdout(stdout)))

    assert "Beta Nguyễn Văn Cừ" in exact(op)
    assert decide(exact(op)) is None


# ---------------------------------------------------------------- the live failure mode


READY_WITHOUT_OPERATION = (
    "Merchant read report: project preview on the test database returned "
    "READY_FOR_CONFIRMATION. Merchant Beta Cinemas (NL2_LIVE_BETA), project_id "
    "30fffeaf-e6b5-5119-b078-52c934e1821e, title Beta Nguyễn Văn Cừ."
)


def unverified_capture(stdout):
    # The pre-fix live outcome: a preview ran but its output was not verified.
    assert not merchant_preview_delivery.record_preview_evidence(
        post_bash(PREVIEW_TEST, "garbled " + stdout[:200])
    )
    assert evidence()["status"] == "UNVERIFIED"


def test_ready_report_without_verified_operation_is_refused(delivery):
    _, stdout = delivery
    unverified_capture(stdout)

    decision = decide(body=READY_WITHOUT_OPERATION)

    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert PREVIEW_DELIVERY_FAILED in reason
    assert "could not be verified" in reason


@pytest.mark.parametrize(
    "body",
    [
        READY_WITHOUT_OPERATION,
        "Preview is Ready for confirmation; confirm when ready.",
        'Type: /solve --confirm --merchant-target test --merchant-scope ["project","create"] x',
        'argv = ["project","create","--merchant-id","6e0c1a2b-5f4d-4b8e-9c71-2a3b4c5d6e7f"]',
    ],
)
def test_no_actionable_or_reconstructed_report_without_evidence(delivery, body):
    # Nothing captured at all (e.g. the capture hook failed to run).
    assert decide(body=body) is not None


def test_explicit_delivery_failure_is_accepted_without_a_resend_loop(delivery):
    _, stdout = delivery
    unverified_capture(stdout)

    first = decide(body=READY_WITHOUT_OPERATION)
    assert first is not None
    # Deterministic: the same report is refused the same way...
    assert decide(body=READY_WITHOUT_OPERATION) == first

    # ...and following the stated correction once is accepted.
    corrected = (
        f"{PREVIEW_DELIVERY_FAILED}: the preview output could not be verified, so "
        "no confirmable operation is available. Read-only findings: Merchant Beta "
        "Cinemas (NL2_LIVE_BETA, CANDIDATE on 'Beta'), OPENING_NEW_CINEMA, "
        "title Beta Nguyễn Văn Cừ, procurement not required. Nothing was written."
    )
    assert decide(body=corrected) is None
    # The non-actionable result grants nothing.
    assert runtime_state.load_state(LEAD).get("merchant_scope") is None


def test_verified_operation_cannot_be_dropped_or_downgraded(delivery):
    op, stdout = delivery
    merchant_preview_delivery.record_preview_evidence(post_bash(PREVIEW_TEST, live_stdout(stdout)))

    # Lead-facing report that summarizes the fields but omits the operation.
    assert decide(body=READY_WITHOUT_OPERATION) is not None
    assert decide(body=f"{PREVIEW_DELIVERY_FAILED}: skipped") is not None
    assert decide(exact(op)) is None


def test_non_ready_preview_cannot_be_reported_as_ready(delivery):
    from tests.merchant.test_nl2e_p1_p2_p4 import LIVE, LiveReader, merchant, LOTTE

    _, _ = delivery
    ambiguous = json.dumps(
        preview(reader=LiveReader(merchants=[
            merchant("11111111-1111-4111-8111-111111111111", "NL2_LIVE_BETA", "Beta Cinemas"),
            merchant(LOTTE, "BETA_MEDIA", "Beta Media"),
        ])),
        ensure_ascii=False, indent=2,
    )
    assert merchant_preview_delivery.record_preview_evidence(
        post_bash(PREVIEW_TEST, live_stdout(ambiguous))
    )
    assert evidence()["outcome"] == "NEEDS_CLARIFICATION"

    assert decide(body="Preview needs clarification: which Beta Merchant?") is None
    assert decide(body=READY_WITHOUT_OPERATION) is not None
