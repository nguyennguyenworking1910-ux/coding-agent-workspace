"""CP12H.NL3A on the Merchant test database: the exact live request, read-only.

Resolves against the real live-acceptance Merchant (NL2_LIVE_BETA, "Beta
Cinemas") and proves the preview changes nothing in any table.
"""

from __future__ import annotations

import os

import pytest

from claude.agents.tools.merchant.read_commands import MerchantReadCommands
from claude.clients.merchant.read_repository import MerchantReadRepository
from claude.clients.merchant.repository import MerchantRepository
from tests.merchant.test_nl1_project_preview_postgres import snapshot
from tests.merchant.test_nl3a_natural_language import LIVE_NL3

LIVE_NL3_PROJECT = "ba5cc7ec-bd78-5582-84e2-46b16037444c"

pytestmark = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME") != "coding_agent_merchant_test"
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database is not configured",
)


def test_exact_live_request_previews_ready_and_mutates_nothing():
    repository = MerchantRepository(role="test")
    assert repository.config.database == "coding_agent_merchant_test"
    reads = MerchantReadRepository(repository)
    if not any(m["code"] == "NL2_LIVE_BETA" for m in reads.list_merchants()):
        pytest.skip("live acceptance Merchant NL2_LIVE_BETA is not present")

    before = snapshot(repository)
    result = MerchantReadCommands(reads).project_preview(
        request=LIVE_NL3, database_target="test"
    )

    assert snapshot(repository) == before
    # The request is understood the same way either way.
    assert result["merchant"]["code"] == "NL2_LIVE_BETA"
    assert result["fields"]["title"] == "Beta NL3 Confirmation Test"
    assert result["fields"]["requires_procurement"] is False

    if LIVE_NL3_PROJECT not in {str(p["id"]) for p in reads.list_projects()}:
        assert result["outcome"] == "READY_FOR_CONFIRMATION", result["clarifications"]
        op = result["requested_operation"]
        assert op["merchant_code"] == "NL2_LIVE_BETA"
        assert op["title"] == "Beta NL3 Confirmation Test"
        assert op["requires_procurement"] is False
        assert op["status"] == "NOT_AUTHORIZED"
        steps = {s["sequence"]: s["initial_status"] for s in result["initial_steps"]}
        assert steps[6] == steps[7] == "SKIPPED"
        assert steps[10] == steps[11] == "PENDING"
    else:
        # The NL3 live acceptance created this Project (2026-11-04): the same
        # request must now be refused as a duplicate and offer no operation.
        assert result["outcome"] == "BLOCKED"
        assert result["requested_operation"] is None
        (conflict,) = result["conflicts"]
        assert conflict["kind"] == "POSSIBLE_DUPLICATE_PROJECT"
        assert conflict["project_id"] == LIVE_NL3_PROJECT
