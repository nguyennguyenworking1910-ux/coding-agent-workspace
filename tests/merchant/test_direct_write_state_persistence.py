from copy import deepcopy

import pytest

from claude.hooks import team_lifecycle
from claude.hooks.merchant_direct_write_state import (
    DirectWriteReservationError,
    reserve_merchant_create,
)


CONTEXT = {
    "owner_session_id": "pytest-persist-owner",
    "teammate_name": "merchant-manager",
    "pane_session_id": "pytest-persist-pane",
    "run_id": "pytest-persist-run",
    "task_id": "pytest-persist-task",
    "write_id": "pytest-persist-write",
    "database": "test",
    "payload": {
        "code": "PERSIST_TEST",
        "name": "Persistence Test Merchant",
    },
}


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    # Use the real state-locking and persistence functions.
    # Redirect all state operations to a temporary directory.
    monkeypatch.setattr(
        team_lifecycle,
        "team_state_dir",
        lambda: tmp_path,
    )

    with team_lifecycle.locked_team_state(
        CONTEXT["owner_session_id"]
    ) as state:
        assert state is not None

        state.setdefault("teammates", {})[
            "merchant-manager"
        ] = {
            "canonical_name": "merchant-manager",
            "status": "RUNNING",
            "current_run_id": CONTEXT["run_id"],
            "current_task_id": CONTEXT["task_id"],
            "trusted_pane_session_id": CONTEXT[
                "pane_session_id"
            ],
            "authorized_operations": ["merchant_execute"],
            "authorized_selected_agents": [
                "merchant-manager"
            ],
            "result_received": False,
            "report_source": None,
        }

    return tmp_path


def get_record():
    state = team_lifecycle.load_team_state(
        CONTEXT["owner_session_id"]
    )
    assert isinstance(state, dict)
    return state["teammates"]["merchant-manager"]


def test_reservation_survives_disk_reload(isolated_state):
    first = reserve_merchant_create(**CONTEXT)

    assert first["status"] == "RESERVED"

    # Load a new state object from the filesystem.
    record = get_record()

    stored = record["direct_writes"][
        CONTEXT["write_id"]
    ]

    assert stored == first

    second = reserve_merchant_create(**CONTEXT)

    assert second == first
    assert len(get_record()["direct_writes"]) == 1


def test_restarted_reader_cannot_change_payload(isolated_state):
    first = reserve_merchant_create(**CONTEXT)

    changed = deepcopy(CONTEXT)
    changed["payload"]["name"] = "Modified Name"

    with pytest.raises(DirectWriteReservationError):
        reserve_merchant_create(**changed)

    assert get_record()["direct_writes"][
        CONTEXT["write_id"]
    ] == first


def test_reassigned_task_cannot_reuse_reservation(
    isolated_state,
):
    first = reserve_merchant_create(**CONTEXT)

    with team_lifecycle.locked_team_state(
        CONTEXT["owner_session_id"]
    ) as state:
        record = state["teammates"]["merchant-manager"]
        record["current_task_id"] = "reassigned-task"

    with pytest.raises(DirectWriteReservationError):
        reserve_merchant_create(**CONTEXT)

    # Rejected request must not rewrite the original record.
    assert get_record()["direct_writes"][
        CONTEXT["write_id"]
    ] == first


def test_wrong_pane_cannot_reuse_reservation(
    isolated_state,
):
    first = reserve_merchant_create(**CONTEXT)

    with team_lifecycle.locked_team_state(
        CONTEXT["owner_session_id"]
    ) as state:
        state["teammates"]["merchant-manager"][
            "trusted_pane_session_id"
        ] = "replacement-pane"

    with pytest.raises(DirectWriteReservationError):
        reserve_merchant_create(**CONTEXT)

    assert get_record()["direct_writes"][
        CONTEXT["write_id"]
    ] == first


def test_reservation_does_not_complete_lifecycle(
    isolated_state,
):
    reserve_merchant_create(**CONTEXT)

    record = get_record()

    assert record["status"] == "RUNNING"
    assert record["result_received"] is False
    assert record["report_source"] is None
    assert record["direct_writes"][
        CONTEXT["write_id"]
    ]["status"] == "RESERVED"
