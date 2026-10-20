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


def test_verified_can_report_and_release(team):
    update(
        team,
        lambda r: r["direct_writes"]["write-1"].update(
            status="VERIFIED"
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
        lambda r: r["direct_writes"]["write-2"].update(
            status="VERIFIED"
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