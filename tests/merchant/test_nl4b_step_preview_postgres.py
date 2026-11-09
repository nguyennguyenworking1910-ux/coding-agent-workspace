"""CP12H.NL4B on the Merchant test database, through the real CLI read path.

Disposable ``PYTEST_NL4B_`` Merchants and Projects are created through the real
workflow repository and removed after each test. Every preview must leave
every table byte-identical: a READY_FOR_CONFIRMATION preview writes,
reserves and claims nothing. The live acceptance Projects are never touched.
"""

from __future__ import annotations

import os
import uuid

import pytest

from claude.agents.tools.merchant import cli as merchant_cli
from claude.agents.tools.merchant.agent_cli import prepare_agent_cli_argv
from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from tests.merchant.test_nl1_project_preview_postgres import _delete_fixtures, snapshot

pytestmark = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME") != "coding_agent_merchant_test"
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database is not configured",
)

PREFIX = "PYTEST_NL4B_"
SHORT = f"Nlstep{uuid.uuid4().hex[:6]}"
OTHER = f"Nlstepo{uuid.uuid4().hex[:6]}"
FRESH = f"{SHORT} Nguyễn Văn Cừ"
STARTED = f"{SHORT} Đà Nẵng"
OF_FRESH = f"Project {FRESH} của Merchant {SHORT} Cinemas"
OF_STARTED = f"Project {STARTED}"


def ask(repository, request):
    argv = prepare_agent_cli_argv(["step", "preview", "--request", request, "--test-database"])
    args = merchant_cli.build_argument_parser().parse_args(list(argv))
    assert args.database == "test"
    return merchant_cli.dispatch_read_command(
        args, MerchantReadCommands(MerchantReadRepository(repository))
    )


def codes(result):
    return [b["code"] for b in result["blocking"]]


def _insert_merchant(cursor, name):
    merchant_id = uuid.uuid4()
    cursor.execute(
        "INSERT INTO merchant_ops.merchants (id, code, name, account_status) "
        "VALUES (%s, %s, %s, 'ACTIVE')",
        (merchant_id, f"{PREFIX}{uuid.uuid4().hex[:8].upper()}", name),
    )
    return str(merchant_id)


@pytest.fixture
def fixtures():
    """FRESH (as created) and STARTED (1-4 done, gate 5 in progress); FRESH's title again elsewhere."""

    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    _delete_fixtures(repository, (), PREFIX)
    with repository.connection() as connection, connection.transaction(), connection.cursor() as cursor:
        merchant_id = _insert_merchant(cursor, f"{SHORT} Cinemas")
        other_id = _insert_merchant(cursor, f"{OTHER} Cinemas")

    workflow = MerchantWorkflowRepository(repository)
    template = get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD")
    ids = {}
    for key, owner, title in (
        ("fresh", merchant_id, FRESH), ("started", merchant_id, STARTED), ("other", other_id, FRESH),
    ):
        created = workflow.create_project(
            merchant_id=owner, template=template, requires_procurement=False, title=title
        )
        ids[key] = str(created.project_id)

    with repository.connection() as connection, connection.transaction(), connection.cursor() as cursor:
        for sequence, state in ((1, "COMPLETED"), (2, "COMPLETED"), (3, "COMPLETED"),
                                (4, "COMPLETED"), (5, "IN_PROGRESS")):
            cursor.execute(
                "UPDATE merchant_ops.project_steps SET status = %s, actual_start = now(), "
                "actual_completion = CASE WHEN %s = 'COMPLETED' THEN now() END "
                "WHERE project_id = %s AND sequence_number = %s",
                (state, state, ids["started"], sequence),
            )

    try:
        before = snapshot(repository)
        yield repository, ids
        assert snapshot(repository) == before  # no preview changed anything
    finally:
        _delete_fixtures(repository, (merchant_id, other_id), PREFIX)
        with repository.connection(read_only=True) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS n FROM merchant_ops.merchants WHERE code LIKE %s",
                (PREFIX + "%",),
            )
            assert cursor.fetchone()["n"] == 0


def test_eligible_update_is_ready_and_writes_nothing(fixtures):
    repository, ids = fixtures

    result = ask(repository, f"Bắt đầu bước 1 của {OF_FRESH} trên database test")

    assert result["outcome"] == "READY_FOR_CONFIRMATION", result["blocking"]
    assert result["database_target"] == "test"
    assert result["project"]["project_id"] == ids["fresh"]
    assert result["project"]["title"] == FRESH and result["project"]["version"] >= 1
    assert result["step"]["name"] == "Draft or renew document" and result["step"]["version"] == 1
    assert result["transition"]["expected_version"] == 1 and result["transition"]["new_version"] == 2
    # CP12H.NL4C (intentional change): confirmable by the user, not authorized.
    assert result["executable"] is False and result["confirmation_available"] is True
    assert result["authorization"] is None


def test_english_named_step_with_unmet_dependencies_is_blocked(fixtures):
    repository, _ = fixtures

    result = ask(repository, f"Mark the Send reviewed revision to Partner step of project {FRESH} "
                             f"of {SHORT} Cinemas as ready")

    assert result["outcome"] == "BLOCKED", result["clarifications"]
    assert codes(result) == ["UNMET_DEPENDENCIES"]
    assert [s["sequence"] for s in result["unmet_dependencies"]] == [2, 3]


def test_unsupported_transition_is_blocked(fixtures):
    repository, _ = fixtures

    result = ask(repository, f"Đánh dấu bước 1 của {OF_FRESH} là hoàn thành")  # READY -> COMPLETED
    assert result["outcome"] == "BLOCKED" and codes(result) == ["TRANSITION_NOT_ALLOWED"]


def test_partner_gate_without_stored_approval_is_blocked(fixtures):
    repository, ids = fixtures

    result = ask(repository, f"Đánh dấu bước Record Partner approval của {OF_STARTED} là hoàn thành")

    assert result["project"]["project_id"] == ids["started"]
    assert result["outcome"] == "BLOCKED" and codes(result) == ["GATE_NOT_MET"]
    assert result["gate"]["kind"] == "RECORD PARTNER APPROVAL"
    assert result["gate"]["blocking_codes"] == ["MISSING_DOCUMENT_REVISION"]


@pytest.mark.parametrize(
    "target,code",
    [("là hoàn thành", "TRANSITION_NOT_ALLOWED"), ("thành sẵn sàng", "REOPEN_NOT_PREVIEWED")],
)
def test_skipped_step_is_never_completed_or_reopened(fixtures, target, code):
    repository, _ = fixtures

    result = ask(repository, f"Cập nhật bước 6 của {OF_STARTED} {target}")
    assert result["step"]["status"] == "SKIPPED"
    assert result["outcome"] == "BLOCKED" and codes(result) == [code]


def test_same_title_under_two_merchants_asks(fixtures):
    repository, ids = fixtures

    result = ask(repository, f"Bắt đầu bước 1 của Project {FRESH}")

    assert result["outcome"] == "NEEDS_CLARIFICATION" and result["step"] is None
    assert {c["project_id"] for c in result["candidates"]} == {ids["fresh"], ids["other"]}


def test_partial_step_name_is_only_a_candidate(fixtures):
    repository, _ = fixtures

    result = ask(repository, f"Đánh dấu bước review của {OF_FRESH} là hoàn thành")

    assert result["outcome"] == "NEEDS_CLARIFICATION" and result["step"] is None
    assert {c["sequence"] for c in result["candidates"]} == {2, 3}
