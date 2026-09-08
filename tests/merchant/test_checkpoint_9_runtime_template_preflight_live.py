"""Opt-in read-only preflight for standard runtime templates."""

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
    TEMPLATE_INITIALIZATION_READY,
    check_runtime_readiness,
    inspect_runtime_backup,
)
from claude.clients.merchant.runtime_template_plan import (
    TEMPLATE_AUTHORIZATION_PHRASE,
    build_runtime_template_initialization_plan,
)


LIVE_PREFLIGHT_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_TEMPLATE_PREFLIGHT",
        "",
    ).strip()
    == "1"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_PREFLIGHT_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_TEMPLATE_PREFLIGHT=1 "
        "for the read-only Gate 9.5 template preflight"
    ),
)
def test_checkpoint_9_runtime_template_plan_is_exact():
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
    repository = MerchantRepository(
        RepositoryConfig.from_env("app")
    )
    readiness = check_runtime_readiness(
        repository,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
        backup_evidence=backup,
    )

    assert readiness.state == TEMPLATE_INITIALIZATION_READY

    plan = build_runtime_template_initialization_plan(
        readiness,
        expected_backup_sha256=_required_environment(
            "MERCHANT_EXPECTED_RUNTIME_BACKUP_SHA256"
        ),
    )

    print(json.dumps(plan.safe_summary(), indent=2))
    assert plan.template_count == 4
    assert plan.step_count == 64
    assert plan.dependency_count == 68
    assert plan.safe_summary()["authorization_phrase"] == (
        TEMPLATE_AUTHORIZATION_PHRASE
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
