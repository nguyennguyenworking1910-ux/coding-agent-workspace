from __future__ import annotations

import subprocess
import sys

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from claude.agents.tools.merchant.cli import (
    dispatch_read_command,
)
from claude.agents.tools.merchant.cli_contract import (
    READ_COMMANDS,
)
from claude.agents.tools.merchant.read_commands import (
    MerchantReadCommands,
)


PROJECT_A = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
)

PROJECT_B = (
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
)

STEP_UAT = (
    "11111111-1111-4111-8111-111111111111"
)

STEP_PROD = (
    "22222222-2222-4222-8222-222222222222"
)

STEP_OTHER = (
    "33333333-3333-4333-8333-333333333333"
)

TEMPLATE_UAT = (
    "44444444-4444-4444-8444-444444444444"
)

TEMPLATE_PROD = (
    "55555555-5555-4555-8555-555555555555"
)

TEMPLATE_OTHER = (
    "66666666-6666-4666-8666-666666666666"
)


def step(
    step_id: str,
    *,
    project_id: str,
    template_step_id: str,
    branch_key: str | None,
    step_name: str,
    step_type: str = "PARALLEL_BRANCH",
    status: str = "READY",
    sequence_number: int = 1,
    version: int = 1,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "project_id": project_id,
        "template_step_id": (
            template_step_id
        ),
        "branch_key": branch_key,
        "step_name": step_name,
        "step_type": step_type,
        "status": status,
        "sequence_number": (
            sequence_number
        ),
        "version": version,
        "condition_key": None,
        "is_optional": False,
    }


PROJECT_A_STEPS = [
    step(
        STEP_UAT,
        project_id=PROJECT_A,
        template_step_id=TEMPLATE_UAT,
        branch_key="uat_branch",
        step_name="Run UAT test",
        sequence_number=20,
    ),
    step(
        STEP_PROD,
        project_id=PROJECT_A,
        template_step_id=TEMPLATE_PROD,
        branch_key="production_branch",
        step_name="Run Production test",
        sequence_number=16,
    ),
]

PROJECT_B_STEPS = [
    step(
        STEP_OTHER,
        project_id=PROJECT_B,
        template_step_id=TEMPLATE_OTHER,
        branch_key="uat_branch",
        step_name="Run UAT test",
        sequence_number=20,
    ),
]


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_project_detail(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            project_id
        )

        if project_id == PROJECT_A:
            return {
                "project": {
                    "id": PROJECT_A,
                },
                "steps": list(
                    PROJECT_A_STEPS
                ),
            }

        if project_id == PROJECT_B:
            return {
                "project": {
                    "id": PROJECT_B,
                },
                "steps": list(
                    PROJECT_B_STEPS
                ),
            }

        return {
            "project": {
                "id": project_id,
            },
            "steps": [],
        }


def commands():
    repository = FakeRepository()

    instance = (
        MerchantReadCommands.__new__(
            MerchantReadCommands
        )
    )

    instance.repository = repository

    return (
        instance,
        repository,
    )


def test_step_resolve_is_allowlisted_read_command():
    assert "step resolve" in READ_COMMANDS


def test_step_resolve_exact_name_returns_resolved():
    instance, repository = commands()

    result = instance.step_resolve(
        project_id=PROJECT_A,
        query="Run UAT test",
    )

    assert result["success"] is True
    assert result["mode"] == "STEP_RESOLUTION"
    assert result["status"] == "RESOLVED"
    assert result["resolved"] is True

    assert (
        result["step_id"]
        == STEP_UAT
    )

    assert (
        result["project_id"]
        == PROJECT_A
    )

    assert (
        result["branch_key"]
        == "uat_branch"
    )

    assert (
        result["step_name"]
        == "Run UAT test"
    )

    assert repository.calls == [
        PROJECT_A
    ]


def test_step_resolve_exact_uuid_returns_resolved():
    instance, _ = commands()

    result = instance.step_resolve(
        project_id=PROJECT_A,
        query=STEP_PROD,
    )

    assert (
        result["status"]
        == "RESOLVED"
    )

    assert (
        result["match_kind"]
        == "UUID"
    )

    assert (
        result["step_id"]
        == STEP_PROD
    )


def test_step_resolve_is_project_scoped():
    instance, repository = commands()

    result = instance.step_resolve(
        project_id=PROJECT_B,
        query="Run UAT test",
    )

    assert (
        result["status"]
        == "RESOLVED"
    )

    assert (
        result["step_id"]
        == STEP_OTHER
    )

    assert (
        result["project_id"]
        == PROJECT_B
    )

    assert repository.calls == [
        PROJECT_B
    ]


def test_step_resolve_unknown_returns_not_found():
    instance, _ = commands()

    result = instance.step_resolve(
        project_id=PROJECT_A,
        query="Unknown Step",
    )

    assert (
        result["status"]
        == "NOT_FOUND"
    )

    assert result["resolved"] is False
    assert result["step_id"] is None
    assert result["candidates"] == []


def test_step_resolve_preserves_branch_metadata():
    instance, _ = commands()

    result = instance.step_resolve(
        project_id=PROJECT_A,
        query="Run Production test",
    )

    assert (
        result["step_id"]
        == STEP_PROD
    )

    assert (
        result["branch_key"]
        == "production_branch"
    )

    assert (
        result["step_type"]
        == "PARALLEL_BRANCH"
    )

    assert (
        result["sequence_number"]
        == 16
    )

    assert result["version"] == 1


def test_step_resolve_ambiguous_name_returns_ambiguous():
    repository = FakeRepository()

    duplicate = step(
        "77777777-7777-4777-8777-777777777777",
        project_id=PROJECT_A,
        template_step_id=(
            "88888888-8888-4888-8888-888888888888"
        ),
        branch_key="uat_branch",
        step_name="Review",
        sequence_number=2,
    )

    original = step(
        "99999999-9999-4999-8999-999999999999",
        project_id=PROJECT_A,
        template_step_id=(
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        ),
        branch_key="production_branch",
        step_name="Review",
        sequence_number=3,
    )

    repository.get_project_detail = (
        lambda project_id: {
            "project": {
                "id": project_id
            },
            "steps": [
                duplicate,
                original,
            ],
        }
    )

    instance = (
        MerchantReadCommands.__new__(
            MerchantReadCommands
        )
    )

    instance.repository = repository

    result = instance.step_resolve(
        project_id=PROJECT_A,
        query="Review",
    )

    assert (
        result["status"]
        == "AMBIGUOUS"
    )

    assert result["resolved"] is False
    assert result["step_id"] is None

    assert len(
        result["candidates"]
    ) == 2


def test_dispatch_routes_step_resolve():
    class StubCommands:
        def __init__(self) -> None:
            self.received = None

        def step_resolve(
            self,
            *,
            project_id: str,
            query: str,
        ) -> dict[str, Any]:
            self.received = (
                project_id,
                query,
            )

            return {
                "success": True,
                "mode": "STEP_RESOLUTION",
                "status": "NOT_FOUND",
                "resolved": False,
                "project_id": (
                    project_id
                ),
                "query": query,
                "step_id": None,
                "candidates": [],
            }

    stub = StubCommands()

    args = SimpleNamespace(
        resource="step",
        action="resolve",
        project_id=PROJECT_A,
        query="Anything",
    )

    result = dispatch_read_command(
        args,
        stub,  # type: ignore[arg-type]
    )

    assert stub.received == (
        PROJECT_A,
        "Anything",
    )

    assert (
        result["mode"]
        == "STEP_RESOLUTION"
    )


def _agent_cli_path() -> Path:
    return (
        Path(__file__)
        .resolve()
        .parents[2]
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
            "step",
            "resolve",
            "--query",
            "Run UAT test",
        ],
        [
            "step",
            "resolve",
            "--project-id",
            PROJECT_A,
        ],
    ],
)
def test_step_resolve_missing_required_argument_is_rejected(
    arguments: list[str],
):
    completed = subprocess.run(
        [
            sys.executable,
            str(
                _agent_cli_path()
            ),
            *arguments,
        ],
        cwd=(
            Path(__file__)
            .resolve()
            .parents[2]
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode != 0

    combined = (
        completed.stdout
        + completed.stderr
    )

    assert (
        "Merchant agent arguments do not match the allowlisted CLI contract"
        in combined
        or "required"
        in combined.lower()
    )