"""Tests for pure integration identifier mutation planning."""

from __future__ import annotations

import pytest

from claude.agents.tools.merchant.identifier_engine import (
    IDENTIFIER_SCOPES,
    IDENTIFIER_TYPES,
    MAX_IDENTIFIER_VALUE_LENGTH,
    IdentifierConflictError,
    IdentifierEngineError,
    IdentifierVersionConflictError,
    propose_identifier_mutation,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
IDENTIFIER_ID = "00000000-0000-0000-0000-000000000003"
OTHER_ID = "00000000-0000-0000-0000-000000000004"
TRIGGERED_BY = "00000000-0000-0000-0000-000000000005"
PRIVATE_VALUE = "private-product-id"


def current_identifier(**overrides):
    record = {
        "id": IDENTIFIER_ID,
        "merchant_id": MERCHANT_ID,
        "project_id": PROJECT_ID,
        "identifier_type": "PRODUCT_ID",
        "identifier_value": PRIVATE_VALUE,
        "scope": "UAT",
        "is_active": True,
        "version": 3,
    }
    record.update(overrides)
    return record


def mutation_arguments(**overrides):
    arguments = {
        "merchant_id": MERCHANT_ID,
        "project_id": PROJECT_ID,
        "identifier_type": "PRODUCT_ID",
        "identifier_value": PRIVATE_VALUE,
        "scope": "UAT",
        "current_identifier": None,
        "identifier_id": IDENTIFIER_ID,
        "triggered_by": TRIGGERED_BY,
    }
    arguments.update(overrides)
    return arguments


def test_identifier_contract_matches_schema():
    assert IDENTIFIER_TYPES == {
        "AGENT",
        "MASTER_MID",
        "MID",
        "MERCHANT_CODE",
        "PARTNER_CODE",
        "PRODUCT_ID",
        "ORDER_GROUP_ID",
        "STORE_ID",
        "JIRA_TICKET",
    }
    assert IDENTIFIER_SCOPES == {
        "MASTER",
        "UAT",
        "PRODUCTION",
    }


def test_new_identifier_is_normalized_and_planned():
    plan = propose_identifier_mutation(
        **mutation_arguments(
            identifier_type=" product_id ",
            identifier_value=f" {PRIVATE_VALUE} ",
            scope=" uat ",
        )
    )

    assert plan.identifier_id == IDENTIFIER_ID
    assert plan.merchant_id == MERCHANT_ID
    assert plan.project_id == PROJECT_ID
    assert plan.identifier_type == "PRODUCT_ID"
    assert plan.identifier_value == PRIVATE_VALUE
    assert plan.scope == "UAT"
    assert plan.is_active is True
    assert plan.current_version is None
    assert plan.new_version == 1
    assert plan.operation == "INSERT"
    assert plan.triggered_by == TRIGGERED_BY
    assert plan.event_type == "INTEGRATION_IDENTIFIER_SET"


def test_merchant_scoped_identifier_supports_null_project():
    plan = propose_identifier_mutation(
        **mutation_arguments(
            project_id=None,
            identifier_type="MASTER_MID",
            scope="MASTER",
        )
    )

    assert plan.project_id is None
    assert plan.identifier_type == "MASTER_MID"
    assert plan.scope == "MASTER"


def test_identifier_audit_metadata_never_contains_value():
    plan = propose_identifier_mutation(
        **mutation_arguments()
    )
    encoded = repr(
        {
            "summary": plan.change_summary,
            "old": plan.old_values,
            "new": plan.new_values,
        }
    )

    assert PRIVATE_VALUE not in encoded
    assert "identifier_value" not in encoded
    assert plan.new_values["value_recorded"] is True
    assert plan.new_values["value_changed"] is True


def test_existing_identifier_requires_version_and_updates():
    plan = propose_identifier_mutation(
        **mutation_arguments(
            current_identifier=current_identifier(),
            identifier_id=None,
            identifier_value="updated-private-product-id",
            expected_version=3,
            is_active=False,
        )
    )

    assert plan.identifier_id == IDENTIFIER_ID
    assert plan.current_version == 3
    assert plan.new_version == 4
    assert plan.operation == "UPDATE"
    assert plan.is_active is False
    assert plan.new_values["value_changed"] is True


@pytest.mark.parametrize(
    "expected_version",
    (None, True, 0, -1, "3"),
)
def test_existing_identifier_rejects_invalid_version(
    expected_version,
):
    with pytest.raises(IdentifierEngineError):
        propose_identifier_mutation(
            **mutation_arguments(
                current_identifier=current_identifier(),
                identifier_id=None,
                identifier_value="updated-value",
                expected_version=expected_version,
            )
        )


def test_stale_identifier_version_is_rejected():
    with pytest.raises(
        IdentifierVersionConflictError,
        match="version changed",
    ):
        propose_identifier_mutation(
            **mutation_arguments(
                current_identifier=current_identifier(),
                identifier_id=None,
                identifier_value="updated-value",
                expected_version=2,
            )
        )


def test_new_identifier_rejects_expected_version():
    with pytest.raises(
        IdentifierConflictError,
        match="does not exist",
    ):
        propose_identifier_mutation(
            **mutation_arguments(expected_version=1)
        )


def test_no_op_identifier_update_is_rejected():
    with pytest.raises(
        IdentifierConflictError,
        match="does not change",
    ):
        propose_identifier_mutation(
            **mutation_arguments(
                current_identifier=current_identifier(),
                identifier_id=None,
                expected_version=3,
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("merchant_id", "not-a-uuid"),
        ("project_id", "not-a-uuid"),
        ("identifier_id", "not-a-uuid"),
        ("triggered_by", "not-a-uuid"),
    ),
)
def test_invalid_uuid_is_rejected(field, value):
    with pytest.raises(IdentifierEngineError, match=field):
        propose_identifier_mutation(
            **mutation_arguments(**{field: value})
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("identifier_type", "OTHER"),
        ("identifier_type", None),
        ("scope", "STAGING"),
        ("scope", None),
        ("identifier_value", ""),
        ("identifier_value", None),
        (
            "identifier_value",
            "x" * (MAX_IDENTIFIER_VALUE_LENGTH + 1),
        ),
        ("is_active", "true"),
    ),
)
def test_invalid_identifier_field_is_rejected(field, value):
    with pytest.raises(IdentifierEngineError):
        propose_identifier_mutation(
            **mutation_arguments(**{field: value})
        )


@pytest.mark.parametrize(
    "override",
    (
        {"merchant_id": OTHER_ID},
        {"project_id": OTHER_ID},
        {"identifier_type": "MID"},
        {"scope": "PRODUCTION"},
    ),
)
def test_current_identifier_must_match_binding(override):
    with pytest.raises(
        IdentifierConflictError,
        match="different binding",
    ):
        propose_identifier_mutation(
            **mutation_arguments(
                current_identifier=current_identifier(
                    **override
                ),
                identifier_id=None,
                identifier_value="updated-value",
                expected_version=3,
            )
        )


def test_requested_id_must_match_current_binding():
    with pytest.raises(
        IdentifierConflictError,
        match="identifier ID",
    ):
        propose_identifier_mutation(
            **mutation_arguments(
                current_identifier=current_identifier(),
                identifier_id=OTHER_ID,
                identifier_value="updated-value",
                expected_version=3,
            )
        )
