"""Behavioral tests for Merchant activation corrections (Gate 11R).

Every test here executes production code against a recording cursor and
asserts on the SQL parameters, row counts, return values, and rollback
behaviour that code produces. Nothing asserts on source text, and no test
touches a database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from claude.agents.tools.merchant.engine import (
    WorkflowDependencyNotMetError,
)
from claude.agents.tools.merchant.gates import GateValidationResult
from claude.agents.tools.merchant.merchant_engine import (
    MerchantConflictError,
    MerchantVersionConflictError,
)
from claude.agents.tools.merchant.workflow import (
    template_step_uuid,
    template_uuid,
)
from claude.agents.tools.merchant.workflow_templates import (
    INTEGRATION_NEW_MERCHANT_STANDARD,
)
from claude.agents.tools.merchant.workflow_activation_integration import (
    activate_merchant_in_workflow_transaction,
    WorkflowActivationIntegrationError,
)
from claude.clients.merchant.merchant_repository import (
    MERCHANT_ACTIVATION_EVENT_COLUMNS,
    MerchantActivationResult,
    MerchantEntityNotFoundError,
    MerchantEntityRepository,
)
from claude.clients.merchant.transition_repository import (
    MerchantStepTransitionRepository,
)


MERCHANT_ID = "550e8400-e29b-41d4-a716-446655440000"
SECOND_MERCHANT_ID = "550e8400-e29b-41d4-a716-446655440001"
PROJECT_ID = "660e8400-e29b-41d4-a716-446655440000"
STEP_ID = "770e8400-e29b-41d4-a716-446655440000"
PREDECESSOR_STEP_ID = "880e8400-e29b-41d4-a716-446655440000"
TRIGGERED_BY = "990e8400-e29b-41d4-a716-446655440000"

TEMPLATE_ID = str(template_uuid(INTEGRATION_NEW_MERCHANT_STANDARD))
ACTIVATE_TEMPLATE_STEP_ID = str(
    template_step_uuid(
        INTEGRATION_NEW_MERCHANT_STANDARD,
        "activate_merchant",
    )
)
FOREIGN_TEMPLATE_STEP_ID = str(
    template_step_uuid(
        INTEGRATION_NEW_MERCHANT_STANDARD,
        "complete_project",
    )
)

OCCURRED_AT = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)
EARLIER = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)

EVENT_INSERT = "INSERT INTO merchant_ops.project_events"
MERCHANT_UPDATE = "UPDATE merchant_ops.merchants"
STEP_UPDATE = "UPDATE merchant_ops.project_steps"

# Column order of the shared merchant activation event INSERT.
EVENT_ID = 0
EVENT_MERCHANT_ID = 1
EVENT_PROJECT_ID = 2
EVENT_TYPE = 3
EVENT_ENTITY_ID = 4
EVENT_CHANGE_SUMMARY = 5
EVENT_OLD_VALUES = 6
EVENT_NEW_VALUES = 7
EVENT_TRIGGERED_BY = 8


class RecordingContext:
    def __init__(self, value):
        self.value = value
        self.entered = False
        self.exception_type = None

    def __enter__(self):
        self.entered = True
        return self.value

    def __exit__(self, exception_type, exception, traceback):
        self.exception_type = exception_type
        return False


def make_entity_repository():
    repository = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    repository.connection.return_value = RecordingContext(connection)
    transaction_context = RecordingContext(None)
    connection.transaction.return_value = transaction_context
    connection.cursor.return_value = RecordingContext(cursor)

    return (
        MerchantEntityRepository(repository),
        cursor,
        transaction_context,
    )


def make_transition_repository():
    repository = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    repository.connection.return_value = RecordingContext(connection)
    transaction_context = RecordingContext(None)
    connection.transaction.return_value = transaction_context
    connection.cursor.return_value = RecordingContext(cursor)

    return (
        MerchantStepTransitionRepository(repository),
        cursor,
        transaction_context,
    )


def executed_sql(cursor):
    return [
        " ".join(call.args[0].split())
        for call in cursor.execute.call_args_list
    ]


def statements_starting_with(cursor, prefix):
    return [
        statement
        for statement in executed_sql(cursor)
        if statement.startswith(prefix)
    ]


def event_calls(cursor):
    return [
        call
        for call in cursor.execute.call_args_list
        if EVENT_INSERT in call.args[0]
    ]


def merchant_row(
    *,
    merchant_id=MERCHANT_ID,
    code="TEST_CODE",
    account_status="ONBOARDING",
    version=1,
):
    return {
        "id": uuid.UUID(merchant_id),
        "code": code,
        "account_status": account_status,
        "version": version,
    }


def manifest_entry(
    *,
    merchant_id=MERCHANT_ID,
    code="TEST_CODE",
    account_status="ONBOARDING",
    version=1,
):
    return {
        "merchant_id": str(uuid.UUID(merchant_id)),
        "code": code,
        "account_status": account_status,
        "version": version,
    }


def workflow_project_record(*, merchant_version=1):
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "project_type": "INTEGRATION_NEW_MERCHANT",
        "workflow_variant": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "workflow_template_version_id": TEMPLATE_ID,
        "requires_procurement": False,
        "template_id": TEMPLATE_ID,
        "template_name": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "template_variant": "INTEGRATION_NEW_MERCHANT_STANDARD",
        "template_version": 1,
        "merchant_row_id": MERCHANT_ID,
        "merchant_account_status": "ONBOARDING",
        "merchant_version": merchant_version,
    }


def workflow_step_record(
    *,
    step_id=STEP_ID,
    status="IN_PROGRESS",
    version=1,
    template_step_id=ACTIVATE_TEMPLATE_STEP_ID,
    template_step_name="Activate Merchant",
    step_name="Activate Merchant",
    actual_start=EARLIER,
    actual_completion=None,
):
    return {
        "id": step_id,
        "project_id": PROJECT_ID,
        "template_step_id": template_step_id,
        "template_step_row_id": template_step_id,
        "template_step_template_id": TEMPLATE_ID,
        "template_step_name": template_step_name,
        "template_step_branch_key": None,
        "branch_key": None,
        "step_name": step_name,
        "step_type": "APPROVAL_GATE",
        "status": status,
        "sequence_number": 25,
        "actual_start": actual_start,
        "actual_completion": actual_completion,
        "version": version,
    }


def predecessor_record(*, status="COMPLETED"):
    return {
        "id": PREDECESSOR_STEP_ID,
        "project_id": PROJECT_ID,
        "template_step_id": FOREIGN_TEMPLATE_STEP_ID,
        "template_step_row_id": FOREIGN_TEMPLATE_STEP_ID,
        "template_step_template_id": TEMPLATE_ID,
        "template_step_name": "Create payment request",
        "step_name": "Create payment request",
        "step_type": "SEQUENTIAL",
        "status": status,
        "sequence_number": 18,
        "actual_start": EARLIER,
        "actual_completion": EARLIER if status == "COMPLETED" else None,
        "version": 1,
    }


def blocking_dependency():
    return {
        "id": str(uuid.uuid4()),
        "from_step_id": PREDECESSOR_STEP_ID,
        "to_step_id": STEP_ID,
        "dependency_type": "MUST_COMPLETE_BEFORE",
    }


def successful_gate():
    return GateValidationResult(
        gate_name="ACTIVATE_MERCHANT",
        project_id=PROJECT_ID,
        document_revision_id=None,
        all_met=True,
        blocking_codes=(),
        approved_roles=(),
        missing_roles=(),
        requires_procurement=False,
        purchase_request_present=False,
        already_signed=False,
    )


class TestDirectActivationEventColumns:
    """The shared activation event helper writes the documented columns."""

    def test_activation_writes_every_event_column(self):
        entity_repository, cursor, transaction_context = (
            make_entity_repository()
        )
        cursor.fetchone.return_value = merchant_row()
        cursor.rowcount = 1

        result = entity_repository.activate_merchant(
            merchant_id=MERCHANT_ID,
            expected_version=1,
            reason="Corrections test activation",
            triggered_by=TRIGGERED_BY,
        )

        assert isinstance(result, MerchantActivationResult)
        assert result.to_dict() == {
            "merchant_id": MERCHANT_ID,
            "previous_status": "ONBOARDING",
            "current_status": "ACTIVE",
            "previous_version": 1,
            "current_version": 2,
            "event_id": result.event_id,
            "event_type": "MERCHANT_ACTIVATED",
        }
        assert uuid.UUID(result.event_id).version == 4
        assert transaction_context.exception_type is None

        query, parameters = event_calls(cursor)[0].args
        collapsed = " ".join(query.split())

        assert collapsed.startswith(EVENT_INSERT)
        for column in MERCHANT_ACTIVATION_EVENT_COLUMNS:
            assert column in collapsed, f"{column} missing from event INSERT"
        assert "'MERCHANT'" in collapsed

        assert parameters[EVENT_ID] == uuid.UUID(result.event_id)
        assert parameters[EVENT_MERCHANT_ID] == uuid.UUID(MERCHANT_ID)
        assert parameters[EVENT_PROJECT_ID] is None
        assert parameters[EVENT_TYPE] == "MERCHANT_ACTIVATED"
        assert parameters[EVENT_ENTITY_ID] == uuid.UUID(MERCHANT_ID)
        assert parameters[EVENT_TRIGGERED_BY] == uuid.UUID(TRIGGERED_BY)

    def test_reason_is_only_in_new_values(self):
        entity_repository, cursor, _ = make_entity_repository()
        cursor.fetchone.return_value = merchant_row()
        cursor.rowcount = 1

        entity_repository.activate_merchant(
            merchant_id=MERCHANT_ID,
            expected_version=1,
            reason="Corrections test activation",
            triggered_by=None,
        )

        parameters = event_calls(cursor)[0].args[1]
        old_values = parameters[EVENT_OLD_VALUES].obj
        new_values = parameters[EVENT_NEW_VALUES].obj

        assert old_values == {
            "account_status": "ONBOARDING",
            "version": 1,
        }
        assert "reason" not in old_values
        assert new_values == {
            "account_status": "ACTIVE",
            "version": 2,
            "reason": "Corrections test activation",
        }

    def test_helper_refuses_a_project_scoped_merchant_event(self):
        """project_events_valid_entity_check forbids MERCHANT + project_id."""
        from claude.agents.tools.merchant.merchant_engine import (
            propose_merchant_activation,
        )
        from claude.clients.merchant.merchant_repository import (
            insert_merchant_activation_event,
            MerchantPersistenceError,
        )

        cursor = MagicMock()
        plan = propose_merchant_activation(
            {
                "id": MERCHANT_ID,
                "code": "TEST_CODE",
                "account_status": "ONBOARDING",
                "version": 1,
            },
            expected_version=1,
            reason="Constraint guard",
        )

        with pytest.raises(
            MerchantPersistenceError,
            match="project_id to be NULL",
        ):
            insert_merchant_activation_event(
                cursor,
                plan,
                uuid.uuid4(),
                project_id=PROJECT_ID,
            )

        cursor.execute.assert_not_called()

    def test_merchant_update_is_guarded_by_status_and_version(self):
        entity_repository, cursor, _ = make_entity_repository()
        cursor.fetchone.return_value = merchant_row(version=7)
        cursor.rowcount = 1

        entity_repository.activate_merchant(
            merchant_id=MERCHANT_ID,
            expected_version=7,
            reason="Guarded update",
        )

        update_call = next(
            call
            for call in cursor.execute.call_args_list
            if MERCHANT_UPDATE in call.args[0]
        )
        collapsed = " ".join(update_call.args[0].split())

        assert "WHERE id = %s AND account_status = %s AND version = %s" in (
            collapsed
        )
        assert update_call.args[1] == (
            "ACTIVE",
            8,
            uuid.UUID(MERCHANT_ID),
            "ONBOARDING",
            7,
        )


class TestDirectActivationFailures:
    """Exact domain exceptions, with no partial writes."""

    def test_missing_merchant_raises_entity_not_found(self):
        entity_repository, cursor, transaction_context = (
            make_entity_repository()
        )
        cursor.fetchone.return_value = None

        with pytest.raises(MerchantEntityNotFoundError):
            entity_repository.activate_merchant(
                merchant_id=MERCHANT_ID,
                expected_version=1,
                reason="Missing merchant",
            )

        assert cursor.execute.call_count == 1
        assert transaction_context.exception_type is (
            MerchantEntityNotFoundError
        )

    def test_already_active_raises_conflict_without_writes(self):
        entity_repository, cursor, transaction_context = (
            make_entity_repository()
        )
        cursor.fetchone.return_value = merchant_row(
            account_status="ACTIVE",
        )

        with pytest.raises(
            MerchantConflictError,
            match="only ONBOARDING merchants can be activated",
        ):
            entity_repository.activate_merchant(
                merchant_id=MERCHANT_ID,
                expected_version=1,
                reason="Should fail",
            )

        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []
        assert transaction_context.exception_type is MerchantConflictError

    def test_stale_version_raises_version_conflict_not_base_conflict(self):
        """MerchantVersionConflictError must not be downgraded to its base."""
        entity_repository, cursor, transaction_context = (
            make_entity_repository()
        )
        cursor.fetchone.return_value = merchant_row(version=3)

        with pytest.raises(MerchantVersionConflictError):
            entity_repository.activate_merchant(
                merchant_id=MERCHANT_ID,
                expected_version=1,
                reason="Stale version",
            )

        assert transaction_context.exception_type is (
            MerchantVersionConflictError
        )
        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []

    def test_zero_rowcount_rolls_back_before_event(self):
        entity_repository, cursor, transaction_context = (
            make_entity_repository()
        )
        cursor.fetchone.return_value = merchant_row()
        cursor.rowcount = 0

        with pytest.raises(MerchantVersionConflictError):
            entity_repository.activate_merchant(
                merchant_id=MERCHANT_ID,
                expected_version=1,
                reason="Lost race",
            )

        assert len(statements_starting_with(cursor, MERCHANT_UPDATE)) == 1
        assert event_calls(cursor) == []
        assert transaction_context.exception_type is (
            MerchantVersionConflictError
        )


class TestBatchActivationManifest:
    """activate-all requires an exact manifest of the locked rows."""

    def _batch_repository(self, rows):
        entity_repository, cursor, transaction_context = (
            make_entity_repository()
        )
        cursor.fetchall.return_value = rows
        cursor.rowcount = 1
        return entity_repository, cursor, transaction_context

    def test_exact_manifest_activates_every_merchant(self):
        rows = [
            merchant_row(merchant_id=MERCHANT_ID, code="ONE"),
            merchant_row(merchant_id=SECOND_MERCHANT_ID, code="TWO"),
        ]
        entity_repository, cursor, transaction_context = (
            self._batch_repository(rows)
        )

        result = entity_repository.activate_merchants_batch(
            from_status="onboarding",
            expected_count=2,
            reason="Batch corrections test",
            manifest=[
                manifest_entry(merchant_id=MERCHANT_ID, code="ONE"),
                manifest_entry(merchant_id=SECOND_MERCHANT_ID, code="TWO"),
            ],
        )

        assert result["success"] is True
        assert result["from_status"] == "ONBOARDING"
        assert result["expected_count"] == 2
        assert result["activated_count"] == 2
        assert [entry["merchant_id"] for entry in result["results"]] == [
            MERCHANT_ID,
            SECOND_MERCHANT_ID,
        ]
        assert all(
            entry["previous_status"] == "ONBOARDING"
            and entry["current_status"] == "ACTIVE"
            and entry["previous_version"] == 1
            and entry["current_version"] == 2
            for entry in result["results"]
        )

        event_ids = {entry["event_id"] for entry in result["results"]}
        assert len(event_ids) == 2
        assert len(statements_starting_with(cursor, MERCHANT_UPDATE)) == 2
        assert len(event_calls(cursor)) == 2
        assert transaction_context.exception_type is None

        select_query = " ".join(
            cursor.execute.call_args_list[0].args[0].split()
        )
        assert "FOR UPDATE" in select_query
        assert cursor.execute.call_args_list[0].args[1] == ("ONBOARDING",)

    @pytest.mark.parametrize(
        "drift,expected_message",
        [
            (
                {"merchant_id": SECOND_MERCHANT_ID},
                "Manifest membership drift",
            ),
            ({"code": "DRIFTED"}, "code changed"),
            ({"account_status": "SUSPENDED"}, "status changed"),
            ({"version": 9}, "version changed"),
        ],
    )
    def test_each_drift_kind_rejects_before_any_write(
        self,
        drift,
        expected_message,
    ):
        rows = [merchant_row(merchant_id=MERCHANT_ID, code="ONE")]
        entity_repository, cursor, transaction_context = (
            self._batch_repository(rows)
        )

        entry = manifest_entry(merchant_id=MERCHANT_ID, code="ONE")
        entry.update(drift)

        with pytest.raises(MerchantConflictError, match=expected_message):
            entity_repository.activate_merchants_batch(
                from_status="ONBOARDING",
                expected_count=1,
                reason="Drift rejection",
                manifest=[entry],
            )

        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []
        assert transaction_context.exception_type is MerchantConflictError

    def test_count_drift_rejects_before_manifest_comparison(self):
        rows = [
            merchant_row(merchant_id=MERCHANT_ID, code="ONE"),
            merchant_row(merchant_id=SECOND_MERCHANT_ID, code="TWO"),
        ]
        entity_repository, cursor, _ = self._batch_repository(rows)

        with pytest.raises(MerchantConflictError, match="Expected 1 merchants"):
            entity_repository.activate_merchants_batch(
                from_status="ONBOARDING",
                expected_count=1,
                reason="Count drift",
                manifest=[manifest_entry(merchant_id=MERCHANT_ID, code="ONE")],
            )

        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []

    def test_missing_manifest_is_rejected_before_connection(self):
        entity_repository, cursor, _ = self._batch_repository([])

        with pytest.raises(MerchantConflictError, match="exact manifest"):
            entity_repository.activate_merchants_batch(
                from_status="ONBOARDING",
                expected_count=1,
                reason="No manifest",
                manifest=None,
            )

        cursor.execute.assert_not_called()

    def test_manifest_length_drift_rejects_before_any_write(self):
        rows = [merchant_row(merchant_id=MERCHANT_ID, code="ONE")]
        entity_repository, cursor, _ = self._batch_repository(rows)

        with pytest.raises(MerchantConflictError, match="Manifest contains"):
            entity_repository.activate_merchants_batch(
                from_status="ONBOARDING",
                expected_count=1,
                reason="Manifest length drift",
                manifest=[
                    manifest_entry(merchant_id=MERCHANT_ID, code="ONE"),
                    manifest_entry(
                        merchant_id=SECOND_MERCHANT_ID,
                        code="TWO",
                    ),
                ],
            )

        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []


class TestWorkflowActivationInCursor:
    """Workflow activation runs on the caller's cursor and writes one event."""

    def test_workflow_activation_records_authorizing_project_provenance(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = merchant_row()
        cursor.rowcount = 1
        step = workflow_step_record()

        result = activate_merchant_in_workflow_transaction(
            cursor,
            MERCHANT_ID,
            1,
            workflow_project_record(),
            step,
            [step, predecessor_record()],
            [blocking_dependency()],
        )

        assert result["success"] is True
        assert result["merchant_id"] == MERCHANT_ID
        assert result["project_id"] == PROJECT_ID
        assert result["template_id"] == TEMPLATE_ID
        assert result["template_step_id"] == ACTIVATE_TEMPLATE_STEP_ID
        assert result["previous_status"] == "ONBOARDING"
        assert result["current_status"] == "ACTIVE"
        assert result["previous_version"] == 1
        assert result["current_version"] == 2
        assert result["event_type"] == "MERCHANT_ACTIVATED"

        assert len(statements_starting_with(cursor, MERCHANT_UPDATE)) == 1
        assert len(event_calls(cursor)) == 1

        parameters = event_calls(cursor)[0].args[1]
        assert parameters[EVENT_MERCHANT_ID] == uuid.UUID(MERCHANT_ID)
        # project_events_valid_entity_check requires project_id IS NULL for
        # MERCHANT events; the project is recorded in new_values instead.
        assert parameters[EVENT_PROJECT_ID] is None
        assert parameters[EVENT_ENTITY_ID] == uuid.UUID(MERCHANT_ID)
        assert parameters[EVENT_TRIGGERED_BY] is None
        assert parameters[EVENT_OLD_VALUES].obj == {
            "account_status": "ONBOARDING",
            "version": 1,
        }

        new_values = parameters[EVENT_NEW_VALUES].obj
        assert new_values["account_status"] == "ACTIVE"
        assert new_values["version"] == 2
        assert "INTEGRATION_NEW_MERCHANT_STANDARD" in new_values["reason"]
        assert "activate_merchant" in new_values["reason"]
        assert new_values["project_id"] == PROJECT_ID
        assert new_values["workflow_template_id"] == TEMPLATE_ID
        assert new_values["workflow_template_step_id"] == (
            ACTIVATE_TEMPLATE_STEP_ID
        )
        assert new_values["workflow_template_step_name"] == (
            "activate_merchant"
        )

        lock_query = " ".join(cursor.execute.call_args_list[0].args[0].split())
        assert "FOR UPDATE" in lock_query
        assert cursor.execute.call_args_list[0].args[1] == (
            uuid.UUID(MERCHANT_ID),
        )

    def test_forged_template_step_writes_nothing(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = merchant_row()
        cursor.rowcount = 1
        step = workflow_step_record(
            template_step_id=FOREIGN_TEMPLATE_STEP_ID,
            step_name="Activate Merchant",
        )

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="is not the canonical",
        ):
            activate_merchant_in_workflow_transaction(
                cursor,
                MERCHANT_ID,
                1,
                workflow_project_record(),
                step,
                [step],
            )

        cursor.execute.assert_not_called()

    def test_unmet_dependency_writes_nothing(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = merchant_row()
        cursor.rowcount = 1
        step = workflow_step_record()

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="has not completed",
        ):
            activate_merchant_in_workflow_transaction(
                cursor,
                MERCHANT_ID,
                1,
                workflow_project_record(),
                step,
                [step, predecessor_record(status="IN_PROGRESS")],
                [blocking_dependency()],
            )

        cursor.execute.assert_not_called()

    def test_merchant_version_drift_raises_before_update(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = merchant_row(version=4)
        cursor.rowcount = 1
        step = workflow_step_record()

        with pytest.raises(MerchantVersionConflictError):
            activate_merchant_in_workflow_transaction(
                cursor,
                MERCHANT_ID,
                1,
                workflow_project_record(),
                step,
                [step],
            )

        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []

    def test_already_active_merchant_raises_before_update(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = merchant_row(account_status="ACTIVE")
        cursor.rowcount = 1
        step = workflow_step_record()

        with pytest.raises(MerchantConflictError):
            activate_merchant_in_workflow_transaction(
                cursor,
                MERCHANT_ID,
                1,
                workflow_project_record(),
                step,
                [step],
            )

        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []

    def test_zero_update_rowcount_raises_before_event(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = merchant_row()
        cursor.rowcount = 0
        step = workflow_step_record()

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="expected exactly 1",
        ):
            activate_merchant_in_workflow_transaction(
                cursor,
                MERCHANT_ID,
                1,
                workflow_project_record(),
                step,
                [step],
            )

        assert len(statements_starting_with(cursor, MERCHANT_UPDATE)) == 1
        assert event_calls(cursor) == []

    def test_missing_merchant_raises_before_update(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        step = workflow_step_record()

        with pytest.raises(
            WorkflowActivationIntegrationError,
            match="not found",
        ):
            activate_merchant_in_workflow_transaction(
                cursor,
                MERCHANT_ID,
                1,
                workflow_project_record(),
                step,
                [step],
            )

        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []


class TestStepTransitionLoadsPersistedIdentity:
    """The transition repository loads the persisted authorization joins."""

    def _prepare(self, cursor, *, steps, dependencies=(), merchant=None):
        cursor.fetchone.side_effect = [
            workflow_project_record(),
            merchant if merchant is not None else merchant_row(),
        ]
        cursor.fetchall.side_effect = [list(steps), list(dependencies)]
        cursor.rowcount = 1

    def test_project_query_joins_template_and_merchant(self):
        transition_repository, cursor, _ = make_transition_repository()
        step = workflow_step_record()
        self._prepare(cursor, steps=[step])

        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            gate_required=True,
            gate_result=successful_gate(),
        )

        project_query = " ".join(
            cursor.execute.call_args_list[0].args[0].split()
        )

        assert "JOIN merchant_ops.workflow_templates AS template" in (
            project_query
        )
        assert "JOIN merchant_ops.merchants AS merchant" in project_query
        for column in (
            "project.project_type",
            "project.workflow_template_version_id",
            "template.id AS template_id",
            "template.name AS template_name",
            "template.variant AS template_variant",
            "template.version AS template_version",
            "merchant.id AS merchant_row_id",
            "merchant.version AS merchant_version",
        ):
            assert column in project_query

        step_query = " ".join(
            cursor.execute.call_args_list[1].args[0].split()
        )

        assert (
            "JOIN merchant_ops.workflow_template_steps AS template_step"
            in step_query
        )
        for column in (
            "step.template_step_id",
            "template_step.id AS template_step_row_id",
            "template_step.template_id AS template_step_template_id",
            "template_step.name AS template_step_name",
        ):
            assert column in step_query

    def test_completion_activates_merchant_in_same_transaction(self):
        transition_repository, cursor, transaction_context = (
            make_transition_repository()
        )
        step = workflow_step_record()
        predecessor = predecessor_record()
        self._prepare(
            cursor,
            steps=[predecessor, step],
            dependencies=[blocking_dependency()],
        )

        result = transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            triggered_by=TRIGGERED_BY,
            gate_required=True,
            gate_result=successful_gate(),
        )

        assert result.current_status == "COMPLETED"
        assert result.event_type == "STEP_COMPLETED"
        assert transaction_context.exception_type is None

        assert len(statements_starting_with(cursor, STEP_UPDATE)) == 1
        assert len(statements_starting_with(cursor, MERCHANT_UPDATE)) == 1

        events = event_calls(cursor)
        assert len(events) == 2

        merchant_event, step_event = events
        assert merchant_event.args[1][EVENT_TYPE] == "MERCHANT_ACTIVATED"
        assert merchant_event.args[1][EVENT_PROJECT_ID] is None
        assert merchant_event.args[1][EVENT_NEW_VALUES].obj["project_id"] == (
            PROJECT_ID
        )
        assert merchant_event.args[1][EVENT_TRIGGERED_BY] is None
        assert "'MERCHANT'" in " ".join(merchant_event.args[0].split())

        assert step_event.args[1][EVENT_TYPE] == "STEP_COMPLETED"
        assert "'STEP'" in " ".join(step_event.args[0].split())

        # The merchant activation must happen before the step event so a
        # failed activation cannot leave a step event behind.
        sql = executed_sql(cursor)
        merchant_update_index = next(
            index
            for index, statement in enumerate(sql)
            if statement.startswith(MERCHANT_UPDATE)
        )
        step_update_index = next(
            index
            for index, statement in enumerate(sql)
            if statement.startswith(STEP_UPDATE)
        )
        assert step_update_index < merchant_update_index < len(sql) - 1

    def test_non_completion_transition_does_not_touch_merchant(self):
        transition_repository, cursor, _ = make_transition_repository()
        step = workflow_step_record(status="READY", actual_start=None)
        self._prepare(cursor, steps=[step])

        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            gate_required=True,
            gate_result=successful_gate(),
        )

        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert len(event_calls(cursor)) == 1

    def test_activation_conflict_rolls_back_step_and_events(self):
        transition_repository, cursor, transaction_context = (
            make_transition_repository()
        )
        step = workflow_step_record()
        self._prepare(
            cursor,
            steps=[step],
            merchant=merchant_row(account_status="ACTIVE"),
        )

        with pytest.raises(MerchantConflictError):
            transition_repository.transition_step(
                step_id=STEP_ID,
                target_status="COMPLETED",
                expected_version=1,
                occurred_at=OCCURRED_AT,
                gate_required=True,
                gate_result=successful_gate(),
            )

        assert transaction_context.exception_type is MerchantConflictError
        assert len(statements_starting_with(cursor, STEP_UPDATE)) == 1
        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []

    def test_unmet_dependency_rolls_back_before_step_or_merchant_write(self):
        transition_repository, cursor, transaction_context = (
            make_transition_repository()
        )
        step = workflow_step_record()
        self._prepare(
            cursor,
            steps=[predecessor_record(status="IN_PROGRESS"), step],
            dependencies=[blocking_dependency()],
        )

        with pytest.raises(WorkflowDependencyNotMetError):
            transition_repository.transition_step(
                step_id=STEP_ID,
                target_status="COMPLETED",
                expected_version=1,
                occurred_at=OCCURRED_AT,
                gate_required=True,
                gate_result=successful_gate(),
            )

        assert transaction_context.exception_type is (
            WorkflowDependencyNotMetError
        )
        assert statements_starting_with(cursor, STEP_UPDATE) == []
        assert statements_starting_with(cursor, MERCHANT_UPDATE) == []
        assert event_calls(cursor) == []
