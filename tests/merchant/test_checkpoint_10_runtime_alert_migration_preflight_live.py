"""Opt-in read-only Gate 10.7A runtime migration preflight."""

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
from claude.clients.merchant.runtime_alert_migration_plan import (
    MIGRATION_AUTHORIZATION_PHRASE,
    build_runtime_alert_migration_deployment_plan,
)
from claude.clients.merchant.runtime_readiness import (
    inspect_runtime_backup,
)
from claude.clients.merchant.runtime_verification import (
    verify_initialized_runtime,
)


LIVE_PREFLIGHT_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_ALERT_MIGRATION_PREFLIGHT",
        "",
    ).strip()
    == "1"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_PREFLIGHT_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_ALERT_MIGRATION_PREFLIGHT=1 "
        "for the read-only Gate 10.7A preflight"
    ),
)
def test_checkpoint_10_runtime_alert_migration_plan_is_exact():
    source_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SOURCE_SHA256"
    )
    catalog_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SHA256"
    )
    catalog = load_private_catalog(
        _required_environment("MERCHANT_PRIVATE_CATALOG_PATH")
    )
    assert catalog.source_sha256 == source_hash
    assert catalog.catalog_sha256 == catalog_hash
    assert _required_environment("MERCHANT_OWNER_USER") == (
        "merchant_owner"
    )
    _required_environment("MERCHANT_OWNER_PASSWORD")

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
    expected_backup_hash = _required_environment(
        "MERCHANT_EXPECTED_RUNTIME_BACKUP_SHA256"
    )
    assert backup.backup_sha256 == expected_backup_hash

    repository = MerchantRepository(
        RepositoryConfig.from_env("app")
    )
    verification = verify_initialized_runtime(
        repository,
        catalog,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
    )
    assert verification.success is True

    config = repository.config
    read_only_plan = migrate.get_plan(
        config.host,
        config.port,
        config.database,
        config.user,
        config.password,
    )
    deployment = build_runtime_alert_migration_deployment_plan(
        verification,
        read_only_plan,
        backup,
        expected_backup_sha256=expected_backup_hash,
    )

    assert deployment.plan_sha256 == _required_environment(
        "MERCHANT_EXPECTED_RUNTIME_ALERT_PLAN_SHA256"
    )

    print(json.dumps(deployment.safe_summary(), indent=2))
    assert deployment.requires_authorization is True
    assert tuple(
        item.version for item in deployment.pending_migrations
    ) == (4,)
    assert deployment.safe_summary()["authorization_phrase"] == (
        MIGRATION_AUTHORIZATION_PHRASE
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
