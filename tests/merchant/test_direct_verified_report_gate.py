from copy import deepcopy
import uuid

import pytest

from claude.hooks import team_lifecycle as lifecycle


@pytest.fixture
def team(tmp_path, monkeypatch):
    monkeypatch.setattr(
        lifecycle, "team_state_dir", lambda: tmp_path
    )

    owner = "report-" + uuid.uuid4().hex

    with lifecycle.locked_team_state(owner) as state:
        state.setdefault("teammates", {})[
            "merchant-manager"
        ] = {
            "canonical_name": "merchant-manager",
            "status": "RUNNING",
            "current_run_id": "run-1",
            "current_task_id": "task-1",
            "authorized_operations": ["merchant_execute"],
            "authorized_selected_agents": [
                "merchant-manager"
            ],
            "result_received": False,
            "report_source": None,
            "direct_writes": {
                "write-1": {
                    "write_id": "write-1",
                    "run_id": "run-1",
                    "task_id": "task-1",
                    "status": "EXECUTING",
                    "claim_generation": 1,
                    "execution_attempt_id": (
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                    ),
                }
            },
        }

    return owner


def update(team, callback):
    with lifecycle.locked_team_state(team) as state:
        callback(state["teammates"]["merchant-manager"])


def record(team):
    return lifecycle.load_team_state(team)[
        "teammates"
    ]["merchant-manager"]


def report(team):
    return lifecycle.mark_bound_report_received(
        team, "merchant-manager",
        "run-1", "task-1", "sendmessage",
    )


def test_executing_cannot_complete(team):
    assert report(team) is False
    assert record(team)["status"] == "RUNNING"


def test_reserved_cannot_complete(team):
    update(
        team,
        lambda r: r["direct_writes"]["write-1"].update(
            status="RESERVED"
        ),
    )
    assert report(team) is False


def test_missing_reservation_cannot_complete(team):
    update(
        team,
        lambda r: r.update(direct_writes={}),
    )
    assert report(team) is False


def stage_verified_receipt_for_test(record):
    """Simulate the output of trusted completion in lifecycle unit tests.

    This does not verify PostgreSQL. Real E2E tests must use the
    actual trusted completion and recovery path.
    """
    from claude.hooks.merchant_completion_receipt import (
        build_completion_receipt,
    )

    writes = record["direct_writes"]

    for write_id, write in writes.items():
        assert write["status"] == "VERIFIED"

        write.setdefault("command", "merchant create")
        write.setdefault("database", "test")
        write.setdefault(
            "operation_key",
            "merchant-direct:v1:" + write_id,
        )
        write.setdefault("payload_hash", "a" * 64)
        write.setdefault(
            "merchant_id",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        )

    receipt = build_completion_receipt(record)
    assert receipt is not None

    record["direct_completion_receipt"] = receipt


def test_verified_can_report_and_release(team):
    update(
        team,
        lambda r: (
            r["direct_writes"]["write-1"].update(
                status="VERIFIED"
            ),
            stage_verified_receipt_for_test(r),
        ),
    )

    assert report(team) is True
    assert record(team)["status"] == "REPORT_RECEIVED"

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )

    assert released is True
    assert record(team)["status"] == "IDLE_REUSABLE"


def test_multiple_writes_require_all_verified(team):
    def prepare(r):
        r["direct_writes"]["write-1"]["status"] = (
            "VERIFIED"
        )
        second = deepcopy(
            r["direct_writes"]["write-1"]
        )
        second["write_id"] = "write-2"
        second["status"] = "EXECUTING"
        r["direct_writes"]["write-2"] = second

    update(team, prepare)

    assert report(team) is False

    update(
        team,
        lambda r: (
            r["direct_writes"]["write-2"].update(
                status="VERIFIED"
            ),
            stage_verified_receipt_for_test(r),
        ),
    )

    assert report(team) is True


def test_wrong_task_cannot_report(team):
    update(
        team,
        lambda r: r["direct_writes"]["write-1"].update(
            status="VERIFIED"
        ),
    )

    assert lifecycle.mark_bound_report_received(
        team, "merchant-manager",
        "run-1", "wrong-task", "sendmessage",
    ) is False


@pytest.mark.parametrize(
    "attempt_id",
    [
        None,
        "",
        "not-a-uuid",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        123,
    ],
)
def test_verified_invalid_attempt_cannot_report_or_release(
    team, attempt_id
):
    """Unbound VERIFIED must not reach report or idle release."""
    def prepare(r):
        write = r["direct_writes"]["write-1"]
        write["status"] = "VERIFIED"

        if attempt_id is None:
            write.pop("execution_attempt_id", None)
        else:
            write["execution_attempt_id"] = attempt_id

    update(team, prepare)

    assert report(team) is False

    current = record(team)
    assert current["status"] == "RUNNING"
    assert current["result_received"] is False

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )

    assert released is False
    assert record(team)["status"] == "RUNNING"


@pytest.mark.parametrize(
    "generation",
    [None, 0, -1, True, "1", 1.0],
)
def test_verified_missing_generation_cannot_report_or_release(
    team, generation
):
    """Invalid generation must block report and teammate release."""

    def prepare(record):
        write = record["direct_writes"]["write-1"]
        write["status"] = "VERIFIED"

        if generation is None:
            write.pop("claim_generation", None)
        else:
            write["claim_generation"] = generation

    update(team, prepare)

    assert report(team) is False

    current = record(team)
    assert current["status"] == "RUNNING"
    assert current["result_received"] is False

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )

    assert released is False
    assert record(team)["status"] == "RUNNING"



def test_generation_changed_after_completion_blocks_report(
    team, monkeypatch
):
    """A generation changed after completion must not authorize report."""
    from claude.hooks import merchant_direct_completion as completion

    def prepare(record):
        write = record["direct_writes"]["write-1"]
        write.update({
            "command": "merchant create",
            "database": "test",
            "operation_key": "merchant-direct:v1:" + "a" * 64,
            "payload_hash": "b" * 64,
            "claim_generation": 1,
            "status": "EXECUTING",
        })

    update(team, prepare)

    monkeypatch.setattr(
        completion,
        "load_team_state",
        lifecycle.load_team_state,
    )

    def reconcile(_repository, **kwargs):
        with lifecycle.locked_team_state(team) as state:
            write = state["teammates"]["merchant-manager"][
                "direct_writes"
            ][kwargs["write_id"]]

            write["status"] = "VERIFIED"
            write["merchant_id"] = "merchant-123"
            return dict(write)

    monkeypatch.setattr(
        completion,
        "reconcile_committed_merchant_create",
        reconcile,
    )

    completed = completion.reconcile_all_direct_writes(
        owner_session_id=team,
        teammate_name="merchant-manager",
        run_id="run-1",
        task_id="task-1",
        repository_factory=lambda database: object(),
    )

    assert completed is True
    assert record(team)["direct_writes"]["write-1"][
        "claim_generation"
    ] == 1

    # Simulate state mutation after successful completion.
    update(
        team,
        lambda r: r["direct_writes"]["write-1"].update(
            claim_generation=2
        ),
    )

    assert report(team) is False

    current = record(team)
    assert current["status"] == "RUNNING"
    assert current["result_received"] is False



def test_generation_changed_after_report_blocks_idle_release(team):
    """A post-report generation mutation must prevent teammate reuse."""

    def prepare(record):
        write = record["direct_writes"]["write-1"]
        write["status"] = "VERIFIED"
        write["claim_generation"] = 1
        stage_verified_receipt_for_test(record)

    update(team, prepare)

    assert report(team) is True
    assert record(team)["status"] == "REPORT_RECEIVED"

    # Mutation after report acceptance but before idle release.
    update(
        team,
        lambda record: record["direct_writes"]["write-1"].update(
            claim_generation=2
        ),
    )

    released, _reason = (
        lifecycle.release_reported_teammate_to_idle(
            team, "merchant-manager"
        )
    )

    assert released is False
    assert record(team)["status"] == "REPORT_RECEIVED"



def test_duplicate_report_rejects_changed_generation(team):
    """Duplicate SendMessage cannot approve mutated verified state."""
    def prepare(record):
        write = record["direct_writes"]["write-1"]
        write["status"] = "VERIFIED"
        stage_verified_receipt_for_test(record)

    update(team, prepare)

    assert report(team) is True
    assert record(team)["status"] == "REPORT_RECEIVED"

    # A valid integer, but no longer the verified generation.
    update(
        team,
        lambda r: r["direct_writes"]["write-1"].update(
            claim_generation=2
        ),
    )

    assert report(team) is False
    assert record(team)["status"] == "REPORT_RECEIVED"


def test_previous_task_receipt_cannot_authorize_new_task(team):
    """Reuse must not transfer old task completion authority."""
    def prepare(record):
        write = record["direct_writes"]["write-1"]
        write["status"] = "VERIFIED"
        stage_verified_receipt_for_test(record)

    update(team, prepare)

    assert report(team) is True

    released, _reason = (
        lifecycle.release_reported_teammate_to_idle(
            team, "merchant-manager"
        )
    )

    assert released is True
    assert record(team)["status"] == "IDLE_REUSABLE"

    # Start a different task without any new DB reconciliation.
    started = lifecycle.mark_teammate_running(
        team,
        "merchant-manager",
        "run-2",
        "task-2",
        operations=["merchant_execute"],
        selected_agents=["merchant-manager"],
    )

    assert started is True

    current = record(team)
    assert current["current_run_id"] == "run-2"
    assert current["current_task_id"] == "task-2"
    assert current["result_received"] is False

    # The previous receipt must not authorize the new task.
    assert lifecycle.mark_bound_report_received(
        team,
        "merchant-manager",
        "run-2",
        "task-2",
        "sendmessage",
    ) is False

    assert record(team)["status"] == "RUNNING"
    assert record(team)["result_received"] is False



def test_reused_teammate_can_complete_new_merchant_task(team):
    """Old verified writes must not obstruct completion of a new task."""
    from claude.hooks.merchant_completion_receipt import (
        build_completion_receipt,
    )

    def finish_first_task(record):
        write = record["direct_writes"]["write-1"]
        write["status"] = "VERIFIED"
        stage_verified_receipt_for_test(record)

    update(team, finish_first_task)

    assert report(team) is True

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )
    assert released is True

    assert lifecycle.mark_teammate_running(
        team,
        "merchant-manager",
        "run-2",
        "task-2",
        operations=["merchant_execute"],
        selected_agents=["merchant-manager"],
    ) is True

    def add_second_write(record):
        record.setdefault("direct_writes", {})["write-2"] = {
            "write_id": "write-2",
            "run_id": "run-2",
            "task_id": "task-2",
            "database": "test",
            "command": "merchant create",
            "operation_key": "merchant-direct:v1:" + "c" * 64,
            "payload_hash": "d" * 64,
            "execution_attempt_id": (
                "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
            ),
            "claim_generation": 1,
            "merchant_id": (
                "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
            ),
            "status": "VERIFIED",
        }

    update(team, add_second_write)

    current = record(team)

    # This checks whether the active state can represent task B.
    # It does not substitute for PostgreSQL evidence verification.
    receipt = build_completion_receipt(current)

    assert receipt is not None
    assert set(receipt["writes"]) == {"write-2"}



def test_real_reservation_after_reuse_preserves_history(team):
    """Real reservation API accepts a new task after verified archive."""
    from claude.hooks.merchant_direct_write_state import (
        reserve_merchant_create,
    )

    def finish_first_task(record):
        write = record["direct_writes"]["write-1"]
        write["status"] = "VERIFIED"
        stage_verified_receipt_for_test(record)

    update(team, finish_first_task)

    assert report(team) is True

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )
    assert released is True

    archived = record(team)

    assert "direct_writes" not in archived
    assert "direct_completion_receipt" not in archived

    history = archived["completed_direct_write_history"]
    assert len(history) == 1
    assert history[0]["run_id"] == "run-1"
    assert history[0]["task_id"] == "task-1"
    assert set(history[0]["writes"]) == {"write-1"}

    # Reservation API checks trusted pane identity.
    update(
        team,
        lambda record: record.update(
            trusted_pane_session_id="pane-2",
        ),
    )

    assert lifecycle.mark_teammate_running(
        team,
        "merchant-manager",
        "run-2",
        "task-2",
        operations=["merchant_execute"],
        selected_agents=["merchant-manager"],
    ) is True

    reserved = reserve_merchant_create(
        owner_session_id=team,
        teammate_name="merchant-manager",
        pane_session_id="pane-2",
        run_id="run-2",
        task_id="task-2",
        write_id="write-2",
        database="test",
        payload={
            "code": "CP78_REUSE_TEST",
            "name": "CP7.8 Reuse Reservation",
        },
    )

    assert reserved["status"] == "RESERVED"
    assert reserved["run_id"] == "run-2"
    assert reserved["task_id"] == "task-2"

    current = record(team)

    assert set(current["direct_writes"]) == {"write-2"}
    assert current["direct_writes"]["write-2"] == reserved

    assert current["completed_direct_write_history"] == history

    # A reserved write must not authorize report or release.
    assert lifecycle.mark_bound_report_received(
        team,
        "merchant-manager",
        "run-2",
        "task-2",
        "sendmessage",
    ) is False

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )

    assert released is False
    assert record(team)["status"] == "RUNNING"



def test_malformed_archive_history_preserves_active_write(team):
    """Malformed history must block release without losing active data."""

    def prepare(record):
        record["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(record)
        record["completed_direct_write_history"] = "invalid"

    update(team, prepare)
    before = record(team)["direct_writes"]["write-1"].copy()

    assert report(team) is True

    released, _reason = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )

    assert released is False

    current = record(team)
    assert current["status"] == "REPORT_RECEIVED"
    assert current["direct_writes"]["write-1"] == before
    assert current["completed_direct_write_history"] == "invalid"
    assert "direct_completion_receipt" in current


def test_generation_mismatch_preserves_active_write_on_release(team):
    """Generation mutation must block archive and retain recovery state."""

    def prepare(record):
        record["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(record)

    update(team, prepare)

    assert report(team) is True

    update(
        team,
        lambda record: record["direct_writes"]["write-1"].update(
            claim_generation=2
        ),
    )

    released, _reason = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )

    assert released is False

    current = record(team)
    assert current["status"] == "REPORT_RECEIVED"
    assert current["direct_writes"]["write-1"]["claim_generation"] == 2
    assert "direct_completion_receipt" in current
    assert not current.get("completed_direct_write_history")



def test_multiple_archive_cycles_preserve_history_and_fence_reuse(team):
    """A -> B -> C retains history without replaying old authority."""

    def finish_task_a(record):
        record["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(record)

    update(team, finish_task_a)

    assert report(team) is True
    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )
    assert released is True

    assert lifecycle.mark_teammate_running(
        team,
        "merchant-manager",
        "run-2",
        "task-2",
        operations=["merchant_execute"],
        selected_agents=["merchant-manager"],
    ) is True

    def finish_task_b(record):
        record["direct_writes"] = {
            "write-2": {
                "write_id": "write-2",
                "run_id": "run-2",
                "task_id": "task-2",
                "database": "test",
                "command": "merchant create",
                "operation_key": "merchant-direct:v1:" + "c" * 64,
                "payload_hash": "d" * 64,
                "execution_attempt_id": (
                    "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
                ),
                "claim_generation": 1,
                "merchant_id": (
                    "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
                ),
                "status": "VERIFIED",
            }
        }
        stage_verified_receipt_for_test(record)

    update(team, finish_task_b)

    assert lifecycle.mark_bound_report_received(
        team,
        "merchant-manager",
        "run-2",
        "task-2",
        "sendmessage",
    ) is True

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )
    assert released is True

    settled = record(team)
    history = settled["completed_direct_write_history"]

    assert len(history) == 2
    assert [
        (item["run_id"], item["task_id"])
        for item in history
    ] == [
        ("run-1", "task-1"),
        ("run-2", "task-2"),
    ]

    assert set(history[0]["writes"]) == {"write-1"}
    assert set(history[1]["writes"]) == {"write-2"}
    assert "direct_writes" not in settled
    assert "direct_completion_receipt" not in settled

    # Exercise the other lifecycle entry point for task C.
    accepted, reason = lifecycle.reserve_reusable_teammate(
        team,
        "merchant-manager",
        "run-3",
        "task-3",
        operations=["merchant_execute"],
        selected_agents=["merchant-manager"],
    )

    assert accepted is True, reason

    current = record(team)
    assert current["status"] == "RUNNING"
    assert current["current_run_id"] == "run-3"
    assert current["current_task_id"] == "task-3"
    assert current["completed_direct_write_history"] == history
    assert "direct_writes" not in current
    assert "direct_completion_receipt" not in current

    # Neither archived receipt can authorize task C.
    assert lifecycle.mark_bound_report_received(
        team,
        "merchant-manager",
        "run-3",
        "task-3",
        "sendmessage",
    ) is False

    assert record(team)["result_received"] is False



@pytest.mark.parametrize(
    "bad_history",
    [
        [{}],
        [{"version": 1}],
        [{"version": 1, "run_id": "old", "task_id": "old",
          "writes": {}}],
        [{"version": "1", "run_id": "old", "task_id": "old",
          "writes": {"write-x": {}}}],
    ],
)
def test_invalid_historical_receipt_blocks_archive(
    team, bad_history
):
    """Malformed historical receipts must not be accepted."""

    def prepare(record):
        record["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(record)
        record["completed_direct_write_history"] = bad_history

    update(team, prepare)

    assert report(team) is True

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )

    assert released is False

    current = record(team)
    assert current["status"] == "REPORT_RECEIVED"
    assert "direct_writes" in current
    assert "direct_completion_receipt" in current
    assert current["completed_direct_write_history"] == bad_history



def test_report_persistence_failure_blocks_release_until_retry(
    team, monkeypatch
):
    """Failed report save cannot authorize idle release."""
    import json
    import pytest
    from pathlib import Path

    from claude.hooks.merchant_completion_receipt import (
        receipt_matches_state,
    )

    def prepare(r):
        r["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(r)

    update(team, prepare)

    before = lifecycle.load_team_state(team)
    before_record = before["teammates"]["merchant-manager"]

    assert before_record["status"] == "RUNNING"
    assert before_record.get("result_received") is not True
    assert receipt_matches_state(
        before_record,
        before_record["direct_completion_receipt"],
    )

    original_replace = lifecycle.replace_with_retry
    failures = []

    def fail_report_save(source, destination):
        pending = json.loads(
            Path(source).read_text(encoding="utf-8")
        )
        pending_record = pending["teammates"]["merchant-manager"]

        if (
            pending_record.get("status") == "REPORT_RECEIVED"
            and pending_record.get("result_received") is True
            and not failures
        ):
            failures.append("report-save")
            raise OSError("INJECTED_REPORT_SAVE_FAILURE")

        return original_replace(source, destination)

    monkeypatch.setattr(
        lifecycle,
        "replace_with_retry",
        fail_report_save,
    )

    with pytest.raises(
        OSError,
        match="INJECTED_REPORT_SAVE_FAILURE",
    ):
        report(team)

    # The durable receipt survives; report transition does not.
    after_failure = lifecycle.load_team_state(team)
    failed_record = after_failure["teammates"]["merchant-manager"]

    assert failed_record["status"] == "RUNNING"
    assert failed_record.get("result_received") is not True
    assert failed_record.get("report_source") != "sendmessage"
    assert failed_record["direct_writes"] == (
        before_record["direct_writes"]
    )
    assert failed_record["direct_completion_receipt"] == (
        before_record["direct_completion_receipt"]
    )
    assert failures == ["report-save"]

    # A report that was not durably persisted cannot release.
    released, _reason = (
        lifecycle.release_reported_teammate_to_idle(
            team,
            "merchant-manager",
        )
    )
    assert released is False

    blocked_record = lifecycle.load_team_state(
        team
    )["teammates"]["merchant-manager"]

    assert blocked_record["status"] == "RUNNING"
    assert blocked_record["direct_completion_receipt"] == (
        before_record["direct_completion_receipt"]
    )

    # Retry the same authenticated report.
    assert report(team) is True

    after_retry = lifecycle.load_team_state(team)
    retried = after_retry["teammates"]["merchant-manager"]

    assert retried["status"] == "REPORT_RECEIVED"
    assert retried["result_received"] is True
    assert retried["report_source"] == "sendmessage"
    assert retried["direct_completion_receipt"] == (
        before_record["direct_completion_receipt"]
    )

    # Duplicate report delivery remains idempotent.
    assert report(team) is True

    repeated = lifecycle.load_team_state(
        team
    )["teammates"]["merchant-manager"]

    assert repeated["status"] == "REPORT_RECEIVED"
    assert repeated["direct_completion_receipt"] == (
        before_record["direct_completion_receipt"]
    )

    # Only a durable authenticated report permits release.
    released, _reason = (
        lifecycle.release_reported_teammate_to_idle(
            team,
            "merchant-manager",
        )
    )
    assert released is True

    final_record = lifecycle.load_team_state(
        team
    )["teammates"]["merchant-manager"]

    assert final_record["status"] == "IDLE_REUSABLE"
    assert "direct_writes" not in final_record
    assert "direct_completion_receipt" not in final_record
    assert len(final_record["completed_direct_write_history"]) == 1



def test_idle_archive_save_failure_retries_exactly_once(
    team, monkeypatch
):
    """Failed archive persistence must preserve the active task."""
    import copy
    import json
    import pytest
    from pathlib import Path

    from claude.hooks.merchant_completion_receipt import (
        receipt_matches_state,
    )

    def prepare(r):
        r["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(r)

    update(team, prepare)
    assert report(team) is True

    before = lifecycle.load_team_state(team)
    before_record = before["teammates"]["merchant-manager"]

    assert before_record["status"] == "REPORT_RECEIVED"
    assert before_record["result_received"] is True

    original_receipt = copy.deepcopy(
        before_record["direct_completion_receipt"]
    )
    original_writes = copy.deepcopy(
        before_record["direct_writes"]
    )

    assert receipt_matches_state(
        before_record, original_receipt
    )

    original_replace = lifecycle.replace_with_retry
    failures = []

    def fail_idle_save(source, destination):
        pending = json.loads(
            Path(source).read_text(encoding="utf-8")
        )
        candidate = pending["teammates"]["merchant-manager"]

        if (
            candidate.get("status") == "IDLE_REUSABLE"
            and not failures
        ):
            failures.append("idle-save")
            raise OSError("INJECTED_IDLE_ARCHIVE_SAVE_FAILURE")

        return original_replace(source, destination)

    monkeypatch.setattr(
        lifecycle, "replace_with_retry", fail_idle_save
    )

    with pytest.raises(
        OSError,
        match="INJECTED_IDLE_ARCHIVE_SAVE_FAILURE",
    ):
        lifecycle.release_reported_teammate_to_idle(
            team, "merchant-manager"
        )

    # The rejected filesystem replacement must preserve
    # the complete durable pre-release state.
    after_failure = lifecycle.load_team_state(team)
    failed = after_failure["teammates"]["merchant-manager"]

    assert failed == before_record
    assert failed["status"] == "REPORT_RECEIVED"
    assert failed["direct_writes"] == original_writes
    assert failed["direct_completion_receipt"] == original_receipt

    assert failed["current_run_id"] == "run-1"
    assert failed["current_task_id"] == "task-1"
    assert failures == ["idle-save"]

    # Retry must archive the same task, without duplication.
    released, _reason = (
        lifecycle.release_reported_teammate_to_idle(
            team, "merchant-manager"
        )
    )
    assert released is True

    after_retry = lifecycle.load_team_state(team)
    settled = after_retry["teammates"]["merchant-manager"]

    assert settled["status"] == "IDLE_REUSABLE"
    assert settled["current_run_id"] is None
    assert settled["current_task_id"] is None
    assert settled["authorized_operations"] == []
    assert settled["authorized_selected_agents"] == []

    assert "direct_writes" not in settled
    assert "direct_completion_receipt" not in settled

    history = settled["completed_direct_write_history"]
    assert len(history) == 1
    assert history[0] == original_receipt

    # An additional idle-release call must not archive again.
    released_again, _reason = (
        lifecycle.release_reported_teammate_to_idle(
            team, "merchant-manager"
        )
    )
    assert released_again is True

    final = lifecycle.load_team_state(
        team
    )["teammates"]["merchant-manager"]

    assert final["status"] == "IDLE_REUSABLE"
    assert final["completed_direct_write_history"] == history



def test_report_diagnostics_respect_durable_persistence(
    team, monkeypatch
):
    """Only a durable, newly accepted report produces telemetry."""
    import json
    import pytest
    from pathlib import Path

    def prepare(r):
        r["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(r)

    update(team, prepare)

    original_replace = lifecycle.replace_with_retry
    failures = []
    events = []

    def fail_once(source, destination):
        pending = json.loads(
            Path(source).read_text(encoding="utf-8")
        )
        pending_record = pending["teammates"]["merchant-manager"]

        if (
            pending_record.get("status") == "REPORT_RECEIVED"
            and not failures
        ):
            failures.append("report-save")
            raise OSError("INJECTED_DIAGNOSTIC_REPORT_SAVE_FAILURE")

        return original_replace(source, destination)

    monkeypatch.setattr(
        lifecycle, "replace_with_retry", fail_once
    )

    def sink(encoded):
        persisted = record(team)
        assert persisted["status"] == "REPORT_RECEIVED"
        assert persisted["result_received"] is True
        events.append(json.loads(encoded))

    def send():
        return lifecycle.mark_bound_report_received(
            team,
            "merchant-manager",
            "run-1",
            "task-1",
            "sendmessage",
            diagnostic_sink=sink,
        )

    with pytest.raises(
        OSError,
        match="INJECTED_DIAGNOSTIC_REPORT_SAVE_FAILURE",
    ):
        send()

    assert failures == ["report-save"]
    assert events == []
    assert record(team)["status"] == "RUNNING"

    assert send() is True

    assert len(events) == 1
    assert events[0]["event_type"] == "merchant.report"
    assert events[0]["stage"] == "report_transition"
    assert events[0]["outcome"] == "completed"
    assert events[0]["run_id"] == "run-1"
    assert events[0]["task_id"] == "task-1"
    assert events[0]["write_id"] == "write-1"
    assert events[0]["claim_generation"] == 1

    # Duplicate SendMessage delivery is idempotent.
    assert send() is True
    assert len(events) == 1

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )
    assert released is True
    assert record(team)["status"] == "IDLE_REUSABLE"


def test_report_diagnostic_sink_failure_does_not_block_lifecycle(
    team
):
    """Telemetry failure must not reject a valid persisted report."""
    def prepare(r):
        r["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(r)

    update(team, prepare)

    def broken_sink(_encoded):
        raise RuntimeError("INJECTED_DIAGNOSTIC_SINK_FAILURE")

    assert lifecycle.mark_bound_report_received(
        team,
        "merchant-manager",
        "run-1",
        "task-1",
        "sendmessage",
        diagnostic_sink=broken_sink,
    ) is True

    assert record(team)["status"] == "REPORT_RECEIVED"

    released, _ = lifecycle.release_reported_teammate_to_idle(
        team, "merchant-manager"
    )
    assert released is True
    assert record(team)["status"] == "IDLE_REUSABLE"



def test_archive_diagnostics_respect_durable_persistence(
    team, monkeypatch
):
    """Archive telemetry requires a durable IDLE transition."""
    import json
    import pytest
    from pathlib import Path

    def prepare(r):
        r["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(r)

    update(team, prepare)
    assert report(team) is True

    original_receipt = record(team)["direct_completion_receipt"]
    original_replace = lifecycle.replace_with_retry

    events = []
    failures = []

    def fail_once(source, destination):
        pending = json.loads(
            Path(source).read_text(encoding="utf-8")
        )
        candidate = pending["teammates"]["merchant-manager"]

        if (
            candidate.get("status") == "IDLE_REUSABLE"
            and not failures
        ):
            failures.append("idle-save")
            raise OSError("INJECTED_ARCHIVE_SAVE_FAILURE")

        return original_replace(source, destination)

    monkeypatch.setattr(
        lifecycle, "replace_with_retry", fail_once
    )

    def sink(encoded):
        persisted = record(team)
        assert persisted["status"] == "IDLE_REUSABLE"
        assert "direct_writes" not in persisted
        events.append(json.loads(encoded))

    def release():
        return lifecycle.release_reported_teammate_to_idle(
            team,
            "merchant-manager",
            diagnostic_sink=sink,
        )

    with pytest.raises(
        OSError,
        match="INJECTED_ARCHIVE_SAVE_FAILURE",
    ):
        release()

    assert failures == ["idle-save"]
    assert events == []

    failed = record(team)
    assert failed["status"] == "REPORT_RECEIVED"
    assert failed["direct_completion_receipt"] == original_receipt

    released, prior = release()
    assert released is True
    assert prior == "REPORT_RECEIVED"

    assert len(events) == 1
    assert events[0]["event_type"] == "merchant.archive"
    assert events[0]["stage"] == "idle_release"
    assert events[0]["outcome"] == "completed"
    assert events[0]["run_id"] == "run-1"
    assert events[0]["task_id"] == "task-1"
    assert events[0]["write_id"] == "write-1"
    assert events[0]["claim_generation"] == 1

    settled = record(team)
    assert settled["status"] == "IDLE_REUSABLE"
    assert settled["current_run_id"] is None
    assert settled["current_task_id"] is None
    assert settled["completed_direct_write_history"] == [
        original_receipt
    ]

    # Duplicate idle release must not emit a second event.
    released_again, prior = release()
    assert released_again is True
    assert prior == "IDLE_REUSABLE"
    assert len(events) == 1
    assert record(team)["completed_direct_write_history"] == [
        original_receipt
    ]


def test_archive_diagnostic_sink_failure_does_not_block_idle(team):
    """Telemetry failure cannot undo persisted teammate release."""
    def prepare(r):
        r["direct_writes"]["write-1"]["status"] = "VERIFIED"
        stage_verified_receipt_for_test(r)

    update(team, prepare)
    assert report(team) is True

    original_receipt = record(team)["direct_completion_receipt"]

    def broken_sink(_encoded):
        raise RuntimeError("INJECTED_SINK_FAILURE")

    released, prior = lifecycle.release_reported_teammate_to_idle(
        team,
        "merchant-manager",
        diagnostic_sink=broken_sink,
    )

    assert released is True
    assert prior == "REPORT_RECEIVED"

    settled = record(team)
    assert settled["status"] == "IDLE_REUSABLE"
    assert settled["completed_direct_write_history"] == [
        original_receipt
    ]
    assert "direct_writes" not in settled
    assert "direct_completion_receipt" not in settled



def test_legacy_lifecycle_does_not_emit_merchant_diagnostics(
    team
):
    """Ordinary teammate lifecycle must not emit Merchant events."""
    events = []

    def prepare(r):
        r["authorized_operations"] = []
        r["authorized_selected_agents"] = []
        r.pop("direct_writes", None)
        r.pop("direct_completion_receipt", None)

    update(team, prepare)

    assert lifecycle.mark_bound_report_received(
        team,
        "merchant-manager",
        "run-1",
        "task-1",
        "sendmessage",
        diagnostic_sink=events.append,
    ) is True

    assert record(team)["status"] == "REPORT_RECEIVED"
    assert events == []

    released, prior = lifecycle.release_reported_teammate_to_idle(
        team,
        "merchant-manager",
        diagnostic_sink=events.append,
    )

    assert released is True
    assert prior == "REPORT_RECEIVED"
    assert record(team)["status"] == "IDLE_REUSABLE"
    assert events == []
