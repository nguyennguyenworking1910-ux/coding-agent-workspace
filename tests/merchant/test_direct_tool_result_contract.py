import copy
import json

import pytest

from claude.hooks.merchant_tool_result_contract import (
    merchant_execute_from_tool_response,
)


def valid_payload():
    return {
        "tool_name": "Bash",
        "tool_response": {
            "stdout": json.dumps({
                "success": True,
                "mode": "EXECUTE",
                "command": "merchant create",
                "database": "runtime",
                "result": {
                    "merchant_id": (
                        "00000000-0000-4000-8000-000000000001"
                    )
                },
            })
        },
    }


def test_accepts_exact_direct_execute_result():
    result = merchant_execute_from_tool_response(
        valid_payload()
    )

    assert result is not None
    assert result["success"] is True
    assert result["mode"] == "EXECUTE"
    assert result["command"] == "merchant create"


@pytest.mark.parametrize("change", [
    {"success": False},
    {"mode": "PROPOSE"},
    {"database": "test"},
    {"command": "merchant list"},
    {"command": "not a command"},
    {"result": None},
    {"result": []},
    {"proposal_hash": "a" * 64},
    {"confirmation_hash": "a" * 64},
    {"requires_confirmation": False},
])
def test_rejects_invalid_execute_result(change):
    payload = valid_payload()
    result = json.loads(payload["tool_response"]["stdout"])
    result.update(change)
    payload["tool_response"]["stdout"] = json.dumps(result)

    assert merchant_execute_from_tool_response(
        payload
    ) is None


def test_rejects_unexpected_tool():
    payload = valid_payload()
    payload["tool_name"] = "SendMessage"

    assert merchant_execute_from_tool_response(
        payload
    ) is None


def test_rejects_non_json_stdout():
    payload = valid_payload()
    payload["tool_response"]["stdout"] = (
        "log output before JSON"
    )

    assert merchant_execute_from_tool_response(
        payload
    ) is None


def test_rejects_multiple_json_objects():
    payload = valid_payload()
    payload["tool_response"]["stdout"] += (
        '\n{"success":true}'
    )

    assert merchant_execute_from_tool_response(
        payload
    ) is None


def test_does_not_mutate_tool_payload():
    payload = valid_payload()
    original = copy.deepcopy(payload)

    merchant_execute_from_tool_response(payload)

    assert payload == original
