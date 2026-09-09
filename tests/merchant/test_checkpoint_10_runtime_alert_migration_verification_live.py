"""Opt-in read-only verification after runtime migration 4."""

from __future__ import annotations

import json
import os

import pytest

from claude.agents.tools.merchant.catalog_contract import (
    load_private_catalog,
)
from claude.clients.merchant import migrate
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
)
from claude.clients.merchant.runtime_alert_migration_verification import (
    verify_runtime_alert_migration,
)
from claude.clients.merchant.runtime_readiness import (
    inspect_runtime_backup,
)
from claude.clients.merchant.runtime_verification import (
    verify_initialized_runtime,
)
from claude.workers.merchant_alert_adapters import (
    InternalDeliveryAdapter,
)
from claude.workers.merchant_alert_contract import WorkerLimits
from claude.workers.merchant_alert_operations import (
    build_health_report,
)


LIVE_VERIFICATION_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_ALERT_MIGRATION_VERIFICATION",
        "",
    ).strip()
    == "1"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_VERIFICATION_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_ALERT_MIGRATION_VERIFICATION=1 "
        "for the read-only Gate 10.7B verification"
    ),
)
def test_checkpoint_10_runtime_alert_migration_is_exact():
    source_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SOURCE_SHA256"
    )
    catalog_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SHA256"
    )
    catalog = load_private_catalog(
        _required_environment("MERCHANT_PRIVATE_CATALOG_PATH")
    )
    app_repository = MerchantRepository(
        RepositoryConfig.from_env("app")
    )
    checkpoint9 = verify_initialized_runtime(
        app_repository,
        catalog,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
    )

    app_config = app_repository.config
    migration_status = migrate.get_status(
        app_config.host,
        app_config.port,
        app_config.database,
        app_config.user,
        app_config.password,
    )
    alert_repository = MerchantRepository(
        RepositoryConfig.from_env("alert")
    )
    alert_health = build_health_report(
        alert_repository,
        adapter=InternalDeliveryAdapter(),
        limits=WorkerLimits(),
    )
    backup = inspect_runtime_backup(
        _required_environment("MERCHANT_RUNTIME_BACKUP_FILE"),
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
    report = verify_runtime_alert_migration(
        checkpoint9,
        migration_status,
        alert_health,
        backup,
        expected_backup_sha256=_required_environment(
            "MERCHANT_EXPECTED_RUNTIME_BACKUP_SHA256"
        ),
    )

    print(json.dumps(report.safe_summary(), indent=2))
    assert report.success, (
        "Runtime alert migration verification failed: "
        + ", ".join(report.failed_checks)
    )


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
