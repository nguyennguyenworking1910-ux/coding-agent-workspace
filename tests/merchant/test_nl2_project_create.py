"""CP12H.NL2: trusted confirmation of a previewed Project creation (no DB)."""

from __future__ import annotations

import types
import uuid

import pytest

from claude.agents.tools.merchant import project_preview
from claude.agents.tools.merchant.agent_cli import (
    MerchantAgentCliError,
    prepare_agent_cli_argv,
)
from claude.agents.tools.merchant.cli import (
    build_argument_parser,
    build_write_payload,
)
from claude.agents.tools.merchant.project_preview import (
    READY,
    ProjectPreviewMismatch,
    build_project_preview,
    verify_project_create,
)
from claude.hooks import merchant_direct_handoff
from claude.system import merchant_runtime_handoff
from tests.merchant.test_nl1_project_preview import (
    BETA,
    LOTTE,
    Reader,
    merchant,
    project,
)


REQUEST = (
    "Create a cinema opening project for Beta Nguyễn Văn Cừ under Beta "
    "Cinemas. No procurement."
)


def confirmed(reader=None):
    """The preview, and the payload the user's exact scope would carry."""

    preview = build_project_preview(REQUEST, reader or Reader())
    assert preview["outcome"] == READY, preview["clarifications"]
    argv = preview["requested_operation"]["argv"]
    args = build_argument_parser().parse_args(["--database", "test", *argv])
    return preview, build_write_payload(args, "project create")


def reason(reader, payload):
    with pytest.raises(ProjectPreviewMismatch) as error:
        verify_project_create(reader, payload)
    return error.value.reason


def test_under_merchant_wording_resolves_the_existing_merchant():
    preview, payload = confirmed()

    assert preview["merchant"]["merchant_id"] == BETA
    assert preview["fields"]["title"] == "Beta Nguyễn Văn Cừ"
    assert payload["project_id"] == preview["requested_operation"]["argv"][11]
    assert payload["expected_basis_hash"] == preview["basis_hash"]
    assert verify_project_create(Reader(), payload)["basis_hash"] == (
        preview["basis_hash"]
    )


def test_project_id_and_basis_are_deterministic_for_the_same_state():
    first, _ = confirmed()
    second, _ = confirmed()

    assert first["requested_operation"] == second["requested_operation"]


def test_stale_merchant_state_is_refused():
    _, payload = confirmed()
    changed = Reader(merchants=[merchant(BETA, "BETA", "Beta Cinemas", version=2)])

    assert reason(changed, payload) == "PREVIEW_BASIS_CHANGED"


def test_template_definition_change_is_refused(monkeypatch):
    _, payload = confirmed()
    monkeypatch.setattr(
        project_preview, "template_fingerprint", lambda template: "changed"
    )

    assert reason(Reader(), payload) == "PREVIEW_BASIS_CHANGED"


def test_uninstalled_template_is_refused():
    _, payload = confirmed()

    assert reason(Reader(installed=False), payload) == "PROJECT_NOT_READY"


def test_cross_merchant_scope_is_refused():
    _, payload = confirmed()
    payload["merchant_id"] = LOTTE

    # CP12H.NL2E P2: the confirmed code (BETA) no longer names the Merchant.
    assert reason(Reader(), payload) == "PROJECT_NOT_READY"


def test_edited_operation_field_is_refused():
    _, payload = confirmed()
    payload["title"] = "Beta Somewhere Else"

    assert reason(Reader(), payload) == "PREVIEW_BASIS_CHANGED"


def test_duplicate_created_after_preview_is_refused():
    _, payload = confirmed()
    later = Reader(projects=[project("Beta Nguyễn Văn Cừ", status="PLANNED")])

    assert reason(later, payload) == "PROJECT_NOT_READY"


def test_unrelated_new_project_still_invalidates_the_basis():
    _, payload = confirmed()
    later = Reader(projects=[project("Lotte renovation")])

    assert reason(later, payload) == "PREVIEW_BASIS_CHANGED"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("expected_basis_hash", None, "PREVIEW_BASIS_REQUIRED"),
        ("project_id", None, "PREVIEW_BASIS_REQUIRED"),
        ("project_id", str(uuid.uuid4()), "PROJECT_ID_MISMATCH"),
    ),
)
def test_missing_or_foreign_confirmation_data_is_refused(field, value, expected):
    _, payload = confirmed()
    payload[field] = value

    assert reason(Reader(), payload) == expected


def test_preview_marker_is_not_a_payload():
    preview, _ = confirmed()

    # The preview object itself carries no confirmed payload fields.
    assert reason(Reader(), preview) == "PREVIEW_BASIS_REQUIRED"


# ------------------------------------------------- execution gate changes


def attempt(target, command):
    return types.SimpleNamespace(
        database_target=target,
        command=command,
        owner_session_id="lead",
        teammate_name="merchant-manager",
        arguments=(),
    )


def test_test_mode_admits_project_create_and_runtime_stays_disabled():
    assert merchant_direct_handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False
    # CP12H.NL4C2A: a confirmed Step Update joined test mode.
    assert merchant_direct_handoff.TEST_MODE_COMMANDS == {
        "merchant create",
        "project create",
        "step update",
        # CP12H.NL4D4A: the confirmed Purchase Request.
        "procurement update",
        # CP12H.MASTER: confirmed lifecycle operations (test database only).
        "document revision-create",
        "document approve",
        "document sign",
        "project update",
    }

    with pytest.raises(merchant_direct_handoff.DirectPreflightRefused) as error:
        merchant_direct_handoff.preflight_direct_execute(
            attempt("runtime", "project create")
        )
    assert error.value.reason == "RUNTIME_EXECUTION_DISABLED"

    with pytest.raises(merchant_direct_handoff.DirectPreflightRefused) as error:
        merchant_direct_handoff.preflight_direct_execute(
            attempt("test", "project update")
        )
    # CP12H.MASTER: `project update` joined test mode only as the user's
    # confirmed Project completion; anything else is refused before any spend.
    assert error.value.reason == "LIFECYCLE_CONFIRMATION_REQUIRED"


def test_test_scope_runs_without_a_runtime_capability(monkeypatch):
    calls = {}
    scope = {
        "argv": ["project", "create", "--merchant-id", BETA],
        "database_target": "test",
        "confirmation": {},
    }
    monkeypatch.setattr(
        merchant_runtime_handoff,
        "reserve_direct_scope_authorization",
        lambda *a, **k: (scope, {}),
    )
    monkeypatch.setattr(
        merchant_runtime_handoff,
        "_verify_team_reservation",
        lambda *a, **k: calls.setdefault("guard", True),
    )
    monkeypatch.setattr(
        merchant_runtime_handoff, "spent_authority_matches", lambda *a, **k: True
    )

    def no_capability(*args, **kwargs):
        raise AssertionError("a test scope must not issue runtime authority")

    monkeypatch.setattr(
        merchant_runtime_handoff, "issue_runtime_apply_authorization", no_capability
    )

    def cli(argv, **kwargs):
        calls["argv"] = list(argv)
        calls["authorization"] = kwargs.get("runtime_authorization")
        return 0

    monkeypatch.setattr(merchant_runtime_handoff, "merchant_cli_main", cli)

    assert merchant_runtime_handoff.invoke_authorized_scope_apply(
        "lead",
        scope["argv"],
        teammate_name="merchant-manager",
        task_id="t1",
        execution_attempt_id="a1",
    ) == 0
    assert calls["guard"] is True
    assert calls["argv"][:2] == ["--database", "test"]
    assert calls["argv"][-1] == "--execute"
    assert calls["authorization"] is None


def test_runtime_scope_still_requires_the_runtime_capability(monkeypatch):
    scope = {"argv": ["project", "create"], "database_target": "runtime",
             "confirmation": {}}
    monkeypatch.setattr(
        merchant_runtime_handoff,
        "reserve_direct_scope_authorization",
        lambda *a, **k: (scope, {}),
    )

    def capability(*args, **kwargs):
        raise RuntimeError("issued")

    monkeypatch.setattr(
        merchant_runtime_handoff, "issue_runtime_apply_authorization", capability
    )

    with pytest.raises(merchant_runtime_handoff.MerchantRuntimeHandoffStageError) as error:
        merchant_runtime_handoff.invoke_authorized_scope_apply(
            "lead", scope["argv"], teammate_name="m", task_id="t",
            execution_attempt_id="a",
        )
    assert error.value.stage == "ISSUE_AUTHORIZATION"


def test_test_and_runtime_confirmations_differ_for_the_same_argv():
    _, payload = confirmed()
    argv = build_project_preview(REQUEST, Reader())["requested_operation"]["argv"]

    test_scope = merchant_runtime_handoff.validate_direct_scope(argv, "test")
    runtime_scope = merchant_runtime_handoff.validate_direct_scope(argv, "runtime")

    assert test_scope["scope_hash"] != runtime_scope["scope_hash"]
    assert test_scope["confirmation_hash"] != runtime_scope["confirmation_hash"]


def test_agent_cli_reads_the_test_database_only_for_preview():
    prepared = prepare_agent_cli_argv(
        ["project", "preview", "--test-database", "--request", REQUEST]
    )
    assert prepared[:2] == ("--database", "test")
    assert "--test-database" not in prepared

    argv = build_project_preview(REQUEST, Reader())["requested_operation"]["argv"]
    for forbidden in (
        ["project", "list", "--test-database"],
        [*argv, "--test-database"],
        ["--database", "test", "project", "preview", "--request", REQUEST],
        argv,
    ):
        with pytest.raises(MerchantAgentCliError):
            prepare_agent_cli_argv(forbidden)
