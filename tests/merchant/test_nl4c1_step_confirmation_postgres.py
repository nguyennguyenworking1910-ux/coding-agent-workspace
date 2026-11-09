"""CP12H.NL4C1 on the Merchant test database: the confirmed Step re-check.

Disposable ``PYTEST_NL4C1_`` Merchants and Projects are created through the real
workflow repository and deleted after each test. Transitions here run only on
those fixtures, through the real ``step update`` write adapter and
``transition_step`` (never through /solve, never on the live acceptance
Projects). The suite must run alone: never concurrently with other
PostgreSQL tests against the same database.
"""

from __future__ import annotations

import os
import threading
import uuid
from types import SimpleNamespace

import pytest

from claude.agents.tools.merchant.step_preview import StepPreviewMismatch, verify_step_update
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.agents.tools.merchant.write_adapters import (
    MerchantRepositoryWriteAdapters,
    MerchantWriteRepositories,
)
from claude.clients.merchant import transition_repository
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from claude.hooks import merchant_direct_handoff as handoff
from tests.merchant.test_nl1_project_preview_postgres import _delete_fixtures
from tests.merchant.test_nl4b_step_preview_postgres import ask
from tests.merchant.test_nl4c1_step_confirmation import payload_of

pytestmark = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME") != "coding_agent_merchant_test"
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database is not configured",
)

PREFIX = "PYTEST_NL4C1_"
SHORT = f"Nlconf{uuid.uuid4().hex[:6]}"
TITLE = f"{SHORT} Nguyễn Văn Cừ"
REQUEST = f"Bắt đầu bước 1 của Project {TITLE} của Merchant {SHORT} Cinemas trên database test"


@pytest.fixture
def fixture():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    _delete_fixtures(repository, (), PREFIX)
    merchant_id = uuid.uuid4()
    with repository.connection() as connection, connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
            "VALUES (%s, %s, %s, 'ACTIVE')",
            (merchant_id, f"{PREFIX}{uuid.uuid4().hex[:8].upper()}", f"{SHORT} Cinemas"),
        )
    created = MerchantWorkflowRepository(repository).create_project(
        merchant_id=str(merchant_id),
        template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
        requires_procurement=False, title=TITLE,
    )
    try:
        yield repository, str(created.project_id)
    finally:
        _delete_fixtures(repository, (merchant_id,), PREFIX)
        with repository.connection(read_only=True) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) AS n FROM merchant_ops.merchants WHERE code LIKE %s",
                           (PREFIX + "%",))
            assert cursor.fetchone()["n"] == 0


def confirmed(repository):
    result = ask(repository, REQUEST)
    assert result["outcome"] == "READY_FOR_CONFIRMATION", result["blocking"]
    operation = result["requested_operation"]
    assert operation["project_title"] == TITLE and operation["database_target"] == "test"
    return operation, payload_of(operation["argv"])


def apply(repository, payload):
    adapters = MerchantRepositoryWriteAdapters(MerchantWriteRepositories.from_repository(repository))
    return adapters.update_step(payload)


def state(repository, project_id):
    with repository.connection(read_only=True) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status, version FROM merchant_ops.project_steps "
                       "WHERE project_id = %s AND sequence_number = 1", (project_id,))
        step = dict(cursor.fetchone())
        cursor.execute("SELECT count(*) AS n FROM merchant_ops.project_events "
                       "WHERE project_id = %s AND entity_type = 'STEP'", (project_id,))
        return step["status"], step["version"], cursor.fetchone()["n"]


def sql(repository, statement, *parameters):
    with repository.connection() as connection, connection.transaction(), connection.cursor() as cursor:
        cursor.execute(statement, parameters)


def test_unchanged_confirmation_applies_exactly_the_previewed_transition(fixture):
    repository, project_id = fixture
    operation, payload = confirmed(repository)
    verify_step_update(MerchantReadRepository(repository), payload)

    result = apply(repository, payload)

    assert (result.previous_status, result.current_status) == ("READY", "IN_PROGRESS")
    assert state(repository, project_id) == ("IN_PROGRESS", operation["step_version"] + 1, 1)
    # The same confirmation can never apply twice.
    with pytest.raises(StepPreviewMismatch):
        apply(repository, payload)
    assert state(repository, project_id)[2] == 1


@pytest.mark.parametrize(
    "change,reason",
    [
        ("UPDATE merchant_ops.projects SET version = version + 1 WHERE id = %s", "STEP_BASIS_CHANGED"),
        ("UPDATE merchant_ops.project_steps SET version = version + 1 "
         "WHERE project_id = %s AND sequence_number = 1", "STEP_VERSION_CHANGED"),
        ("UPDATE merchant_ops.project_steps SET version = version + 1 "
         "WHERE project_id = %s AND sequence_number = 3", "STEP_BASIS_CHANGED"),
        ("DELETE FROM merchant_ops.project_step_dependencies d USING merchant_ops.project_steps s "
         "WHERE d.to_step_id = s.id AND s.project_id = %s AND s.sequence_number = 3",
         "STEP_BASIS_CHANGED"),
    ],
    ids=["project-version", "step-version", "other-step", "dependency-graph"],
)
def test_state_changed_after_preview_is_refused_in_the_write_transaction(fixture, change, reason):
    repository, project_id = fixture
    _, payload = confirmed(repository)
    sql(repository, change, project_id)
    before = state(repository, project_id)

    with pytest.raises(StepPreviewMismatch) as error:
        apply(repository, payload)

    assert error.value.reason == reason
    assert state(repository, project_id) == before          # nothing written


def test_preflight_rejudges_before_any_spend(fixture):
    repository, project_id = fixture
    operation, _ = confirmed(repository)
    attempt = SimpleNamespace(arguments=tuple(operation["argv"]))

    handoff._verify_step_preview(attempt, repository)        # unchanged: accepted

    bare = SimpleNamespace(arguments=tuple(operation["argv"][:7]))  # no basis
    with pytest.raises(handoff.DirectPreflightRefused) as error:
        handoff._verify_step_preview(bare, repository)
    assert error.value.reason == "STEP_BASIS_REQUIRED"

    sql(repository, "UPDATE merchant_ops.projects SET version = version + 1 WHERE id = %s", project_id)
    with pytest.raises(handoff.DirectPreflightRefused) as error:
        handoff._verify_step_preview(attempt, repository)
    assert error.value.reason == "STEP_BASIS_CHANGED"


def test_concurrent_applies_of_one_confirmation_write_once(fixture):
    repository, project_id = fixture
    _, payload = confirmed(repository)
    outcomes = []
    barrier = threading.Barrier(4)

    def run():
        barrier.wait()
        try:
            apply(repository, dict(payload))
            outcomes.append("ok")
        except Exception as error:  # noqa: BLE001 - every loser must refuse
            outcomes.append(type(error).__name__)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("ok") == 1, outcomes
    status, version, events = state(repository, project_id)
    assert (status, events) == ("IN_PROGRESS", 1)


def test_crash_inside_the_write_transaction_leaves_nothing(fixture, monkeypatch):
    repository, project_id = fixture
    _, payload = confirmed(repository)
    before = state(repository, project_id)

    def crash(*_a, **_k):
        raise RuntimeError("connection lost after UPDATE, before commit")

    with monkeypatch.context() as patch:
        patch.setattr(transition_repository, "should_activate_merchant_on_step_transition", crash)
        with pytest.raises(RuntimeError):
            apply(repository, payload)

    assert state(repository, project_id) == before          # rolled back as a whole
    verify_step_update(MerchantReadRepository(repository), payload)  # basis still valid
