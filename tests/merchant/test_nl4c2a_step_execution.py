"""CP12H.NL4C2A: test-only Step Update execution, authorization gates (no database).

A Step Update joins test-mode Direct EXECUTE only as the user's own
confirmation of a verified preview, spent for this exact run. A typed or
model-built scope, another run's or session's confirmation, an edited argv
or a runtime target is refused before any reservation, spend or database
connection.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from claude.hooks import merchant_direct_handoff as handoff
from claude.hooks import merchant_pending_confirmation as pending
from tests.merchant.test_nl4c1_step_confirmation import (  # noqa: F401 (fixtures)
    OTHER_SESSION,
    isolated,
    put,
    ready_operation,
    status_of,
    submit,
)
from tests.merchant.test_nl2e_p1_p2_p4 import LEAD, intent_gate, runtime_state


def attempt(operation, *, run_id, owner=LEAD, argv=None, target="test"):
    return SimpleNamespace(
        owner_session_id=owner, teammate_name="merchant-manager", run_id=run_id,
        task_id="task-1", command="step update", database_target=target,
        arguments=tuple(argv if argv is not None else operation["argv"]),
    )


@pytest.fixture
def no_database(monkeypatch):
    """Every refusal here happens before a database connection."""

    def connect(_target):
        raise AssertionError("refused attempts never reach the database")

    monkeypatch.setattr(handoff, "_target_repository", connect)


def confirmed(operation):
    put(operation)
    output = submit("/solve Xác nhận cập nhật")
    assert output.get("decision") != "block", output
    return runtime_state.load_state(LEAD)["run_id"]


def refused(attempt_):
    with pytest.raises(handoff.DirectPreflightRefused) as error:
        handoff.preflight_direct_execute(attempt_)
    return error.value.reason


# ------------------------------------------------------------ allowlist


def test_test_mode_admits_step_update_and_runtime_stays_disabled():
    assert handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False
    # CP12H.NL4D4A: the confirmed Purchase Request joined test mode.
    assert handoff.TEST_MODE_COMMANDS == {"merchant create", "project create", "step update",
                                          "procurement update"}
    assert handoff.direct_execute_enabled("step update", "test")
    assert not handoff.direct_execute_enabled("step update", "runtime")
    # No other Step or Project write joined test mode.
    for command in ("project update", "document approve"):
        assert not handoff.direct_execute_enabled(command, "test")


@pytest.mark.parametrize("target", [None, "test"])
def test_typed_step_scope_is_never_authority(isolated, target):
    operation = ready_operation()
    prefix = "/solve --confirm" + (f" --merchant-target {target}" if target else "")

    output = submit(f"{prefix} --merchant-scope {json.dumps(operation['argv'])} Update the step")

    assert output["decision"] == "block"
    assert "Xác nhận cập nhật" in output["reason"]
    assert runtime_state.load_state(LEAD) is None


# ------------------------------------------- preflight: trusted confirmation


def test_scope_without_a_confirmed_record_is_refused(isolated, no_database):
    operation = ready_operation()
    put(operation)                                       # pending, never confirmed

    assert refused(attempt(operation, run_id="run-x")) == "STEP_CONFIRMATION_REQUIRED"
    assert status_of(operation["step_id"]) == ["PENDING"]


def test_confirmation_of_another_run_or_session_is_refused(isolated, no_database):
    operation = ready_operation()
    run_id = confirmed(operation)

    assert refused(attempt(operation, run_id="other-run")) == "STEP_CONFIRMATION_REQUIRED"
    assert refused(attempt(operation, run_id=run_id, owner=OTHER_SESSION)) == (
        "STEP_CONFIRMATION_REQUIRED"
    )


@pytest.mark.parametrize(
    "edit,target",
    [
        (lambda argv: argv[:4] + ["COMPLETED"] + argv[5:], "test"),  # target status swapped
        (lambda argv: argv[:6] + ["99"] + argv[7:], "test"),         # version edited
        (lambda argv: argv, "runtime"),                              # database swapped
    ],
    ids=["target-status", "version", "database"],
)
def test_changed_scope_is_refused(isolated, no_database, edit, target):
    operation = ready_operation()
    run_id = confirmed(operation)
    reason = refused(attempt(operation, run_id=run_id, argv=edit(list(operation["argv"])),
                             target=target))

    assert reason == ("RUNTIME_EXECUTION_DISABLED" if target == "runtime"
                      else "STEP_CONFIRMATION_MISMATCH")


def test_damaged_confirmed_record_is_refused(isolated, no_database):
    operation = ready_operation()
    run_id = confirmed(operation)
    with pending._locked(LEAD, pending.STEP_KIND) as records:
        records[0]["operation"]["target_status"] = "COMPLETED"   # argv no longer canonical

    assert refused(attempt(operation, run_id=run_id)) == "STEP_CONFIRMATION_REQUIRED"


def test_missing_store_is_refused(isolated, no_database):
    operation = ready_operation()
    run_id = confirmed(operation)
    pending.store_path(LEAD, pending.STEP_KIND).unlink()

    assert refused(attempt(operation, run_id=run_id)) == "STEP_CONFIRMATION_REQUIRED"


def test_project_create_confirmation_never_authorizes_a_step(isolated, no_database):
    operation = ready_operation()
    put(operation)
    with pending._locked(LEAD, pending.STEP_KIND) as records:     # a Project store look-alike
        records[0].update(status=pending.CONFIRMED, confirmed_run_id="run-p")
    records = pending.load_records(LEAD, pending.STEP_KIND)
    pending.store_path(LEAD, pending.PROJECT_KIND).write_text(json.dumps(records), encoding="utf-8")
    pending.store_path(LEAD, pending.STEP_KIND).unlink()

    assert refused(attempt(operation, run_id="run-p")) == "STEP_CONFIRMATION_REQUIRED"


def test_valid_confirmation_passes_to_the_database_rejudgement(isolated, monkeypatch):
    operation = ready_operation()
    run_id = confirmed(operation)
    seen = []
    monkeypatch.setattr(handoff, "_target_repository", lambda target: seen.append(target) or "repo")
    monkeypatch.setattr(handoff, "_verify_step_preview",
                        lambda attempt_, repository: seen.append(repository))

    assert handoff.preflight_direct_execute(attempt(operation, run_id=run_id)) == "repo"
    assert seen == ["test", "repo"]                       # re-judged before any spend


def test_unverifiable_rejudgement_is_refused(isolated, monkeypatch):
    operation = ready_operation()
    run_id = confirmed(operation)
    monkeypatch.setattr(handoff, "_target_repository", lambda target: object())

    assert refused(attempt(operation, run_id=run_id)) == "STEP_PREVIEW_UNVERIFIABLE"


# -------------------------------------------------- confirmation entry points


def test_runtime_record_is_refused_unspent(isolated):
    operation = ready_operation(target="runtime")
    put(operation)

    output = submit("/solve Xác nhận cập nhật")

    assert output["decision"] == "block" and "only on the test database" in output["reason"]
    assert status_of(operation["step_id"]) == ["PENDING"]


def test_relayed_expansion_without_submit_never_confirms(isolated):
    operation = ready_operation()
    put(operation)

    output = intent_gate.run(
        {"hook_event_name": "UserPromptExpansion", "session_id": LEAD,
         "prompt": "/solve Xác nhận cập nhật"},
        env={},
    )

    assert output["decision"] == "block"
    assert status_of(operation["step_id"]) == ["PENDING"]


@pytest.mark.parametrize("prompt", [
    "/solve Xác nhận cập nhật COMPLETED",
    "/solve Xác nhận cập nhật trên database runtime",
    "/solve Xác nhận cập nhật bước 2 thành hoàn thành",
])
def test_target_cannot_be_replaced_in_the_confirmation(isolated, prompt):
    operation = ready_operation()
    put(operation)

    class NeverConfirms:
        def parse(self, request):
            raise RuntimeError("not a confirmation: classified as ordinary text")

    output = submit(prompt, parser=NeverConfirms)

    assert output["decision"] == "block"
    assert status_of(operation["step_id"]) == ["PENDING"]
