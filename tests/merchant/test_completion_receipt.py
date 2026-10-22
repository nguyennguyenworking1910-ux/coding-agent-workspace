from copy import deepcopy

import pytest

from claude.hooks.merchant_completion_receipt import (
    build_completion_receipt,
    receipt_matches_state,
)


def record():
    return {
        "current_run_id": "run-1",
        "current_task_id": "task-1",
        "direct_writes": {
            "write-1": {
                "write_id": "write-1",
                "run_id": "run-1",
                "task_id": "task-1",
                "database": "test",
                "command": "merchant create",
                "operation_key": "merchant-direct:v1:" + "a" * 64,
                "payload_hash": "b" * 64,
                "execution_attempt_id":
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "claim_generation": 1,
                "merchant_id":
                    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "status": "VERIFIED",
            }
        },
    }


def test_exact_receipt_matches():
    state = record()
    receipt = build_completion_receipt(state)
    assert receipt is not None
    assert receipt_matches_state(state, receipt)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("claim_generation", 2),
        ("execution_attempt_id", "different"),
        ("payload_hash", "c" * 64),
        ("operation_key", "different"),
        ("merchant_id", "different"),
        ("database", "runtime"),
    ],
)
def test_changed_identity_is_rejected(field, replacement):
    state = record()
    receipt = build_completion_receipt(state)

    state["direct_writes"]["write-1"][field] = replacement

    assert not receipt_matches_state(state, receipt)


def test_added_write_is_rejected():
    state = record()
    receipt = build_completion_receipt(state)

    second = deepcopy(state["direct_writes"]["write-1"])
    second["write_id"] = "write-2"
    state["direct_writes"]["write-2"] = second

    assert not receipt_matches_state(state, receipt)


def test_deleted_write_is_rejected():
    state = record()
    receipt = build_completion_receipt(state)
    state["direct_writes"].clear()

    assert not receipt_matches_state(state, receipt)


@pytest.mark.parametrize(
    "generation",
    [None, 0, -1, True, "1", 1.0],
)
def test_invalid_generation_cannot_build_receipt(generation):
    state = record()
    state["direct_writes"]["write-1"]["claim_generation"] = generation

    assert build_completion_receipt(state) is None
