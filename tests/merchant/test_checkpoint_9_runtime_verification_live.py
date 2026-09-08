"""Opt-in read-only proof of the initialized Merchant runtime."""

from __future__ import annotations

import json
import os

import pytest

from claude.agents.tools.merchant.catalog_contract import (
    load_private_catalog,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
)
from claude.clients.merchant.runtime_verification import (
    EXPECTED_STATUS_COUNTS,
    verify_initialized_runtime,
)


LIVE_VERIFICATION_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_VERIFICATION",
        "",
    ).strip()
    == "1"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_VERIFICATION_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_VERIFICATION=1 for the "
        "read-only initialized-runtime proof"
    ),
)
def test_checkpoint_9_initialized_runtime_is_compatible():
    source_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SOURCE_SHA256"
    )
    catalog_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SHA256"
    )
    catalog = load_private_catalog(
        _required_environment("MERCHANT_PRIVATE_CATALOG_PATH")
    )
    repository = MerchantRepository(
        RepositoryConfig.from_env("app")
    )
    report = verify_initialized_runtime(
        repository,
        catalog,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
    )

    print(json.dumps(report.safe_summary(), indent=2))
    assert report.success, (
        "Initialized runtime verification failed: "
        + ", ".join(report.failed_checks)
    )
    assert report.record_count == 22
    assert dict(report.status_counts) == EXPECTED_STATUS_COUNTS
    assert report.ordinary_reads == {
        "all_merchants": 22,
        "onboarding_merchants": 22,
        "active_merchants": 0,
        "projects": 0,
        "alerts": 0,
    }
    assert report.workflow_preconditions[
        "runtime_projects_created"
    ] == 0


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()

    if not value:
        raise AssertionError(f"Missing required environment: {name}")

    return value
