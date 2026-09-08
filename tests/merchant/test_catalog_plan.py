"""Checkpoint 9.2 private catalog initialization planning tests."""

from __future__ import annotations

import inspect
import json

import pytest

from claude.agents.tools.merchant import catalog_plan
from claude.agents.tools.merchant.catalog_contract import (
    PrivateMerchantCatalog,
    validate_private_catalog_bytes,
)
from claude.agents.tools.merchant.catalog_plan import (
    CATALOG_INSERT,
    CATALOG_NO_OP,
    CatalogBindingError,
    CatalogPlanError,
    CatalogTargetConflictError,
    build_catalog_initialization_plan,
)


def _catalog_records() -> list[dict[str, object]]:
    return [
        {
            "code": f"CATALOG_{number:02d}",
            "name": f"Đối Tác Thử Nghiệm {number:02d}",
            "region_code": (
                "VN_S"
                if number % 2
                else None
            ),
            "account_status": (
                "ONBOARDING"
                if number <= 5
                else "ACTIVE"
            ),
        }
        for number in range(1, 23)
    ]


def _catalog() -> PrivateMerchantCatalog:
    encoded = json.dumps(
        _catalog_records(),
        ensure_ascii=False,
    ).encode("utf-8")
    return validate_private_catalog_bytes(encoded)


def _target_records(
    catalog: PrivateMerchantCatalog,
) -> list[dict[str, object]]:
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


def _plan(
    catalog: PrivateMerchantCatalog,
    existing_records,
):
    return build_catalog_initialization_plan(
        catalog,
        existing_records=existing_records,
        expected_source_sha256=catalog.source_sha256,
        expected_catalog_sha256=catalog.catalog_sha256,
    )


def _assert_no_private_values(
    rendered: str,
    catalog: PrivateMerchantCatalog,
) -> None:
    for record in catalog.records:
        assert record.code not in rendered
        assert record.name not in rendered
        assert record.merchant_id not in rendered


def test_empty_target_produces_atomic_insert_plan():
    catalog = _catalog()
    plan = _plan(catalog, [])

    assert plan.action == CATALOG_INSERT
    assert plan.records == catalog.records
    assert plan.record_count == 22
    assert plan.target_count_before == 0
    assert plan.target_count_after == 22
    assert plan.requires_authorization is True
    assert plan.status_counts == {
        "ACTIVE": 17,
        "ONBOARDING": 5,
    }
    assert len(plan.plan_sha256) == 64
    assert plan.safe_summary()["transaction_mode"] == (
        "SINGLE_ATOMIC_TRANSACTION"
    )


def test_identical_target_produces_verified_no_op():
    catalog = _catalog()
    existing = list(reversed(_target_records(catalog)))
    plan = _plan(catalog, existing)

    assert plan.action == CATALOG_NO_OP
    assert plan.target_count_before == 22
    assert plan.target_count_after == 22
    assert plan.requires_authorization is False
    assert plan.safe_summary()["action"] == "NO_OP"


def test_plan_is_deterministic_for_equivalent_target_order():
    catalog = _catalog()
    forward = _plan(
        catalog,
        _target_records(catalog),
    )
    reverse = _plan(
        catalog,
        list(reversed(_target_records(catalog))),
    )

    assert forward == reverse
    assert forward.plan_sha256 == reverse.plan_sha256


def test_safe_summary_contains_only_counts_hashes_and_contract():
    catalog = _catalog()
    plan = _plan(catalog, [])
    encoded = json.dumps(
        plan.safe_summary(),
        sort_keys=True,
    )

    _assert_no_private_values(encoded, catalog)
    assert "records" not in plan.safe_summary()
    assert plan.safe_summary() == {
        "success": True,
        "plan_version": 1,
        "action": "INSERT",
        "record_count": 22,
        "status_counts": {
            "ACTIVE": 17,
            "ONBOARDING": 5,
        },
        "target_count_before": 0,
        "target_count_after": 22,
        "source_sha256": catalog.source_sha256,
        "catalog_sha256": catalog.catalog_sha256,
        "plan_sha256": plan.plan_sha256,
        "requires_authorization": True,
        "transaction_mode": "SINGLE_ATOMIC_TRANSACTION",
    }


def test_plan_and_record_representations_are_redacted():
    catalog = _catalog()
    plan = _plan(catalog, [])
    rendered = repr(plan)

    _assert_no_private_values(rendered, catalog)
    _assert_no_private_values(
        repr(plan.records[0]),
        catalog,
    )


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    (
        (
            "source",
            "0" * 64,
            "SOURCE_HASH_MISMATCH",
        ),
        (
            "catalog",
            "0" * 64,
            "CATALOG_HASH_MISMATCH",
        ),
    ),
)
def test_changed_reviewed_binding_fails_closed(
    field,
    value,
    reason_code,
):
    catalog = _catalog()
    arguments = {
        "existing_records": [],
        "expected_source_sha256": catalog.source_sha256,
        "expected_catalog_sha256": catalog.catalog_sha256,
    }
    arguments[
        f"expected_{field}_sha256"
    ] = value

    with pytest.raises(
        CatalogBindingError,
        match="does not match",
    ) as error:
        build_catalog_initialization_plan(
            catalog,
            **arguments,
        )

    assert error.value.reason_code == reason_code
    _assert_no_private_values(
        str(error.value),
        catalog,
    )


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    (
        (
            "expected_source_sha256",
            None,
            "INVALID_SOURCE_HASH",
        ),
        (
            "expected_source_sha256",
            "A" * 64,
            "INVALID_SOURCE_HASH",
        ),
        (
            "expected_catalog_sha256",
            "short",
            "INVALID_CATALOG_HASH",
        ),
    ),
)
def test_reviewed_hash_format_is_exact(
    field,
    value,
    reason_code,
):
    catalog = _catalog()
    arguments = {
        "existing_records": [],
        "expected_source_sha256": catalog.source_sha256,
        "expected_catalog_sha256": catalog.catalog_sha256,
    }
    arguments[field] = value

    with pytest.raises(
        CatalogBindingError,
        match="lowercase SHA-256",
    ) as error:
        build_catalog_initialization_plan(
            catalog,
            **arguments,
        )

    assert error.value.reason_code == reason_code


def test_unvalidated_catalog_is_rejected():
    with pytest.raises(
        CatalogPlanError,
        match="validated private catalog",
    ) as error:
        build_catalog_initialization_plan(
            object(),  # type: ignore[arg-type]
            existing_records=[],
            expected_source_sha256="0" * 64,
            expected_catalog_sha256="0" * 64,
        )

    assert error.value.reason_code == "INVALID_CATALOG"


@pytest.mark.parametrize(
    "existing_records",
    (
        None,
        "private-target",
        {"private": "target"},
    ),
)
def test_target_state_must_be_sequence_without_echo(
    existing_records,
):
    catalog = _catalog()

    with pytest.raises(
        CatalogTargetConflictError,
        match="must be a sequence",
    ) as error:
        _plan(catalog, existing_records)

    assert error.value.reason_code == "INVALID_TARGET_STATE"
    assert "private-target" not in str(error.value)


def test_partial_target_fails_closed_without_private_values():
    catalog = _catalog()
    existing = _target_records(catalog)[:21]

    with pytest.raises(
        CatalogTargetConflictError,
        match="neither empty nor identical",
    ) as error:
        _plan(catalog, existing)

    assert error.value.reason_code == "TARGET_STATE_CONFLICT"
    _assert_no_private_values(
        str(error.value),
        catalog,
    )


def test_extra_target_fails_closed_without_private_values():
    catalog = _catalog()
    existing = _target_records(catalog)
    extra = dict(existing[-1])
    extra["merchant_id"] = (
        "00000000-0000-0000-0000-000000000023"
    )
    extra["code"] = "CATALOG_23"
    extra["name"] = "Đối Tác Thử Nghiệm 23"
    existing.append(extra)

    with pytest.raises(
        CatalogTargetConflictError,
        match="neither empty nor identical",
    ) as error:
        _plan(catalog, existing)

    assert error.value.reason_code == "TARGET_STATE_CONFLICT"
    assert "CATALOG_23" not in str(error.value)
    assert "Đối Tác Thử Nghiệm 23" not in str(
        error.value
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        (
            "merchant_id",
            "00000000-0000-0000-0000-000000000099",
        ),
        ("code", "PRIVATE_CHANGED_CODE"),
        ("name", "Tên Riêng Đã Đổi"),
        ("region_code", "OTHER"),
        ("account_status", "ONBOARDING"),
        ("version", 2),
    ),
)
def test_changed_target_record_fails_without_echo(
    field,
    value,
):
    catalog = _catalog()
    existing = _target_records(catalog)
    existing[-1][field] = value

    with pytest.raises(
        CatalogTargetConflictError,
    ) as error:
        _plan(catalog, existing)

    assert error.value.reason_code in {
        "TARGET_STATE_CONFLICT",
        "INVALID_TARGET_VERSION",
    }

    if isinstance(value, str):
        assert value not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    (
        (
            "merchant_id",
            None,
            "INVALID_TARGET_ID",
        ),
        ("code", None, "INVALID_TARGET_CODE"),
        ("name", None, "INVALID_TARGET_NAME"),
        ("region_code", 7, "INVALID_TARGET_REGION"),
        ("account_status", "INACTIVE", "INVALID_TARGET_STATUS"),
        ("version", True, "INVALID_TARGET_VERSION"),
    ),
)
def test_invalid_target_types_fail_with_safe_position(
    field,
    value,
    reason_code,
):
    catalog = _catalog()
    existing = _target_records(catalog)
    existing[3][field] = value

    with pytest.raises(
        CatalogTargetConflictError,
        match="target record 4",
    ) as error:
        _plan(catalog, existing)

    assert error.value.reason_code == reason_code
    assert error.value.record_number == 4


def test_invalid_target_field_set_fails_without_field_names():
    catalog = _catalog()
    existing = _target_records(catalog)
    existing[0]["private_field"] = "private-value"

    with pytest.raises(
        CatalogTargetConflictError,
        match="record 1 has invalid fields",
    ) as error:
        _plan(catalog, existing)

    assert error.value.reason_code == "INVALID_TARGET_FIELDS"
    assert "private_field" not in str(error.value)
    assert "private-value" not in str(error.value)


def test_target_record_must_be_object_without_echo():
    catalog = _catalog()
    existing = _target_records(catalog)
    existing[1] = "private-target-value"

    with pytest.raises(
        CatalogTargetConflictError,
        match="record 2 must be an object",
    ) as error:
        _plan(catalog, existing)

    assert error.value.reason_code == (
        "TARGET_RECORD_NOT_OBJECT"
    )
    assert "private-target-value" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "reason_code"),
    (
        ("merchant_id", "DUPLICATE_TARGET_ID"),
        ("code", "DUPLICATE_TARGET_CODE"),
    ),
)
def test_duplicate_target_identity_or_code_fails_closed(
    field,
    reason_code,
):
    catalog = _catalog()
    existing = _target_records(catalog)
    existing[1][field] = existing[0][field]

    with pytest.raises(
        CatalogTargetConflictError,
        match="duplicate",
    ) as error:
        _plan(catalog, existing)

    assert error.value.reason_code == reason_code
    _assert_no_private_values(
        str(error.value),
        catalog,
    )


def test_planning_does_not_mutate_catalog_or_target_input():
    catalog = _catalog()
    existing = _target_records(catalog)
    before = json.dumps(
        existing,
        ensure_ascii=False,
        sort_keys=True,
    )

    _plan(catalog, existing)

    assert json.dumps(
        existing,
        ensure_ascii=False,
        sort_keys=True,
    ) == before


def test_gate_9_2_planner_has_no_database_or_write_dependency():
    source = inspect.getsource(catalog_plan)

    assert "psycopg" not in source
    assert "MerchantRepository" not in source
    assert "RepositoryConfig" not in source
    assert "connection(" not in source
    assert "execute(" not in source
    assert "INSERT INTO" not in source
    assert "UPDATE " not in source
    assert "DELETE " not in source
