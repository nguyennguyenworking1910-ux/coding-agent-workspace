"""CP12H.NL4C2B-FIX on the Merchant test database: the live phrasings resolve.

A throwaway ``PYTEST_NL4C2BF_`` Merchant gets a Project titled like the live
acceptance Project ("<short> NL4C2B Step Acceptance"), through the real
workflow repository. The read-only ``step preview`` of each live phrasing must
bind the persisted step 1 and be READY; nothing is written. The live
acceptance Project itself is never read or touched here. Must run alone.
"""

from __future__ import annotations

import json
import uuid

import pytest

from claude.agents.tools.merchant.workflow_templates import get_standard_workflow_template
from claude.clients.merchant.repository import MerchantRepository
from claude.clients.merchant.workflow_repository import MerchantWorkflowRepository
from tests.merchant.test_nl1_project_preview_postgres import _delete_fixtures, snapshot
from tests.merchant.test_nl4b_step_preview_postgres import ask
from tests.merchant.test_nl4c1_step_confirmation_postgres import pytestmark  # noqa: F401

PREFIX = "PYTEST_NL4C2BF_"
SHORT = f"Nlfix{uuid.uuid4().hex[:6]}"
TITLE = f"{SHORT} NL4C2B Step Acceptance"


@pytest.fixture
def acceptance_like():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    _delete_fixtures(repository, (), PREFIX)
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
        with repository.connection(read_only=True) as connection:
            step_1 = connection.execute(
                "SELECT id::text FROM merchant_ops.project_steps "
                "WHERE project_id = %s AND sequence_number = 1", (project_id,),
            ).fetchone()["id"]
        yield repository, project_id, step_1
    finally:
        _delete_fixtures(repository, (merchant_id,), PREFIX)
        with repository.connection(read_only=True) as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM merchant_ops.merchants WHERE code LIKE %s",
                (PREFIX + "%",),
            ).fetchone()["n"] == 0


@pytest.mark.parametrize("text", [
    f"Cập nhật bước 1 của Project {TITLE} thành đang thực hiện trên database test",
    f'Cập nhật bước "Draft or renew document" của Project {TITLE} thành đang thực hiện '
    "trên database test",
    f"Bắt đầu bước 1 của Project {TITLE} của Merchant {SHORT} Cinemas trên database test",
    f"Mark Step 01 of Project {TITLE} as in progress on the test database",
])
def test_live_phrasings_bind_the_persisted_step_read_only(acceptance_like, text):
    repository, project_id, step_1 = acceptance_like
    before = snapshot(repository)

    result = json.loads(json.dumps(ask(repository, text), default=str))

    assert snapshot(repository) == before                       # read-only
    assert result["outcome"] == "READY_FOR_CONFIRMATION", (result["missing"], result["blocking"])
    assert result["project"]["project_id"] == project_id
    operation = result["requested_operation"]
    assert (operation["step_id"], operation["step_sequence"]) == (step_1, 1)
    assert (operation["current_status"], operation["target_status"]) == ("READY", "IN_PROGRESS")
    assert operation["status"] == "NOT_AUTHORIZED" and operation["database_target"] == "test"


def test_an_invalid_step_number_binds_nothing(acceptance_like):
    repository, _, _ = acceptance_like
    result = ask(repository, f"Cập nhật bước 99 của Project {TITLE} thành đang thực hiện "
                             "trên database test")

    assert result["outcome"] == "NEEDS_CLARIFICATION" and "step" in result["missing"]
    assert result["requested_operation"] is None
