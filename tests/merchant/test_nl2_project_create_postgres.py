"""CP12H.NL2: previewed Project creation through the real Direct EXECUTE path.

Real intent gate, policy gate, team-result hook, pane identity, reservation,
evidence-bound transaction and TeammateIdle settlement, on the Merchant test
database. Each test seeds its own uniquely named ACTIVE Merchant, confirms
the exact previewed operation, and removes only the rows it created.
"""

from __future__ import annotations

import uuid

import pytest

from claude.agents.tools.merchant.project_preview import READY, build_project_preview
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from claude.hooks import merchant_attempt_resolution, merchant_direct_handoff
from claude.hooks import policy_gate, runtime_state
from claude.hooks.merchant_runtime_handoff_gate import (
    HANDOFF_STATE_KEY,
    HANDOFF_SUCCESS,
)
from tests.merchant.test_direct_execute_end_to_end import (  # noqa: F401
    LEAD,
    TEAMMATE,
    TEST_DB_CONFIGURED,
    dispatch,
    execute_request,
    idle,
    isolated,
    record,
    report,
    run_state,
    submit,
)
from tests.merchant.test_nl1_project_preview_postgres import snapshot


pytestmark = pytest.mark.skipif(
    not TEST_DB_CONFIGURED, reason="Merchant test database not configured"
)

KEY_PREFIX = "pytest:nl2-scope:"


@pytest.fixture(autouse=True)
def pytest_operation_keys(monkeypatch):
    # Evidence and fences of these runs carry pytest: keys only.
    monkeypatch.setattr(
        merchant_attempt_resolution, "SCOPE_OPERATION_KEY_PREFIX", KEY_PREFIX
    )


@pytest.fixture
def merchant():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    short = f"Nlbeta{uuid.uuid4().hex[:6]}"
    merchant_id = uuid.uuid4()

    with repository.connection() as connection:
        with connection.transaction():
            connection.execute(
                "INSERT INTO merchant_ops.merchants (id, code, name, account_status)"
                " VALUES (%s, %s, %s, 'ACTIVE')",
                (merchant_id, f"PYTEST_NL2_{short.upper()}", f"{short} Cinemas"),
            )

    yield repository, str(merchant_id), short

    with repository.connection() as connection:
        with connection.transaction():
            for statement in (
                "DELETE FROM merchant_ops.project_step_dependencies d"
                " USING merchant_ops.project_steps s, merchant_ops.projects p"
                " WHERE d.from_step_id = s.id AND s.project_id = p.id"
                " AND p.merchant_id = %(m)s",
                "DELETE FROM merchant_ops.project_steps s USING merchant_ops.projects p"
                " WHERE s.project_id = p.id AND p.merchant_id = %(m)s",
                "DELETE FROM merchant_ops.project_events WHERE merchant_id = %(m)s",
                "DELETE FROM merchant_ops.projects WHERE merchant_id = %(m)s",
                "DELETE FROM merchant_ops.merchants WHERE id = %(m)s",
            ):
                connection.execute(statement, {"m": merchant_id})
            for table in ("merchant_execution_claims", "merchant_execution_ledger"):
                connection.execute(
                    f"DELETE FROM merchant_ops.{table} WHERE operation_key LIKE %s",
                    (KEY_PREFIX + "%",),
                )


def request_for(short):
    return (
        f"Create a cinema opening project for {short} Nguyễn Văn Cừ under "
        f"{short} Cinemas. No procurement."
    )


def preview(repository, short):
    result = build_project_preview(
        request_for(short), MerchantReadRepository(repository), database_target="test"
    )
    assert result["outcome"] == READY, result["clarifications"] + result["conflicts"]
    return result


def projects(repository, merchant_id):
    with repository.connection(read_only=True) as connection:
        return connection.execute(
            "SELECT id, merchant_id, project_type, workflow_variant, title, status,"
            " (SELECT count(*) FROM merchant_ops.project_steps s"
            "  WHERE s.project_id = p.id) AS steps"
            " FROM merchant_ops.projects p WHERE merchant_id = %s",
            (uuid.UUID(merchant_id),),
        ).fetchall()


def claims(repository):
    with repository.connection(read_only=True) as connection:
        return connection.execute(
            "SELECT claim_status FROM merchant_ops.merchant_execution_claims"
            " WHERE operation_key LIKE %s",
            (KEY_PREFIX + "%",),
        ).fetchall()


def confirm(argv, short, *, reuse=False):
    submit(request_for(short), argv=argv, target="test")
    assert run_state()["operations"] == ["merchant_execute"]
    assert run_state()["merchant_scope"]["database_target"] == "test"

    if not reuse:
        assert dispatch() is None
        return

    # An idle teammate is reused: the Agent call is redirected to
    # SendMessage, which starts the new task.
    assert dispatch() is not None
    with runtime_state.locked_state(LEAD) as state:
        assert policy_gate.apply_call(
            state,
            "SendMessage",
            {"to": TEAMMATE, "message": "Perform the user's Merchant request."},
            session_id=LEAD,
        ) is None


def authority_spent():
    return run_state().get("merchant_runtime_authorization_issued") is True


def test_confirmed_preview_creates_exactly_one_project_and_releases(merchant):
    repository, merchant_id, short = merchant
    result = preview(repository, short)
    argv = result["requested_operation"]["argv"]

    confirm(argv, short)
    assert execute_request(argv, target="test") == 0

    execution = record()["direct_scope_execution"]
    assert execution["status"] == "SUCCEEDED"
    assert run_state()[HANDOFF_STATE_KEY]["status"] == HANDOFF_SUCCESS

    (created,) = projects(repository, merchant_id)
    assert str(created["id"]) == result["requested_operation"]["argv"][11]
    assert str(created["merchant_id"]) == merchant_id
    assert created["workflow_variant"] == "OPENING_NEW_CINEMA_STANDARD"
    assert created["title"] == f"{short} Nguyễn Văn Cừ"
    assert created["status"] == "PLANNED"
    assert created["steps"] == len(result["initial_steps"]) == 22
    assert [row["claim_status"] for row in claims(repository)] == ["COMPLETED"]

    # Replaying the request in the same task never reaches PostgreSQL.
    assert execute_request(argv, target="test") == 0
    assert len(projects(repository, merchant_id)) == 1

    assert report(
        "EXECUTE_SUCCESS", command="project create", database_target="test"
    ) == 0
    assert idle() == 0
    assert record()["status"] == "IDLE_REUSABLE"

    # A fresh confirmation of the same operation is refused before any spend:
    # the Project it would duplicate now exists.
    confirm(argv, short, reuse=True)
    before = snapshot(repository)
    execute_request(argv, target="test")
    assert snapshot(repository) == before
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == (
        "PREFLIGHT:PROJECT_NOT_READY"
    )
    assert not authority_spent()
    assert len(projects(repository, merchant_id)) == 1


def test_stale_basis_is_refused_before_any_spend(merchant):
    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"]

    with repository.connection() as connection:
        with connection.transaction():
            connection.execute(
                "UPDATE merchant_ops.merchants SET version = version + 1"
                " WHERE id = %s",
                (uuid.UUID(merchant_id),),
            )

    confirm(argv, short)
    before = snapshot(repository)
    execute_request(argv, target="test")

    assert snapshot(repository) == before
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == (
        "PREFLIGHT:PREVIEW_BASIS_CHANGED"
    )
    assert not authority_spent()
    assert "direct_scope_execution" not in record()
    assert projects(repository, merchant_id) == []


def test_scope_without_preview_basis_is_refused(merchant):
    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"][:10]

    confirm(argv, short)
    execute_request(argv, target="test")

    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == (
        "PREFLIGHT:PREVIEW_BASIS_REQUIRED"
    )
    assert not authority_spent()
    assert projects(repository, merchant_id) == []


def test_change_after_preflight_fails_inside_the_transaction(merchant, monkeypatch):
    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"]
    confirm(argv, short)

    original = merchant_direct_handoff._verify_project_preview

    def then_change(attempt, target_repository):
        original(attempt, target_repository)
        # Another writer changes the Merchant after the read-only check.
        with repository.connection() as connection:
            with connection.transaction():
                connection.execute(
                    "UPDATE merchant_ops.merchants SET version = version + 1"
                    " WHERE id = %s",
                    (uuid.UUID(merchant_id),),
                )

    monkeypatch.setattr(merchant_direct_handoff, "_verify_project_preview", then_change)

    execute_request(argv, target="test")

    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert projects(repository, merchant_id) == []
    # The attempt was fenced, so it can never commit late.
    assert [row["claim_status"] for row in claims(repository)] == ["REVOKED"]

    # The spent, failed attempt is never retried.
    execute_request(argv, target="test")
    assert projects(repository, merchant_id) == []
    assert record()["direct_scope_execution"]["status"] == "FAILED"


def test_crash_before_commit_writes_nothing_and_is_not_retried(merchant, monkeypatch):
    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"]
    confirm(argv, short)

    from claude.clients.merchant import workflow_repository

    def crash(*args, **kwargs):
        raise RuntimeError("connection lost mid-transaction")

    monkeypatch.setattr(
        workflow_repository.MerchantWorkflowRepository, "_insert_event", crash
    )

    execute_request(argv, target="test")

    # Unclassified failure: settled from evidence, never inferred.
    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert projects(repository, merchant_id) == []
    assert [row["claim_status"] for row in claims(repository)] == ["REVOKED"]

    execute_request(argv, target="test")
    assert projects(repository, merchant_id) == []


def test_crash_after_commit_is_settled_from_evidence(merchant, monkeypatch):
    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"]
    confirm(argv, short)

    # The commit happens but its acknowledgement is lost.
    monkeypatch.setattr(
        merchant_direct_handoff, "bounded_runtime_apply_result", lambda *a: None
    )

    execute_request(argv, target="test")

    assert record()["direct_scope_execution"]["status"] == "SUCCEEDED"
    assert len(projects(repository, merchant_id)) == 1
    assert [row["claim_status"] for row in claims(repository)] == ["COMPLETED"]


def test_runtime_confirmation_of_a_test_operation_is_refused(merchant):
    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"]

    submit(request_for(short), argv=argv)
    assert run_state()["merchant_scope"]["database_target"] == "runtime"
    assert dispatch() is None
    execute_request(argv, target="runtime")

    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == (
        "PREFLIGHT:RUNTIME_EXECUTION_DISABLED"
    )
    assert not authority_spent()
    assert projects(repository, merchant_id) == []


def test_teammate_cannot_retarget_a_test_scope(merchant):
    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"]

    confirm(argv, short)
    execute_request(argv, target="runtime")

    assert not authority_spent()
    assert "direct_scope_execution" not in record()
    assert projects(repository, merchant_id) == []


# ---- CP12H.NL2E P2: the confirmed --merchant-code against real PostgreSQL ----


def _code_token(argv):
    return argv.index("--merchant-code") + 1


def test_merchant_code_of_another_merchant_is_refused_before_any_spend(merchant):
    repository, merchant_id, short = merchant
    argv = list(preview(repository, short)["requested_operation"]["argv"])
    assert argv[_code_token(argv)] == f"PYTEST_NL2_{short.upper()}"
    # Another existing Merchant's code (the live fixture, read only).
    argv[_code_token(argv)] = "NL2_LIVE_BETA"

    confirm(argv, short)
    before = snapshot(repository)
    execute_request(argv, target="test")

    assert snapshot(repository) == before
    assert run_state()[HANDOFF_STATE_KEY]["failure_type"] == (
        "PREFLIGHT:PROJECT_NOT_READY"
    )
    assert not authority_spent()
    assert projects(repository, merchant_id) == []


def test_transaction_precondition_rechecks_the_confirmed_merchant_code(merchant):
    """The in-transaction re-check sees the locked row's current code."""

    from psycopg.rows import dict_row

    from claude.agents.tools.merchant.cli import (
        build_argument_parser,
        build_write_payload,
    )
    from claude.agents.tools.merchant.project_preview import ProjectPreviewMismatch
    from claude.agents.tools.merchant.write_adapters import (
        _confirmed_preview_precondition,
    )

    class Rollback(Exception):
        pass

    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"]
    args = build_argument_parser().parse_args(["--database", "test", *argv])
    precondition = _confirmed_preview_precondition(
        build_write_payload(args, "project create")
    )

    # Control: unchanged state passes inside a real write transaction.
    with pytest.raises(Rollback):
        with repository.connection() as connection:
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cursor:
                    precondition(cursor)
                    raise Rollback

    # The code is re-assigned inside the same transaction: refused.
    with pytest.raises(Rollback):
        with repository.connection() as connection:
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        "UPDATE merchant_ops.merchants SET code = code || '_X'"
                        " WHERE id = %s",
                        (uuid.UUID(merchant_id),),
                    )
                    with pytest.raises(ProjectPreviewMismatch) as error:
                        precondition(cursor)
                    assert "MERCHANT_CODE_MISMATCH" in str(error.value)
                    raise Rollback

    # Both transactions rolled back: the Merchant is unchanged.
    assert projects(repository, merchant_id) == []
    with repository.connection(read_only=True) as connection:
        (row,) = connection.execute(
            "SELECT code FROM merchant_ops.merchants WHERE id = %s",
            (uuid.UUID(merchant_id),),
        ).fetchall()
    assert row["code"] == f"PYTEST_NL2_{short.upper()}"


def test_merchant_code_changed_after_preflight_fails_inside_the_transaction(
    merchant, monkeypatch
):
    repository, merchant_id, short = merchant
    argv = preview(repository, short)["requested_operation"]["argv"]
    confirm(argv, short)

    original = merchant_direct_handoff._verify_project_preview

    def then_recode(attempt, target_repository):
        original(attempt, target_repository)
        with repository.connection() as connection:
            with connection.transaction():
                connection.execute(
                    "UPDATE merchant_ops.merchants SET code = code || '_X'"
                    " WHERE id = %s",
                    (uuid.UUID(merchant_id),),
                )

    monkeypatch.setattr(merchant_direct_handoff, "_verify_project_preview", then_recode)

    execute_request(argv, target="test")

    assert record()["direct_scope_execution"]["status"] == "FAILED"
    assert projects(repository, merchant_id) == []
    assert [row["claim_status"] for row in claims(repository)] == ["REVOKED"]
