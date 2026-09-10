"""Tests for the pure Merchant CLI safety contract."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

import pytest

from claude.agents.tools.merchant.cli_contract import (
    ALL_COMMANDS,
    READ_COMMANDS,
    REDACTED_VALUE,
    WRITE_COMMANDS,
    CommandNotAllowedError,
    DatabaseTargetError,
    MerchantCliContractError,
    ProposalHashError,
    RuntimeWriteDeniedError,
    build_proposal,
    normalize_command,
    normalize_database_target,
    proposal_hash,
    redact_payload,
    render_json,
    repository_role_for_target,
    require_apply_authorization,
    to_json_value,
    verify_proposal_hash,
)


PROJECT_ID = uuid.UUID(
    "00000000-0000-0000-0000-000000000001"
)


class ExampleStatus(Enum):
    ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class ExampleRecord:
    project_id: uuid.UUID
    status: ExampleStatus
    due_date: date


def test_command_allowlists_are_complete_and_disjoint():
    assert READ_COMMANDS == {
        "merchant list",
        "project alerts",
        "project blockers",
        "project history",
        "project list",
        "project show",
    }
    assert WRITE_COMMANDS == {
        "contact import",
        "document approve",
        "document revision-create",
        "integration identifier-set",
        "merchant activate",
        "merchant activate-all",
        "merchant create",
        "procurement update",
        "project create",
        "project update",
        "step update",
    }
    assert not READ_COMMANDS & WRITE_COMMANDS
    assert ALL_COMMANDS == READ_COMMANDS | WRITE_COMMANDS


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("test", "test"),
        (" TEST ", "test"),
        ("runtime", "runtime"),
        (" RuNtImE ", "runtime"),
    ),
)
def test_database_target_is_normalized(value, expected):
    assert normalize_database_target(value) == expected


@pytest.mark.parametrize(
    "value",
    (None, "", "production", "coding_agent_merchant"),
)
def test_invalid_database_target_is_rejected(value):
    with pytest.raises(DatabaseTargetError):
        normalize_database_target(value)


def test_repository_role_uses_least_privilege_mapping():
    assert repository_role_for_target("test") == "test"
    assert repository_role_for_target("runtime") == "app"


def test_command_is_normalized_and_allowlisted():
    assert normalize_command(
        "  DOCUMENT   REVISION-CREATE "
    ) == "document revision-create"


@pytest.mark.parametrize(
    "command",
    (None, "", "document sign", "merchant delete"),
)
def test_unknown_command_is_rejected(command):
    with pytest.raises(CommandNotAllowedError):
        normalize_command(command)


def test_json_values_are_deterministic_and_lossless():
    value = {
        "record": ExampleRecord(
            project_id=PROJECT_ID,
            status=ExampleStatus.ACTIVE,
            due_date=date(2026, 9, 6),
        ),
        "amount": Decimal("123.4500"),
        "occurred_at": datetime(
            2026,
            9,
            5,
            12,
            0,
            tzinfo=timezone(timedelta(hours=7)),
        ),
        "items": ("one", "two"),
    }

    assert to_json_value(value) == {
        "record": {
            "project_id": str(PROJECT_ID),
            "status": "ACTIVE",
            "due_date": "2026-09-06",
        },
        "amount": "123.4500",
        "occurred_at": "2026-09-05T05:00:00+00:00",
        "items": ["one", "two"],
    }


def test_naive_datetime_is_interpreted_as_utc():
    value = datetime(2026, 9, 5, 12, 30)

    assert to_json_value(value) == (
        "2026-09-05T12:30:00+00:00"
    )


@pytest.mark.parametrize(
    "value",
    (
        {"not-json"},
        {1: "non-string-key"},
        float("nan"),
        float("inf"),
        float("-inf"),
    ),
)
def test_unsupported_json_values_are_rejected(value):
    with pytest.raises(MerchantCliContractError):
        to_json_value(value)


def test_render_json_is_sorted_and_utf8_friendly():
    rendered = render_json(
        {
            "z": "Điện ảnh",
            "a": PROJECT_ID,
        }
    )

    assert "Điện ảnh" in rendered
    assert rendered.index('"a"') < rendered.index('"z"')
    assert json.loads(rendered) == {
        "a": str(PROJECT_ID),
        "z": "Điện ảnh",
    }


def test_redaction_is_recursive_without_mutating_input():
    payload = {
        "merchant_code": "BETA",
        "merchant_name": "Beta Media",
        "contacts": [
            {
                "contact_name": "Private Person",
                "work_email": "private@example.com",
                "phone": "0900000000",
            }
        ],
        "document": {
            "content_hash": "private-hash",
            "notes": "private-notes",
        },
        "identifier_value": "private-id",
    }

    redacted = redact_payload(payload)

    assert redacted == {
        "merchant_code": "BETA",
        "merchant_name": "Beta Media",
        "contacts": [
            {
                "contact_name": REDACTED_VALUE,
                "work_email": REDACTED_VALUE,
                "phone": REDACTED_VALUE,
            }
        ],
        "document": {
            "content_hash": REDACTED_VALUE,
            "notes": REDACTED_VALUE,
        },
        "identifier_value": REDACTED_VALUE,
    }
    assert payload["contacts"][0]["contact_name"] == (
        "Private Person"
    )


def test_absent_sensitive_values_remain_null():
    assert redact_payload(
        {
            "email": None,
            "phone": None,
        }
    ) == {
        "email": None,
        "phone": None,
    }


def test_extra_sensitive_field_can_be_command_specific():
    assert redact_payload(
        {
            "type": "PRODUCT_ID",
            "value": "private-value",
        },
        extra_sensitive_fields=("value",),
    ) == {
        "type": "PRODUCT_ID",
        "value": REDACTED_VALUE,
    }


def test_proposal_hash_is_independent_of_key_order():
    first = proposal_hash(
        "merchant create",
        "test",
        {
            "code": "BETA",
            "name": "Beta Media",
        },
    )
    second = proposal_hash(
        " MERCHANT   CREATE ",
        " TEST ",
        {
            "name": "Beta Media",
            "code": "BETA",
        },
    )

    assert first == second
    assert len(first) == 64


def test_proposal_hash_binds_command_database_and_payload():
    payload = {
        "merchant_id": str(PROJECT_ID),
        "status": "IN_PROGRESS",
    }
    baseline = proposal_hash(
        "project update",
        "test",
        payload,
    )

    assert baseline != proposal_hash(
        "step update",
        "test",
        payload,
    )
    assert baseline != proposal_hash(
        "project update",
        "runtime",
        payload,
    )
    assert baseline != proposal_hash(
        "project update",
        "test",
        {
            **payload,
            "status": "BLOCKED",
        },
    )


def test_read_command_cannot_create_proposal():
    with pytest.raises(CommandNotAllowedError):
        proposal_hash(
            "project show",
            "test",
            {"project_id": str(PROJECT_ID)},
        )


def test_build_proposal_redacts_output_but_binds_raw_value():
    payload = {
        "merchant_id": str(PROJECT_ID),
        "type": "PRODUCT_ID",
        "value": "private-product-id",
        "scope": "UAT",
    }

    proposal = build_proposal(
        "integration identifier-set",
        "test",
        payload,
    )
    output = proposal.to_dict()

    assert output["payload"]["value"] == REDACTED_VALUE
    assert "private-product-id" not in render_json(output)
    assert proposal.proposal_hash == proposal_hash(
        "integration identifier-set",
        "test",
        payload,
    )
    assert output["requires_confirmation"] is True


def test_built_proposal_payload_is_deeply_immutable():
    proposal = build_proposal(
        "project update",
        "test",
        {
            "project_id": str(PROJECT_ID),
            "changes": {
                "status": "IN_PROGRESS",
            },
        },
    )

    with pytest.raises(TypeError):
        proposal.payload["project_id"] = "changed"

    with pytest.raises(TypeError):
        proposal.payload["changes"]["status"] = "BLOCKED"


def test_matching_proposal_hash_is_accepted():
    payload = {
        "code": "BETA",
        "name": "Beta Media",
    }
    expected = proposal_hash(
        "merchant create",
        "test",
        payload,
    )

    assert verify_proposal_hash(
        expected.upper(),
        "merchant create",
        "test",
        payload,
    ) is None


@pytest.mark.parametrize(
    "supplied_hash",
    (None, "", "not-a-hash", "0" * 64),
)
def test_invalid_or_mismatched_proposal_hash_is_rejected(
    supplied_hash,
):
    with pytest.raises(ProposalHashError):
        verify_proposal_hash(
            supplied_hash,
            "merchant create",
            "test",
            {
                "code": "BETA",
                "name": "Beta Media",
            },
        )


def test_test_database_apply_is_allowed_for_write_command():
    assert require_apply_authorization(
        "merchant create",
        "test",
    ) is None


def test_runtime_apply_fails_closed_without_trusted_authority():
    with pytest.raises(RuntimeWriteDeniedError):
        require_apply_authorization(
            "merchant create",
            "runtime",
        )


def test_runtime_apply_rejects_boolean_authority():
    with pytest.raises(RuntimeWriteDeniedError):
        require_apply_authorization(
            "merchant create",
            "runtime",
            runtime_authorization=True,
            payload={
                "code": "BETA",
                "name": "Beta Media",
            },
            proposal_hash="0" * 64,
        )


def test_read_command_cannot_enter_apply_mode():
    with pytest.raises(CommandNotAllowedError):
        require_apply_authorization(
            "project show",
            "test",
        )
