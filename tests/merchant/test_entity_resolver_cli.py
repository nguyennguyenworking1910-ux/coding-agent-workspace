"""Read-only CLI exposure tests for Merchant entity resolution."""

from __future__ import annotations

from claude.agents.tools.merchant.cli import (
    build_argument_parser,
    dispatch_read_command,
)
from claude.agents.tools.merchant.read_commands import (
    MerchantReadCommands,
)


CGV_ID = (
    "2da7ab08-1eda-5ca2-b28e-f94f3e1be0d0"
)

BETA_ID = (
    "a6949851-958d-51df-95b8-07cdf8065291"
)

BETA_PHU_MY_ID = (
    "5b4c9bc1-bad3-5b03-9bdc-604f5adb3f26"
)


class FakeRepository:
    def list_merchants(
        self,
        *,
        status=None,
    ):
        assert status is None

        return [
            {
                "id": CGV_ID,
                "code": "CGV",
                "name": "CGV",
            },
            {
                "id": BETA_ID,
                "code": "BETA_CINEMA",
                "name": "BETA CINEMA",
            },
            {
                "id": BETA_PHU_MY_ID,
                "code": "BETA_PHU_MY",
                "name": "BETA PHÚ MỸ",
            },
        ]


def test_parser_accepts_merchant_resolve():
    parser = build_argument_parser()

    args = parser.parse_args(
        (
            "--database",
            "runtime",
            "merchant",
            "resolve",
            "--query",
            "CGV",
        )
    )

    assert args.resource == "merchant"
    assert args.action == "resolve"
    assert args.query == "CGV"


def test_read_commands_resolve_exact_code():
    commands = MerchantReadCommands(
        FakeRepository()
    )

    result = commands.merchant_resolve(
        "CGV"
    )

    assert result == {
        "success": True,
        "mode": "RESOLUTION",
        "query": "CGV",
        "status": "RESOLVED",
        "match_kind": "CODE",
        "resolved": True,
        "merchant_id": CGV_ID,
        "code": "CGV",
        "name": "CGV",
        "candidates": [
            {
                "merchant_id": CGV_ID,
                "code": "CGV",
                "name": "CGV",
            }
        ],
    }


def test_read_commands_resolve_uuid():
    commands = MerchantReadCommands(
        FakeRepository()
    )

    result = commands.merchant_resolve(
        CGV_ID
    )

    assert result["status"] == "RESOLVED"
    assert result["match_kind"] == "UUID"
    assert result["merchant_id"] == CGV_ID


def test_read_commands_ambiguous_candidate_fails_closed():
    commands = MerchantReadCommands(
        FakeRepository()
    )

    result = commands.merchant_resolve(
        "BETA"
    )

    assert result["success"] is True
    assert result["mode"] == "RESOLUTION"
    assert result["status"] == "AMBIGUOUS"
    assert result["resolved"] is False
    assert result["merchant_id"] is None

    assert [
        candidate["code"]
        for candidate in result[
            "candidates"
        ]
    ] == [
        "BETA_CINEMA",
        "BETA_PHU_MY",
    ]


def test_read_commands_unknown_is_not_found():
    commands = MerchantReadCommands(
        FakeRepository()
    )

    result = commands.merchant_resolve(
        "UNKNOWN"
    )

    assert result["status"] == "NOT_FOUND"
    assert result["resolved"] is False
    assert result["merchant_id"] is None
    assert result["candidates"] == []


def test_dispatch_read_command_routes_resolver():
    parser = build_argument_parser()

    args = parser.parse_args(
        (
            "--database",
            "runtime",
            "merchant",
            "resolve",
            "--query",
            "CGV",
        )
    )

    commands = MerchantReadCommands(
        FakeRepository()
    )

    result = dispatch_read_command(
        args,
        commands,
    )

    assert result["status"] == "RESOLVED"
    assert result["merchant_id"] == CGV_ID