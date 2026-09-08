"""Checkpoint 9.1 private Merchant catalog contract tests."""

from __future__ import annotations

import inspect
import json

import pytest

from claude.agents.tools.merchant import catalog_contract
from claude.agents.tools.merchant.catalog_contract import (
    EXPECTED_CATALOG_RECORDS,
    MAX_CATALOG_BYTES,
    PrivateCatalogReadError,
    PrivateCatalogValidationError,
    load_private_catalog,
    validate_private_catalog_bytes,
)


def _records() -> list[dict[str, object]]:
    return [
        {
            "code": f"MERCHANT_{number:02d}",
            "name": f"Rạp Thử Nghiệm {number:02d}",
            "region_code": (
                "south"
                if number % 2
                else None
            ),
            "account_status": (
                "ONBOARDING"
                if number <= 7
                else "ACTIVE"
            ),
        }
        for number in range(
            1,
            EXPECTED_CATALOG_RECORDS + 1,
        )
    ]


_DEFAULT_RECORDS = object()


def _source(
    records: object = _DEFAULT_RECORDS,
    *,
    indent: int | None = None,
) -> bytes:
    payload = (
        _records()
        if records is _DEFAULT_RECORDS
        else records
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=indent,
    ).encode("utf-8")


def _assert_private_value_absent(
    error: BaseException,
    private_value: str,
) -> None:
    rendered = f"{error!s} {error!r}"
    assert private_value not in rendered


def test_valid_catalog_normalizes_and_returns_safe_summary():
    catalog = validate_private_catalog_bytes(_source())

    assert catalog.record_count == 22
    assert catalog.status_counts == {
        "ACTIVE": 15,
        "ONBOARDING": 7,
    }
    assert catalog.records[0].code == "MERCHANT_01"
    assert catalog.records[0].region_code == "SOUTH"
    assert catalog.records[1].region_code is None
    assert catalog.records[0].name == "Rạp Thử Nghiệm 01"
    assert len(catalog.source_sha256) == 64
    assert len(catalog.catalog_sha256) == 64
    assert catalog.safe_summary() == {
        "success": True,
        "record_count": 22,
        "status_counts": {
            "ACTIVE": 15,
            "ONBOARDING": 7,
        },
        "source_sha256": catalog.source_sha256,
        "catalog_sha256": catalog.catalog_sha256,
    }


def test_stable_ids_and_catalog_hash_ignore_format_and_input_order():
    records = _records()
    first = validate_private_catalog_bytes(
        _source(records),
    )
    second = validate_private_catalog_bytes(
        _source(list(reversed(records)), indent=2),
    )

    assert first.source_sha256 != second.source_sha256
    assert first.catalog_sha256 == second.catalog_sha256
    assert [
        record.merchant_id for record in first.records
    ] == [
        record.merchant_id for record in second.records
    ]


def test_unicode_names_are_normalized_to_nfc():
    records = _records()
    records[0]["name"] = "Ra\u0323p Thu\u031b\u0309 Nghie\u0323\u0302m"

    catalog = validate_private_catalog_bytes(
        _source(records)
    )

    assert catalog.records[0].name == "Rạp Thử Nghiệm"


@pytest.mark.parametrize(
    "payload",
    (
        {},
        "private-root",
        22,
        None,
    ),
)
def test_root_must_be_array_without_echoing_payload(payload):
    private_value = "private-root"

    with pytest.raises(
        PrivateCatalogValidationError,
        match="root must be a JSON array",
    ) as error:
        validate_private_catalog_bytes(
            _source(payload)
        )

    assert error.value.reason_code == "ROOT_NOT_ARRAY"
    _assert_private_value_absent(
        error.value,
        private_value,
    )


@pytest.mark.parametrize("count", (0, 1, 21, 23))
def test_catalog_requires_exactly_22_records(count):
    records = _records()

    if count > len(records):
        records.append(
            {
                "code": "MERCHANT_23",
                "name": "Rạp Thử Nghiệm 23",
                "region_code": None,
                "account_status": "ACTIVE",
            }
        )

    with pytest.raises(
        PrivateCatalogValidationError,
        match="exactly 22 records",
    ) as error:
        validate_private_catalog_bytes(
            _source(records[:count])
        )

    assert error.value.reason_code == "INVALID_RECORD_COUNT"
    assert error.value.record_number is None


def test_every_record_must_be_an_object():
    records = _records()
    records[4] = "private-record-value"

    with pytest.raises(
        PrivateCatalogValidationError,
        match="record 5 must be an object",
    ) as error:
        validate_private_catalog_bytes(
            _source(records)
        )

    assert error.value.reason_code == "RECORD_NOT_OBJECT"
    assert error.value.record_number == 5
    _assert_private_value_absent(
        error.value,
        "private-record-value",
    )


def test_missing_fields_are_reported_without_values():
    records = _records()
    private_name = str(records[2]["name"])
    del records[2]["account_status"]

    with pytest.raises(
        PrivateCatalogValidationError,
        match="record 3 is missing required fields",
    ) as error:
        validate_private_catalog_bytes(
            _source(records)
        )

    assert error.value.reason_code == "MISSING_FIELDS"
    _assert_private_value_absent(
        error.value,
        private_name,
    )


@pytest.mark.parametrize(
    "unknown_field",
    (
        "contact_email",
        "partner_code",
        "credential",
        "private_unknown_field",
    ),
)
def test_unknown_or_private_fields_fail_without_printing_name(
    unknown_field,
):
    records = _records()
    records[0][unknown_field] = "private-field-value"

    with pytest.raises(
        PrivateCatalogValidationError,
        match="record 1 contains unknown fields",
    ) as error:
        validate_private_catalog_bytes(
            _source(records)
        )

    assert error.value.reason_code == "UNKNOWN_FIELDS"
    _assert_private_value_absent(
        error.value,
        unknown_field,
    )
    _assert_private_value_absent(
        error.value,
        "private-field-value",
    )


@pytest.mark.parametrize(
    ("value", "reason_code"),
    (
        (None, "INVALID_CODE_TYPE"),
        (7, "INVALID_CODE_TYPE"),
        ("", "INVALID_CODE"),
        ("private code with spaces", "INVALID_CODE"),
        ("A" * 51, "INVALID_CODE"),
    ),
)
def test_invalid_codes_are_redacted(value, reason_code):
    records = _records()
    records[3]["code"] = value

    with pytest.raises(
        PrivateCatalogValidationError,
        match="record 4",
    ) as error:
        validate_private_catalog_bytes(
            _source(records)
        )

    assert error.value.reason_code == reason_code

    if isinstance(value, str) and value:
        _assert_private_value_absent(
            error.value,
            value,
        )


def test_codes_are_normalized_before_duplicate_check():
    records = _records()
    records[1]["code"] = " merchant_01 "

    with pytest.raises(
        PrivateCatalogValidationError,
        match="duplicate normalized codes",
    ) as error:
        validate_private_catalog_bytes(
            _source(records)
        )

    assert error.value.reason_code == "DUPLICATE_CODE"
    _assert_private_value_absent(
        error.value,
        "MERCHANT_01",
    )


@pytest.mark.parametrize(
    ("value", "reason_code"),
    (
        (None, "INVALID_NAME_TYPE"),
        (9, "INVALID_NAME_TYPE"),
        ("   ", "BLANK_NAME"),
        ("Private\nName", "INVALID_NAME_CHARACTER"),
        ("X" * 501, "NAME_TOO_LONG"),
    ),
)
def test_invalid_names_are_redacted(value, reason_code):
    records = _records()
    records[5]["name"] = value

    with pytest.raises(
        PrivateCatalogValidationError,
        match="record 6",
    ) as error:
        validate_private_catalog_bytes(
            _source(records)
        )

    assert error.value.reason_code == reason_code

    if isinstance(value, str) and value.strip():
        _assert_private_value_absent(
            error.value,
            value,
        )


@pytest.mark.parametrize(
    ("value", "reason_code"),
    (
        (9, "INVALID_REGION_TYPE"),
        ("", "INVALID_REGION"),
        ("private region", "INVALID_REGION"),
        ("ABCDEFGHIJK", "INVALID_REGION"),
    ),
)
def test_invalid_regions_are_redacted(value, reason_code):
    records = _records()
    records[6]["region_code"] = value

    with pytest.raises(
        PrivateCatalogValidationError,
        match="record 7",
    ) as error:
        validate_private_catalog_bytes(
            _source(records)
        )

    assert error.value.reason_code == reason_code

    if isinstance(value, str) and value:
        _assert_private_value_absent(
            error.value,
            value,
        )


@pytest.mark.parametrize(
    "value",
    (
        None,
        1,
        "active",
        "INACTIVE",
        "PRIVATE_STATUS",
    ),
)
def test_status_requires_exact_allowlisted_value_without_echo(
    value,
):
    records = _records()
    records[7]["account_status"] = value

    with pytest.raises(
        PrivateCatalogValidationError,
        match="record 8 has an invalid account status",
    ) as error:
        validate_private_catalog_bytes(
            _source(records)
        )

    assert error.value.reason_code == "INVALID_ACCOUNT_STATUS"

    if isinstance(value, str):
        _assert_private_value_absent(
            error.value,
            value,
        )


def test_duplicate_json_fields_fail_without_echoing_values():
    source = (
        b'[{"code":"PRIVATE_ONE","code":"PRIVATE_TWO",'
        b'"name":"PRIVATE_NAME","account_status":"ACTIVE"}]'
    )

    with pytest.raises(
        PrivateCatalogValidationError,
        match="contains duplicate fields",
    ) as error:
        validate_private_catalog_bytes(source)

    assert error.value.reason_code == "DUPLICATE_FIELD"

    for value in (
        "PRIVATE_ONE",
        "PRIVATE_TWO",
        "PRIVATE_NAME",
    ):
        _assert_private_value_absent(
            error.value,
            value,
        )


@pytest.mark.parametrize(
    ("source", "reason_code", "message"),
    (
        (
            b"\xffprivate-bytes",
            "INVALID_UTF8",
            "must be valid UTF-8",
        ),
        (
            b"\xef\xbb\xbf[]",
            "UTF8_BOM_NOT_ALLOWED",
            "without BOM",
        ),
        (
            b'["PRIVATE_JSON"',
            "INVALID_JSON",
            "must be valid JSON",
        ),
    ),
)
def test_encoding_and_json_errors_are_safe(
    source,
    reason_code,
    message,
):
    with pytest.raises(
        PrivateCatalogValidationError,
        match=message,
    ) as error:
        validate_private_catalog_bytes(source)

    assert error.value.reason_code == reason_code
    _assert_private_value_absent(
        error.value,
        "PRIVATE",
    )


def test_non_bytes_source_fails_closed():
    with pytest.raises(
        PrivateCatalogValidationError,
        match="must be bytes",
    ) as error:
        validate_private_catalog_bytes(
            "private-text"  # type: ignore[arg-type]
        )

    assert error.value.reason_code == "SOURCE_NOT_BYTES"
    _assert_private_value_absent(
        error.value,
        "private-text",
    )


def test_source_size_limit_is_enforced_before_json_parse():
    source = b"x" * (MAX_CATALOG_BYTES + 1)

    with pytest.raises(
        PrivateCatalogValidationError,
        match="exceeds the size limit",
    ) as error:
        validate_private_catalog_bytes(source)

    assert error.value.reason_code == "SOURCE_TOO_LARGE"


def test_file_loader_reads_explicit_file_without_storing_path(
    tmp_path,
):
    private_path = tmp_path / "private-catalog-name.json"
    private_path.write_bytes(_source())

    catalog = load_private_catalog(private_path)

    assert catalog.record_count == 22
    assert "private-catalog-name" not in repr(catalog)
    assert "private-catalog-name" not in json.dumps(
        catalog.safe_summary()
    )


def test_missing_file_error_does_not_echo_private_path(tmp_path):
    private_path = (
        tmp_path
        / "private-partner-catalog-do-not-print.json"
    )

    with pytest.raises(
        PrivateCatalogReadError,
        match="source is not a file",
    ) as error:
        load_private_catalog(private_path)

    assert error.value.reason_code == "SOURCE_NOT_FILE"
    _assert_private_value_absent(
        error.value,
        str(private_path),
    )
    _assert_private_value_absent(
        error.value,
        private_path.name,
    )


def test_directory_is_rejected_without_echoing_path(tmp_path):
    with pytest.raises(
        PrivateCatalogReadError,
        match="source is not a file",
    ) as error:
        load_private_catalog(tmp_path)

    assert error.value.reason_code == "SOURCE_NOT_FILE"
    _assert_private_value_absent(
        error.value,
        str(tmp_path),
    )


def test_catalog_and_record_representations_are_redacted():
    private_name = "Rạp Thử Nghiệm 01"
    catalog = validate_private_catalog_bytes(_source())

    assert private_name not in repr(catalog)
    assert private_name not in repr(catalog.records[0])
    assert catalog.records[0].code not in repr(catalog)
    assert catalog.records[0].code not in repr(
        catalog.records[0]
    )


def test_safe_summary_serialization_contains_no_private_values():
    catalog = validate_private_catalog_bytes(_source())
    encoded = json.dumps(
        catalog.safe_summary(),
        sort_keys=True,
    )

    for record in catalog.records:
        assert record.code not in encoded
        assert record.name not in encoded
        assert (
            record.region_code is None
            or record.region_code not in encoded
        )
        assert record.merchant_id not in encoded


def test_gate_9_1_contract_has_no_database_dependency():
    source = inspect.getsource(catalog_contract)

    assert "psycopg" not in source
    assert "MerchantRepository" not in source
    assert "RepositoryConfig" not in source
    assert "connection(" not in source
    assert "execute(" not in source
