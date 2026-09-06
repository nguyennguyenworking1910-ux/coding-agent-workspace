"""Tests for the credential-safe Merchant Manager CLI adapter."""

from __future__ import annotations

import json

import pytest

from claude.agents.tools.merchant.agent_cli import (
    CREDENTIAL_OR_TARGET_OPTIONS,
    MerchantAgentCliError,
    invoke_agent_cli,
    main,
    prepare_agent_cli_argv,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"


class RecordingReads:
    def __init__(self):
        self.calls = []

    def merchant_list(self, *, status=None):
        self.calls.append(("merchant_list", status))
        return [{"code": "SAFE", "name": "Safe Merchant"}]

    def project_list(self, *, merchant_id=None, status=None):
        self.calls.append(
            ("project_list", merchant_id, status)
        )
        return []

    def project_show(self, project_id):
        self.calls.append(("project_show", project_id))
        return {"project": {"id": project_id}}

    def project_history(self, project_id, *, limit):
        self.calls.append(("project_history", project_id, limit))
        return []

    def project_blockers(self, project_id):
        self.calls.append(("project_blockers", project_id))
        return []

    def project_alerts(self, project_id):
        self.calls.append(("project_alerts", project_id))
        return []


class RecordingWrites:
    def __init__(self):
        self.calls = []

    def propose(self, command, database, payload):
        self.calls.append(
            ("propose", command, database, payload)
        )
        return {
            "success": True,
            "mode": "PROPOSE",
            "command": command,
            "database": database,
            "proposal_hash": "a" * 64,
            "requires_confirmation": True,
        }

    def apply(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("Agent adapter must never dispatch apply")


@pytest.mark.parametrize(
    "arguments",
    (
        ["merchant", "list"],
        ["project", "list"],
        ["project", "show", PROJECT_ID],
        ["project", "history", PROJECT_ID],
        ["project", "blockers", PROJECT_ID],
        ["project", "alerts", PROJECT_ID],
    ),
)
def test_all_reads_receive_the_fixed_runtime_target(arguments):
    prepared = prepare_agent_cli_argv(arguments)

    assert prepared[:2] == ("--database", "runtime")
    assert prepared[2:] == tuple(arguments)


def test_agent_read_invocation_uses_runtime_repository(capsys):
    reads = RecordingReads()
    selected_targets = []

    def factory(database):
        selected_targets.append(database)
        return reads

    exit_code = invoke_agent_cli(
        ["merchant", "list", "--status", "active"],
        command_factory=factory,
    )

    assert exit_code == 0
    assert selected_targets == ["runtime"]
    assert reads.calls == [("merchant_list", "ACTIVE")]
    result = json.loads(capsys.readouterr().out)
    assert result == [{"code": "SAFE", "name": "Safe Merchant"}]


def test_agent_write_invocation_dispatches_only_propose(capsys):
    writes = RecordingWrites()
    selected_targets = []

    def factory(database):
        selected_targets.append(database)
        return writes

    exit_code = invoke_agent_cli(
        [
            "merchant",
            "create",
            "--propose",
            "--code",
            "SAFE",
            "--name",
            "Fictitious Merchant",
        ],
        write_command_factory=factory,
    )

    assert exit_code == 0
    assert selected_targets == ["runtime"]
    assert len(writes.calls) == 1
    assert writes.calls[0][:3] == (
        "propose",
        "merchant create",
        "runtime",
    )
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "PROPOSE"
    assert result["requires_confirmation"] is True


@pytest.mark.parametrize(
    "arguments",
    (
        ["--database", "test", "merchant", "list"],
        ["--database=runtime", "merchant", "list"],
        ["--db", "coding_agent_merchant", "merchant", "list"],
    ),
)
def test_agent_cannot_select_or_override_a_database(arguments):
    with pytest.raises(
        MerchantAgentCliError,
        match="Database target and credential arguments",
    ):
        prepare_agent_cli_argv(arguments)


@pytest.mark.parametrize(
    "option",
    sorted(CREDENTIAL_OR_TARGET_OPTIONS - {"--database", "--db"}),
)
def test_agent_rejects_every_credential_or_connection_option(option):
    with pytest.raises(
        MerchantAgentCliError,
        match="Database target and credential arguments",
    ):
        prepare_agent_cli_argv(
            ["merchant", "list", option, "private-value"]
        )


def test_agent_rejects_equals_form_credential_options():
    with pytest.raises(MerchantAgentCliError):
        prepare_agent_cli_argv(
            ["merchant", "list", "--password=private-value"]
        )


def test_agent_rejects_runtime_apply_before_dispatch():
    factory_called = False

    def factory(database):
        nonlocal factory_called
        factory_called = True
        return RecordingWrites()

    with pytest.raises(
        MerchantAgentCliError,
        match="may not apply",
    ):
        invoke_agent_cli(
            [
                "merchant",
                "create",
                "--apply",
                "--proposal-hash",
                "a" * 64,
                "--code",
                "SAFE",
                "--name",
                "Fictitious Merchant",
            ],
            write_command_factory=factory,
        )

    assert factory_called is False


@pytest.mark.parametrize(
    "arguments",
    (
        [],
        ["merchant"],
        ["merchant", "delete"],
        ["project", "show"],
        ["--help"],
    ),
)
def test_invalid_or_incomplete_arguments_fail_closed(arguments):
    with pytest.raises(
        MerchantAgentCliError,
        match=(
            "command is required"
            if not arguments
            else "do not match"
        ),
    ):
        prepare_agent_cli_argv(arguments)


def test_string_is_not_accepted_as_an_argument_sequence():
    with pytest.raises(
        MerchantAgentCliError,
        match="sequence of tokens",
    ):
        prepare_agent_cli_argv("merchant list")


def test_non_string_or_empty_tokens_are_rejected():
    with pytest.raises(
        MerchantAgentCliError,
        match="must be strings",
    ):
        prepare_agent_cli_argv(["merchant", 1])

    with pytest.raises(
        MerchantAgentCliError,
        match="non-empty text",
    ):
        prepare_agent_cli_argv(["merchant", ""])


def test_command_line_error_is_json_and_does_not_echo_secret(capsys):
    exit_code = main(
        ["merchant", "list", "--password", "do-not-print-this"]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.err)
    assert exit_code == 2
    assert captured.out == ""
    assert result["success"] is False
    assert result["error"]["type"] == "MerchantAgentCliError"
    assert "do-not-print-this" not in captured.err


def test_adapter_has_no_runtime_authorization_parameter():
    import inspect

    signature = inspect.signature(invoke_agent_cli)

    assert "runtime_authorized" not in signature.parameters
