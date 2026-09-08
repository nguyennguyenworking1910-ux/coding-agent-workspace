"""Opt-in authorized private runtime catalog initialization."""

from __future__ import annotations

import json
import os

import pytest

from claude.agents.tools.merchant.catalog_contract import (
    load_private_catalog,
)
from claude.agents.tools.merchant.catalog_plan import CATALOG_NO_OP
from claude.clients.merchant.catalog_initializer import (
    CATALOG_AUDIT_EVENT_TYPE,
    RuntimeCatalogInitializer,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
)
from claude.clients.merchant.runtime_catalog_plan import (
    build_runtime_catalog_initialization_plan,
)
from claude.clients.merchant.runtime_readiness import (
    CATALOG_INITIALIZATION_READY,
    check_runtime_readiness,
    inspect_runtime_backup,
)


LIVE_INITIALIZATION_ENABLED = (
    os.environ.get(
        "MERCHANT_RUN_RUNTIME_CATALOG_INITIALIZATION",
        "",
    ).strip()
    == "1"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not LIVE_INITIALIZATION_ENABLED,
    reason=(
        "Set MERCHANT_RUN_RUNTIME_CATALOG_INITIALIZATION=1 "
        "only after exact private catalog authorization"
    ),
)
def test_checkpoint_9_initializes_exact_private_catalog():
    source_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SOURCE_SHA256"
    )
    catalog_hash = _required_environment(
        "MERCHANT_EXPECTED_CATALOG_SHA256"
    )
    expected_runtime_plan_hash = _required_environment(
        "MERCHANT_EXPECTED_RUNTIME_CATALOG_PLAN_SHA256"
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

    assert readiness.success is True
    assert readiness.state == CATALOG_INITIALIZATION_READY

    existing_before = _read_catalog(repository)
    plan = build_runtime_catalog_initialization_plan(
        readiness,
        catalog,
        existing_records=existing_before,
        expected_source_sha256=source_hash,
        expected_catalog_sha256=catalog_hash,
        expected_backup_sha256=_required_environment(
            "MERCHANT_EXPECTED_RUNTIME_BACKUP_SHA256"
        ),
    )

    assert plan.runtime_plan_sha256 == expected_runtime_plan_hash

    initializer = RuntimeCatalogInitializer(repository)
    applied = initializer.initialize(plan)
    identical_retry = initializer.initialize(plan)
    stored_after = _read_catalog(repository)
    post_state = _read_post_state(repository)

    assert identical_retry.action == CATALOG_NO_OP

    checks = {
        "runtime_plan_exact": (
            plan.runtime_plan_sha256
            == expected_runtime_plan_hash
        ),
        "twenty_two_merchants_inserted": (
            applied.action == "INSERT"
            and applied.merchants_inserted == 22
            and applied.merchant_count == 22
        ),
        "status_distribution_exact": (
            dict(applied.status_counts)
            == {
                "ACTIVE": 0,
                "ONBOARDING": 22,
            }
        ),
        "twenty_two_redacted_events_inserted": (
            applied.audit_events_inserted == 22
            and post_state["catalog_event_count"] == 22
            and post_state["project_event_count"] == 22
        ),
        "identical_retry_is_no_op": (
            identical_retry.merchants_inserted == 0
            and identical_retry.merchants_unchanged == 22
            and identical_retry.audit_events_inserted == 0
            and post_state["catalog_event_count"] == 22
        ),
        "stored_catalog_is_identical": (
            len(stored_after) == 22
            and stored_after
            == _expected_target_records(catalog)
        ),
        "templates_unchanged": (
            post_state["template_count"] == 4
            and post_state["template_step_count"] == 64
            and post_state["template_dependency_count"] == 68
        ),
        "migrations_unchanged": (
            post_state["migration_versions"] == [1, 2, 3]
        ),
        "no_contacts_or_projects": (
            post_state["contact_count"] == 0
            and post_state["project_count"] == 0
        ),
    }
    summary = {
        "success": all(checks.values()),
        "checks": checks,
        "record_count": applied.merchant_count,
        "status_counts": dict(applied.status_counts),
        "catalog_event_count": post_state["catalog_event_count"],
        "template_count": post_state["template_count"],
        "migration_versions": post_state["migration_versions"],
        "source_sha256": applied.source_sha256,
        "catalog_sha256": applied.catalog_sha256,
        "catalog_plan_sha256": applied.catalog_plan_sha256,
        "runtime_plan_sha256": applied.runtime_plan_sha256,
        "identical_retry": identical_retry.safe_summary(),
        "backup_sha256": backup.backup_sha256,
    }

    print(json.dumps(summary, indent=2))
    assert summary["success"], (
        "Runtime catalog initialization verification failed: "
        + ", ".join(
            name for name, passed in checks.items() if not passed
        )
    )


def _read_catalog(
    repository: MerchantRepository,
) -> list[dict[str, object]]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id::text AS merchant_id,
                        code,
                        name,
                        region_code,
                        account_status,
                        version
                    FROM merchant_ops.merchants
                    ORDER BY code, id
                    """,
                    (),
                )
                return [dict(row) for row in cursor.fetchall()]


def _expected_target_records(catalog):
    return [
        {
            "merchant_id": record.merchant_id,
            "code": record.code,
            "name": record.name,
            "region_code": record.region_code,
            "account_status": record.account_status,
            "version": 1,
        }
        for record in catalog.records
    ]


def _read_post_state(
    repository: MerchantRepository,
) -> dict[str, object]:
    with repository.connection(read_only=True) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                counts = {}

                for name, query, parameters in (
                    (
                        "catalog_event_count",
                        "SELECT COUNT(*) AS count "
                        "FROM merchant_ops.project_events "
                        "WHERE event_type = %s",
                        (CATALOG_AUDIT_EVENT_TYPE,),
                    ),
                    (
                        "project_event_count",
                        "SELECT COUNT(*) AS count "
                        "FROM merchant_ops.project_events",
                        (),
                    ),
                    (
                        "template_count",
                        "SELECT COUNT(*) AS count "
                        "FROM merchant_ops.workflow_templates",
                        (),
                    ),
                    (
                        "template_step_count",
                        "SELECT COUNT(*) AS count "
                        "FROM merchant_ops.workflow_template_steps",
                        (),
                    ),
                    (
                        "template_dependency_count",
                        "SELECT COUNT(*) AS count "
                        "FROM merchant_ops"
                        ".workflow_template_dependencies",
                        (),
                    ),
                    (
                        "contact_count",
                        "SELECT COUNT(*) AS count "
                        "FROM merchant_ops.merchant_contacts",
                        (),
                    ),
                    (
                        "project_count",
                        "SELECT COUNT(*) AS count "
                        "FROM merchant_ops.projects",
                        (),
                    ),
                ):
                    cursor.execute(query, parameters)
                    counts[name] = int(cursor.fetchone()["count"])

                cursor.execute(
                    """
                    SELECT version
                    FROM merchant_ops.schema_migrations
                    ORDER BY version
                    """,
                    (),
                )
                counts["migration_versions"] = [
                    int(row["version"]) for row in cursor.fetchall()
                ]

    return counts


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
