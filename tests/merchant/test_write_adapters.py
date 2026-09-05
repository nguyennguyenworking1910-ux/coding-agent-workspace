"""Tests for Merchant CLI-to-repository write adapters."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from claude.agents.tools.merchant.cli_contract import (
    ProposalHashError,
    WRITE_COMMANDS,
)
from claude.agents.tools.merchant.write_adapters import (
    MerchantRepositoryWriteAdapters,
    MerchantWriteRepositories,
    WriteAdapterError,
    build_repository_write_commands,
)


MERCHANT_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "00000000-0000-0000-0000-000000000002"
STEP_ID = "00000000-0000-0000-0000-000000000003"
REVISION_ID = "00000000-0000-0000-0000-000000000004"


class RecordingService:
    def __init__(self, label):
        self.label = label
        self.calls = []

    def __getattr__(self, method_name):
        def method(**kwargs):
            self.calls.append((method_name, kwargs))
            return {
                "service": self.label,
                "method": method_name,
            }

        return method


def make_repositories():
    services = {
        name: RecordingService(name)
        for name in (
            "merchants",
            "workflows",
            "projects",
            "steps",
            "documents",
            "approvals",
            "procurement",
            "identifiers",
        )
    }
    repositories = MerchantWriteRepositories(**services)
    return repositories, services


def apply_payload(commands, command, payload):
    proposal = commands.propose(command, "test", payload)
    return commands.apply(
        command,
        "test",
        payload,
        proposal_hash=proposal["proposal_hash"],
    )


def test_repository_builder_configures_every_write_command():
    repositories, _ = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )

    assert commands.configured_commands == WRITE_COMMANDS


def test_merchant_create_adapter_uses_stable_generated_id():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )

    result = apply_payload(
        commands,
        "merchant create",
        {
            "merchant_id": None,
            "code": "BETA",
            "name": "Beta Media",
            "region_code": "VN",
            "created_by": None,
        },
    )

    method, arguments = services["merchants"].calls[0]
    assert method == "create_merchant"
    assert uuid.UUID(arguments["merchant_id"])
    assert arguments["code"] == "BETA"
    assert arguments["name"] == "Beta Media"
    assert result["result"]["service"] == "merchants"


def test_contact_import_adapter_passes_materialized_rows():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )

    apply_payload(
        commands,
        "contact import",
        {
            "merchant_id": MERCHANT_ID,
            "contacts": [
                {
                    "name": "Private Contact",
                    "email": "private@example.com",
                }
            ],
            "expected_version": 3,
            "triggered_by": None,
        },
    )

    method, arguments = services["merchants"].calls[0]
    assert method == "import_contacts"
    assert arguments["expected_version"] == 3
    assert uuid.UUID(arguments["contacts"][0]["contact_id"])


def test_project_create_resolves_exact_standard_template():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )

    apply_payload(
        commands,
        "project create",
        {
            "project_id": None,
            "merchant_id": MERCHANT_ID,
            "project_type": "MEDIA_TOP_UP",
            "workflow_variant": "MEDIA_TOP_UP_NEW_DOCUMENT",
            "requires_procurement": True,
            "payment_period_number": None,
            "reused_document_revision_id": None,
            "title": "Test Project",
            "created_by": None,
        },
    )

    method, arguments = services["workflows"].calls[0]
    assert method == "create_project"
    assert arguments["template"].variant == (
        "MEDIA_TOP_UP_NEW_DOCUMENT"
    )
    assert arguments["template"].project_type == "MEDIA_TOP_UP"
    assert uuid.UUID(arguments["project_id"])


def test_project_create_rejects_type_variant_mismatch():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )
    payload = {
        "project_id": None,
        "merchant_id": MERCHANT_ID,
        "project_type": "OPENING_NEW_CINEMA",
        "workflow_variant": "MEDIA_TOP_UP_NEW_DOCUMENT",
        "requires_procurement": False,
    }
    proposal = commands.propose(
        "project create",
        "test",
        payload,
    )

    with pytest.raises(WriteAdapterError, match="does not match"):
        commands.apply(
            "project create",
            "test",
            payload,
            proposal_hash=proposal["proposal_hash"],
        )

    assert services["workflows"].calls == []


def test_project_and_step_updates_map_status_fields():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )
    occurred_at = "2026-09-05T08:30:00+07:00"

    apply_payload(
        commands,
        "project update",
        {
            "project_id": PROJECT_ID,
            "status": "IN_PROGRESS",
            "expected_version": 1,
            "occurred_at": occurred_at,
            "triggered_by": None,
            "allow_reopen": False,
        },
    )
    apply_payload(
        commands,
        "step update",
        {
            "step_id": STEP_ID,
            "status": "IN_PROGRESS",
            "assigned_to": MERCHANT_ID,
            "expected_version": 2,
            "occurred_at": occurred_at,
            "triggered_by": None,
            "allow_reopen": False,
        },
    )

    project_method, project_args = services["projects"].calls[0]
    step_method, step_args = services["steps"].calls[0]
    assert project_method == "transition_project"
    assert project_args["target_status"] == "IN_PROGRESS"
    assert project_args["occurred_at"] == datetime(
        2026,
        9,
        5,
        1,
        30,
        tzinfo=timezone.utc,
    )
    assert step_method == "transition_step"
    assert step_args["target_status"] == "IN_PROGRESS"
    assert step_args["assigned_to"] == MERCHANT_ID


def test_document_revision_converts_dates():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )

    apply_payload(
        commands,
        "document revision-create",
        {
            "revision_id": None,
            "project_id": PROJECT_ID,
            "document_type": "MERCHANT_AGREEMENT",
            "content_hash": "private-hash",
            "effective_date": "2026-09-05",
            "expiry_date": "2027-09-05",
            "created_by": None,
        },
    )

    method, arguments = services["documents"].calls[0]
    assert method == "create_revision"
    assert arguments["effective_date"] == date(2026, 9, 5)
    assert arguments["expiry_date"] == date(2027, 9, 5)
    assert uuid.UUID(arguments["revision_id"])


def test_document_approval_maps_revision_and_timestamp():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )

    apply_payload(
        commands,
        "document approve",
        {
            "approval_id": None,
            "document_revision_id": REVISION_ID,
            "approver_role": "LEGAL",
            "approval_status": "APPROVED",
            "expected_status": None,
            "occurred_at": "2026-09-05T01:30:00Z",
            "acted_by": MERCHANT_ID,
            "notes": "Private note",
        },
    )

    method, arguments = services["approvals"].calls[0]
    assert method == "record_approval"
    assert arguments["document_revision_id"] == REVISION_ID
    assert arguments["occurred_at"].tzinfo == timezone.utc
    assert uuid.UUID(arguments["approval_id"])


def test_procurement_adapter_maps_optional_version():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )

    apply_payload(
        commands,
        "procurement update",
        {
            "procurement_id": None,
            "project_id": PROJECT_ID,
            "procurement_type": "PURCHASE_REQUEST",
            "external_id": "PR-TEST-001",
            "status": "RECORDED",
            "expected_version": None,
            "document_type": None,
            "triggered_by": None,
        },
    )

    method, arguments = services["procurement"].calls[0]
    assert method == "record_procurement"
    assert arguments["expected_version"] is None
    assert uuid.UUID(arguments["procurement_id"])


def test_identifier_adapter_renames_sensitive_value():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )

    apply_payload(
        commands,
        "integration identifier-set",
        {
            "identifier_id": None,
            "merchant_id": MERCHANT_ID,
            "project_id": PROJECT_ID,
            "identifier_type": "PRODUCT_ID",
            "value": "private-product-id",
            "scope": "UAT",
            "is_active": True,
            "expected_version": None,
            "triggered_by": None,
        },
    )

    method, arguments = services["identifiers"].calls[0]
    assert method == "set_identifier"
    assert arguments["identifier_value"] == "private-product-id"
    assert "value" not in arguments


def test_changed_payload_stops_before_repository_adapter():
    repositories, services = make_repositories()
    commands = build_repository_write_commands(
        "test",
        repositories=repositories,
    )
    payload = {
        "project_id": PROJECT_ID,
        "status": "IN_PROGRESS",
        "expected_version": 1,
        "occurred_at": None,
        "triggered_by": None,
        "allow_reopen": False,
    }
    proposal = commands.propose(
        "project update",
        "test",
        payload,
    )

    with pytest.raises(ProposalHashError):
        commands.apply(
            "project update",
            "test",
            {**payload, "status": "BLOCKED"},
            proposal_hash=proposal["proposal_hash"],
        )

    assert services["projects"].calls == []


@pytest.mark.parametrize(
    "value",
    ("not-a-date", "2026-02-30"),
)
def test_invalid_document_date_stops_before_repository(value):
    repositories, services = make_repositories()
    adapters = MerchantRepositoryWriteAdapters(repositories)

    with pytest.raises(WriteAdapterError, match="YYYY-MM-DD"):
        adapters.create_revision(
            {
                "revision_id": REVISION_ID,
                "project_id": PROJECT_ID,
                "document_type": "MERCHANT_AGREEMENT",
                "content_hash": "private-hash",
                "effective_date": value,
            }
        )

    assert services["documents"].calls == []


def test_builder_rejects_ambiguous_repository_injection():
    repositories, _ = make_repositories()

    with pytest.raises(WriteAdapterError, match="not both"):
        build_repository_write_commands(
            "test",
            repository=object(),
            repositories=repositories,
        )
