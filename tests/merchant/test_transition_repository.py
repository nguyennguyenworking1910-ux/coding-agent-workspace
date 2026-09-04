"""Tests for atomic Merchant step-transition persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from claude.agents.tools.merchant.engine import (
    WorkflowDependencyNotMetError,
    WorkflowGateNotMetError,
    WorkflowStepNotFoundError,
    WorkflowVersionConflictError,
)
from claude.agents.tools.merchant.gates import (
    GateValidationResult,
)
from claude.clients.merchant.transition_repository import (
    MerchantStepTransitionRepository,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
STEP_ID = "00000000-0000-0000-0000-000000000003"
SOURCE_ID = "00000000-0000-0000-0000-000000000004"
TEMPLATE_STEP_ID = (
    "00000000-0000-0000-0000-000000000005"
)
TRIGGERED_BY = "00000000-0000-0000-0000-000000000006"

OCCURRED_AT = datetime(
    2026,
    9,
    4,
    9,
    0,
    tzinfo=timezone.utc,
)
EARLIER = datetime(
    2026,
    9,
    4,
    8,
    0,
    tzinfo=timezone.utc,
)
DOCUMENT_REVISION_ID = (
    "00000000-0000-0000-0000-000000000008"
)
APPROVAL_ID = (
    "00000000-0000-0000-0000-000000000009"
)
LEGAL_APPROVAL_ID = (
    "00000000-0000-0000-0000-000000000010"
)
ACCOUNTING_APPROVAL_ID = (
    "00000000-0000-0000-0000-000000000011"
)
PROCUREMENT_ID = (
    "00000000-0000-0000-0000-000000000012"
)


def approval_record(
    role,
    approval_id,
):
    return {
        "id": approval_id,
        "document_revision_id":
            DOCUMENT_REVISION_ID,
        "approver_role": role,
        "approval_status": "APPROVED",
        "approved_at": OCCURRED_AT,
        "notes": None,
    }


def signing_approvals():
    return [
        approval_record(
            "LEGAL",
            LEGAL_APPROVAL_ID,
        ),
        approval_record(
            "ACCOUNTING",
            ACCOUNTING_APPROVAL_ID,
        ),
        approval_record(
            "PARTNER",
            APPROVAL_ID,
        ),
    ]


def purchase_request_record():
    return {
        "id": PROCUREMENT_ID,
        "project_id": PROJECT_ID,
        "procurement_type": "PURCHASE_REQUEST",
        "external_id": "PR-2026-001",
        "status": "CREATED",
        "created_at": EARLIER,
        "updated_at": OCCURRED_AT,
        "version": 1,
    }

def document_revision():
    return {
        "id": DOCUMENT_REVISION_ID,
        "project_id": PROJECT_ID,
        "document_type": "MASTER_AGREEMENT",
        "revision_number": 1,
        "content_hash": "safe-content-hash",
        "signed": False,
        "signed_at": None,
        "effective_date": None,
        "expiry_date": None,
        "superseded_by": None,
        "created_at": OCCURRED_AT,
    }


def partner_approval():
    return {
        "id": APPROVAL_ID,
        "document_revision_id": DOCUMENT_REVISION_ID,
        "approver_role": "PARTNER",
        "approval_status": "APPROVED",
        "approved_at": OCCURRED_AT,
        "notes": None,
    }

class RecordingContext:
    def __init__(self, value):
        self.value = value
        self.entered = False
        self.exception_type = None

    def __enter__(self):
        self.entered = True
        return self.value

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ):
        self.exception_type = exception_type
        return False


def make_transition_repository():
    repository = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    connection_context = RecordingContext(connection)
    transaction_context = RecordingContext(None)
    cursor_context = RecordingContext(cursor)

    repository.connection.return_value = (
        connection_context
    )
    connection.transaction.return_value = (
        transaction_context
    )
    connection.cursor.return_value = cursor_context

    transition_repository = (
        MerchantStepTransitionRepository(repository)
    )

    return (
        transition_repository,
        repository,
        connection,
        cursor,
        transaction_context,
    )


def project_record(
    *,
    requires_procurement=False,
):
    return {
        "id": PROJECT_ID,
        "merchant_id": MERCHANT_ID,
        "requires_procurement":
            requires_procurement,
    }


def step_record(
    *,
    step_id=STEP_ID,
    status="READY",
    version=1,
    actual_start=None,
    actual_completion=None,
    step_type="SEQUENTIAL",
    step_name="Test step",
):
    return {
        "id": step_id,
        "project_id": PROJECT_ID,
        "template_step_id": TEMPLATE_STEP_ID,
        "branch_key": None,
        "step_name": step_name,
        "step_type": step_type,
        "status": status,
        "sequence_number": 1,
        "actual_start": actual_start,
        "actual_completion": actual_completion,
        "version": version,
    }


def dependency_record():
    return {
        "id": (
            "00000000-0000-0000-0000-000000000007"
        ),
        "from_step_id": SOURCE_ID,
        "to_step_id": STEP_ID,
        "dependency_type": "MUST_COMPLETE_BEFORE",
    }


def prepare_snapshot(
    cursor,
    *,
    steps,
    dependencies=(),
):
    cursor.fetchone.return_value = project_record()
    cursor.fetchall.side_effect = [
        list(steps),
        list(dependencies),
    ]
    cursor.rowcount = 1


def executed_sql(cursor):
    return [
        " ".join(call.args[0].split())
        for call in cursor.execute.call_args_list
    ]


def successful_gate():
    return GateValidationResult(
        gate_name="TEST_GATE",
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


def failed_gate():
    return GateValidationResult(
        gate_name="TEST_GATE",
        project_id=PROJECT_ID,
        document_revision_id=None,
        all_met=False,
        blocking_codes=("MISSING_APPROVAL",),
        approved_roles=(),
        missing_roles=("LEGAL",),
        requires_procurement=False,
        purchase_request_present=False,
        already_signed=False,
    )


def test_ready_step_is_started_and_audited():
    (
        transition_repository,
        repository,
        connection,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[
            step_record(
                status="READY",
                version=1,
            )
        ],
    )

    result = transition_repository.transition_step(
        step_id=STEP_ID,
        target_status="IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
        triggered_by=TRIGGERED_BY,
    )

    assert result.project_id == PROJECT_ID
    assert result.step_id == STEP_ID
    assert result.previous_status == "READY"
    assert result.current_status == "IN_PROGRESS"
    assert result.previous_version == 1
    assert result.current_version == 2
    assert result.event_type == "STEP_STARTED"

    repository.connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    assert transaction_context.entered
    assert transaction_context.exception_type is None

    sql = executed_sql(cursor)
    combined = "\n".join(sql)

    assert "FOR UPDATE OF project" in combined
    assert (
        "FROM merchant_ops.project_steps AS step"
        in combined
    )
    assert (
        "JOIN merchant_ops.workflow_template_steps "
        "AS template_step"
        in combined
    )
    assert (
        "template_step.id = step.template_step_id"
        in combined
    )
    assert "WHERE step.project_id = %s" in combined
    assert "FOR UPDATE OF step" in combined
    assert combined.count(
        "UPDATE merchant_ops.project_steps"
    ) == 1
    assert combined.count(
        "INSERT INTO merchant_ops.project_events"
    ) == 1


def test_event_is_inserted_after_step_update():
    (
        transition_repository,
        _,
        _,
        cursor,
        _,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[step_record()],
    )

    transition_repository.transition_step(
        step_id=STEP_ID,
        target_status="IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    sql = executed_sql(cursor)
    update_index = next(
        index
        for index, query in enumerate(sql)
        if query.startswith(
            "UPDATE merchant_ops.project_steps"
        )
    )
    event_index = next(
        index
        for index, query in enumerate(sql)
        if query.startswith(
            "INSERT INTO merchant_ops.project_events"
        )
    )

    assert event_index == update_index + 1
    assert event_index == len(sql) - 1


def test_completed_dependency_allows_transition():
    (
        transition_repository,
        _,
        _,
        cursor,
        _,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[
            step_record(
                step_id=SOURCE_ID,
                status="COMPLETED",
                actual_completion=EARLIER,
            ),
            step_record(status="READY"),
        ],
        dependencies=[dependency_record()],
    )

    result = transition_repository.transition_step(
        step_id=STEP_ID,
        target_status="IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert result.current_status == "IN_PROGRESS"


def test_unmet_dependency_rolls_back_without_update():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[
            step_record(
                step_id=SOURCE_ID,
                status="IN_PROGRESS",
                actual_start=EARLIER,
            ),
            step_record(status="READY"),
        ],
        dependencies=[dependency_record()],
    )

    with pytest.raises(
        WorkflowDependencyNotMetError
    ):
        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

    assert transaction_context.exception_type is (
        WorkflowDependencyNotMetError
    )

    combined = "\n".join(executed_sql(cursor))
    assert "UPDATE merchant_ops.project_steps" not in (
        combined
    )
    assert "INSERT INTO merchant_ops.project_events" not in (
        combined
    )


def test_stale_expected_version_rolls_back_without_update():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[
            step_record(
                status="READY",
                version=2,
            )
        ],
    )

    with pytest.raises(
        WorkflowVersionConflictError
    ):
        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

    assert transaction_context.exception_type is (
        WorkflowVersionConflictError
    )
    assert "UPDATE merchant_ops.project_steps" not in (
        "\n".join(executed_sql(cursor))
    )


def test_zero_update_rowcount_rolls_back_without_event():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[step_record()],
    )
    cursor.rowcount = 0

    with pytest.raises(
        WorkflowVersionConflictError,
        match="changed before",
    ):
        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

    assert transaction_context.exception_type is (
        WorkflowVersionConflictError
    )

    combined = "\n".join(executed_sql(cursor))
    assert "UPDATE merchant_ops.project_steps" in combined
    assert "INSERT INTO merchant_ops.project_events" not in (
        combined
    )


def test_missing_step_rolls_back_before_other_queries():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    cursor.fetchone.return_value = None

    with pytest.raises(WorkflowStepNotFoundError):
        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="IN_PROGRESS",
            expected_version=1,
            occurred_at=OCCURRED_AT,
        )

    assert transaction_context.exception_type is (
        WorkflowStepNotFoundError
    )
    assert len(cursor.execute.call_args_list) == 1

def test_stored_approval_gate_cannot_bypass_validation():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[
            step_record(
                status="IN_PROGRESS",
                actual_start=EARLIER,
                step_type="APPROVAL_GATE",
            )
        ],
    )

    with pytest.raises(WorkflowGateNotMetError):
        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            # Intentionally omit gate_required.
            # Stored template metadata must force it.
        )

    assert transaction_context.exception_type is (
        WorkflowGateNotMetError
    )

    combined = "\n".join(executed_sql(cursor))

    assert "UPDATE merchant_ops.project_steps" not in (
        combined
    )
    assert "INSERT INTO merchant_ops.project_events" not in (
        combined
    )

def test_failed_required_gate_rolls_back_without_update():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[
            step_record(
                status="IN_PROGRESS",
                actual_start=EARLIER,
            )
        ],
    )

    with pytest.raises(WorkflowGateNotMetError):
        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            gate_required=True,
            gate_result=failed_gate(),
        )

    assert transaction_context.exception_type is (
        WorkflowGateNotMetError
    )

    combined = "\n".join(executed_sql(cursor))
    assert "UPDATE merchant_ops.project_steps" not in (
        combined
    )
    assert "INSERT INTO merchant_ops.project_events" not in (
        combined
    )


def test_successful_gate_allows_atomic_completion():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[
            step_record(
                status="IN_PROGRESS",
                actual_start=EARLIER,
            )
        ],
    )

    result = transition_repository.transition_step(
        step_id=STEP_ID,
        target_status="COMPLETED",
        expected_version=1,
        occurred_at=OCCURRED_AT,
        gate_required=True,
        gate_result=successful_gate(),
    )

    assert result.current_status == "COMPLETED"
    assert result.current_version == 2
    assert result.event_type == "STEP_COMPLETED"
    assert transaction_context.exception_type is None

    combined = "\n".join(executed_sql(cursor))
    assert combined.count(
        "UPDATE merchant_ops.project_steps"
    ) == 1
    assert combined.count(
        "INSERT INTO merchant_ops.project_events"
    ) == 1


def test_explicit_reopen_is_persisted():
    (
        transition_repository,
        _,
        _,
        cursor,
        _,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[
            step_record(
                status="COMPLETED",
                actual_start=EARLIER,
                actual_completion=OCCURRED_AT,
            )
        ],
    )

    result = transition_repository.transition_step(
        step_id=STEP_ID,
        target_status="READY",
        expected_version=1,
        occurred_at=OCCURRED_AT,
        allow_reopen=True,
    )

    assert result.previous_status == "COMPLETED"
    assert result.current_status == "READY"
    assert result.event_type == "STEP_REOPENED"


def test_result_is_json_compatible():
    (
        transition_repository,
        _,
        _,
        cursor,
        _,
    ) = make_transition_repository()

    prepare_snapshot(
        cursor,
        steps=[step_record()],
    )

    result = transition_repository.transition_step(
        step_id=STEP_ID,
        target_status="IN_PROGRESS",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert result.to_dict() == {
        "project_id": PROJECT_ID,
        "step_id": STEP_ID,
        "previous_status": "READY",
        "current_status": "IN_PROGRESS",
        "previous_version": 1,
        "current_version": 2,
        "event_id": result.event_id,
        "event_type": "STEP_STARTED",
    }

def test_persisted_gate_ignores_forged_success_result():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    cursor.fetchone.return_value = project_record()
    cursor.fetchall.side_effect = [
        [
            step_record(
                status="IN_PROGRESS",
                actual_start=EARLIER,
                step_type="APPROVAL_GATE",
                step_name="Record Partner approval",
            )
        ],
        [],
        [document_revision()],
        [],
        [],
    ]
    cursor.rowcount = 1

    with pytest.raises(WorkflowGateNotMetError):
        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            gate_result=successful_gate(),
        )

    assert transaction_context.exception_type is (
        WorkflowGateNotMetError
    )

    combined = "\n".join(executed_sql(cursor))

    assert "FROM merchant_ops.document_revisions" in (
        combined
    )
    assert "FROM merchant_ops.document_approvals" in (
        combined
    )
    assert "FROM merchant_ops.procurement_records" in (
        combined
    )
    assert "UPDATE merchant_ops.project_steps" not in (
        combined
    )
    assert "INSERT INTO merchant_ops.project_events" not in (
        combined
    )


def test_persisted_partner_approval_allows_completion():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    cursor.fetchone.return_value = project_record()
    cursor.fetchall.side_effect = [
        [
            step_record(
                status="IN_PROGRESS",
                actual_start=EARLIER,
                step_type="APPROVAL_GATE",
                step_name="Record Partner approval",
            )
        ],
        [],
        [document_revision()],
        [partner_approval()],
        [],
    ]
    cursor.rowcount = 1

    result = transition_repository.transition_step(
        step_id=STEP_ID,
        target_status="COMPLETED",
        expected_version=1,
        occurred_at=OCCURRED_AT,
        # No caller-provided gate result.
    )

    assert result.previous_status == "IN_PROGRESS"
    assert result.current_status == "COMPLETED"
    assert result.previous_version == 1
    assert result.current_version == 2
    assert result.event_type == "STEP_COMPLETED"
    assert transaction_context.exception_type is None

    combined = "\n".join(executed_sql(cursor))

    assert "FROM merchant_ops.document_revisions" in (
        combined
    )
    assert "FROM merchant_ops.document_approvals" in (
        combined
    )
    assert "UPDATE merchant_ops.project_steps" in (
        combined
    )
    assert "INSERT INTO merchant_ops.project_events" in (
        combined
    )

def test_persisted_signing_gate_rejects_missing_purchase_request():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    cursor.fetchone.return_value = project_record(
        requires_procurement=True
    )
    cursor.fetchall.side_effect = [
        [
            step_record(
                status="IN_PROGRESS",
                actual_start=EARLIER,
                step_type="APPROVAL_GATE",
                step_name="Validate signing gate",
            )
        ],
        [],
        [document_revision()],
        signing_approvals(),
        [],
    ]
    cursor.rowcount = 1

    with pytest.raises(WorkflowGateNotMetError):
        transition_repository.transition_step(
            step_id=STEP_ID,
            target_status="COMPLETED",
            expected_version=1,
            occurred_at=OCCURRED_AT,
            gate_result=successful_gate(),
        )

    assert transaction_context.exception_type is (
        WorkflowGateNotMetError
    )

    combined = "\n".join(executed_sql(cursor))

    assert "FROM merchant_ops.document_revisions" in (
        combined
    )
    assert "FROM merchant_ops.document_approvals" in (
        combined
    )
    assert "FROM merchant_ops.procurement_records" in (
        combined
    )
    assert "UPDATE merchant_ops.project_steps" not in (
        combined
    )
    assert "INSERT INTO merchant_ops.project_events" not in (
        combined
    )


def test_persisted_signing_gate_passes_with_all_evidence():
    (
        transition_repository,
        _,
        _,
        cursor,
        transaction_context,
    ) = make_transition_repository()

    cursor.fetchone.return_value = project_record(
        requires_procurement=True
    )
    cursor.fetchall.side_effect = [
        [
            step_record(
                status="IN_PROGRESS",
                actual_start=EARLIER,
                step_type="APPROVAL_GATE",
                step_name="Validate signing gate",
            )
        ],
        [],
        [document_revision()],
        signing_approvals(),
        [purchase_request_record()],
    ]
    cursor.rowcount = 1

    result = transition_repository.transition_step(
        step_id=STEP_ID,
        target_status="COMPLETED",
        expected_version=1,
        occurred_at=OCCURRED_AT,
    )

    assert result.previous_status == "IN_PROGRESS"
    assert result.current_status == "COMPLETED"
    assert result.previous_version == 1
    assert result.current_version == 2
    assert result.event_type == "STEP_COMPLETED"
    assert transaction_context.exception_type is None

    combined = "\n".join(executed_sql(cursor))

    assert "FOR SHARE OF revision" in combined
    assert "FOR SHARE OF approval, revision" in (
        combined
    )
    assert "FOR SHARE OF procurement" in combined
    assert "UPDATE merchant_ops.project_steps" in (
        combined
    )
    assert "INSERT INTO merchant_ops.project_events" in (
        combined
    )