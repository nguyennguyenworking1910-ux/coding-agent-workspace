import pytest

from claude.hooks import team_lifecycle as lifecycle


@pytest.fixture
def team(monkeypatch, tmp_path):
    monkeypatch.setenv(
        lifecycle.TEAM_STATE_DIR_ENV_VAR,
        str(tmp_path),
    )

    owner = "direct-fencing-owner"
    name = "merchant-manager"

    with lifecycle.locked_team_state(owner) as state:
        assert state is not None
        record = lifecycle.init_teammate_record(
            name, name
        )
        record.update({
            "status": "RUNNING",
            "current_run_id": "run-1",
            "current_task_id": "task-1",
            "authorized_operations": ["merchant_execute"],
            "authorized_selected_agents": [name],
            "result_received": False,
            "direct_writes": {
                "write-1": {
                    "write_id": "write-1",
                    "run_id": "run-1",
                    "task_id": "task-1",
                    "status": "EXECUTING",
                },
            },
        })
        state.setdefault("teammates", {})[name] = record

    return owner, name


def test_legacy_report_cannot_bypass_direct_execution(team):
    owner, name = team

    before = lifecycle.load_team_state(owner)
    accepted = lifecycle.mark_report_received(
        owner, name, "task-1", source="sendmessage"
    )
    after = lifecycle.load_team_state(owner)

    assert accepted is False
    assert after == before


def test_legacy_report_remains_available_for_normal_teammates(
    team,
):
    owner, name = team

    with lifecycle.locked_team_state(owner) as state:
        record = state["teammates"][name]
        record["authorized_operations"] = []
        record.pop("direct_writes", None)

    accepted = lifecycle.mark_report_received(
        owner, name, "task-1", source="sendmessage"
    )

    current = lifecycle.load_team_state(owner)["teammates"][name]

    assert accepted is True
    assert current["status"] == "REPORT_RECEIVED"
    assert current["result_received"] is True


def test_unresolved_write_cannot_be_reallocated(team):
    owner, name = team

    with lifecycle.locked_team_state(owner) as state:
        state["teammates"][name]["status"] = "IDLE_REUSABLE"

    before = lifecycle.load_team_state(owner)

    decision, _ = lifecycle.allocate_teammate(
        owner, name, name
    )

    after = lifecycle.load_team_state(owner)

    assert decision == lifecycle.TeammateAllocationDecision.BUSY
    assert after == before


def test_stale_owner_cannot_fail_executing_write(team, monkeypatch):
    owner, name = team

    monkeypatch.setattr(
        lifecycle,
        "load_run_state",
        lambda session_id: None,
    )
    monkeypatch.setattr(
        lifecycle,
        "_record_is_expired",
        lambda record: True,
    )

    before = lifecycle.load_team_state(owner)

    accepted = lifecycle._reconcile_stale_owner(
        owner,
        name,
        expected_run_id="run-1",
        expected_task_id="task-1",
    )

    after = lifecycle.load_team_state(owner)

    assert accepted is False
    assert after == before
