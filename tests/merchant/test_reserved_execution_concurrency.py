"""Real-thread concurrency tests for Direct Merchant lifecycle guards."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
import uuid

import pytest

from claude.clients.merchant.atomic_create import _canonical_hash
from claude.hooks import team_lifecycle
from claude.hooks import merchant_reserved_execution as execution


PAYLOAD = {
    "code": "CONCURRENCY_TEST",
    "name": "Concurrency Test Merchant",
}

OPERATION_KEY = "merchant-direct:v1:" + "a" * 64


def payload_hash():
    return _canonical_hash({
        "command": "merchant create",
        "merchant_id": None,
        "code": PAYLOAD["code"],
        "name": PAYLOAD["name"],
        "region_code": None,
        "created_by": None,
    })


@pytest.fixture
def environment(tmp_path, monkeypatch):
    # Both threads use actual filesystem state and FileLock.
    monkeypatch.setattr(
        team_lifecycle,
        "team_state_dir",
        lambda: tmp_path,
    )

    owner = "concurrent-owner-" + uuid.uuid4().hex
    context = {
        "owner_session_id": owner,
        "teammate_name": "merchant-manager",
        "pane_session_id": "pane-1",
        "run_id": "run-1",
        "task_id": "task-1",
        "write_id": "write-1",
        "database": "test",
    }

    with team_lifecycle.locked_team_state(owner) as state:
        state.setdefault("teammates", {})["merchant-manager"] = {
            "canonical_name": "merchant-manager",
            "status": "RUNNING",
            "current_run_id": "run-1",
            "current_task_id": "task-1",
            "trusted_pane_session_id": "pane-1",
            "authorized_operations": ["merchant_execute"],
            "authorized_selected_agents": ["merchant-manager"],
            "result_received": False,
            "report_source": None,
            "direct_writes": {
                "write-1": {
                    "write_id": "write-1",
                    "run_id": "run-1",
                    "task_id": "task-1",
                    "database": "test",
                    "command": "merchant create",
                    "payload_hash": payload_hash(),
                    "operation_key": OPERATION_KEY,
                    "status": "RESERVED",
                },
            },
        }

    return context


def current_record(context):
    state = team_lifecycle.load_team_state(
        context["owner_session_id"]
    )
    return state["teammates"]["merchant-manager"]


@pytest.mark.parametrize(
    "transition",
    [
        "mark_running",
        "mark_idle",
        "mark_failed",
        "release_reported",
    ],
)
def test_inflight_write_blocks_ownership_mutation(
    environment,
    monkeypatch,
    transition,
):
    context = environment
    started = Event()
    unblock = Event()
    calls = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        started.set()

        if not unblock.wait(timeout=10):
            raise TimeoutError("Test did not unblock executor")

        return {
            "success": True,
            "mode": "EXECUTE",
            "command": "merchant create",
            "database": "test",
            "result": {
                "success": True,
                "merchant_id": str(uuid.uuid4()),
            },
            "replayed": False,
        }

    monkeypatch.setattr(
        execution,
        "execute_protected_merchant_create",
        fake_execute,
    )

    repo = SimpleNamespace(
        config=SimpleNamespace(
            database="coding_agent_merchant_test"
        )
    )

    def run_execution():
        return execution.execute_reserved_merchant_create(
            repository=repo,
            payload=PAYLOAD,
            **context,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(run_execution)

        try:
            assert started.wait(timeout=10), (
                "Executor did not start"
            )

            # The claim must already be durable on disk
            # while the executor is blocked.
            current = current_record(context)
            assert current["direct_writes"][
                "write-1"
            ]["status"] == "EXECUTING"

            owner = context["owner_session_id"]
            teammate = context["teammate_name"]

            if transition == "mark_running":
                outcome = pool.submit(
                    team_lifecycle.mark_teammate_running,
                    owner,
                    teammate,
                    "replacement-run",
                    "replacement-task",
                    ["merchant_execute"],
                    ["merchant-manager"],
                ).result(timeout=10)

                assert outcome is False

            elif transition == "mark_idle":
                outcome = pool.submit(
                    team_lifecycle.mark_teammate_idle_reusable,
                    owner,
                    teammate,
                ).result(timeout=10)

                assert outcome is False

            elif transition == "mark_failed":
                outcome = pool.submit(
                    team_lifecycle.mark_teammate_failed,
                    owner,
                    teammate,
                    "test failure",
                ).result(timeout=10)

                assert outcome is False

            elif transition == "release_reported":
                # Simulate a report flag being set separately;
                # in-flight writes must still block release.
                with team_lifecycle.locked_team_state(owner) as state:
                    record = state["teammates"][teammate]
                    record["status"] = "REPORT_RECEIVED"
                    record["result_received"] = True
                    record["report_source"] = "sendmessage"

                outcome = pool.submit(
                    team_lifecycle.release_reported_teammate_to_idle,
                    owner,
                    teammate,
                ).result(timeout=10)

                assert outcome[0] is False

            current = current_record(context)

            assert current["current_run_id"] == "run-1"
            assert current["current_task_id"] == "task-1"
            assert current["direct_writes"][
                "write-1"
            ]["status"] == "EXECUTING"

        finally:
            # Ensure worker shutdown even if an assertion fails.
            unblock.set()

        result = future.result(timeout=10)

    assert result["success"] is True
    assert len(calls) == 1

    # Execution does not itself prove committed evidence.
    assert current_record(context)["direct_writes"][
        "write-1"
    ]["status"] == "EXECUTING"


def test_second_execution_cannot_claim_same_write(
    environment,
    monkeypatch,
):
    context = environment
    started = Event()
    unblock = Event()
    calls = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        started.set()

        if not unblock.wait(timeout=10):
            raise TimeoutError("Executor blocked")

        return {
            "success": True,
            "mode": "EXECUTE",
            "command": "merchant create",
            "database": "test",
            "result": {
                "success": True,
                "merchant_id": str(uuid.uuid4()),
            },
            "replayed": False,
        }

    monkeypatch.setattr(
        execution,
        "execute_protected_merchant_create",
        fake_execute,
    )

    repo = SimpleNamespace(
        config=SimpleNamespace(
            database="coding_agent_merchant_test"
        )
    )

    def execute():
        return execution.execute_reserved_merchant_create(
            repository=repo,
            payload=PAYLOAD,
            **context,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute)

        try:
            assert started.wait(timeout=10)

            second = pool.submit(execute)

            with pytest.raises(
                execution.ReservedExecutionError
            ):
                second.result(timeout=10)

        finally:
            unblock.set()

        assert first.result(timeout=10)["success"] is True

    assert len(calls) == 1


def test_executing_write_blocks_bound_report(environment):
    context = environment
    owner = context["owner_session_id"]
    teammate = context["teammate_name"]

    with team_lifecycle.locked_team_state(owner) as state:
        record = state["teammates"][teammate]
        record["direct_writes"]["write-1"]["status"] = "EXECUTING"

    accepted = team_lifecycle.mark_bound_report_received(
        owner,
        teammate,
        context["run_id"],
        context["task_id"],
        source="sendmessage",
    )

    assert accepted is False

    current = current_record(context)
    assert current["result_received"] is not True
    assert current["direct_writes"]["write-1"]["status"] == "EXECUTING"
