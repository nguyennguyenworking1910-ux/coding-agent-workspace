"""Tests for pure Merchant and contact mutation planning."""

from __future__ import annotations

import pytest

from claude.agents.tools.merchant.merchant_engine import (
    CONTACT_EMAIL_LIMIT,
    MAX_CONTACT_IMPORT_ROWS,
    MerchantConflictError,
    MerchantEngineError,
    MerchantVersionConflictError,
    propose_contact_import,
    propose_merchant_creation,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
CONTACT_ID = "00000000-0000-0000-0000-000000000002"
SECOND_CONTACT_ID = "00000000-0000-0000-0000-000000000003"
TRIGGERED_BY = "00000000-0000-0000-0000-000000000004"


def merchant_record(*, version=3):
    return {
        "id": MERCHANT_ID,
        "code": "BETA",
        "account_status": "ACTIVE",
        "version": version,
    }


def contact_record(**overrides):
    record = {
        "contact_id": CONTACT_ID,
        "contact_type": "PRIMARY",
        "contact_name": "Nguyễn Văn A",
        "contact_email": "private@example.com",
        "contact_phone": "0900000000",
        "privacy_classification": "PII",
        "is_primary": True,
    }
    record.update(overrides)
    return record


def test_merchant_creation_is_normalized_and_auditable():
    plan = propose_merchant_creation(
        merchant_id=MERCHANT_ID,
        code=" beta-vn ",
        name="  Beta Việt Nam  ",
        region_code=" vn_s ",
        created_by=TRIGGERED_BY,
    )

    assert plan.merchant_id == MERCHANT_ID
    assert plan.code == "BETA-VN"
    assert plan.name == "Beta Việt Nam"
    assert plan.region_code == "VN_S"
    assert plan.account_status == "ONBOARDING"
    assert plan.version == 1
    assert plan.created_by == TRIGGERED_BY
    assert plan.event_type == "MERCHANT_CREATED"
    assert plan.old_values == {}
    assert plan.new_values["name"] == "Beta Việt Nam"


@pytest.mark.parametrize(
    "code",
    (None, "", "has space", "*INVALID*", "X" * 51),
)
def test_invalid_merchant_code_is_rejected(code):
    with pytest.raises(MerchantEngineError, match="code"):
        propose_merchant_creation(
            merchant_id=MERCHANT_ID,
            code=code,
            name="Beta",
        )


@pytest.mark.parametrize("name", (None, "", "   ", "X" * 501))
def test_invalid_merchant_name_is_rejected(name):
    with pytest.raises(MerchantEngineError, match="name"):
        propose_merchant_creation(
            merchant_id=MERCHANT_ID,
            code="BETA",
            name=name,
        )


@pytest.mark.parametrize(
    "region_code",
    ("", "has space", "X" * 11, 7),
)
def test_invalid_region_code_is_rejected(region_code):
    with pytest.raises(MerchantEngineError, match="region_code"):
        propose_merchant_creation(
            merchant_id=MERCHANT_ID,
            code="BETA",
            name="Beta",
            region_code=region_code,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("merchant_id", "not-a-uuid"),
        ("created_by", "not-a-uuid"),
    ),
)
def test_merchant_creation_rejects_invalid_uuid(field, value):
    arguments = {
        "merchant_id": MERCHANT_ID,
        "code": "BETA",
        "name": "Beta",
        field: value,
    }

    with pytest.raises(MerchantEngineError, match=field):
        propose_merchant_creation(**arguments)


def test_contact_import_normalizes_records_and_versions():
    plan = propose_contact_import(
        merchant_record(version=3),
        contacts=[contact_record()],
        expected_version=3,
        triggered_by=TRIGGERED_BY,
    )

    assert plan.merchant_id == MERCHANT_ID
    assert plan.expected_version == 3
    assert plan.new_merchant_version == 4
    assert plan.triggered_by == TRIGGERED_BY
    assert plan.event_type == "MERCHANT_CONTACTS_IMPORTED"
    assert plan.new_values == {
        "contacts_imported": 1,
        "primary_contacts_imported": 1,
        "merchant_version": 4,
    }
    record = plan.records[0]
    assert record.contact_id == CONTACT_ID
    assert record.contact_type == "PRIMARY"
    assert record.contact_name == "Nguyễn Văn A"
    assert record.privacy_classification == "PII"
    assert record.is_primary is True
    assert record.version == 1


def test_contact_short_field_aliases_are_supported():
    plan = propose_contact_import(
        merchant_record(),
        contacts=[
            {
                "id": CONTACT_ID,
                "name": "Private Person",
                "email": "private@example.com",
                "phone": "0900000000",
            }
        ],
        expected_version=3,
    )

    record = plan.records[0]
    assert record.contact_name == "Private Person"
    assert record.contact_email == "private@example.com"
    assert record.contact_phone == "0900000000"
    assert record.privacy_classification == "PII"
    assert record.is_primary is False


def test_contact_audit_values_never_contain_pii():
    private_values = (
        "Private Person",
        "private@example.com",
        "0900000000",
    )
    plan = propose_contact_import(
        merchant_record(),
        contacts=[contact_record()],
        expected_version=3,
    )
    encoded = repr(
        {
            "summary": plan.change_summary,
            "old": plan.old_values,
            "new": plan.new_values,
        }
    )

    for private_value in private_values:
        assert private_value not in encoded


def test_stale_merchant_version_is_rejected():
    with pytest.raises(
        MerchantVersionConflictError,
        match="version changed",
    ):
        propose_contact_import(
            merchant_record(version=4),
            contacts=[contact_record()],
            expected_version=3,
        )


@pytest.mark.parametrize(
    "expected_version",
    (None, True, 0, -1, "3"),
)
def test_invalid_expected_version_is_rejected(expected_version):
    with pytest.raises(
        MerchantEngineError,
        match="expected_version must be a positive integer",
    ):
        propose_contact_import(
            merchant_record(),
            contacts=[contact_record()],
            expected_version=expected_version,
        )


@pytest.mark.parametrize(
    "contacts",
    ([], "not-records", None),
)
def test_invalid_contact_collection_is_rejected(contacts):
    with pytest.raises(MerchantEngineError, match="contacts|at least"):
        propose_contact_import(
            merchant_record(),
            contacts=contacts,
            expected_version=3,
        )


def test_contact_import_row_limit_is_enforced():
    contacts = [
        {
            "contact_id": (
                f"00000000-0000-0000-0001-{index:012d}"
            ),
            "name": "Private Person",
        }
        for index in range(MAX_CONTACT_IMPORT_ROWS + 1)
    ]

    with pytest.raises(MerchantEngineError, match="cannot exceed"):
        propose_contact_import(
            merchant_record(),
            contacts=contacts,
            expected_version=3,
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"unknown": "value"},
        {"contact_type": "OTHER"},
        {"privacy_classification": "PUBLIC"},
        {"is_primary": "true"},
        {
            "contact_name": None,
            "contact_email": None,
            "contact_phone": None,
        },
        {"contact_email": "x" * (CONTACT_EMAIL_LIMIT + 1)},
    ),
)
def test_invalid_contact_row_is_rejected(changes):
    record = contact_record(**changes)

    with pytest.raises(MerchantEngineError):
        propose_contact_import(
            merchant_record(),
            contacts=[record],
            expected_version=3,
        )


def test_duplicate_contact_ids_are_rejected():
    with pytest.raises(
        MerchantConflictError,
        match="duplicate contact IDs",
    ):
        propose_contact_import(
            merchant_record(),
            contacts=[
                contact_record(),
                contact_record(
                    contact_name="Second Person"
                ),
            ],
            expected_version=3,
        )


def test_conflicting_contact_aliases_are_rejected():
    with pytest.raises(
        MerchantConflictError,
        match="conflicting name fields",
    ):
        propose_contact_import(
            merchant_record(),
            contacts=[
                contact_record(
                    name="Different Person"
                )
            ],
            expected_version=3,
        )


def test_multiple_unique_contacts_are_preserved_in_order():
    plan = propose_contact_import(
        merchant_record(),
        contacts=[
            contact_record(),
            contact_record(
                contact_id=SECOND_CONTACT_ID,
                contact_type="BILLING",
                is_primary=False,
            ),
        ],
        expected_version=3,
    )

    assert [record.contact_id for record in plan.records] == [
        CONTACT_ID,
        SECOND_CONTACT_ID,
    ]
