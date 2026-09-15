"""Live lifecycle test for Merchant activation on coding_agent_merchant_test.

One cleanup-safe integration test covers the whole activation lifecycle so
execution order can never affect the result:

a. single activation: ONBOARDING -> ACTIVE, version 1 -> 2, exact event;
b. already ACTIVE: exact conflict type, no version change, no event;
c. exact batch manifest: every generated merchant activated, one event each;
d. drift: membership, code, status and version drift each fail with zero
   updates and zero events;
e. workflow activation: a real INTEGRATION_NEW_MERCHANT_STANDARD project and
   its canonical activation step, seeded from persisted template and
   template-step IDs, activate the merchant in the same transaction;
f. rollback: an unmet dependency and a forced activation conflict leave the
   step, the merchant and project_events unchanged;
g. cleanup: only generated records are deleted, in foreign-key-safe order,
   even after an assertion failure, and every business table's final count is
   compared with its initial count.

Safety:
- disabled unless MERCHANT_RUN_LIVE_TESTS is exactly "1";
- the repository is built with RepositoryConfig.from_env("test") and every
  mutation is preceded by an assertion on the configured target;
- the connected session is validated with current_database() and current_user.
  inet_server_addr() is deliberately NOT compared with 127.0.0.1 because a
  PostgreSQL running inside Docker reports its container address.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest
from psycopg.rows import dict_row

from claude.agents.tools.merchant.engine import (
    WorkflowDependencyNotMetError,
)
from claude.agents.tools.merchant.gates import GateValidationResult
from claude.agents.tools.merchant.merchant_engine import (
    MerchantConflictError,
    MerchantVersionConflictError,
)
from claude.agents.tools.merchant.workflow_activation_integration import (
    canonical_activation_template_step_id,
    WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT,
)
from claude.clients.merchant.merchant_repository import (
    MerchantActivationResult,
    MerchantEntityRepository,
)
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
)
from claude.clients.merchant.transition_repository import (
    MerchantStepTransitionRepository,
)


LIVE_TESTS_ENABLED = (
    os.environ.get("MERCHANT_RUN_LIVE_TESTS") == "1"
)

DATABASE_NAME = "coding_agent_merchant_test"
DATABASE_HOST = "127.0.0.1"
DATABASE_PORT = 5434
DATABASE_USER = "merchant_test"

PROJECT_TYPE = "INTEGRATION_NEW_MERCHANT"
ACTIVATION_STEP_KEY = "activate_merchant"
PREDECESSOR_STEP_KEY = "create_payment_request"

# Every table whose row count must be identical before and after the run.
BUSINESS_TABLES = (
    "merchants",
    "merchant_contacts",
    "workflow_templates",
    "workflow_template_steps",
    "workflow_template_dependencies",
    "projects",
    "project_steps",
    "project_step_dependencies",
    "project_events",
    "document_revisions",
    "document_approvals",
    "procurement_records",
    "integration_identifiers",
    "alert_deliveries",
)


def normalize_jsonb(value: Any) -> dict[str, Any]:
    """Return a JSONB column as a dict.

    psycopg returns JSONB as a Python mapping; some drivers and some views
    return it as text. Anything else is a bug, not something to coerce.
    """

    if isinstance(value, Mapping):
        return dict(value)

    if isinstance(value, str):
        decoded = json.loads(value)

        if not isinstance(decoded, Mapping):
            raise TypeError(
                f"Decoded JSONB is {type(decoded).__name__}, expected object"
            )

        return dict(decoded)

    raise TypeError(
        f"Unexpected JSONB payload type: {type(value).__name__}"
    )


def assert_test_target(config: RepositoryConfig) -> None:
    """Refuse to mutate anything that is not the local test database."""

    assert config.database == DATABASE_NAME, (
        f"Refusing to mutate database {config.database}"
    )
    assert config.database.endswith("_test"), (
        f"Refusing to mutate non-test database {config.database}"
    )
    assert config.user == DATABASE_USER, (
        f"Refusing to mutate as user {config.user}"
    )
    assert config.host == DATABASE_HOST, (
        f"Refusing to mutate host {config.host}"
    )
    assert config.port == DATABASE_PORT, (
        f"Refusing to mutate port {config.port}"
    )


def successful_gate(project_id: str) -> GateValidationResult:
    return GateValidationResult(
        gate_name="ACTIVATE_MERCHANT",
        project_id=project_id,
        document_revision_id=None,
        all_met=True,
        blocking_codes=(),
        approved_roles=(),
        missing_roles=(),
        requires_procurement=False,
        purchase_request_present=False,
        already_signed=False,
    )


class GeneratedRecords:
    """Every identifier this run created, for foreign-key-safe cleanup."""

    def __init__(self) -> None:
        self.merchant_ids: list[uuid.UUID] = []
        self.project_ids: list[uuid.UUID] = []
        self.step_ids: list[uuid.UUID] = []
        self.dependency_ids: list[uuid.UUID] = []
        self.template_step_ids: list[uuid.UUID] = []
        self.template_ids: list[uuid.UUID] = []


@pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason="Live tests disabled; set MERCHANT_RUN_LIVE_TESTS=1",
)
class TestMerchantActivationLive:
    """One cleanup-safe activation lifecycle on coding_agent_merchant_test."""

    def test_merchant_activation_full_lifecycle(self):
        config = RepositoryConfig.from_env("test")
        assert_test_target(config)

        repository = MerchantRepository(config=config)
        merchants = MerchantEntityRepository(repository)
        transitions = MerchantStepTransitionRepository(repository)
        generated = GeneratedRecords()

        with repository.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT current_database() AS database, "
                    "current_user AS username"
                )
                session = cursor.fetchone()

                assert session["database"] == DATABASE_NAME
                assert session["username"] == DATABASE_USER

                cursor.execute(
                    """
                    SELECT pg_get_constraintdef(oid) AS definition
                    FROM pg_constraint
                    WHERE conname = 'project_events_valid_entity_check'
                    """
                )
                constraint = cursor.fetchone()

                assert constraint is not None, (
                    "project_events_valid_entity_check is missing"
                )
                # MERCHANT events must keep project_id NULL. Workflow
                # activation records the authorizing project in new_values.
                assert "project_id IS NULL" in constraint["definition"]

            initial_counts = self._table_counts(connection)

        try:
            self._assert_single_activation(
                repository,
                merchants,
                generated,
            )
            self._assert_already_active_rejected(
                repository,
                merchants,
                generated,
            )
            self._assert_exact_batch_manifest(
                repository,
                merchants,
                generated,
            )
            self._assert_drift_rejections(
                repository,
                merchants,
                generated,
            )
            self._assert_workflow_activation(
                repository,
                transitions,
                generated,
            )
            self._assert_workflow_rollbacks(
                repository,
                transitions,
                generated,
            )
        finally:
            with repository.connection() as connection:
                self._cleanup(connection, generated)
                final_counts = self._table_counts(connection)

            assert final_counts == initial_counts, (
                "Business table counts changed: "
                + ", ".join(
                    f"{table}: {initial_counts[table]} -> "
                    f"{final_counts[table]}"
                    for table in BUSINESS_TABLES
                    if initial_counts[table] != final_counts[table]
                )
            )

    # ------------------------------------------------------------------
    # a. Single activation
    # ------------------------------------------------------------------

    def _assert_single_activation(
        self,
        repository: MerchantRepository,
        merchants: MerchantEntityRepository,
        generated: GeneratedRecords,
    ) -> None:
        assert_test_target(repository.config)
        merchant_id = self._seed_merchant(repository, generated)
        reason = "Live lifecycle single activation"

        result = merchants.activate_merchant(
            merchant_id=str(merchant_id),
            expected_version=1,
            reason=reason,
        )

        assert isinstance(result, MerchantActivationResult)
        payload = result.to_dict()
        assert payload["merchant_id"] == str(merchant_id)
        assert payload["previous_status"] == "ONBOARDING"
        assert payload["current_status"] == "ACTIVE"
        assert payload["previous_version"] == 1
        assert payload["current_version"] == 2
        assert payload["event_type"] == "MERCHANT_ACTIVATED"

        with repository.connection() as connection:
            merchant = self._read_merchant(connection, merchant_id)

            assert merchant["account_status"] == "ACTIVE"
            assert merchant["version"] == 2

            events = self._read_merchant_events(connection, merchant_id)

            assert len(events) == 1
            event = events[0]
            assert str(event["id"]) == payload["event_id"]
            assert event["event_type"] == "MERCHANT_ACTIVATED"
            assert event["entity_type"] == "MERCHANT"
            assert str(event["entity_id"]) == str(merchant_id)
            assert event["project_id"] is None
            assert event["triggered_by"] is None

            old_values = normalize_jsonb(event["old_values"])
            new_values = normalize_jsonb(event["new_values"])

            assert old_values == {
                "account_status": "ONBOARDING",
                "version": 1,
            }
            assert "reason" not in old_values
            assert new_values == {
                "account_status": "ACTIVE",
                "version": 2,
                "reason": reason,
            }

    # ------------------------------------------------------------------
    # b. Already ACTIVE
    # ------------------------------------------------------------------

    def _assert_already_active_rejected(
        self,
        repository: MerchantRepository,
        merchants: MerchantEntityRepository,
        generated: GeneratedRecords,
    ) -> None:
        assert_test_target(repository.config)
        merchant_id = self._seed_merchant(
            repository,
            generated,
            account_status="ACTIVE",
        )

        with pytest.raises(
            MerchantConflictError,
            match="only ONBOARDING merchants can be activated",
        ):
            merchants.activate_merchant(
                merchant_id=str(merchant_id),
                expected_version=1,
                reason="Live lifecycle already-active rejection",
            )

        with repository.connection() as connection:
            merchant = self._read_merchant(connection, merchant_id)

            assert merchant["account_status"] == "ACTIVE"
            assert merchant["version"] == 1
            assert self._read_merchant_events(connection, merchant_id) == []

    # ------------------------------------------------------------------
    # c. Exact batch manifest
    # ------------------------------------------------------------------

    def _assert_exact_batch_manifest(
        self,
        repository: MerchantRepository,
        merchants: MerchantEntityRepository,
        generated: GeneratedRecords,
    ) -> None:
        assert_test_target(repository.config)
        batch_ids = [
            self._seed_merchant(repository, generated)
            for _ in range(3)
        ]

        with repository.connection() as connection:
            onboarding = self._read_onboarding_ids(connection)

            assert onboarding == sorted(batch_ids), (
                "activate-all operates on every ONBOARDING merchant. The "
                "test database must contain no ONBOARDING merchants other "
                "than the ones this run generated. Found: "
                f"{[str(value) for value in onboarding]}"
            )

            manifest = [
                {
                    "merchant_id": str(row["id"]),
                    "code": row["code"],
                    "account_status": row["account_status"],
                    "version": row["version"],
                }
                for row in self._read_merchants(connection, batch_ids)
            ]

        reason = "Live lifecycle batch activation"
        result = merchants.activate_merchants_batch(
            from_status="ONBOARDING",
            expected_count=len(batch_ids),
            reason=reason,
            manifest=manifest,
        )

        assert result["success"] is True
        assert result["activated_count"] == len(batch_ids)
        assert sorted(
            entry["merchant_id"] for entry in result["results"]
        ) == sorted(str(value) for value in batch_ids)

        with repository.connection() as connection:
            for merchant_id in batch_ids:
                merchant = self._read_merchant(connection, merchant_id)

                assert merchant["account_status"] == "ACTIVE"
                assert merchant["version"] == 2

                events = self._read_merchant_events(connection, merchant_id)

                assert len(events) == 1
                assert events[0]["event_type"] == "MERCHANT_ACTIVATED"
                assert normalize_jsonb(events[0]["new_values"])["reason"] == (
                    reason
                )

    # ------------------------------------------------------------------
    # d. Drift rejections
    # ------------------------------------------------------------------

    def _assert_drift_rejections(
        self,
        repository: MerchantRepository,
        merchants: MerchantEntityRepository,
        generated: GeneratedRecords,
    ) -> None:
        assert_test_target(repository.config)
        drift_ids = [
            self._seed_merchant(repository, generated)
            for _ in range(2)
        ]
        absent_id = str(uuid.uuid4())

        with repository.connection() as connection:
            rows = self._read_merchants(connection, drift_ids)

        baseline = [
            {
                "merchant_id": str(row["id"]),
                "code": row["code"],
                "account_status": row["account_status"],
                "version": row["version"],
            }
            for row in rows
        ]

        drifted_manifests = {
            "membership": self._with_drift(
                baseline,
                merchant_id=absent_id,
            ),
            "code": self._with_drift(baseline, code="DRIFTED_CODE"),
            "status": self._with_drift(baseline, account_status="SUSPENDED"),
            "version": self._with_drift(baseline, version=99),
        }

        for label, manifest in drifted_manifests.items():
            with pytest.raises(MerchantConflictError) as failure:
                merchants.activate_merchants_batch(
                    from_status="ONBOARDING",
                    expected_count=len(drift_ids),
                    reason=f"Live lifecycle {label} drift",
                    manifest=manifest,
                )

            assert label in str(failure.value).lower() or "drift" in str(
                failure.value
            ).lower(), (
                f"{label} drift produced an unexpected message: "
                f"{failure.value}"
            )

            with repository.connection() as connection:
                for merchant_id in drift_ids:
                    merchant = self._read_merchant(connection, merchant_id)

                    assert merchant["account_status"] == "ONBOARDING", (
                        f"{label} drift updated a merchant"
                    )
                    assert merchant["version"] == 1
                    assert self._read_merchant_events(
                        connection,
                        merchant_id,
                    ) == [], f"{label} drift wrote an event"

        # A stale expected_version must surface as the precise subclass.
        with repository.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE merchant_ops.merchants
                        SET version = version + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (drift_ids[0],),
                    )

        with pytest.raises(MerchantVersionConflictError):
            merchants.activate_merchant(
                merchant_id=str(drift_ids[0]),
                expected_version=1,
                reason="Live lifecycle stale version",
            )

        with repository.connection() as connection:
            merchant = self._read_merchant(connection, drift_ids[0])

            assert merchant["account_status"] == "ONBOARDING"
            assert merchant["version"] == 2
            assert self._read_merchant_events(
                connection,
                drift_ids[0],
            ) == []

            # Leave nothing ONBOARDING behind for later sections.
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE merchant_ops.merchants
                        SET account_status = 'INACTIVE',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ANY(%s)
                        """,
                        (drift_ids,),
                    )

    @staticmethod
    def _with_drift(
        baseline: list[dict[str, Any]],
        **overrides: Any,
    ) -> list[dict[str, Any]]:
        drifted = [dict(entry) for entry in baseline]
        drifted[0].update(overrides)
        return drifted

    # ------------------------------------------------------------------
    # e. Workflow activation
    # ------------------------------------------------------------------

    def _assert_workflow_activation(
        self,
        repository: MerchantRepository,
        transitions: MerchantStepTransitionRepository,
        generated: GeneratedRecords,
    ) -> None:
        assert_test_target(repository.config)
        merchant_id = self._seed_merchant(repository, generated)
        project_id, step_id, _ = self._seed_workflow_project(
            repository,
            generated,
            merchant_id,
            predecessor_status="COMPLETED",
        )

        result = transitions.transition_step(
            step_id=str(step_id),
            target_status="COMPLETED",
            expected_version=1,
            occurred_at=datetime.now(timezone.utc),
            gate_required=True,
            gate_result=successful_gate(str(project_id)),
        )

        assert result.current_status == "COMPLETED"
        assert result.event_type == "STEP_COMPLETED"

        with repository.connection() as connection:
            merchant = self._read_merchant(connection, merchant_id)

            assert merchant["account_status"] == "ACTIVE"
            assert merchant["version"] == 2

            events = self._read_merchant_events(connection, merchant_id)

            assert len(events) == 1
            event = events[0]
            assert event["event_type"] == "MERCHANT_ACTIVATED"
            assert event["entity_type"] == "MERCHANT"
            assert str(event["entity_id"]) == str(merchant_id)
            assert event["project_id"] is None
            assert event["triggered_by"] is None

            old_values = normalize_jsonb(event["old_values"])
            new_values = normalize_jsonb(event["new_values"])

            assert old_values == {
                "account_status": "ONBOARDING",
                "version": 1,
            }
            assert "reason" not in old_values
            assert new_values["account_status"] == "ACTIVE"
            assert new_values["version"] == 2
            assert ACTIVATION_STEP_KEY in new_values["reason"]
            assert new_values["project_id"] == str(project_id)
            assert new_values["workflow_template_step_name"] == (
                ACTIVATION_STEP_KEY
            )
            assert new_values["workflow_template_step_id"] == (
                canonical_activation_template_step_id(
                    new_values["workflow_template_id"]
                )
            )

            step = self._read_step(connection, step_id)

            assert step["status"] == "COMPLETED"
            assert step["version"] == 2

    # ------------------------------------------------------------------
    # f. Rollback
    # ------------------------------------------------------------------

    def _assert_workflow_rollbacks(
        self,
        repository: MerchantRepository,
        transitions: MerchantStepTransitionRepository,
        generated: GeneratedRecords,
    ) -> None:
        assert_test_target(repository.config)

        unmet_merchant_id = self._seed_merchant(repository, generated)
        unmet_project_id, unmet_step_id, _ = self._seed_workflow_project(
            repository,
            generated,
            unmet_merchant_id,
            predecessor_status="PENDING",
        )

        with repository.connection() as connection:
            events_before = self._count_project_events(connection)

        with pytest.raises(WorkflowDependencyNotMetError):
            transitions.transition_step(
                step_id=str(unmet_step_id),
                target_status="COMPLETED",
                expected_version=1,
                occurred_at=datetime.now(timezone.utc),
                gate_required=True,
                gate_result=successful_gate(str(unmet_project_id)),
            )

        self._assert_workflow_unchanged(
            repository,
            merchant_id=unmet_merchant_id,
            step_id=unmet_step_id,
            expected_events=events_before,
        )

        conflict_merchant_id = self._seed_merchant(
            repository,
            generated,
            account_status="ACTIVE",
        )
        conflict_project_id, conflict_step_id, _ = (
            self._seed_workflow_project(
                repository,
                generated,
                conflict_merchant_id,
                predecessor_status="COMPLETED",
            )
        )

        with repository.connection() as connection:
            events_before = self._count_project_events(connection)

        with pytest.raises(MerchantConflictError):
            transitions.transition_step(
                step_id=str(conflict_step_id),
                target_status="COMPLETED",
                expected_version=1,
                occurred_at=datetime.now(timezone.utc),
                gate_required=True,
                gate_result=successful_gate(str(conflict_project_id)),
            )

        self._assert_workflow_unchanged(
            repository,
            merchant_id=conflict_merchant_id,
            step_id=conflict_step_id,
            expected_events=events_before,
            expected_status="ACTIVE",
        )

    def _assert_workflow_unchanged(
        self,
        repository: MerchantRepository,
        *,
        merchant_id: uuid.UUID,
        step_id: uuid.UUID,
        expected_events: int,
        expected_status: str = "ONBOARDING",
    ) -> None:
        with repository.connection() as connection:
            merchant = self._read_merchant(connection, merchant_id)

            assert merchant["account_status"] == expected_status
            assert merchant["version"] == 1

            step = self._read_step(connection, step_id)

            assert step["status"] == "IN_PROGRESS"
            assert step["version"] == 1
            assert step["actual_completion"] is None

            assert self._count_project_events(connection) == expected_events

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def _seed_merchant(
        self,
        repository: MerchantRepository,
        generated: GeneratedRecords,
        *,
        account_status: str = "ONBOARDING",
    ) -> uuid.UUID:
        assert_test_target(repository.config)
        merchant_id = uuid.uuid4()

        with repository.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO merchant_ops.merchants (
                            id,
                            code,
                            name,
                            region_code,
                            account_status,
                            created_at,
                            updated_at,
                            created_by,
                            version
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP,
                            NULL, %s
                        )
                        """,
                        (
                            merchant_id,
                            f"LIVE_{merchant_id.hex[:24].upper()}",
                            f"Live lifecycle merchant {merchant_id}",
                            "VN_S",
                            account_status,
                            1,
                        ),
                    )

                    assert cursor.rowcount == 1

        generated.merchant_ids.append(merchant_id)
        return merchant_id

    def _seed_workflow_project(
        self,
        repository: MerchantRepository,
        generated: GeneratedRecords,
        merchant_id: uuid.UUID,
        *,
        predecessor_status: str,
    ) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        """Seed a real INTEGRATION_NEW_MERCHANT_STANDARD project.

        Both the project's template and its activation step use the persisted
        template and template-step identity that authorizes activation.
        """

        assert_test_target(repository.config)
        template_id = self._resolve_template(repository, generated)
        activation_template_step_id = uuid.UUID(
            canonical_activation_template_step_id(template_id)
        )
        predecessor_template_step_id = uuid.uuid5(
            template_id,
            f"step:{PREDECESSOR_STEP_KEY}",
        )

        self._ensure_template_step(
            repository,
            generated,
            template_id,
            activation_template_step_id,
            sequence_number=25,
            step_type="APPROVAL_GATE",
            name="Activate Merchant",
        )
        self._ensure_template_step(
            repository,
            generated,
            template_id,
            predecessor_template_step_id,
            sequence_number=18,
            step_type="SEQUENTIAL",
            name="Create payment request",
        )

        project_id = uuid.uuid4()
        activation_step_id = uuid.uuid4()
        predecessor_step_id = uuid.uuid4()
        dependency_id = uuid.uuid4()

        with repository.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO merchant_ops.projects (
                            id,
                            merchant_id,
                            project_type,
                            workflow_variant,
                            workflow_template_version_id,
                            title,
                            status,
                            requires_procurement,
                            started_at,
                            created_at,
                            updated_at,
                            version
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s,
                            'IN_PROGRESS', FALSE,
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP,
                            1
                        )
                        """,
                        (
                            project_id,
                            merchant_id,
                            PROJECT_TYPE,
                            WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT,
                            template_id,
                            f"Live lifecycle project {project_id}",
                        ),
                    )

                    assert cursor.rowcount == 1

                    self._insert_project_step(
                        cursor,
                        step_id=predecessor_step_id,
                        project_id=project_id,
                        template_step_id=predecessor_template_step_id,
                        step_name="Create payment request",
                        status=predecessor_status,
                        sequence_number=18,
                    )
                    self._insert_project_step(
                        cursor,
                        step_id=activation_step_id,
                        project_id=project_id,
                        template_step_id=activation_template_step_id,
                        step_name="Activate Merchant",
                        status="IN_PROGRESS",
                        sequence_number=25,
                    )

                    cursor.execute(
                        """
                        INSERT INTO merchant_ops.project_step_dependencies (
                            id,
                            from_step_id,
                            to_step_id,
                            dependency_type,
                            created_at
                        )
                        VALUES (
                            %s, %s, %s, 'MUST_COMPLETE_BEFORE',
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            dependency_id,
                            predecessor_step_id,
                            activation_step_id,
                        ),
                    )

                    assert cursor.rowcount == 1

        generated.project_ids.append(project_id)
        generated.step_ids.extend([predecessor_step_id, activation_step_id])
        generated.dependency_ids.append(dependency_id)

        return project_id, activation_step_id, predecessor_step_id

    @staticmethod
    def _insert_project_step(
        cursor: Any,
        *,
        step_id: uuid.UUID,
        project_id: uuid.UUID,
        template_step_id: uuid.UUID,
        step_name: str,
        status: str,
        sequence_number: int,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO merchant_ops.project_steps (
                id,
                project_id,
                template_step_id,
                branch_key,
                step_name,
                status,
                sequence_number,
                actual_start,
                actual_completion,
                created_at,
                updated_at,
                version
            )
            VALUES (
                %s, %s, %s, NULL, %s, %s, %s,
                CURRENT_TIMESTAMP,
                CASE WHEN %s = 'COMPLETED'
                     THEN CURRENT_TIMESTAMP
                     ELSE NULL
                END,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                1
            )
            """,
            (
                step_id,
                project_id,
                template_step_id,
                step_name,
                status,
                sequence_number,
                status,
            ),
        )

        assert cursor.rowcount == 1

    def _resolve_template(
        self,
        repository: MerchantRepository,
        generated: GeneratedRecords,
    ) -> uuid.UUID:
        """Return the persisted INTEGRATION_NEW_MERCHANT_STANDARD template."""

        with repository.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, variant, version
                    FROM merchant_ops.workflow_templates
                    WHERE name = %s
                      AND variant = %s
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (
                        WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT,
                        WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT,
                    ),
                )
                template = cursor.fetchone()

            if template is not None:
                return template["id"]

            template_id = uuid.uuid4()

            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO merchant_ops.workflow_templates (
                            id,
                            name,
                            version,
                            description,
                            variant,
                            is_active,
                            created_at
                        )
                        VALUES (
                            %s, %s, 1, %s, %s, TRUE, CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            template_id,
                            WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT,
                            "Live lifecycle generated template",
                            WORKFLOW_TEMPLATE_ACTIVATE_MERCHANT,
                        ),
                    )

                    assert cursor.rowcount == 1

        generated.template_ids.append(template_id)
        return template_id

    def _ensure_template_step(
        self,
        repository: MerchantRepository,
        generated: GeneratedRecords,
        template_id: uuid.UUID,
        template_step_id: uuid.UUID,
        *,
        sequence_number: int,
        step_type: str,
        name: str,
    ) -> None:
        with repository.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, template_id, name
                    FROM merchant_ops.workflow_template_steps
                    WHERE id = %s
                    """,
                    (template_step_id,),
                )
                existing = cursor.fetchone()

            if existing is not None:
                assert existing["template_id"] == template_id
                return

            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO merchant_ops.workflow_template_steps (
                            id,
                            template_id,
                            sequence_number,
                            branch_key,
                            step_type,
                            name,
                            description,
                            is_optional,
                            condition_key,
                            created_at
                        )
                        VALUES (
                            %s, %s, %s, NULL, %s, %s, NULL, FALSE, NULL,
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            template_step_id,
                            template_id,
                            sequence_number,
                            step_type,
                            name,
                        ),
                    )

                    assert cursor.rowcount == 1

        generated.template_step_ids.append(template_step_id)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @staticmethod
    def _table_counts(connection: Any) -> dict[str, int]:
        counts: dict[str, int] = {}

        with connection.cursor(row_factory=dict_row) as cursor:
            for table in BUSINESS_TABLES:
                cursor.execute(
                    f"SELECT COUNT(*) AS total "
                    f"FROM merchant_ops.{table}"
                )
                counts[table] = cursor.fetchone()["total"]

        return counts

    @staticmethod
    def _read_merchant(
        connection: Any,
        merchant_id: uuid.UUID,
    ) -> dict[str, Any]:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, code, name, account_status, version
                FROM merchant_ops.merchants
                WHERE id = %s
                """,
                (merchant_id,),
            )
            merchant = cursor.fetchone()

        assert merchant is not None, f"Merchant {merchant_id} disappeared"
        return dict(merchant)

    @staticmethod
    def _read_merchants(
        connection: Any,
        merchant_ids: list[uuid.UUID],
    ) -> list[dict[str, Any]]:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, code, account_status, version
                FROM merchant_ops.merchants
                WHERE id = ANY(%s)
                ORDER BY id ASC
                """,
                (merchant_ids,),
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _read_onboarding_ids(connection: Any) -> list[uuid.UUID]:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id
                FROM merchant_ops.merchants
                WHERE account_status = 'ONBOARDING'
                ORDER BY id ASC
                """
            )
            return [row["id"] for row in cursor.fetchall()]

    @staticmethod
    def _read_merchant_events(
        connection: Any,
        merchant_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    merchant_id,
                    project_id,
                    event_type,
                    entity_type,
                    entity_id,
                    change_summary,
                    old_values,
                    new_values,
                    triggered_by,
                    created_at
                FROM merchant_ops.project_events
                WHERE merchant_id = %s
                  AND entity_type = 'MERCHANT'
                ORDER BY created_at ASC, id ASC
                """,
                (merchant_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _read_step(
        connection: Any,
        step_id: uuid.UUID,
    ) -> dict[str, Any]:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, status, version, actual_completion
                FROM merchant_ops.project_steps
                WHERE id = %s
                """,
                (step_id,),
            )
            step = cursor.fetchone()

        assert step is not None, f"Project step {step_id} disappeared"
        return dict(step)

    @staticmethod
    def _count_project_events(connection: Any) -> int:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM merchant_ops.project_events"
            )
            return cursor.fetchone()["total"]

    # ------------------------------------------------------------------
    # g. Cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup(connection: Any, generated: GeneratedRecords) -> None:
        """Delete only generated records, in foreign-key-safe order."""

        with connection.transaction():
            with connection.cursor() as cursor:
                if generated.merchant_ids or generated.project_ids:
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.project_events
                        WHERE merchant_id = ANY(%s)
                           OR project_id = ANY(%s)
                        """,
                        (
                            generated.merchant_ids,
                            generated.project_ids,
                        ),
                    )

                if generated.project_ids:
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.alert_deliveries
                        WHERE project_id = ANY(%s)
                        """,
                        (generated.project_ids,),
                    )

                if generated.dependency_ids:
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.project_step_dependencies
                        WHERE id = ANY(%s)
                        """,
                        (generated.dependency_ids,),
                    )

                if generated.step_ids:
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.project_steps
                        WHERE id = ANY(%s)
                        """,
                        (generated.step_ids,),
                    )

                if generated.project_ids:
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.projects
                        WHERE id = ANY(%s)
                        """,
                        (generated.project_ids,),
                    )

                if generated.template_step_ids:
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.workflow_template_steps
                        WHERE id = ANY(%s)
                        """,
                        (generated.template_step_ids,),
                    )

                if generated.template_ids:
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.workflow_templates
                        WHERE id = ANY(%s)
                        """,
                        (generated.template_ids,),
                    )

                if generated.merchant_ids:
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.merchant_contacts
                        WHERE merchant_id = ANY(%s)
                        """,
                        (generated.merchant_ids,),
                    )
                    cursor.execute(
                        """
                        DELETE FROM merchant_ops.merchants
                        WHERE id = ANY(%s)
                        """,
                        (generated.merchant_ids,),
                    )
