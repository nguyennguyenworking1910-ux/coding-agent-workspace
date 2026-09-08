"""Opt-in read-only Checkpoint 9 runtime readiness proof."""

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
from claude.clients.merchant.runtime_readiness import (
    RUNTIME_MIGRATIONS_READY,
    check_runtime_readiness,
    inspect_runtime_backup,
)


LIVE_READINESS_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_READINESS",
        "",
    ).strip()
    == "1"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_READINESS_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_READINESS=1 for the "
        "read-only runtime readiness proof"
    ),
)
def test_checkpoint_9_runtime_is_ready_for_migrations_2_and_3():
    private_catalog_path = _required_environment(
        "MERCHANT_PRIVATE_CATALOG_PATH"
    )
    expected_source_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SOURCE_SHA256"
    )
    expected_catalog_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SHA256"
    )
    backup_path = _required_environment(
        "MERCHANT_RUNTIME_BACKUP_FILE"
    )

    catalog = load_private_catalog(private_catalog_path)
    assert catalog.source_sha256 == expected_source_hash
    assert catalog.catalog_sha256 == expected_catalog_hash

    backup = inspect_runtime_backup(
        backup_path,
        restore_list_verified=_required_flag(
            "MERCHANT_RUNTIME_BACKUP_LIST_VERIFIED"
        ),
        recovery_procedure_reviewed=_required_flag(
            "MERCHANT_RUNTIME_RECOVERY_REVIEWED"
        ),
        roles_recoverable=_required_flag(
            "MERCHANT_RUNTIME_ROLES_RECOVERABLE"
        ),
    )
    repository = MerchantRepository(
        RepositoryConfig.from_env("app")
    )
    report = check_runtime_readiness(
        repository,
        expected_source_sha256=expected_source_hash,
        expected_catalog_sha256=expected_catalog_hash,
        backup_evidence=backup,
    )

    print(json.dumps(report.safe_summary(), indent=2))
    assert report.success, (
        "Runtime readiness failed: "
        + ", ".join(report.failed_checks)
    )
    assert report.state == RUNTIME_MIGRATIONS_READY
    assert report.applied_versions == (1,)
    assert report.pending_versions == (2, 3)
    assert report.stored_template_count == 0


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()

    if not value:
        raise AssertionError(f"Missing required environment: {name}")

    return value


def _required_flag(name: str) -> bool:
    value = _required_environment(name)

    if value != "1":
        raise AssertionError(f"{name} must be exactly 1")

    return True
