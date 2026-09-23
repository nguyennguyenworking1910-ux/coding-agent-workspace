from __future__ import annotations

import json

from claude.agents.tools.merchant.cli import (
    main,
)


def _forbidden_factory(_database):
    raise AssertionError(
        "completeness command must not "
        "initialize Merchant repository"
    )


def test_completeness_cli_reports_missing_fields_without_database(
    capsys,
):
    exit_code = main(
        [
            "completeness",
            "check",
            "--command",
            "document revision-create",
            "--payload-json",
            "{}",
        ],
        command_factory=(
            _forbidden_factory
        ),
    )

    assert exit_code == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert output == {
        "success": True,
        "mode": "COMPLETENESS",
        "command": (
            "document revision-create"
        ),
        "complete": False,
        "missing_fields": [
            "project_id",
            "document_type",
            "content_hash",
        ],
        "missing_one_of": [],
        "clarification": {
            "outcome": (
                "REQUIRES_CLARIFICATION"
            ),
            "missing_fields": [
                "project_id",
                "document_type",
                "content_hash",
            ],
            "missing_one_of": [],
            "question": (
                "Please provide project_id, "
                "document_type, and content_hash."
            ),
        },
    }


def test_completeness_cli_supports_stateful_requirements(
    capsys,
):
    exit_code = main(
        [
            "completeness",
            "check",
            "--command",
            "procurement update",
            "--payload-json",
            json.dumps(
                {
                    "project_id": (
                        "project-123"
                    ),
                    "procurement_type": (
                        "PURCHASE_REQUEST"
                    ),
                }
            ),
            "--context-json",
            json.dumps(
                {
                    "current_record_exists": (
                        False
                    ),
                }
            ),
        ],
        command_factory=(
            _forbidden_factory
        ),
    )

    assert exit_code == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert (
        output["missing_fields"]
        == []
    )

    assert (
        output["missing_one_of"]
        == [
            [
                "status",
                "external_id",
            ]
        ]
    )

    assert output[
        "clarification"
    ][
        "outcome"
    ] == "REQUIRES_CLARIFICATION"


def test_completeness_cli_returns_no_clarification_when_complete(
    capsys,
):
    exit_code = main(
        [
            "completeness",
            "check",
            "--command",
            "merchant create",
            "--payload-json",
            json.dumps(
                {
                    "code": "CGV",
                    "name": "CGV",
                }
            ),
        ],
        command_factory=(
            _forbidden_factory
        ),
    )

    assert exit_code == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert output[
        "complete"
    ] is True

    assert output[
        "missing_fields"
    ] == []

    assert output[
        "missing_one_of"
    ] == []

    assert output[
        "clarification"
    ] is None