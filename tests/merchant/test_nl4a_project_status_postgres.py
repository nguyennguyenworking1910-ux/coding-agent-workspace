"""CP12H.NL4A on the Merchant test database, through the real CLI read path.

General coverage uses disposable fixtures: two ``PYTEST_NL4A_`` Merchants and
three Projects created through the real workflow repository, removed after
each test. It runs on a clean, provisioned test database and on one holding
the live acceptance Projects, which it never touches.

``TestLiveAcceptance`` reads the real NL2 and NL3 acceptance Projects with the
exact live requests. It is read-only (whole-table snapshot asserted unchanged)
and skips when those Projects are absent.
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

PREFIX = "PYTEST_NL4A_"
# Unique words keep fixture names clear of every other Merchant and Project.
SHORT = f"Nlfour{uuid.uuid4().hex[:6]}"
OTHER = f"Nlother{uuid.uuid4().hex[:6]}"
FRESH = f"{SHORT} Nguyễn Văn Cừ"
STARTED = f"{SHORT} NL3 Confirmation Test"


def ask(repository, request):
    argv = prepare_agent_cli_argv(["project", "status", "--request", request, "--test-database"])
    args = merchant_cli.build_argument_parser().parse_args(list(argv))
    assert args.database == "test"
    return merchant_cli.dispatch_read_command(
        args, MerchantReadCommands(MerchantReadRepository(repository))
    )


def by_sequence(steps):
    return {s["sequence"]: s for s in steps}


def unmet(waiting, sequence):
    return [p["sequence"] for p in waiting[sequence]["unmet_predecessors"]]


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
    """Fresh and started Projects under one Merchant; FRESH's title again under another."""

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
        ("fresh", merchant_id, FRESH),
        ("started", merchant_id, STARTED),
        ("other", other_id, FRESH),
    ):
        created = workflow.create_project(
            merchant_id=owner, template=template, requires_procurement=False, title=title
        )
        ids[key] = str(created.project_id)

    # Progress STARTED as stored rows: 1 and 2 done, 3 in progress.
    with repository.connection() as connection, connection.transaction(), connection.cursor() as cursor:
        for sequence, state in ((1, "COMPLETED"), (2, "COMPLETED"), (3, "IN_PROGRESS")):
            cursor.execute(
                "UPDATE merchant_ops.project_steps SET status = %s, "
                "actual_completion = CASE WHEN %s = 'COMPLETED' THEN now() END "
                "WHERE project_id = %s AND sequence_number = %s",
                (state, state, ids["started"], sequence),
            )

    try:
        before = snapshot(repository)
        yield repository, ids
        assert snapshot(repository) == before  # every read changed nothing
    finally:
        _delete_fixtures(repository, (merchant_id, other_id), PREFIX)
        with repository.connection(read_only=True) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS n FROM merchant_ops.merchants WHERE code LIKE %s",
                (PREFIX + "%",),
            )
            assert cursor.fetchone()["n"] == 0  # nothing left behind


def test_fresh_project_graph_follows_the_stored_dependencies(fixtures):
    repository, ids = fixtures

    result = ask(repository, f"Project {FRESH} của Merchant {SHORT} Cinemas hiện tại đến bước nào?")

    assert result["outcome"] == "PROJECT_STATUS", result["clarifications"]
    assert result["project"]["project_id"] == ids["fresh"]
    assert result["step_counts"] == {
        "total": 22, "PENDING": 19, "READY": 1, "IN_PROGRESS": 0, "BLOCKED": 0,
        "COMPLETED": 0, "SKIPPED": 2, "SUPERSEDED": 0,
    }
    assert [s["sequence"] for s in result["current_steps"]] == [1]
    assert result["dependency_ready_steps"] == [] and result["completed_steps"] == []
    assert [s["sequence"] for s in result["skipped_steps"]] == [6, 7]
    waiting = by_sequence(result["waiting_steps"])
    assert 6 not in waiting and 7 not in waiting
    # Parallel reviews after 1, joined at 4 (listed in sequence order).
    assert unmet(waiting, 2) == unmet(waiting, 3) == [1]
    assert unmet(waiting, 4) == [2, 3]
    # No procurement: the signing gate waits on Partner approval only.
    assert unmet(waiting, 8) == [5]
    # Purchase Order and Payment Request stay required after signing.
    assert waiting[10]["name"] == "Create Purchase Order" and unmet(waiting, 10) == [9]
    assert waiting[11]["name"] == "Create Payment Request" and unmet(waiting, 11) == [10]
    # Production and UAT branch in parallel from the signature.
    assert unmet(waiting, 12) == unmet(waiting, 15) == [9]
    assert unmet(waiting, 22) == [11, 14, 21]
    assert result["read_only"] is True and result["authorization"] is None


def test_live_2_shape_reads_the_started_project_without_a_merchant(fixtures):
    repository, ids = fixtures

    result = ask(
        repository,
        f"Các bước đang chờ của Project {STARTED} trên database test là gì? "
        "Bước nào đang bị phụ thuộc vào bước khác?",
    )

    assert result["outcome"] == "PROJECT_STATUS", result["clarifications"]
    assert result["query"]["merchant_phrase"] is None
    assert result["project"]["project_id"] == ids["started"]
    assert result["merchant"]["match_kind"] == "FROM_PROJECT"
    assert [s["sequence"] for s in result["completed_steps"]] == [1, 2]
    assert [s["sequence"] for s in result["current_steps"]] == [3]
    waiting = by_sequence(result["waiting_steps"])
    assert unmet(waiting, 4) == [3]  # 2 is done; only the open review remains


def test_live_3_shape_lists_each_project_with_its_status(fixtures):
    repository, ids = fixtures

    result = ask(
        repository,
        f"Liệt kê tất cả Project của Merchant {SHORT} Cinemas trên database test "
        "và cho biết trạng thái từng Project",
    )

    assert result["outcome"] == "PROJECT_LIST", result["clarifications"]
    assert {p["project_id"]: p["status"] for p in result["projects"]} == {
        ids["fresh"]: "PLANNED", ids["started"]: "PLANNED",
    }


def test_same_title_under_two_merchants_returns_candidates(fixtures):
    repository, ids = fixtures

    result = ask(repository, f"Project {FRESH} đang ở bước nào?")

    assert result["outcome"] == "NEEDS_CLARIFICATION"
    assert result["project"] is None
    assert {c["project_id"] for c in result["candidates"]} == {ids["fresh"], ids["other"]}


def test_status_by_exact_project_id(fixtures):
    repository, ids = fixtures

    result = ask(repository, f"Which step is project {ids['started']} at?")

    assert result["project"]["project_id"] == ids["started"]
    assert result["project"]["match_kind"] == "UUID"


def test_missing_project_asks(fixtures):
    repository, _ = fixtures

    result = ask(repository, "Những bước nào đã hoàn thành và còn vướng ở đâu?")

    assert result["outcome"] == "NEEDS_CLARIFICATION"
    assert result["project"] is None


# ------------------------------------------------------------- live acceptance

NL2 = "30fffeaf-e6b5-5119-b078-52c934e1821e"
NL3 = "ba5cc7ec-bd78-5582-84e2-46b16037444c"


@pytest.fixture
def live():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    ids = {str(p["id"]) for p in MerchantReadRepository(repository).list_projects()}
    if not {NL2, NL3} <= ids:
        pytest.skip("live acceptance Projects are not present")
    before = snapshot(repository)
    yield repository
    assert snapshot(repository) == before


class TestLiveAcceptance:
    """The four live NL4A requests, read-only, against the accepted Projects."""

    def test_1_current_step(self, live):
        result = ask(live, "Project Beta Nguyễn Văn Cừ của Merchant Beta Cinemas hiện tại đến bước nào trên database test?")

        assert result["project"]["project_id"] == NL2
        assert [s["name"] for s in result["current_steps"]] == ["Draft or renew document"]

    def test_2_waiting_steps_without_a_merchant(self, live):
        result = ask(
            live,
            "Các bước đang chờ của Project Beta NL3 Confirmation Test trên database test là gì? "
            "Bước nào đang bị phụ thuộc vào bước khác?",
        )

        assert result["outcome"] == "PROJECT_STATUS", result["clarifications"]
        assert result["project"]["project_id"] == NL3
        assert result["merchant"]["code"] == "NL2_LIVE_BETA"
        assert unmet(by_sequence(result["waiting_steps"]), 4) == [2, 3]

    def test_3_list_with_status(self, live):
        result = ask(
            live,
            "Liệt kê tất cả Project của Merchant Beta Cinemas trên database test "
            "và cho biết trạng thái từng Project",
        )

        assert result["outcome"] == "PROJECT_LIST", result["clarifications"]
        assert {NL2, NL3} <= {p["project_id"] for p in result["projects"]}
        assert all(p["merchant_code"] == "NL2_LIVE_BETA" and p["status"] for p in result["projects"])

    def test_4_completed_and_stuck(self, live):
        result = ask(
            live,
            "Những bước nào đã hoàn thành và còn vướng ở đâu trong Project Beta Nguyễn Văn Cừ trên database test?",
        )

        assert result["project"]["project_id"] == NL2
        assert result["step_counts"]["COMPLETED"] == len(result["completed_steps"])
        assert [s["sequence"] for s in result["skipped_steps"]] == [6, 7]
