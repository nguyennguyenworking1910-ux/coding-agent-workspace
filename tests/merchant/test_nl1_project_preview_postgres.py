"""CP12H.NL1: Project preview against the real Merchant test database.

Fixture rows (a pytest-coded Beta Merchant and, for the duplicate case, one
Project created through the real workflow repository) are inserted and
removed around each test. The preview itself must leave every table
byte-identical.
"""

from __future__ import annotations

import os
import uuid

import pytest

from claude.agents.tools.merchant.project_preview import (
    BLOCKED,
    NEEDS_CLARIFICATION,
    READY,
    build_project_preview,
)
from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.agents.tools.merchant.workflow_templates import (
    get_standard_workflow_template,
)
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository


pytestmark = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME")
    != "coding_agent_merchant_test"
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database is not configured",
)

CODE_PREFIX = "PYTEST_NL1_"
# A unique Merchant word keeps these tests independent of other "Beta" rows
# (for example a live-validation fixture).
SHORT = f"Nlbeta{uuid.uuid4().hex[:6]}"
REQUEST = f"Tạo project mở rạp {SHORT} Nguyễn Văn Cừ. Không cần mua sắm."
TABLES = (
    "merchants", "projects", "project_steps", "project_step_dependencies",
    "project_events", "merchant_execution_claims", "merchant_execution_ledger",
    "workflow_templates",
)


def _delete_fixtures(repository, merchant_ids):
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM merchant_ops.merchants WHERE code LIKE %s",
                    (CODE_PREFIX + "%",),
                )
                ids = {row["id"] for row in cursor.fetchall()} | set(merchant_ids)
                for merchant_id in ids:
                    cursor.execute(
                        "DELETE FROM merchant_ops.project_step_dependencies d "
                        "USING merchant_ops.project_steps s, merchant_ops.projects p "
                        "WHERE d.from_step_id = s.id AND s.project_id = p.id "
                        "AND p.merchant_id = %s",
                        (merchant_id,),
                    )
                    cursor.execute(
                        "DELETE FROM merchant_ops.project_steps s "
                        "USING merchant_ops.projects p "
                        "WHERE s.project_id = p.id AND p.merchant_id = %s",
                        (merchant_id,),
                    )
                    for table in ("project_events", "projects", "merchants"):
                        column = "id" if table == "merchants" else "merchant_id"
                        cursor.execute(
                            f"DELETE FROM merchant_ops.{table} WHERE {column} = %s",
                            (merchant_id,),
                        )


@pytest.fixture
def beta():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    merchant_id = uuid.uuid4()
    _delete_fixtures(repository, ())

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO merchant_ops.merchants "
                    "(id, code, name, account_status) VALUES (%s, %s, %s, 'ACTIVE')",
                    (
                        merchant_id,
                        f"{CODE_PREFIX}{uuid.uuid4().hex[:8].upper()}",
                        f"{SHORT} Cinemas",
                    ),
                )

    yield repository, str(merchant_id)

    _delete_fixtures(repository, (merchant_id,))


def snapshot(repository):
    with repository.connection(read_only=True) as connection:
        with connection.cursor() as cursor:
            out = {}
            for table in TABLES:
                cursor.execute(
                    "SELECT count(*) AS n, coalesce(md5(string_agg(x::text, '|' "
                    f"ORDER BY x::text)), '') AS h FROM merchant_ops.{table} x"
                )
                out[table] = dict(cursor.fetchone())
            return out


def test_real_preview_resolves_beta_and_mutates_nothing(beta):
    repository, merchant_id = beta
    reads = MerchantReadRepository(repository)
    before = snapshot(repository)

    preview = MerchantReadCommands(reads).project_preview(request=REQUEST)

    assert snapshot(repository) == before
    assert preview["outcome"] == READY, preview["clarifications"]
    assert preview["merchant"]["merchant_id"] == merchant_id
    assert preview["fields"]["title"] == f"{SHORT} Nguyễn Văn Cừ"
    assert preview["project"]["template"]["installed"] is True
    assert preview["initial_steps"][0]["name"] == "Draft or renew document"
    assert preview["executable"] is False
    assert preview["authorization"] is None


def test_real_duplicate_project_blocks(beta):
    repository, merchant_id = beta
    MerchantWorkflowRepository(repository).create_project(
        merchant_id=merchant_id,
        template=get_standard_workflow_template("OPENING_NEW_CINEMA_STANDARD"),
        requires_procurement=False,
        title=f"Mở rạp {SHORT} Nguyễn Văn Cừ",
    )
    reads = MerchantReadRepository(repository)
    before = snapshot(repository)

    preview = build_project_preview(REQUEST, reads)

    assert snapshot(repository) == before
    assert preview["outcome"] == BLOCKED
    assert preview["conflicts"][0]["kind"] == "POSSIBLE_DUPLICATE_PROJECT"
    assert preview["requested_operation"] is None


def test_real_stale_merchant_candidate_is_rejected(beta):
    repository, _ = beta

    preview = build_project_preview(
        REQUEST,
        MerchantReadRepository(repository),
        merchant_hint=str(uuid.uuid4()),
    )

    assert preview["outcome"] == NEEDS_CLARIFICATION
    assert preview["merchant"] is None
