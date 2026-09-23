from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from claude.agents.tools.merchant.cli import dispatch_read_command
from claude.agents.tools.merchant.cli_contract import READ_COMMANDS
from claude.agents.tools.merchant.read_commands import MerchantReadCommands


MERCHANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MERCHANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

PROJECT_2026 = "11111111-1111-4111-8111-111111111111"
PROJECT_2027 = "22222222-2222-4222-8222-222222222222"
OTHER_MERCHANT_PROJECT = "33333333-3333-4333-8333-333333333333"


PROJECTS = [
    {
        "id": PROJECT_2026,
        "merchant_id": MERCHANT_A,
        "title": "CGV Media Top Up 2026",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "status": "PLANNED",
        "version": 1,
    },
    {
        "id": PROJECT_2027,
        "merchant_id": MERCHANT_A,
        "title": "CGV Media Top Up 2027",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "status": "IN_PROGRESS",
        "version": 2,
    },
    {
        "id": OTHER_MERCHANT_PROJECT,
        "merchant_id": MERCHANT_B,
        "title": "CGV Media Top Up 2026",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "status": "PLANNED",
        "version": 1,
    },
]


class FakeRepository:
    def __init__(self, projects: list[dict[str, Any]]) -> None:
        self.projects = projects
        self.calls: list[dict[str, Any]] = []

    def list_projects(
        self,
        *,
        merchant_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "merchant_id": merchant_id,
                "status": status,
            }
        )

        result = list(self.projects)

        if merchant_id is not None:
            result = [
                project
                for project in result
                if project["merchant_id"] == merchant_id
            ]

        if status is not None:
            result = [
                project
                for project in result
                if project["status"] == status
            ]

        return result


def _commands(
    projects: list[dict[str, Any]] | None = None,
) -> tuple[MerchantReadCommands, FakeRepository]:
    repository = FakeRepository(
        list(PROJECTS if projects is None else projects)
    )

    commands = MerchantReadCommands.__new__(MerchantReadCommands)
    commands.repository = repository

    return commands, repository


def test_project_resolve_is_allowlisted_read_command():
    assert "project resolve" in READ_COMMANDS


def test_project_resolve_unique_title_returns_resolved():
    commands, repository = _commands()

    result = commands.project_resolve(
        merchant_id=MERCHANT_A,
        query="CGV Media Top Up 2026",
    )

    assert result["success"] is True
    assert result["mode"] == "PROJECT_RESOLUTION"
    assert result["status"] == "RESOLVED"
    assert result["resolved"] is True
    assert result["project_id"] == PROJECT_2026

    assert repository.calls == [
        {
            "merchant_id": MERCHANT_A,
            "status": None,
        }
    ]


def test_project_resolve_ambiguous_title_returns_ambiguous():
    commands, _ = _commands()

    result = commands.project_resolve(
        merchant_id=MERCHANT_A,
        query="Media Top Up",
    )

    assert result["success"] is True
    assert result["mode"] == "PROJECT_RESOLUTION"
    assert result["status"] == "AMBIGUOUS"
    assert result["resolved"] is False
    assert result["project_id"] is None

    assert {
        candidate["project_id"]
        for candidate in result["candidates"]
    } == {
        PROJECT_2026,
        PROJECT_2027,
    }


def test_project_resolve_unknown_title_returns_not_found():
    commands, _ = _commands()

    result = commands.project_resolve(
        merchant_id=MERCHANT_A,
        query="Unknown Project",
    )

    assert result["success"] is True
    assert result["mode"] == "PROJECT_RESOLUTION"
    assert result["status"] == "NOT_FOUND"
    assert result["resolved"] is False
    assert result["project_id"] is None
    assert result["candidates"] == []


def test_project_resolve_is_strictly_merchant_scoped():
    commands, repository = _commands()

    result = commands.project_resolve(
        merchant_id=MERCHANT_B,
        query="CGV Media Top Up 2026",
    )

    assert result["status"] == "RESOLVED"
    assert result["project_id"] == OTHER_MERCHANT_PROJECT
    assert result["merchant_id"] == MERCHANT_B

    assert repository.calls[-1] == {
        "merchant_id": MERCHANT_B,
        "status": None,
    }


def test_project_resolve_does_not_cross_merchant_scope_for_uuid():
    commands, _ = _commands()

    result = commands.project_resolve(
        merchant_id=MERCHANT_A,
        query=OTHER_MERCHANT_PROJECT,
    )

    assert result["status"] == "NOT_FOUND"
    assert result["resolved"] is False
    assert result["project_id"] is None


def test_project_resolve_preserves_project_metadata():
    commands, _ = _commands()

    result = commands.project_resolve(
        merchant_id=MERCHANT_A,
        query=PROJECT_2027,
    )

    assert result["status"] == "RESOLVED"
    assert result["project_id"] == PROJECT_2027
    assert result["title"] == "CGV Media Top Up 2027"
    assert result["project_type"] == "MEDIA_TOP_UP"
    assert result["workflow_variant"] == "STANDARD"
    assert result["project_status"] == "IN_PROGRESS"
    assert result["version"] == 2


def test_dispatch_read_command_routes_project_resolve():
    class StubCommands:
        def __init__(self) -> None:
            self.received: tuple[str, str] | None = None

        def project_resolve(
            self,
            *,
            merchant_id: str,
            query: str,
        ) -> dict[str, Any]:
            self.received = (merchant_id, query)
            return {
                "success": True,
                "mode": "PROJECT_RESOLUTION",
                "status": "NOT_FOUND",
                "resolved": False,
                "merchant_id": merchant_id,
                "query": query,
                "project_id": None,
                "candidates": [],
            }

    commands = StubCommands()

    args = SimpleNamespace(
        resource="project",
        action="resolve",
        merchant_id=MERCHANT_A,
        query="Anything",
    )

    result = dispatch_read_command(
        args,
        commands,  # type: ignore[arg-type]
    )

    assert commands.received == (
        MERCHANT_A,
        "Anything",
    )
    assert result["mode"] == "PROJECT_RESOLUTION"


def _agent_cli_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / ".claude"
        / "agents"
        / "tools"
        / "merchant"
        / "agent_cli.py"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "project",
            "resolve",
            "--query",
            "Anything",
        ],
        [
            "project",
            "resolve",
            "--merchant-id",
            MERCHANT_A,
        ],
    ],
)
def test_project_resolve_missing_required_argument_is_rejected(
    arguments: list[str],
):
    completed = subprocess.run(
        [
            sys.executable,
            str(_agent_cli_path()),
            *arguments,
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode != 0

    combined_output = (
        completed.stdout
        + completed.stderr
    )

    assert (
        "Merchant agent arguments do not match the allowlisted CLI contract"
        in combined_output
        or "required" in combined_output.lower()
    )