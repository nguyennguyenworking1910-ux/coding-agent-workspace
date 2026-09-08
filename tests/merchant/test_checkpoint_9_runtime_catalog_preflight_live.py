"""Opt-in read-only preflight for the private runtime catalog."""

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
from claude.clients.merchant.runtime_catalog_plan import (
    CATALOG_AUTHORIZATION_PHRASE,
    build_runtime_catalog_initialization_plan,
)
from claude.clients.merchant.runtime_readiness import (
    CATALOG_INITIALIZATION_READY,
    check_runtime_readiness,
    inspect_runtime_backup,
)


LIVE_PREFLIGHT_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_CATALOG_PREFLIGHT",
        "",
    ).strip()
    == "1"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_PREFLIGHT_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_CATALOG_PREFLIGHT=1 "
        "for the read-only Gate 9.5 catalog preflight"
    ),
)
def test_checkpoint_9_runtime_catalog_plan_is_exact():
    source_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SOURCE_SHA256"
    )
    catalog_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SHA256"
    )
    catalog = load_private_catalog(
        _required_environment("MERCHANT_PRIVATE_CATALOG_PATH")
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
    repository = MerchantRepository(
        RepositoryConfig.from_env("app")
    )
    readiness = check_runtime_readiness(
        repository,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
        backup_evidence=backup,
    )

    assert readiness.state == CATALOG_INITIALIZATION_READY

    existing_records = _read_existing_catalog(repository)
    plan = build_runtime_catalog_initialization_plan(
        readiness,
        catalog,
        existing_records=existing_records,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
        expected_backup_sha256=_required_environment(
            "MERCHANT_EXPECTED_RUNTIME_BACKUP_SHA256"
        ),
    )

    print(json.dumps(plan.safe_summary(), indent=2))
    assert plan.catalog_plan.record_count == 22
    assert plan.catalog_plan.target_count_before == 0
    assert plan.safe_summary()["authorization_phrase"] == (
        CATALOG_AUTHORIZATION_PHRASE
    )


def _read_existing_catalog(
    repository: MerchantRepository,
) -> list[dict[str, object]]:
    query = """
        SELECT
            id::text AS merchant_id,
            code,
            name,
            region_code,
            account_status,
            version
        FROM merchant_ops.merchants
        ORDER BY code, id
    """

    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(query, ())
                return [dict(row) for row in cursor.fetchall()]


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
