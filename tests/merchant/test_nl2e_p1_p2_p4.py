"""CP12H.NL2E: database target (P1), Merchant identity (P2), operation delivery (P4).

Reproduces the live preview of 2026-11-02 ("Xem trước dự án mở rạp Beta
Nguyễn Văn Cừ trên database test, không cần mua sắm"):

- P1: the lead declared ``database_target: runtime`` while the teammate read
  the test database on its own judgement; nothing trusted carried or checked
  the target.
- P2: the Merchant matched only as CANDIDATE on "Beta", yet the operation
  bound it like an exact identity.
- P4: the operation reached the lead only as prose the model retyped, and
  ``requires_procurement`` was implicit (absent flag).

No database is used: the reader is the NL1 fake, the OS pane identity and
the team-state directory are isolated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "hooks"))

import intent_envelope_bridge  # noqa: E402
import intent_gate  # noqa: E402
import policy_gate  # noqa: E402
import runtime_state  # noqa: E402
from team_lifecycle import TEAM_STATE_DIR_ENV_VAR, load_team_state  # noqa: E402

from claude.agents.tools.merchant.cli import (  # noqa: E402
    build_argument_parser,
    build_write_payload,
)
from claude.agents.tools.merchant.project_nl import (  # noqa: E402
    requests_test_database,
)
from claude.agents.tools.merchant.project_preview import (  # noqa: E402
    READY,
    ProjectPreviewMismatch,
    build_project_preview,
    canonical_create_argv,
    confirmation_command,
    validate_requested_operation,
    verify_project_create,
)
from claude.hooks import harness_team_identity, merchant_preview_delivery  # noqa: E402
from claude.hooks.merchant_preview_delivery import (  # noqa: E402
    PREVIEW_OPERATION_MARKER,
)
from claude.system.merchant_runtime_handoff import (  # noqa: E402
    MerchantRuntimeHandoffError,
    validate_direct_scope,
)
from tests.merchant.test_nl1_project_preview import (  # noqa: E402
    BETA,
    LOTTE,
    Reader,
    merchant,
    project,
)

LIVE = "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ trên database test, không cần mua sắm"
RUNTIME_ASK = "Xem trước dự án mở rạp Beta Nguyễn Văn Cừ, không cần mua sắm"
LEAD = "nl2e-lead"
PANE_SESSION = "nl2e-pane"
MM = "merchant-manager"
CLI = "python .claude/agents/tools/merchant/agent_cli.py"
CODE = "NL2_LIVE_BETA"  # live test-DB fixture: "Beta" is only a CANDIDATE


def live_merchants(**beta):
    return [merchant(BETA, beta.pop("code", CODE), "Beta Cinemas", **beta),
            merchant(LOTTE, "LOTTE", "Lotte Cinema")]


def LiveReader(merchants=None, **kwargs):
    return Reader(merchants=merchants or live_merchants(), **kwargs)


def preview(text=LIVE, reader=None, target="test"):
    return build_project_preview(text, reader or LiveReader(), database_target=target)


def operation(text=LIVE, reader=None, target="test"):
    result = preview(text, reader, target)
    assert result["outcome"] == READY, result["clarifications"]
    return result["requested_operation"]


def payload_of(argv):
    args = build_argument_parser().parse_args(["--database", "test", *argv])
    return build_write_payload(args, "project create")


# ===================================================================== P1


@pytest.mark.parametrize(
    "text,expected",
    [
        (LIVE, True),
        ("Preview the Beta Nguyễn Văn Cừ project on the test database", True),
        ("Xem trước dự án Beta trên cơ sở dữ liệu thử nghiệm", True),
        ("Xem trước dự án Beta trên db test", True),
        (RUNTIME_ASK, False),
        ("Xem trước dự án Beta, không dùng database test", False),
        ("Preview the Beta project, not on the test database", False),
        ("Run the unit test for the database layer", False),
    ],
)
def test_test_database_request_detection(text, expected):
    assert requests_test_database(text) is expected


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(runtime_state.STATE_DIR_ENV_VAR, str(tmp_path / "run"))
    monkeypatch.setenv(TEAM_STATE_DIR_ENV_VAR, str(tmp_path / "team"))
    monkeypatch.setenv(
        intent_envelope_bridge.ENVELOPE_DIR_ENV_VAR, str(tmp_path / "envelopes")
    )
    monkeypatch.setenv("CLAUDE_PENDING_TEAM_RESULT_DIR", str(tmp_path / "pending"))
    return tmp_path


def classify(text):
    envelope = {
        "request_id": "nl2e",
        "raw_request": text,
        "task_class": "small_task",
        "risk_level": "read_only",
        "operations": ["merchant_read"],
        "candidate_agents": [MM],
        "selected_agents": [MM],
        "limits": {"max_members": 1, "max_tool_rounds": 1,
                   "max_total_tool_calls": 10, "max_run_budget_usd": 1.0},
        "requires_clarification": False,
        "requires_confirmation": False,
        "reasons": [],
    }

    class Parser:
        def parse(self, _request):
            return envelope

    output = intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": LEAD,
         "prompt": f"/solve {text}"},
        parser_factory=Parser,
    )
    context = output["hookSpecificOutput"]["additionalContext"]
    shown = json.loads(context.split("```json\n", 1)[1].split("\n```", 1)[0])
    return runtime_state.load_state(LEAD), shown


@pytest.mark.parametrize("text,target", [(LIVE, "test"), (RUNTIME_ASK, "runtime")])
def test_intent_gate_binds_the_read_target_from_the_users_text(isolated, text, target):
    state, shown = classify(text)

    assert runtime_state.merchant_database_target(state) == target
    assert shown["merchant_database_target"] == target


def spawn(isolated, text=LIVE, declared="test", monkeypatch=None):
    state, _ = classify(text)
    prompt = (
        "operation: merchant_read\n"
        + (f"database_target: {declared}\n" if declared else "")
        + "Preview the Project the user described."
    )
    decision = policy_gate.apply_call(
        state, "Agent",
        {"subagent_type": MM, "name": MM, "prompt": prompt}, LEAD,
    )
    runtime_state.save_state(LEAD, state)
    return decision


@pytest.mark.parametrize("declared", ["runtime", None])
def test_lead_assignment_must_declare_the_trusted_test_target(isolated, declared):
    decision = spawn(isolated, declared=declared)

    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "database_target" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_lead_assignment_with_the_trusted_target_is_dispatched(isolated):
    assert spawn(isolated, declared="test") is None


def test_lead_assignment_cannot_escalate_a_runtime_run_to_test(isolated):
    decision = spawn(isolated, text=RUNTIME_ASK, declared="test")

    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"


def bash(command):
    return {
        "hook_event_name": "PreToolUse", "session_id": PANE_SESSION,
        "agent_type": MM, "tool_name": "Bash", "tool_input": {"command": command},
    }


def deny(reason):
    return {"hookSpecificOutput": {"permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


PREVIEW_TEST = f'{CLI} project preview --request "{LIVE}" --test-database'
PREVIEW_RUNTIME = f'{CLI} project preview --request "{LIVE}"'


@pytest.mark.parametrize(
    "command,allowed",
    [
        (PREVIEW_TEST, True),
        (PREVIEW_RUNTIME, False),            # test -> runtime escalation
        (f"{CLI} merchant list", False),     # any runtime read
        (f"{CLI} completeness check --command \"project create\"", True),  # no DB
    ],
)
def test_teammate_reads_only_the_trusted_test_target(isolated, command, allowed):
    assert spawn(isolated) is None

    decision = merchant_preview_delivery.teammate_target_decision(bash(command), deny)

    assert (decision is None) is allowed


@pytest.mark.parametrize("command,allowed", [(PREVIEW_TEST, False), (PREVIEW_RUNTIME, True)])
def test_teammate_cannot_switch_a_runtime_run_to_the_test_database(isolated, command, allowed):
    assert spawn(isolated, text=RUNTIME_ASK, declared="runtime") is None

    decision = merchant_preview_delivery.teammate_target_decision(bash(command), deny)

    assert (decision is None) is allowed


def test_test_database_read_without_a_trusted_owner_is_refused(isolated):
    assert merchant_preview_delivery.teammate_target_decision(
        bash(PREVIEW_TEST), deny
    ) is not None
    # Runtime reads outside a /solve run keep their existing behaviour.
    assert merchant_preview_delivery.teammate_target_decision(
        bash(PREVIEW_RUNTIME), deny
    ) is None


# ===================================================================== P2


def test_candidate_match_requires_explicit_merchant_confirmation():
    op = operation()

    assert op["merchant_match_kind"] == "CANDIDATE"
    assert op["merchant_matched_text"] == "Beta"
    assert op["merchant_confirmation_required"] is True
    assert op["merchant_code"] == CODE
    assert op["argv"][op["argv"].index("--merchant-code") + 1] == CODE


def test_exact_name_match_needs_no_candidate_confirmation():
    op = operation(
        "Create a cinema opening project for Beta Nguyễn Văn Cừ under Beta "
        "Cinemas. No procurement.",
        target="runtime",
    )

    assert op["merchant_match_kind"] == "NAME"
    assert op["merchant_confirmation_required"] is False


def reason(reader, payload):
    with pytest.raises(ProjectPreviewMismatch) as error:
        verify_project_create(reader, payload)
    return error.value.reason


def test_confirmed_candidate_verifies_against_current_state():
    op = operation()

    assert verify_project_create(LiveReader(), payload_of(op["argv"]))["basis_hash"] == (
        op["expected_basis"]
    )


def test_scope_without_the_merchant_code_is_refused():
    payload = payload_of(operation()["argv"])
    payload.pop("merchant_code")

    assert reason(LiveReader(), payload) == "MERCHANT_CONFIRMATION_REQUIRED"


@pytest.mark.parametrize(
    "merchants",
    [
        # Code re-assigned: the confirmed code no longer names this Merchant.
        live_merchants(code="NL2_LIVE_BETA_OLD"),
        # Same code, newer version (stale identity).
        live_merchants(version=2),
        # Merchant deactivated after the preview.
        live_merchants(status="INACTIVE"),
    ],
)
def test_stale_confirmed_merchant_is_refused(merchants):
    payload = payload_of(operation()["argv"])

    assert reason(Reader(merchants=merchants), payload) in {
        "PROJECT_NOT_READY", "PREVIEW_BASIS_CHANGED",
    }


def test_another_merchants_code_is_refused():
    payload = payload_of(operation()["argv"])
    payload["merchant_code"] = "LOTTE"

    assert reason(LiveReader(), payload) == "PROJECT_NOT_READY"


def test_ambiguous_merchant_yields_no_operation():
    reader = Reader(merchants=[
        merchant(BETA, CODE, "Beta Cinemas"),
        merchant(LOTTE, "BETA_MEDIA", "Beta Media"),
    ])

    result = preview(reader=reader)

    assert result["requested_operation"] is None
    assert result["outcome"] != READY


def test_unknown_merchant_never_becomes_a_merchant_create():
    result = preview(reader=Reader(merchants=[merchant(LOTTE, "LOTTE", "Lotte Cinema")]))

    assert result["requested_operation"] is None
    assert "never creates a Merchant" in " ".join(result["clarifications"])


def test_replayed_operation_after_creation_is_refused():
    op = operation()
    created = LiveReader(projects=[project("Beta Nguyễn Văn Cừ")])

    assert reason(created, payload_of(op["argv"])) == "PROJECT_NOT_READY"


# ===================================================================== P4


def test_operation_carries_every_confirmation_field_losslessly():
    op = operation()

    assert op["title"] == "Beta Nguyễn Văn Cừ"
    assert op["merchant_id"] == BETA
    assert op["project_type"] == "OPENING_NEW_CINEMA"
    assert op["workflow_variant"] == "OPENING_NEW_CINEMA_STANDARD"
    assert op["requires_procurement"] is False
    assert op["database_target"] == "test"
    assert op["status"] == "NOT_AUTHORIZED"
    assert op["argv"] == canonical_create_argv(op)
    assert "--no-requires-procurement" in op["argv"]
    assert op["argv"][op["argv"].index("--title") + 1] == "Beta Nguyễn Văn Cừ"
    assert op["confirmation_command"] == confirmation_command(op["argv"], "test")
    assert "Beta Nguyễn Văn Cừ" in op["confirmation_command"]  # not \\u-escaped
    assert op["confirmation_command"].startswith(
        "/solve --confirm --merchant-target test --merchant-scope ["
    )
    validate_requested_operation(op)


def test_runtime_preview_command_has_no_test_target():
    op = operation(RUNTIME_ASK, target="runtime")

    assert op["confirmation_command"].startswith("/solve --confirm --merchant-scope [")


def test_copied_confirmation_command_round_trips_through_the_intent_gate():
    op = operation()
    text = op["confirmation_command"][len("/solve --confirm --merchant-target test "):]

    argv, description = intent_gate.split_merchant_scope(text)
    scope = validate_direct_scope(argv, "test")

    assert argv == op["argv"]
    assert description
    assert scope["database_target"] == "test"


def mutate(op, **changes):
    changed = json.loads(json.dumps(op, ensure_ascii=False))
    changed.update(changes)
    return changed


@pytest.mark.parametrize(
    "broken",
    [
        lambda op: mutate(op, argv=op["argv"][:-2]),                       # truncated
        lambda op: mutate(op, argv=op["argv"][:2] + op["argv"][4:6]
                          + op["argv"][2:4] + op["argv"][6:]),             # reordered
        lambda op: mutate(op, title="Beta Nguyen Van Cu"),                 # folded
        lambda op: mutate(op, argv=[t.replace("Nguyễn Văn Cừ", "Nguyen Van Cu")
                                    for t in op["argv"]]),
        lambda op: {k: v for k, v in op.items() if k != "expected_basis"},  # missing
        lambda op: mutate(op, argv=[*op["argv"], "--created-by", "x"]),    # extra
        lambda op: mutate(op, command="merchant create"),
        lambda op: mutate(op, status="AUTHORIZED"),
        lambda op: mutate(op, confirmation_command=op["confirmation_command"]
                          .replace(" --merchant-target test", "")),
    ],
)
def test_malformed_or_reconstructed_operations_are_rejected(broken):
    with pytest.raises(ValueError):
        validate_requested_operation(broken(operation()))


def test_scope_must_be_the_canonical_preview_argv():
    argv = operation()["argv"]
    validate_direct_scope(argv, "test")

    reordered = argv[:2] + argv[4:6] + argv[2:4] + argv[6:]
    implicit = [token for token in argv if token != "--no-requires-procurement"]

    for scope in (reordered, implicit):
        with pytest.raises(MerchantRuntimeHandoffError):
            validate_direct_scope(scope, "test")


# ---- trusted capture and delivery --------------------------------------


@pytest.fixture
def delivery(isolated, monkeypatch):
    assert spawn(isolated) is None
    monkeypatch.setattr(
        harness_team_identity, "verified_teammate_pane",
        lambda owner, name: "7000:%7" if (owner, name) == (LEAD, MM) else None,
    )
    op = operation()
    stdout = json.dumps(preview(), ensure_ascii=False, indent=2)
    return op, stdout


def post_bash(command, stdout):
    return {
        "hook_event_name": "PostToolUse", "session_id": PANE_SESSION,
        "agent_type": MM, "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": "FutureWarning: ..."},
    }


def report(*blocks):
    body = "Preview ready. Merchant matched as CANDIDATE on Beta.\n"
    for block in blocks:
        body += f"{PREVIEW_OPERATION_MARKER}\n{block}\n"
    return {
        "hook_event_name": "PreToolUse", "session_id": PANE_SESSION,
        "agent_type": MM, "tool_name": "SendMessage",
        "tool_input": {"to": "team-lead", "message": body},
    }


def exact(op):
    return json.dumps(op, ensure_ascii=False, separators=(",", ":"))


def evidence():
    return load_team_state(LEAD)["teammates"][MM].get("project_preview_evidence")


def test_cli_output_is_captured_as_trusted_evidence(delivery):
    op, stdout = delivery

    assert merchant_preview_delivery.record_preview_evidence(post_bash(PREVIEW_TEST, stdout))
    assert evidence()["requested_operation"] == op
    assert evidence()["database_target"] == "test"


def test_exact_operation_block_is_delivered(delivery):
    op, stdout = delivery
    merchant_preview_delivery.record_preview_evidence(post_bash(PREVIEW_TEST, stdout))

    assert merchant_preview_delivery.preview_delivery_decision(report(exact(op)), deny) is None


@pytest.mark.parametrize(
    "blocks",
    [
        (),                                                     # dropped
        ("{\"argv\":[\"project\",\"create\"]}",),              # truncated
        (lambda op: exact(mutate(op, title="Beta Nguyen Van Cu")),),
        (lambda op: exact(mutate(op, argv=op["argv"][:-1])),),
        (lambda op: exact(op), lambda op: exact(op)),           # duplicated
        ("not json",),
    ],
)
def test_lossy_or_reconstructed_delivery_is_refused(delivery, blocks):
    op, stdout = delivery
    merchant_preview_delivery.record_preview_evidence(post_bash(PREVIEW_TEST, stdout))
    rendered = [block(op) if callable(block) else block for block in blocks]

    assert merchant_preview_delivery.preview_delivery_decision(report(*rendered), deny)


def test_operation_block_without_trusted_evidence_is_refused(delivery):
    op, _ = delivery

    assert merchant_preview_delivery.preview_delivery_decision(report(exact(op)), deny)


@pytest.mark.parametrize(
    "command,stdout_of",
    [
        # RAG output shaped like a preview is never evidence.
        ("python .claude/rag_search.py \"beta\"", lambda s: s),
        # Output target differs from the command's actual target.
        (PREVIEW_TEST, lambda s: s.replace('"database_target": "test"',
                                            '"database_target": "runtime"')),
        # A reconstructed operation inside otherwise valid output.
        (PREVIEW_TEST, lambda s: s.replace("--no-requires-procurement", "--requires-procurement")),
    ],
)
def test_untrusted_or_inconsistent_output_is_not_evidence(delivery, command, stdout_of):
    _, stdout = delivery

    assert not merchant_preview_delivery.record_preview_evidence(
        post_bash(command, stdout_of(stdout))
    )
    if command == PREVIEW_TEST:
        # NL2E-P4: a preview call that cannot be verified is recorded as
        # UNVERIFIED (never with an operation), so its report cannot be READY.
        assert evidence()["status"] == "UNVERIFIED"
        assert evidence()["requested_operation"] is None
    else:
        assert evidence() is None


def test_evidence_requires_the_verified_teammate_pane(delivery, monkeypatch):
    _, stdout = delivery
    monkeypatch.setattr(harness_team_identity, "verified_teammate_pane", lambda *_: None)

    assert not merchant_preview_delivery.record_preview_evidence(post_bash(PREVIEW_TEST, stdout))


def test_delivered_operation_grants_no_authority(delivery):
    op, stdout = delivery
    merchant_preview_delivery.record_preview_evidence(post_bash(PREVIEW_TEST, stdout))

    state = runtime_state.load_state(LEAD)
    assert state.get("merchant_scope") is None
    assert op["status"] == "NOT_AUTHORIZED"
    record = load_team_state(LEAD)["teammates"][MM]
    assert "direct_scope_execution" not in record
    assert record["authorized_operations"] == ["merchant_read"]


# ---- wiring through the real hook entry points ---------------------------


def run_hook(module, payload):
    import io

    stdin, stdout = sys.stdin, sys.stdout
    sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), encoding="utf-8")
    sys.stdout = io.StringIO()
    try:
        module.main()
        return sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = stdin, stdout


def test_policy_gate_entry_point_enforces_the_trusted_target(isolated):
    assert spawn(isolated) is None

    out = run_hook(policy_gate, bash(PREVIEW_RUNTIME))

    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_post_tool_entry_point_captures_and_gate_enforces_delivery(delivery):
    import team_result_hook

    op, stdout = delivery
    run_hook(team_result_hook, post_bash(PREVIEW_TEST, stdout))

    assert evidence()["requested_operation"] == op
    denied = run_hook(policy_gate, report())
    assert json.loads(denied)["hookSpecificOutput"]["permissionDecision"] == "deny"
    allowed = run_hook(policy_gate, report(exact(op)))
    assert "deny" not in allowed
