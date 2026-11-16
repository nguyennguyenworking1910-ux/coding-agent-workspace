"""CP12H.NL4C2B-PREP: approval evidence changing while a confirmed Step Update commits.

Real PostgreSQL (``coding_agent_merchant_test``), real repositories, real
locks. Each test builds a throwaway ``PYTEST_NL4C2B_`` Project whose step 5,
"Record Partner approval", is a database-verified APPROVAL_GATE satisfied by
one stored PARTNER approval. It previews "step 5 -> COMPLETED", then changes
the approval evidence at a precise point of the confirmed write transaction:

- a repository writer (a new CONTRACT revision, which leaves the PARTNER
  approval on a superseded revision) after the re-check: it waits on the
  Project lock and commits after the Step Update (serialized, never stale);
- the same writer holding the Project lock first: the Step Update waits,
  then its in-transaction re-check refuses the changed basis;
- raw SQL between the re-check and the gate read: the gate reads the
  rejection and refuses;
- raw SQL after the gate read (update or a new revision): blocked by the
  gate's row locks until the Step Update commits.

Deterministic: pauses are placed with Events at named points, never by
timing alone. Must run alone (no concurrent PostgreSQL test process).
"""

from __future__ import annotations

import json
import threading
import uuid

import psycopg
import pytest

from claude.agents.tools.merchant import write_adapters
from claude.agents.tools.merchant.engine import WorkflowGateNotMetError
from claude.agents.tools.merchant.step_preview import StepPreviewMismatch
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.agents.tools.merchant.write_adapters import (
    MerchantRepositoryWriteAdapters,
    MerchantWriteRepositories,
)
from claude.clients.merchant import document_repository, transition_repository
from claude.clients.merchant.approval_repository import MerchantApprovalRepository
from claude.clients.merchant.document_repository import MerchantDocumentRepository
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.transition_repository import MerchantStepTransitionRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from tests.merchant.test_nl1_project_preview_postgres import _delete_fixtures
from tests.merchant.test_nl4b_step_preview_postgres import ask
from tests.merchant.test_nl4c1_step_confirmation import payload_of
from tests.merchant.test_nl4c1_step_confirmation_postgres import pytestmark  # noqa: F401

PREFIX = "PYTEST_NL4C2B_"
WAIT = 1.0          # well under the 5 s lock_timeout


def delete_all(repository, merchant_ids=()):
    """Remove this module's fixtures, evidence included (FK order)."""

    with repository.connection() as connection, connection.transaction():
        scope = (" FROM merchant_ops.projects p, merchant_ops.merchants m"
                 " WHERE d.project_id = p.id AND p.merchant_id = m.id AND m.code LIKE %s")
        connection.execute(
            "DELETE FROM merchant_ops.document_approvals a USING merchant_ops.document_revisions d,"
            " merchant_ops.projects p, merchant_ops.merchants m WHERE a.document_revision_id = d.id"
            " AND d.project_id = p.id AND p.merchant_id = m.id AND m.code LIKE %s", (PREFIX + "%",))
        connection.execute("UPDATE merchant_ops.document_revisions d SET superseded_by = NULL"
                           + scope, (PREFIX + "%",))
        connection.execute("DELETE FROM merchant_ops.document_revisions d USING"
                           + scope[5:], (PREFIX + "%",))
    _delete_fixtures(repository, merchant_ids, PREFIX)


@pytest.fixture
def gated():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    delete_all(repository)
    short = f"Nlgate{uuid.uuid4().hex[:6]}"
    title = f"{short} Nguyễn Văn Cừ"
    merchant_id = uuid.uuid4()
    with repository.connection() as connection, connection.transaction():
        connection.execute(
            "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
            "VALUES (%s, %s, %s, 'ACTIVE')",
            (merchant_id, f"{PREFIX}{uuid.uuid4().hex[:8].upper()}", f"{short} Cinemas"),
        )
    try:
        project_id = str(MerchantWorkflowRepository(repository).create_project(
            merchant_id=str(merchant_id),
            template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
            requires_procurement=False, title=title,
        ).project_id)
        steps = MerchantStepTransitionRepository(repository)

        def move(sequence, target):
            row = step(repository, project_id, sequence)
            steps.transition_step(step_id=row["id"], target_status=target,
                                  expected_version=row["version"])

        def ready(sequence):
            if step(repository, project_id, sequence)["status"] == "PENDING":
                move(sequence, "READY")

        for sequence in (1, 2, 3, 4):
            ready(sequence)
            move(sequence, "IN_PROGRESS")
            move(sequence, "COMPLETED")
        revision = MerchantDocumentRepository(repository).create_revision(
            project_id=project_id, document_type="CONTRACT", content_hash="a" * 64,
        ).revision_id
        approval = MerchantApprovalRepository(repository).record_approval(
            document_revision_id=revision, approver_role="PARTNER", approval_status="APPROVED",
        ).approval_id
        ready(5)
        move(5, "IN_PROGRESS")

        text = (f"Đánh dấu bước 5 của Project {title} của Merchant {short} Cinemas "
                "là hoàn thành trên database test")
        result = json.loads(json.dumps(ask(repository, text), default=str))
        assert result["outcome"] == "READY_FOR_CONFIRMATION", result["blocking"]
        assert result["gate"]["all_met"] is True
        payload = payload_of(result["requested_operation"]["argv"])
        yield SimpleFixture(repository, project_id, revision, approval, payload)
    finally:
        delete_all(repository, (merchant_id,))
        with repository.connection(read_only=True) as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM merchant_ops.merchants WHERE code LIKE %s",
                (PREFIX + "%",),
            ).fetchone()["n"] == 0


class SimpleFixture:
    def __init__(self, repository, project_id, revision, approval, payload):
        self.repository, self.project_id = repository, project_id
        self.revision, self.approval, self.payload = revision, approval, payload


def step(repository, project_id, sequence):
    with repository.connection(read_only=True) as connection:
        return connection.execute(
            "SELECT id::text, status, version FROM merchant_ops.project_steps "
            "WHERE project_id = %s AND sequence_number = %s", (project_id, sequence),
        ).fetchone()


def facts(fixture):
    with fixture.repository.connection(read_only=True) as connection:
        events = connection.execute(
            # Confirmed transitions only; dependency promotions to READY are their consequence.
            "SELECT count(*) AS n FROM merchant_ops.project_events "
            "WHERE project_id = %s AND entity_type = 'STEP' "
            "AND NOT (new_values ? 'promoted_after_step_id')", (fixture.project_id,),
        ).fetchone()["n"]
        approval = connection.execute(
            "SELECT approval_status FROM merchant_ops.document_approvals WHERE id = %s",
            (fixture.approval,),
        ).fetchone()["approval_status"]
    return step(fixture.repository, fixture.project_id, 5)["status"], events, approval


def apply(fixture):
    adapters = MerchantRepositoryWriteAdapters(
        MerchantWriteRepositories.from_repository(fixture.repository)
    )
    return adapters.update_step(dict(fixture.payload))


def in_thread(target):
    box = {"done": threading.Event()}

    def run():
        try:
            box["result"] = target()
        except Exception as error:  # noqa: BLE001 - asserted by the caller
            box["error"] = error
        finally:
            box["done"].set()

    thread = threading.Thread(target=run)
    thread.start()
    box["thread"] = thread
    return box


def pause_after_recheck(monkeypatch, reached, release):
    """The confirmed write stops right after its in-transaction re-check."""

    real = write_adapters._confirmed_step_precondition

    def wrapped(steps, payload):
        check = real(steps, payload)

        def paused(connection):
            check(connection)
            reached.set()
            assert release.wait(30)

        return paused

    monkeypatch.setattr(write_adapters, "_confirmed_step_precondition", wrapped)


def supersede(fixture):
    """A new CONTRACT revision: the PARTNER approval no longer covers the latest one.

    (An APPROVED decision itself is final: ApprovalFinalizedError.)
    """

    return MerchantDocumentRepository(fixture.repository).create_revision(
        project_id=fixture.project_id, document_type="CONTRACT", content_hash="c" * 64,
    )


def revisions(fixture):
    with fixture.repository.connection(read_only=True) as connection:
        return connection.execute(
            "SELECT count(*) AS n FROM merchant_ops.document_revisions WHERE project_id = %s",
            (fixture.project_id,),
        ).fetchone()["n"]


def raw(fixture, statement, *parameters):
    with fixture.repository.connection() as connection, connection.transaction():
        connection.execute(statement, parameters)


# ------------------------------------------------------------------ tests


def test_repository_writer_after_the_recheck_is_serialized_behind_the_commit(gated, monkeypatch):
    reached, release = threading.Event(), threading.Event()
    pause_after_recheck(monkeypatch, reached, release)
    before = facts(gated)

    update = in_thread(lambda: apply(gated))
    assert reached.wait(30)
    writer = in_thread(lambda: supersede(gated))

    assert not writer["done"].wait(WAIT)        # blocked on the Project lock
    release.set()
    update["thread"].join(30)
    writer["thread"].join(30)

    assert "error" not in update and "error" not in writer, (update, writer)
    # Serial order: the approved transition committed, then the new revision.
    assert facts(gated) == ("COMPLETED", before[1] + 1, "APPROVED")
    assert revisions(gated) == 2


def test_repository_writer_holding_the_project_lock_first_invalidates_the_confirmation(
    gated, monkeypatch
):
    locked, release = threading.Event(), threading.Event()
    real = document_repository.MerchantDocumentRepository._lock_revisions

    def hold(cursor, project_id):
        locked.set()                              # the Project row is locked here
        assert release.wait(30)
        return real(cursor, project_id)

    monkeypatch.setattr(document_repository.MerchantDocumentRepository,
                        "_lock_revisions", staticmethod(hold))
    before = facts(gated)

    writer = in_thread(lambda: supersede(gated))
    assert locked.wait(30)
    update = in_thread(lambda: apply(gated))
    assert not update["done"].wait(WAIT)        # waits for the Project lock
    release.set()
    writer["thread"].join(30)
    update["thread"].join(30)

    assert "error" not in writer, writer
    assert isinstance(update.get("error"), StepPreviewMismatch), update
    assert update["error"].reason == "STEP_NOT_READY"   # the gate is re-judged first
    assert facts(gated) == before                       # nothing written
    assert revisions(gated) == 2


def test_raw_rejection_before_the_gate_read_is_refused_by_the_gate(gated, monkeypatch):
    reached, release = threading.Event(), threading.Event()
    pause_after_recheck(monkeypatch, reached, release)
    before = facts(gated)

    update = in_thread(lambda: apply(gated))
    assert reached.wait(30)
    # CP12H.MASTER (migration 010): a recorded decision is immutable, so a raw
    # APPROVED -> REJECTED flip is refused by the database itself; the
    # bypassing change used here is the owner-only removal of the approval.
    try:
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            raw(gated, "UPDATE merchant_ops.document_approvals SET approval_status = 'REJECTED' "
                       "WHERE id = %s", gated.approval)
        raw(gated, "DELETE FROM merchant_ops.document_approvals WHERE id = %s",
            gated.approval)                          # bypasses every repository lock
    finally:
        release.set()
    update["thread"].join(30)

    assert isinstance(update.get("error"), WorkflowGateNotMetError), update
    assert step(gated.repository, gated.project_id, 5)["status"] == before[0]


@pytest.mark.parametrize("kind", ["update-approval", "new-revision", "delete-approval"])
def test_raw_change_after_the_gate_read_waits_for_the_commit(gated, monkeypatch, kind):
    gate_read, release = threading.Event(), threading.Event()
    real = transition_repository.resolve_database_gate

    def hold(**kwargs):
        result = real(**kwargs)
        gate_read.set()
        assert release.wait(30)
        return result

    monkeypatch.setattr(transition_repository, "resolve_database_gate", hold)
    before = facts(gated)
    statement = {
        "update-approval": ("UPDATE merchant_ops.document_approvals SET approval_status = "
                            "'REJECTED' WHERE id = %s", gated.approval),
        "new-revision": ("INSERT INTO merchant_ops.document_revisions (id, project_id, "
                         "document_type, revision_number, content_hash, signed, created_at) "
                         "VALUES (gen_random_uuid(), %s, 'CONTRACT', 2, %s, FALSE, now())",
                         gated.project_id, "b" * 64),
        "delete-approval": ("DELETE FROM merchant_ops.document_approvals WHERE id = %s",
                            gated.approval),
    }[kind]

    update = in_thread(lambda: apply(gated))
    assert gate_read.wait(30)
    writer = in_thread(lambda: raw(gated, *statement))

    assert not writer["done"].wait(WAIT)        # held by the gate's row locks
    release.set()
    update["thread"].join(30)
    writer["thread"].join(30)

    if kind == "update-approval":
        # CP12H.MASTER (migration 010): the database refuses changing a
        # recorded decision at all; the Step Update committed against what it read.
        assert isinstance(writer.get("error"), psycopg.errors.IntegrityConstraintViolation), writer
        writer.pop("error")
    assert "error" not in update and "error" not in writer, (update, writer)
    status, events, _ = facts(gated) if kind != "delete-approval" else (
        step(gated.repository, gated.project_id, 5)["status"], before[1] + 1, None)
    assert (status, events) == ("COMPLETED", before[1] + 1)  # committed against what it read
