"""Opt-in authorized Gate 9.5 standard-template initialization."""

from __future__ import annotations

import json
import os

import pytest

from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
)
from claude.clients.merchant.runtime_readiness import (
    BUSINESS_TABLES,
    CATALOG_INITIALIZATION_READY,
    TEMPLATE_INITIALIZATION_READY,
    check_runtime_readiness,
    inspect_runtime_backup,
)
from claude.clients.merchant.runtime_template_plan import (
    EXPECTED_FULL_TEMPLATE_SHA256,
    build_runtime_template_initialization_plan,
)
from claude.clients.merchant.template_loader import (
    WorkflowTemplateLoadResult,
    WorkflowTemplateLoader,
)


LIVE_INITIALIZATION_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_TEMPLATE_INITIALIZATION",
        "",
    ).strip()
    == "1"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_INITIALIZATION_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_TEMPLATE_INITIALIZATION=1 "
        "only after exact template authorization"
    ),
)
def test_checkpoint_9_initializes_exact_standard_templates():
    source_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SOURCE_SHA256"
    )
    catalog_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SHA256"
    )
    expected_backup_hash = _required_environment(
        "MERCHANT_EXPECTED_RUNTIME_BACKUP_SHA256"
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

    assert backup.backup_sha256 == expected_backup_hash

    read_repository = MerchantRepository(
        RepositoryConfig.from_env("app")
    )
    before = check_runtime_readiness(
        read_repository,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
        backup_evidence=backup,
    )

    assert before.success is True
    assert before.state == TEMPLATE_INITIALIZATION_READY

    plan = build_runtime_template_initialization_plan(
        before,
        expected_backup_sha256=expected_backup_hash,
    )
    assert plan.manifest_sha256 == (
        EXPECTED_FULL_TEMPLATE_SHA256
    )

    owner_config = RepositoryConfig.from_env("owner")
    assert (
        owner_config.host,
        owner_config.port,
        owner_config.database,
        owner_config.user,
    ) == (
        "127.0.0.1",
        5434,
        "coding_agent_merchant",
        "merchant_owner",
    )

    loader = WorkflowTemplateLoader(
        MerchantRepository(owner_config)
    )
    applied = loader.load_standard_templates()

    assert applied == WorkflowTemplateLoadResult(
        templates_inserted=4,
        templates_unchanged=0,
        steps_inserted=64,
        dependencies_inserted=68,
    )

    # This second call performs a complete stored-definition comparison.
    # Identical data is a verified no-op; any difference fails closed.
    identical_retry = loader.load_standard_templates()
    assert identical_retry == WorkflowTemplateLoadResult(
        templates_inserted=0,
        templates_unchanged=4,
        steps_inserted=0,
        dependencies_inserted=0,
    )

    after = check_runtime_readiness(
        read_repository,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
        backup_evidence=backup,
    )
    checks = {
        "initial_state_exact": (
            before.state == TEMPLATE_INITIALIZATION_READY
        ),
        "four_templates_inserted": (
            applied.templates_inserted == 4
        ),
        "sixty_four_steps_inserted": (
            applied.steps_inserted == 64
        ),
        "sixty_eight_dependencies_inserted": (
            applied.dependencies_inserted == 68
        ),
        "identical_retry_is_no_op": (
            identical_retry.templates_inserted == 0
            and identical_retry.templates_unchanged == 4
            and identical_retry.steps_inserted == 0
            and identical_retry.dependencies_inserted == 0
        ),
        "catalog_initialization_is_next": (
            after.success is True
            and after.state == CATALOG_INITIALIZATION_READY
        ),
        "template_manifest_exact": (
            after.stored_template_count == 4
            and after.standard_templates_match is True
        ),
        "migrations_unchanged": (
            after.applied_versions == (1, 2, 3)
            and after.pending_versions == ()
        ),
        "business_tables_empty": (
            set(after.business_counts) == set(BUSINESS_TABLES)
            and all(
                count == 0
                for count in after.business_counts.values()
            )
        ),
    }
    summary = {
        "success": all(checks.values()),
        "state_before": before.state,
        "state_after": after.state,
        "checks": checks,
        "plan_sha256": plan.plan_sha256,
        "manifest_sha256": plan.manifest_sha256,
        "load_result": applied.to_dict(),
        "identical_retry": identical_retry.to_dict(),
        "stored_template_count": after.stored_template_count,
        "business_counts": dict(after.business_counts),
        "backup_sha256": backup.backup_sha256,
    }

    print(json.dumps(summary, indent=2))
    assert summary["success"], (
        "Runtime template initialization verification failed: "
        + ", ".join(
            name for name, passed in checks.items() if not passed
        )
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
