"""CP12H.NL4D2 on the Merchant test database: evidence discovery is read-only and exact.

A throwaway ``PYTEST_NL4D2_`` Project gets real evidence through the domain
repositories: revision 1 with a PARTNER approval, then revision 2 (which
supersedes it) with a LEGAL approval. The CLI read must report exactly what
``resolve_database_gate`` decides on the stored rows, never count the
historical PARTNER approval for revision 2, and change nothing: no row, no
claim, no ledger entry, no pending confirmation. Must run alone.
"""

from __future__ import annotations

import json
import uuid

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant.agent_cli import prepare_agent_cli_argv
from claude.agents.tools.merchant.gate_resolver import resolve_database_gate
from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.clients.merchant.approval_repository import MerchantApprovalRepository
from claude.clients.merchant.document_repository import MerchantDocumentRepository
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.transition_repository import MerchantStepTransitionRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from tests.merchant.test_nl1_project_preview_postgres import _delete_fixtures
from tests.merchant.test_nl4c1_step_confirmation_postgres import pytestmark  # noqa: F401

PREFIX = "PYTEST_NL4D2_"
SHORT = f"Nlev{uuid.uuid4().hex[:6]}"
TITLE = f"{SHORT} Nguyễn Văn Cừ Evidence"


def delete_all(repository, merchant_ids=()):
    scope = (" merchant_ops.projects p, merchant_ops.merchants m"
             " WHERE d.project_id = p.id AND p.merchant_id = m.id AND m.code LIKE %s")
    with repository.connection() as connection, connection.transaction():
        connection.execute(
            "DELETE FROM merchant_ops.document_approvals a USING merchant_ops.document_revisions d,"
            + scope + " AND a.document_revision_id = d.id", (PREFIX + "%",))
        connection.execute("UPDATE merchant_ops.document_revisions d SET superseded_by = NULL FROM"
                           + scope, (PREFIX + "%",))
        connection.execute("DELETE FROM merchant_ops.document_revisions d USING" + scope,
                           (PREFIX + "%",))
    _delete_fixtures(repository, merchant_ids, PREFIX)


def counts(repository):
    """Every table the read could touch, with a content digest."""

    with repository.connection(read_only=True) as connection:
        out = {}
        for table in ("projects", "project_steps", "project_events", "document_revisions",
                      "document_approvals", "procurement_records",
                      "merchant_execution_claims", "merchant_execution_ledger"):
            out[table] = dict(connection.execute(
                "SELECT count(*) AS n, coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '')"
                f" AS h FROM merchant_ops.{table} x").fetchone())
        return out


@pytest.fixture
def evidence():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    delete_all(repository)
    merchant_id = uuid.uuid4()
    with repository.connection() as connection, connection.transaction():
        connection.execute(
            "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
            "VALUES (%s, %s, %s, 'ACTIVE')",
            (merchant_id, f"{PREFIX}{uuid.uuid4().hex[:8].upper()}", f"{SHORT} Cinemas"),
        )
    try:
        project_id = str(MerchantWorkflowRepository(repository).create_project(
            merchant_id=str(merchant_id),
            template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
            requires_procurement=False, title=TITLE,
        ).project_id)
        steps = MerchantStepTransitionRepository(repository)

        def row(sequence):
            with repository.connection(read_only=True) as connection:
                return connection.execute(
                    "SELECT id::text, status, version FROM merchant_ops.project_steps "
                    "WHERE project_id = %s AND sequence_number = %s", (project_id, sequence),
                ).fetchone()

        for sequence in (1, 2, 3, 4):
            for target in (("READY",) if row(sequence)["status"] == "PENDING" else ()) + (
                    "IN_PROGRESS", "COMPLETED"):
                current = row(sequence)
                steps.transition_step(step_id=current["id"], target_status=target,
                                      expected_version=current["version"])
        documents = MerchantDocumentRepository(repository)
        approvals = MerchantApprovalRepository(repository)
        first = documents.create_revision(project_id=project_id, document_type="CONTRACT",
                                          content_hash="a" * 64).revision_id
        approvals.record_approval(document_revision_id=first, approver_role="PARTNER",
                                  approval_status="APPROVED")
        second = documents.create_revision(project_id=project_id, document_type="CONTRACT",
                                           content_hash="b" * 64).revision_id
        approvals.record_approval(document_revision_id=second, approver_role="LEGAL",
                                  approval_status="APPROVED")
        yield repository, project_id, first, second
    finally:
        delete_all(repository, (merchant_id,))
        with repository.connection(read_only=True) as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM merchant_ops.merchants WHERE code LIKE %s",
                (PREFIX + "%",),
            ).fetchone()["n"] == 0


def read(repository, text):
    """The exact CLI read the teammate runs: agent_cli argv, then the read dispatcher."""

    argv = prepare_agent_cli_argv(["project", "evidence", "--request", text, "--test-database"])
    args = merchant_cli.build_argument_parser().parse_args(list(argv))
    assert args.database == "test"
    result = merchant_cli.dispatch_read_command(
        args, MerchantReadCommands(MerchantReadRepository(repository)))
    return json.loads(json.dumps(result, default=str))


def test_discovery_matches_the_domain_on_stored_rows_and_writes_nothing(evidence):
    repository, project_id, first, second = evidence
    before = counts(repository)

    result = read(repository, f"Project {TITLE} còn thiếu phê duyệt nào trên database test?")

    assert counts(repository) == before                       # nothing written anywhere
    assert result["outcome"] == "EVIDENCE_STATUS" and result["project"]["project_id"] == project_id
    assert result["read_only"] is True and result["authorization"] is None
    assert "a" * 64 not in json.dumps(result) and "b" * 64 not in json.dumps(result)

    detail = MerchantReadRepository(repository).get_project_detail(project_id)
    for step in detail["steps"]:
        if step["sequence_number"] in (5, 8):
            expected = resolve_database_gate(
                step=step, project=detail["project"], revisions=detail["document_revisions"],
                approvals=detail["document_approvals"],
                procurement_records=detail["procurement_records"],
            ).to_dict()
            reported = next(g for g in result["gates"] if g["sequence"] == step["sequence_number"])
            assert reported["evaluation"] == json.loads(json.dumps(expected, default=str))

    roles = {a["role"]: a for a in result["approvals"]}
    assert (roles["LEGAL"]["status"], roles["LEGAL"]["document_revision_id"]) == ("PRESENT", second)
    assert roles["PARTNER"]["status"] == "MISSING"            # revision 1's approval never counts
    assert roles["ACCOUNTING"]["status"] == "MISSING"
    (outdated,) = result["outdated_approvals"]
    assert (outdated["role"], outdated["document_revision_id"], outdated["status"]) == (
        "PARTNER", first, "INVALID")
    (document,) = result["documents"]
    assert [(r["revision_id"], r["status"]) for r in document["revisions"]] == [
        (first, "INVALID"), (second, "PRESENT")]


def test_a_step_question_reports_its_gate_and_dependencies(evidence):
    repository, project_id, _, second = evidence
    before = counts(repository)

    result = read(repository, f"Bước Partner Approval của Project {TITLE} còn thiếu gì trên database test?")

    assert counts(repository) == before
    focus = result["focus_step"]
    assert (focus["sequence"], focus["match_kind"]) == (5, "PARTIAL_UNIQUE")
    assert focus["gate"]["evaluation"]["missing_roles"] == ["PARTNER"]
    assert focus["gate"]["evaluation"]["document_revision_id"] == second
    assert focus["unmet_direct_dependencies"] == []           # 4 is COMPLETED


def test_an_unknown_project_asks_and_reads_nothing_more(evidence):
    repository, _, _, _ = evidence

    result = read(repository, "Project này còn thiếu giấy tờ gì trên database test?")

    assert result["outcome"] == "NEEDS_CLARIFICATION" and result["gates"] == []
