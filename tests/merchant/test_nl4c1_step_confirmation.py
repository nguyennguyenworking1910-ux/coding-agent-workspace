"""CP12H.NL4C1: trusted conversational Step Update confirmation (foundation).

- A READY ``step preview`` carries ``requested_operation``: the exact
  ``step update`` argv bound to a basis hash of the judged snapshot. Data only.
- Only the PostToolUse capture of a VERIFIED READY preview records a pending
  Step Update, in a store separate from Project creates.
- ``/solve Xác nhận cập nhật [<step id>]`` (the whole prompt, the user's own
  session) spends one record into an ordinary ``merchant_scope``. While Step
  execution is disabled it is refused unspent.
- ``verify_step_update`` re-judges everything before any spend and inside the
  write transaction; any change to the snapshot refuses it.

No database here; see ``test_nl4c1_step_confirmation_postgres.py``.
"""

from __future__ import annotations

import copy
import json
import threading
from types import SimpleNamespace

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant.step_preview import (
    READY,
    StepPreviewMismatch,
    canonical_step_argv,
    validate_step_operation,
    verify_step_update,
)
from claude.hooks import merchant_direct_handoff as handoff
from claude.hooks import merchant_pending_confirmation as pending
from claude.system.merchant_runtime_handoff import (
    MerchantRuntimeHandoffError,
    validate_direct_scope,
)
from tests.merchant.test_nl4b_fix1_routing_and_teammate import BUG_FIXER, parse
from tests.merchant.test_nl4b_step_preview import (  # noqa: F401 (fixtures)
    EDGES,
    NVC,
    P_NVC,
    PARTNER_OK,
    REV,
    STEP_TEST,
    StepReader,
    capture,
    edge,
    isolated,
    preview,
    revision,
    step_run,
)
from tests.merchant.test_nl2e_p1_p2_p4 import LEAD, intent_gate, runtime_state

START_2 = f"Bắt đầu bước 2 của {NVC}"          # step 2 Legal Review READY -> IN_PROGRESS
OTHER_SESSION = "another-lead-session"


def ready_operation(text=START_2, reader=None, target="test"):
    result = preview(text, reader, target)
    assert result["outcome"] == READY, result["blocking"]
    # As delivered: the exact JSON the CLI printed.
    return json.loads(json.dumps(result["requested_operation"], default=str))


def payload_of(argv):
    """The CLI payload of a scope argv, exactly as trusted execution builds it."""

    args = merchant_cli.build_argument_parser().parse_args(["--database", "runtime", *argv])
    return merchant_cli.build_write_payload(args, "step update")


def submit(text, session=LEAD, parser=None):
    class Replayed:
        def parse(self, request):
            return parse(request, BUG_FIXER)

    return intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": text},
        parser_factory=parser or Replayed, env={},
    )


@pytest.fixture
def enabled(monkeypatch):
    """Step execution switched on for the test target only (NL4C2 territory)."""

    monkeypatch.setattr(handoff, "TEST_MODE_COMMANDS",
                        handoff.TEST_MODE_COMMANDS | {handoff.STEP_UPDATE_COMMAND})


def put(operation, session=LEAD):
    return pending.record_pending_step(session, operation, run_id="run-src", task_id="task-src")


def status_of(step_id, session=LEAD):
    return [r["status"] for r in pending.load_records(session, pending.STEP_KIND)
            if r["step_id"] == step_id]


# ------------------------------------------------------- operation contract


def test_ready_preview_carries_the_exact_operation_as_data():
    operation = ready_operation()

    assert operation["status"] == "NOT_AUTHORIZED" and operation["command"] == "step update"
    assert (operation["step_sequence"], operation["step_name"]) == (2, "Legal Review")
    assert (operation["current_status"], operation["target_status"]) == ("READY", "IN_PROGRESS")
    assert operation["project_title"] == "Beta Nguyễn Văn Cừ"  # UTF-8 kept
    assert operation["project_version"] == 3 and operation["step_version"] == 2
    assert operation["database_target"] == "test"
    assert operation["argv"] == canonical_step_argv(operation) == [
        "step", "update", operation["step_id"], "--status", "IN_PROGRESS",
        "--expected-version", "2", "--project-id", P_NVC,
        "--merchant-code", "NL2_LIVE_BETA", "--expected-basis", operation["expected_basis"],
    ]
    validate_step_operation(operation)


@pytest.mark.parametrize(
    "edit",
    [
        {"target_status": "COMPLETED"},               # confirmation may not change the status
        {"database_target": "production"},
        {"status": "AUTHORIZED"},
        {"step_version": 0},
        {"step_version": True},
        {"expected_basis": "0" * 63},
        {"step_id": "NOT-A-UUID"},
        {"current_status": "IN_PROGRESS"},            # no-op transition
        {"command": "project create"},
    ],
)
def test_edited_operations_are_rejected(edit):
    operation = dict(ready_operation(), **edit)

    with pytest.raises(ValueError):
        validate_step_operation(operation)


def test_argv_must_be_canonical():
    operation = ready_operation()
    for argv in (operation["argv"][:-2],
                 operation["argv"] + ["--allow-reopen"],
                 operation["argv"][:3] + operation["argv"][5:7] + operation["argv"][3:5] + operation["argv"][7:]):
        with pytest.raises(ValueError):
            validate_step_operation(dict(operation, argv=argv))


def test_blocked_and_clarifying_previews_carry_no_operation():
    for text in (f"Đánh dấu bước Legal Review của {NVC} là hoàn thành",   # READY -> COMPLETED
                 f"Bắt đầu bước 4 của {NVC}",                             # unmet dependencies
                 "Đánh dấu bước Legal Review hoàn thành"):                # no Project
        assert preview(text)["requested_operation"] is None


# --------------------------------------------------- re-judgement (verify)


def test_unchanged_state_verifies():
    operation = ready_operation()

    judged = verify_step_update(StepReader(), payload_of(operation["argv"]))
    assert judged["outcome"] == READY


def changed(mutate):
    reader = StepReader(steps=copy.deepcopy(StepReader().steps))
    mutate(reader)
    return reader


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda r: r.projects[0].update(version=4), "STEP_BASIS_CHANGED"),             # Project version
        (lambda r: r.projects[0].update(status="ON_HOLD"), "STEP_BASIS_CHANGED"),
        (lambda r: r.steps[1].update(version=3), "STEP_VERSION_CHANGED"),              # Step version
        (lambda r: r.steps[1].update(status="IN_PROGRESS"), "STEP_NOT_READY"),         # already moved
        (lambda r: r.steps[0].update(status="IN_PROGRESS", version=3), "STEP_NOT_READY"),  # dependency reopened
        (lambda r: r.steps[7].update(version=2), "STEP_BASIS_CHANGED"),                # unrelated step
        (lambda r: r.projects[0].update(merchant_code="LOTTE"), "MERCHANT_MISMATCH"),
    ],
)
def test_changed_state_is_refused(mutate, reason):
    payload = payload_of(ready_operation()["argv"])

    with pytest.raises(StepPreviewMismatch) as error:
        verify_step_update(changed(mutate), payload)
    assert error.value.reason == reason


def test_changed_dependencies_are_refused(monkeypatch):
    payload = payload_of(ready_operation()["argv"])
    from tests.merchant import test_nl4b_step_preview as fake

    monkeypatch.setattr(fake, "EDGES", EDGES + [edge(3, 2)])  # 2 now also waits on 3
    with pytest.raises(StepPreviewMismatch) as error:
        verify_step_update(StepReader(), payload)
    assert error.value.reason == "STEP_NOT_READY"

    monkeypatch.setattr(fake, "EDGES", EDGES + [edge(1, 9)])  # an edge elsewhere
    with pytest.raises(StepPreviewMismatch) as error:
        verify_step_update(StepReader(), payload)
    assert error.value.reason == "STEP_BASIS_CHANGED"


def test_approval_gate_evidence_is_bound_and_cannot_be_bypassed():
    text = f"Đánh dấu bước Record Partner approval của {NVC} là hoàn thành"
    approved = StepReader(revisions=[revision(P_NVC)], approvals=[PARTNER_OK])
    operation = ready_operation(text, approved)
    payload = payload_of(operation["argv"])

    assert verify_step_update(approved, payload)["outcome"] == READY
    # The approval is withdrawn: the gate is no longer met.
    with pytest.raises(StepPreviewMismatch) as error:
        verify_step_update(StepReader(revisions=[revision(P_NVC)]), payload)
    assert error.value.reason == "STEP_NOT_READY"
    # Without a preview there is no basis: the gate cannot be skipped by a bare scope.
    bare = {k: v for k, v in payload.items() if k != "expected_basis_hash"}
    with pytest.raises(StepPreviewMismatch) as error:
        verify_step_update(approved, bare)
    assert error.value.reason == "STEP_BASIS_REQUIRED"


def test_gate_without_database_evaluator_never_yields_an_operation():
    result = preview(f"Đánh dấu bước Complete UAT acceptance của {NVC} là hoàn thành")
    assert result["outcome"] != READY and result["requested_operation"] is None


@pytest.mark.parametrize("field", ["expected_basis_hash", "project_id", "merchant_code"])
def test_missing_evidence_is_refused(field):
    payload = payload_of(ready_operation()["argv"])
    payload.pop(field)

    with pytest.raises(StepPreviewMismatch) as error:
        verify_step_update(StepReader(), payload)
    assert error.value.reason == "STEP_BASIS_REQUIRED"


def test_target_status_cannot_be_swapped_under_the_same_basis():
    operation = ready_operation()
    payload = payload_of(operation["argv"])
    payload["status"] = "SKIPPED"

    with pytest.raises(StepPreviewMismatch):
        verify_step_update(StepReader(), payload)


# -------------------------------------------------------------- scope


def test_scope_accepts_only_the_canonical_argv():
    operation = ready_operation()
    validated = validate_direct_scope(operation["argv"], "test")
    assert validated["argv"] == operation["argv"] and validated["command"] == "step update"

    argv = operation["argv"]
    for bad in (argv + ["--allow-reopen"],
                argv[:9] + argv[11:],                        # no --merchant-code
                argv[:3] + argv[5:7] + argv[3:5] + argv[7:]):  # reordered
        with pytest.raises(MerchantRuntimeHandoffError):
            validate_direct_scope(bad, "test")


def test_database_target_is_bound_into_the_scope_hash():
    argv = ready_operation()["argv"]

    assert validate_direct_scope(argv, "test")["scope_hash"] != validate_direct_scope(argv, "runtime")["scope_hash"]


# ------------------------------------------------------- pending store


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Xác nhận cập nhật", ("confirm", None)),
        ("xac nhan cap nhat buoc 00000000", ("confirm", "00000000")),
        ("Confirm update step 00000000-0000-0000-0000-000000000002", ("confirm", "00000000000000000000000000000002"[:32])),
        ("Hủy cập nhật", ("cancel", None)),
        ("Cancel update", ("cancel", None)),
        ("Xác nhận cập nhật thành COMPLETED", None),        # cannot change the status
        ("Xác nhận cập nhật trên database runtime", None),  # cannot change the target
        ("Không xác nhận cập nhật", None),
        ("Xác nhận tạo", None),                             # a Project phrase
    ],
)
def test_step_phrases_are_exact(text, expected):
    assert pending.parse_step_confirmation(text) == expected


def test_project_and_step_records_never_cross(isolated, enabled):
    operation = ready_operation()
    put(operation)

    assert pending.load_records(LEAD) == []                          # Project store untouched
    assert "Project create" in submit("/solve Xác nhận tạo")["reason"]
    assert status_of(operation["step_id"]) == ["PENDING"]
    with pytest.raises(ValueError):
        pending.record_pending(LEAD, operation, run_id="r", task_id="t")  # not a Project create


# ------------------------------------------------- gate (UserPromptSubmit)


def test_confirmation_is_refused_unspent_while_execution_is_disabled(isolated):
    # NL4C2A enabled the test target only; a runtime Step stays refused unspent.
    operation = ready_operation(target="runtime")
    put(operation)

    output = submit("/solve Xác nhận cập nhật")

    assert output["decision"] == "block" and "only on the test database" in output["reason"]
    assert status_of(operation["step_id"]) == ["PENDING"]
    assert runtime_state.load_state(LEAD) is None
    assert handoff.direct_execute_enabled("step update", "test")
    assert not handoff.direct_execute_enabled("step update", "runtime")


def test_valid_confirmation_yields_the_recorded_scope(isolated, enabled):
    operation = ready_operation()
    put(operation)

    output = submit("/solve Xác nhận cập nhật")

    assert output.get("decision") != "block", output
    run = runtime_state.load_state(LEAD)
    assert run["merchant_scope"]["argv"] == operation["argv"]
    assert run["merchant_scope"]["database_target"] == "test"
    assert run["operations"] == ["merchant_execute"] and run["risk_level"] == "external_write"
    assert run["selected_agents"] == ["merchant-manager"] and run["confirmed"] is True
    envelope = intent_gate.load_intent_envelope(LEAD)
    detail = envelope["conversational_confirmation"]
    assert detail["kind"] == "step_update" and detail["target_status"] == "IN_PROGRESS"
    assert "Nguyễn Văn Cừ" in output["systemMessage"]
    assert status_of(operation["step_id"]) == ["CONFIRMED"]


def test_replayed_confirmation_is_refused(isolated, enabled):
    put(ready_operation())
    assert submit("/solve Xác nhận cập nhật").get("decision") != "block"
    runtime_state.clear_state(LEAD)

    output = submit("/solve Xác nhận cập nhật")
    assert output["decision"] == "block" and "no pending Step Update" in output["reason"]
    assert runtime_state.load_state(LEAD) is None


def test_expired_confirmation_is_refused(isolated, enabled, monkeypatch):
    operation = ready_operation()
    put(operation)
    monkeypatch.setattr(pending, "_now", lambda: 10 ** 12)

    output = submit("/solve Xác nhận cập nhật")
    assert output["decision"] == "block" and "expired" in output["reason"]


def test_wrong_session_cannot_confirm(isolated, enabled):
    operation = ready_operation()
    put(operation, OTHER_SESSION)

    output = submit("/solve Xác nhận cập nhật")
    assert output["decision"] == "block"
    assert status_of(operation["step_id"], OTHER_SESSION) == ["PENDING"]


def test_ambiguous_confirmation_names_the_choices_and_an_id_picks_one(isolated, enabled):
    first = ready_operation()
    second = ready_operation(f"Bỏ qua bước 5 của {NVC}")  # optional step 5 -> SKIPPED
    put(first)
    put(second)

    output = submit("/solve Xác nhận cập nhật")
    assert output["decision"] == "block" and "More than one Step Update" in output["reason"]
    assert status_of(first["step_id"]) == status_of(second["step_id"]) == ["PENDING"]

    picked = submit(f"/solve Xác nhận cập nhật {second['step_id'][:8]}")  # all-zero prefixes...
    # ...are shared by both fake ids, so a short prefix is still ambiguous;
    # the full id resolves exactly one.
    assert picked["decision"] == "block"
    assert submit(f"/solve Xác nhận cập nhật {second['step_id']}").get("decision") != "block"
    assert status_of(second["step_id"]) == ["CONFIRMED"] and status_of(first["step_id"]) == ["PENDING"]


def test_cancel_spends_without_running(isolated, enabled):
    operation = ready_operation()
    put(operation)

    output = submit("/solve Hủy cập nhật")
    assert output["decision"] == "block" and "Cancelled" in output["reason"]
    assert status_of(operation["step_id"]) == ["CANCELLED"]


def test_damaged_record_is_never_confirmed(isolated, enabled):
    operation = ready_operation()
    put(operation)
    with pending._locked(LEAD, pending.STEP_KIND) as records:
        records[0]["operation"]["target_status"] = "COMPLETED"   # tampered on disk

    output = submit("/solve Xác nhận cập nhật")
    assert output["decision"] == "block" and "could not be verified" in output["reason"]
    assert runtime_state.load_state(LEAD) is None


def test_edited_confirmation_is_not_a_confirmation(isolated, enabled):
    put(ready_operation())

    for text in ("/solve Xác nhận cập nhật thành COMPLETED",
                 "/solve Xác nhận cập nhật trên database runtime"):
        output = submit(text)
        assert output["decision"] == "block"                     # classified; external_write needs --confirm
        assert runtime_state.load_state(LEAD) is None


def test_bare_phrase_without_solve_is_only_guidance(isolated, enabled):
    operation = ready_operation()
    put(operation)

    output = submit("Xác nhận cập nhật")
    assert output["decision"] == "block" and "/solve Xác nhận cập nhật" in output["reason"]
    assert status_of(operation["step_id"]) == ["PENDING"]


def test_scheduled_confirmation_prompts_are_denied():
    for tool in pending.SCHEDULING_TOOLS:
        assert pending.scheduled_prompt_denial(tool, {"prompt": "Xác nhận cập nhật"})
        assert pending.scheduled_prompt_denial(tool, {"prompt": "/solve Confirm update"})


def test_mixed_request_never_confirms(isolated, enabled):
    put(ready_operation())

    output = submit("/solve Xác nhận cập nhật và xóa merchant Beta")
    assert output["decision"] == "block" and runtime_state.load_state(LEAD) is None


def test_concurrent_confirmations_spend_once(isolated, enabled):
    operation = ready_operation()
    put(operation)
    results = []

    def confirm(index):
        record, refusal = pending.resolve(LEAD, pending.CONFIRM, None, f"run-{index}",
                                          kind=pending.STEP_KIND)
        results.append(record is not None)

    threads = [threading.Thread(target=confirm, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False] * 7 + [True]


def test_crash_after_spend_never_restores_the_record(isolated, enabled, monkeypatch):
    operation = ready_operation()
    put(operation)

    def crash(*_a, **_k):
        raise RuntimeError("process died after the spend")

    with monkeypatch.context() as patch:
        patch.setattr(intent_gate, "_conversational_scope", crash)
        with pytest.raises(RuntimeError):
            submit("/solve Xác nhận cập nhật")

    assert status_of(operation["step_id"]) == ["CONFIRMED"]     # spent, not restored
    assert submit("/solve Xác nhận cập nhật")["decision"] == "block"


# ------------------------------------------------- trusted creator (hook)


def test_verified_ready_capture_records_one_pending_step(step_run):
    result, stdout = step_run()
    assert capture(STEP_TEST, stdout)

    (record,) = pending.load_records(LEAD, pending.STEP_KIND)
    assert record["operation"] == result["requested_operation"]
    assert record["database_target"] == "test" and record["owner_session_id"] == LEAD
    assert pending.load_records(LEAD) == []


@pytest.mark.parametrize(
    "forge",
    [
        lambda r: r["requested_operation"].update(target_status="COMPLETED"),
        lambda r: r["requested_operation"].update(database_target="runtime"),
        lambda r: r.update(outcome="BLOCKED"),                       # BLOCKED with an operation
        lambda r: r.update(requested_operation=None),                # READY without one
    ],
)
def test_inconsistent_capture_is_unverified_and_records_nothing(step_run, forge):
    result, _ = step_run()
    forged = copy.deepcopy(result)
    forge(forged)

    assert not capture(STEP_TEST, json.dumps(forged, ensure_ascii=False))
    assert pending.load_records(LEAD, pending.STEP_KIND) == []


def test_blocked_capture_records_nothing(step_run):
    text = f"Đánh dấu bước Legal Review của {NVC} là hoàn thành"
    result, stdout = step_run(text)
    from tests.merchant.test_nl2e_p1_p2_p4 import CLI

    assert capture(f'{CLI} step preview --request "{text}" --test-database', stdout)
    assert pending.load_records(LEAD, pending.STEP_KIND) == []


# -------------------------------------------- execution boundary (preflight)


def test_runtime_step_update_execution_stays_disabled():
    # NL4C2A admits a confirmed Step Update on the test target only.
    attempt = SimpleNamespace(database_target="runtime", command="step update",
                              arguments=tuple(ready_operation()["argv"]))

    with pytest.raises(handoff.DirectPreflightRefused) as error:
        handoff.preflight_direct_execute(attempt)
    assert error.value.reason == "RUNTIME_EXECUTION_DISABLED"
    assert handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False
