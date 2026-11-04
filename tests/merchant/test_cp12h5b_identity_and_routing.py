"""CP12H.5B: live psmux identity (D2-D4), DB preflight (D1), test routing.

Pane identity is decided by the real harness record and TMUX_PANE checks;
only the operating-system evidence (process table and pane listing) is
replaced. In-memory handler or test database only.
"""

from __future__ import annotations

import json

import pytest

from claude.hooks import (
    harness_team_identity,
    intent_gate,
    merchant_direct_handoff,
    merchant_reserved_execution,
    policy_gate,
    runtime_state,
    team_lifecycle,
)
from claude.hooks.merchant_runtime_handoff_gate import HANDOFF_STATE_KEY
from claude.system.merchant_runtime_handoff import validate_direct_scope

from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    LEAD_PID,
    PANE,
    PANE_SERVER,
    PANE_TMUX,
    PROJECT_ID,
    TEAMMATE,
    UPDATE_ARGV,
    _parser,
    dispatch,
    execute_request,
    fake_runtime_handler,
    idle,
    isolated,
    record,
    report,
    run_state,
    send,
    submit,
    write_harness_team,
)

OTHER_SERVER = 8000

# The real OS-evidence check, captured before any fixture replaces it.
REAL_OS_PANE_SERVER = getattr(harness_team_identity, "_os_pane_server", None)

# The lead process runs in a pane of PANE_SERVER.
TABLE = {
    LEAD_PID: (100, "claude.exe"),
    100: (PANE_SERVER, "powershell.exe"),
    PANE_SERVER: (1, "tmux.exe"),
    OTHER_SERVER: (1, "tmux.exe"),
}

CREATE_ARGV = ["merchant", "create", "--code", "CP12H5B", "--name", "CP12H5B"]


@pytest.fixture
def os_server(monkeypatch):
    """The psmux server this hook process's pane belongs to (mutable)."""

    current = {"server": PANE_SERVER}
    # Replace only the process-tree evidence; _os_pane_server keeps its
    # real lead-ancestry check.
    monkeypatch.setattr(
        harness_team_identity,
        "_os_pane_server",
        REAL_OS_PANE_SERVER,
        raising=False,
    )
    monkeypatch.setattr(
        harness_team_identity,
        "own_pane_server",
        lambda tmux_pane, *_: (current["server"], TABLE),
        raising=False,
    )
    return current


def _spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


def _reuse_for_new_task(request):
    """The lead reassigns the idle teammate to a new run (real gate path)."""

    submit(request, argv=UPDATE_ARGV)
    dispatch()
    with runtime_state.locked_state(LEAD) as state:
        assert policy_gate.apply_call(
            state,
            "SendMessage",
            {"to": TEAMMATE, "message": "Perform the user's Merchant request."},
            session_id=LEAD,
        ) is None


# -------------------------------------------------------------------
# D2: a stale pane from the previous task cannot settle the new task
# -------------------------------------------------------------------


def test_d2_stale_pane_cannot_settle_reassigned_task(
    fake_runtime_handler, os_server, tmp_path
):
    calls, _ = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    assert execute_request(UPDATE_ARGV) == 0
    assert report("EXECUTE_SUCCESS", command="project update") == 0
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    _reuse_for_new_task(f"Update merchant project {PROJECT_ID} again")
    new_task = record()["current_task_id"]
    assert record()["status"] == "RUNNING"

    # The harness respawned the teammate in %8; %7 is now stale.
    write_harness_team(tmp_path / "harness_teams", "%8")

    assert execute_request(UPDATE_ARGV) == 0
    assert report("FAILED", command="project update") == 0
    assert idle() == 0
    assert idle() == 0

    assert record()["status"] == "RUNNING"
    assert record()["current_task_id"] == new_task
    assert len(calls) == 1
    assert not _spent()

    # The assigned pane still executes once and releases.
    assert execute_request(UPDATE_ARGV, pane="pane-next", tmux="%8") == 0
    assert len(calls) == 2
    assert record()["trusted_tmux_pane_id"] == f"{PANE_SERVER}:%8"
    assert (
        report("EXECUTE_SUCCESS", pane="pane-next", tmux="%8",
               command="project update")
        == 0
    )
    assert idle("pane-next", tmux="%8") == 0
    assert record()["status"] == "IDLE_REUSABLE"


# -------------------------------------------------------------------
# D3: a foreign pane on an unbound task gets no feedback and no effect
# -------------------------------------------------------------------


def test_d3_foreign_pane_on_unbound_task_is_ignored(
    fake_runtime_handler, os_server
):
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    before = record()

    for _ in range(3):
        assert idle("rogue-pane", tmux="%9") == 0

    assert report("FAILED", pane="rogue-pane", tmux="%9",
                  command="project update") == 0
    assert idle("rogue-pane", tmux="%9") == 0
    assert record() == before


def test_unbound_task_binds_only_from_verified_pane_at_idle(
    fake_runtime_handler, os_server
):
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    # The assigned pane idles before executing: it is bound, not trusted
    # merely because nothing conflicts, and is asked for its result.
    assert idle() == 2
    assert record()["trusted_pane_task_id"] == record()["current_task_id"]
    assert record()["trusted_tmux_pane_id"] == f"{PANE_SERVER}:{PANE_TMUX}"


# -------------------------------------------------------------------
# D4: equal pane ids in different psmux servers
# -------------------------------------------------------------------


def test_d4_same_pane_id_in_another_psmux_server_is_rejected(
    fake_runtime_handler, os_server
):
    calls, _ = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    # Another psmux session's server also numbers a pane %7.
    os_server["server"] = OTHER_SERVER
    other = {"pane": "other-server-pane", "tmux": PANE_TMUX}
    assert execute_request(UPDATE_ARGV, **other) == 0
    assert report("FAILED", command="project update", **other) == 0
    assert idle(**other) == 0
    assert calls == []
    assert not _spent()
    assert record()["status"] == "RUNNING"
    assert not record().get("trusted_pane_session_id")

    # The genuine %7 in the lead's server still works.
    os_server["server"] = PANE_SERVER
    assert execute_request(UPDATE_ARGV) == 0
    assert len(calls) == 1


def test_d4_outer_nested_psmux_server_is_rejected(
    fake_runtime_handler, os_server, monkeypatch
):
    # Found live: psmux spawned the lead's server from another session's
    # server, so that outer server is also an ancestor of the lead.
    nested = dict(TABLE)
    nested[PANE_SERVER] = (OTHER_SERVER, "tmux.exe")
    monkeypatch.setattr(
        harness_team_identity,
        "own_pane_server",
        lambda tmux_pane, *_: (os_server["server"], nested),
    )
    calls, _ = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None

    os_server["server"] = OTHER_SERVER
    outer = {"pane": "outer-server-pane", "tmux": PANE_TMUX}
    assert execute_request(UPDATE_ARGV, **outer) == 0
    assert idle(**outer) == 0
    assert calls == []
    assert not _spent()

    os_server["server"] = PANE_SERVER
    assert execute_request(UPDATE_ARGV) == 0
    assert len(calls) == 1


def test_own_pane_server_picks_the_ancestor_pane_only(monkeypatch):
    # psmux lists %1 once per server; only one is this process's ancestor.
    table = {
        50: (11, "python.exe"),
        11: (900, "powershell.exe"),
        900: (1, "tmux.exe"),
        12: (901, "powershell.exe"),
        901: (1, "tmux.exe"),
    }
    monkeypatch.setattr(harness_team_identity, "_process_table", lambda: table)
    monkeypatch.setattr(harness_team_identity.os, "getpid", lambda: 50)
    monkeypatch.setattr(harness_team_identity, "_pane_pids", lambda p: [12, 11])

    assert harness_team_identity.own_pane_server("%1") == (900, table)

    monkeypatch.setattr(harness_team_identity, "_pane_pids", lambda p: [12])
    assert harness_team_identity.own_pane_server("%1") is None

    # A pane whose parent is not a tmux/psmux server is not a pane.
    table[900] = (1, "explorer.exe")
    monkeypatch.setattr(harness_team_identity, "_pane_pids", lambda p: [11])
    assert harness_team_identity.own_pane_server("%1") is None


@pytest.mark.parametrize(
    "lead",
    [None, {"pid": LEAD_PID, "pidSpace": "another-host"}, {"pid": "4242"}],
)
def test_missing_or_foreign_lead_process_fails_closed(
    lead, os_server, tmp_path, monkeypatch
):
    write_harness_team(tmp_path / "harness_teams", PANE_TMUX)
    config = next((tmp_path / "harness_teams").glob("*/config.json"))
    data = json.loads(config.read_text(encoding="utf-8"))
    data.pop("leadProcess")
    if lead is not None:
        data["leadProcess"] = lead
    config.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("TMUX_PANE", PANE_TMUX)

    assert harness_team_identity.verified_teammate_pane(LEAD, TEAMMATE) is None


def test_duplicate_idle_after_release_writes_once(
    fake_runtime_handler, os_server
):
    calls, _ = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    assert execute_request(UPDATE_ARGV) == 0
    assert execute_request(UPDATE_ARGV) == 0
    assert report("EXECUTE_SUCCESS", command="project update") == 0

    for _ in range(3):
        assert idle() == 0

    assert len(calls) == 1
    assert record()["status"] == "IDLE_REUSABLE"


def test_conflicting_session_in_verified_pane_is_terminal(
    fake_runtime_handler, os_server
):
    calls, _ = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    assert idle() == 2  # binds PANE

    # Same verified pane %7, different session: conflict, once, bounded.
    for _ in range(3):
        assert idle("restarted-session", tmux=PANE_TMUX) == 0

    assert record()["status"] == "FAILED"
    assert record()["failure_reason"] == "PANE_BINDING_CONFLICT"
    assert execute_request(UPDATE_ARGV) == 0
    assert calls == []


def test_trusted_teammate_completes_read_only_task(monkeypatch):
    # No pane can be verified at all: read-only work never needs it.
    monkeypatch.setattr(
        harness_team_identity,
        "verified_teammate_pane",
        lambda owner, name: None,
    )
    from claude.system.intent_parser import Operation

    intent_gate.run(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": LEAD,
            "prompt": "/solve List merchants",
        },
        parser_factory=lambda: _parser([Operation.MERCHANT_READ]),
        env={},
    )
    assert dispatch() is None
    assert record()["authorized_operations"] == ["merchant_read"]

    assert send("Merchants: none found in the read-only listing.") == 0
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"


# -------------------------------------------------------------------
# D1: database preflight before any authority is spent
# -------------------------------------------------------------------


def _test_create_attempt(argv=CREATE_ARGV):
    submit("Create merchant CP12H5B", argv=argv, target="test")
    assert dispatch() is None
    return execute_request(argv, target="test")


def _refused_before_spend(capsys, reason):
    out = capsys.readouterr().out
    assert "refused before execution" in out
    assert reason in out
    assert not _spent()
    assert "direct_writes" not in record()
    assert run_state()[HANDOFF_STATE_KEY]["status"] == "FAILED"


def test_d1_runtime_target_maps_to_app_role(monkeypatch):
    seen = []

    class Repo:
        def __init__(self, *, role):
            seen.append(role)
            self.config = type(
                "C", (), {"database": "coding_agent_merchant",
                          "user": "merchant_app"}
            )()

    monkeypatch.setattr(
        "claude.clients.merchant.repository.MerchantRepository", Repo
    )
    repository = merchant_reserved_execution.repository_for_target("runtime")
    assert isinstance(repository, Repo)
    assert seen == ["app"]


def test_d1_runtime_create_is_refused_before_spend(capsys):
    submit("Create merchant CP12H5B", argv=CREATE_ARGV)
    assert dispatch() is None
    assert execute_request(CREATE_ARGV) == 0
    _refused_before_spend(capsys, "RUNTIME_EXECUTION_DISABLED")


def test_d1_invalid_test_configuration_is_refused_before_spend(
    capsys, monkeypatch
):
    monkeypatch.setenv("MERCHANT_TEST_PASSWORD", "unused")
    monkeypatch.setenv("MERCHANT_TEST_USER", "merchant_app")
    assert _test_create_attempt() == 0
    _refused_before_spend(capsys, "INVALID_CONFIGURATION")


def test_database_unavailable_is_refused_before_spend(capsys, monkeypatch):
    monkeypatch.setenv("MERCHANT_TEST_PASSWORD", "unused")
    monkeypatch.setenv("MERCHANT_TEST_USER", "merchant_test")
    monkeypatch.setenv("MERCHANT_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("MERCHANT_DB_PORT", "1")
    monkeypatch.setenv("MERCHANT_CONNECT_TIMEOUT_SECONDS", "2")
    assert _test_create_attempt() == 0
    _refused_before_spend(capsys, "DATABASE_UNAVAILABLE")


def test_effective_identity_mismatch_is_refused(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            pass

        def fetchone(self):
            return {"current_database": "coding_agent_merchant",
                    "current_user": "merchant_app"}

    class Connection(Cursor):
        def cursor(self):
            return Cursor()

    class Repo:
        def connection(self, read_only):
            assert read_only is True
            return Connection()

    with pytest.raises(merchant_reserved_execution.DatabasePreflightError) as e:
        merchant_reserved_execution.preflight_database_identity(Repo(), "test")
    assert e.value.reason == "INVALID_CONFIGURATION"


# -------------------------------------------------------------------
# Phase C: test routing cannot reach runtime, targets cannot be swapped
# -------------------------------------------------------------------


def test_test_routing_never_reads_runtime_credentials(monkeypatch):
    monkeypatch.setenv("MERCHANT_DB_PASSWORD", "runtime-secret")
    monkeypatch.setenv("MERCHANT_TEST_PASSWORD", "test-secret")
    monkeypatch.setenv("MERCHANT_TEST_USER", "merchant_test")
    monkeypatch.delenv("MERCHANT_TEST_DB_NAME", raising=False)

    config = merchant_reserved_execution.repository_for_target("test").config
    assert (config.database, config.user, config.password) == (
        "coding_agent_merchant_test", "merchant_test", "test-secret"
    )

    monkeypatch.setenv("MERCHANT_TEST_DB_NAME", "coding_agent_merchant")
    with pytest.raises(merchant_reserved_execution.DatabasePreflightError):
        merchant_reserved_execution.repository_for_target("test")


def test_target_is_bound_into_scope_and_confirmation():
    runtime = validate_direct_scope(CREATE_ARGV, "runtime")
    test = validate_direct_scope(CREATE_ARGV, "test")
    assert runtime["scope_hash"] != test["scope_hash"]
    assert runtime["confirmation_hash"] != test["confirmation_hash"]
    with pytest.raises(Exception):
        validate_direct_scope(CREATE_ARGV, "production")


def test_test_scope_rejects_runtime_execute_request():
    submit("Create merchant CP12H5B", argv=CREATE_ARGV, target="test")
    assert dispatch() is None
    assert execute_request(CREATE_ARGV, target="runtime") == 0
    assert not _spent()
    assert HANDOFF_STATE_KEY not in run_state()


def test_runtime_scope_rejects_test_execute_request(fake_runtime_handler):
    calls, _ = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV)
    assert dispatch() is None
    assert execute_request(UPDATE_ARGV, target="test") == 0
    assert calls == []
    assert not _spent()


def test_test_to_runtime_escalation_in_state_is_rejected():
    submit("Create merchant CP12H5B", argv=CREATE_ARGV, target="test")
    assert dispatch() is None

    # Rewriting the persisted target cannot re-target the authorized scope.
    with runtime_state.locked_state(LEAD) as state:
        state["merchant_scope"]["database_target"] = "runtime"

    for target in ("runtime", "test"):
        assert execute_request(CREATE_ARGV, target=target) == 0

    assert not _spent()
    assert HANDOFF_STATE_KEY not in run_state()


def test_test_mode_refuses_non_create_writes(fake_runtime_handler, capsys):
    calls, _ = fake_runtime_handler
    submit(f"Update merchant project {PROJECT_ID}", argv=UPDATE_ARGV,
           target="test")
    assert dispatch() is None
    assert execute_request(UPDATE_ARGV, target="test") == 0
    assert calls == []
    _refused_before_spend(capsys, "TEST_MODE_COMMAND_UNSUPPORTED")


def test_runtime_execution_stays_disabled_without_code_change():
    assert merchant_direct_handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False


@pytest.mark.parametrize(
    "prefix",
    [
        "--merchant-target runtime --merchant-scope",
        "--merchant-target production --merchant-scope",
        "--merchant-target test",
    ],
)
def test_only_the_test_target_can_be_typed(prefix):
    result = intent_gate.run(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": LEAD,
            "prompt": f'/solve --confirm {prefix} ["merchant"] Create it',
        },
        parser_factory=lambda: _parser(),
        env={},
    )
    assert result["decision"] == "block"
    assert runtime_state.load_state(LEAD) is None
