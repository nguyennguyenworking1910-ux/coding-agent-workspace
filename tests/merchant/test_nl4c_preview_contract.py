"""CP12H.NL4C: ``confirmation_available`` tells the truth, and grants nothing.

A READY Step preview on the test database leaves a trusted pending record the
user may confirm with ``/solve Xác nhận cập nhật``; its report says so with
``confirmation_available: true``. Every other preview (runtime target,
BLOCKED, NEEDS_CLARIFICATION) says false. The flag is reporting only:
``executable`` stays false, ``authorization`` null and the operation
NOT_AUTHORIZED, and a capture whose flag disagrees with its outcome and
target is unverified and records no pending confirmation.
"""

from __future__ import annotations

import copy
import json

import pytest

from claude.agents.tools.merchant.step_preview import BLOCKED, CLARIFY, CONFIRMABLE_TARGETS, READY
from claude.hooks import merchant_direct_handoff as handoff
from claude.hooks import merchant_pending_confirmation as pending
from tests.merchant.test_nl4b_step_preview import (  # noqa: F401 (fixtures)
    LEAD,
    NVC,
    STEP_TEST,
    capture,
    isolated,
    preview,
    step_run,
)

START_2 = f"Bắt đầu bước 2 của {NVC}"


def test_confirmable_targets_mirror_the_execution_switch():
    assert CONFIRMABLE_TARGETS == {
        target for target in ("test", "runtime")
        if handoff.direct_execute_enabled("step update", target)
    } == {"test"}
    assert handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False


def test_ready_test_preview_is_confirmable_but_not_authorized():
    result = preview(START_2, target="test")

    assert result["outcome"] == READY and result["confirmation_available"] is True
    assert result["executable"] is False and result["authorization"] is None
    assert result["requested_operation"]["status"] == "NOT_AUTHORIZED"
    assert "confirmation_command" not in json.dumps(result, default=str)


@pytest.mark.parametrize(
    "text,target,outcome",
    [
        (START_2, "runtime", READY),                                         # runtime disabled
        (f"Đánh dấu bước Legal Review của {NVC} là hoàn thành", "test", BLOCKED),
        (f"Cập nhật bước 2 của {NVC}", "test", CLARIFY),                     # no status
    ],
)
def test_every_other_preview_is_not_confirmable(text, target, outcome):
    result = preview(text, target=target)

    assert result["outcome"] == outcome and result["confirmation_available"] is False
    assert result["executable"] is False and result["authorization"] is None


def test_the_honest_ready_capture_records_one_pending_step(step_run):
    result, stdout = step_run()
    assert result["confirmation_available"] is True

    assert capture(STEP_TEST, stdout)
    assert len(pending.load_records(LEAD, pending.STEP_KIND)) == 1


@pytest.mark.parametrize(
    "forge",
    [
        lambda r: r.update(confirmation_available=False),        # hides a confirmable READY
        lambda r: r.update(confirmation_available="true"),       # not a boolean
        lambda r: r.update(confirmation_available=None),
        lambda r: r.pop("confirmation_available"),
        lambda r: r.update(executable=True),                      # never executable
        lambda r: r.update(authorization={"granted": True}),      # never authorized
    ],
)
def test_a_capture_with_a_wrong_flag_is_unverified_and_records_nothing(step_run, forge):
    result, _ = step_run()
    forged = copy.deepcopy(result)
    forge(forged)

    assert not capture(STEP_TEST, json.dumps(forged, ensure_ascii=False))
    assert pending.load_records(LEAD, pending.STEP_KIND) == []


def test_a_blocked_capture_claiming_confirmation_records_nothing(step_run):
    from tests.merchant.test_nl2e_p1_p2_p4 import CLI

    text = f"Đánh dấu bước Legal Review của {NVC} là hoàn thành"
    result, _ = step_run(text)
    assert result["outcome"] == BLOCKED
    forged = dict(result, confirmation_available=True)

    assert not capture(f'{CLI} step preview --request "{text}" --test-database',
                       json.dumps(forged, ensure_ascii=False))
    assert pending.load_records(LEAD, pending.STEP_KIND) == []
