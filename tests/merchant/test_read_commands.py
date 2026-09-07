"""Tests for redacted Merchant read command orchestration."""

from __future__ import annotations

from datetime import date

from claude.agents.tools.merchant.checker import ProjectAlert
from claude.agents.tools.merchant.cli_contract import REDACTED_VALUE
from claude.agents.tools.merchant.read_commands import (
    BLOCKER_ALERT_TYPES,
    MerchantReadCommands,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
MERCHANT_ID = "00000000-0000-0000-0000-000000000002"
STEP_ID = "00000000-0000-0000-0000-000000000003"


class FakeReadRepository:
    def __init__(self):
        self.calls = []
        self.detail = {
            "project": {
                "id": PROJECT_ID,
                "merchant_id": MERCHANT_ID,
                "merchant_code": "BETA",
                "merchant_name": "Beta Media",
                "status": "IN_PROGRESS",
            },
            "merchant_contacts": [
                {
                    "contact_name": "Private Person",
                    "contact_email": "private@example.com",
                    "contact_phone": "0900000000",
                }
            ],
            "steps": [
                {
                    "id": STEP_ID,
                    "project_id": PROJECT_ID,
                    "step_name": "Contract",
                    "status": "BLOCKED",
                    "notes": "private note",
                }
            ],
            "dependencies": [],
            "document_revisions": [
                {
                    "id": (
                        "00000000-0000-0000-0000-000000000004"
                    ),
                    "content_hash": "private-document-hash",
                }
            ],
            "document_approvals": [],
            "procurement_records": [],
            "integration_identifiers": [
                {
                    "identifier_type": "PRODUCT_ID",
                    "identifier_value": "private-product-id",
                }
            ],
        }

    def list_merchants(self, *, status=None):
        self.calls.append(("merchant_list", status))
        return [
            {
                "id": MERCHANT_ID,
                "code": "BETA",
                "name": "Beta Media",
                "account_status": "ACTIVE",
            }
        ]

    def list_projects(self, *, merchant_id=None, status=None):
        self.calls.append(
            ("project_list", merchant_id, status)
        )
        return [self.detail["project"]]

    def get_project_detail(self, project_id):
        self.calls.append(("project_detail", project_id))
        return self.detail

    def list_alert_candidate_project_ids(
        self,
        *,
        merchant_id=None,
        project_id=None,
        limit=100,
    ):
        self.calls.append(
            (
                "alert_candidates",
                merchant_id,
                project_id,
                limit,
            )
        )
        return [project_id or PROJECT_ID]

    def get_project_history(self, project_id, *, limit):
        self.calls.append(("project_history", project_id, limit))
        return [
            {
                "event_type": "CONTACT_IMPORTED",
                "new_values": {
                    "contact_email": "private@example.com",
                },
            }
        ]


class FakeChecker:
    def __init__(self):
        self.calls = []

    def check_snapshot(self, snapshot, *, business_date=None):
        self.calls.append((snapshot, business_date))
        return [
            ProjectAlert(
                project_id=PROJECT_ID,
                project_step_id=STEP_ID,
                step_name="Contract",
                alert_type="OVERDUE",
                severity="CRITICAL",
                business_due_date=date(2026, 9, 4),
                message="Contract is overdue.",
            ),
            ProjectAlert(
                project_id=PROJECT_ID,
                project_step_id=STEP_ID,
                step_name="Contract",
                alert_type="BLOCKED",
                severity="HIGH",
                condition_fingerprint="step-status:BLOCKED",
                message="Contract is blocked.",
            ),
            ProjectAlert(
                project_id=PROJECT_ID,
                project_step_id=STEP_ID,
                step_name="Legal gate",
                alert_type="MISSING_GATE",
                severity="HIGH",
                condition_fingerprint="gate:legal",
                message="Legal approval is missing.",
            ),
            ProjectAlert(
                project_id=PROJECT_ID,
                project_step_id=STEP_ID,
                step_name="Contract",
                alert_type="DUE_SOON",
                severity="MEDIUM",
                business_due_date=date(2026, 9, 8),
                message="Contract is due soon.",
            ),
        ]


def make_commands():
    repository = FakeReadRepository()
    checker = FakeChecker()
    return (
        MerchantReadCommands(
            repository,
            checker=checker,
        ),
        repository,
        checker,
    )


def test_blocker_alert_contract_is_explicit():
    assert BLOCKER_ALERT_TYPES == {
        "BLOCKED",
        "MISSING_GATE",
    }


def test_merchant_list_preserves_public_names():
    commands, repository, checker = make_commands()

    result = commands.merchant_list(status="ACTIVE")

    assert result[0]["code"] == "BETA"
    assert result[0]["name"] == "Beta Media"
    assert repository.calls == [("merchant_list", "ACTIVE")]
    assert checker.calls == []


def test_project_list_forwards_filters():
    commands, repository, checker = make_commands()

    result = commands.project_list(
        merchant_id=MERCHANT_ID,
        status="IN_PROGRESS",
    )

    assert result[0]["merchant_name"] == "Beta Media"
    assert repository.calls == [
        ("project_list", MERCHANT_ID, "IN_PROGRESS")
    ]
    assert checker.calls == []


def test_project_show_redacts_all_private_values():
    commands, repository, checker = make_commands()

    result = commands.project_show(PROJECT_ID)

    contact = result["merchant_contacts"][0]
    revision = result["document_revisions"][0]
    identifier = result["integration_identifiers"][0]
    assert contact["contact_name"] == REDACTED_VALUE
    assert contact["contact_email"] == REDACTED_VALUE
    assert contact["contact_phone"] == REDACTED_VALUE
    assert result["steps"][0]["notes"] == REDACTED_VALUE
    assert revision["content_hash"] == REDACTED_VALUE
    assert identifier["identifier_value"] == REDACTED_VALUE
    assert result["project"]["merchant_name"] == "Beta Media"
    assert repository.detail["merchant_contacts"][0][
        "contact_name"
    ] == "Private Person"
    assert repository.calls == [("project_detail", PROJECT_ID)]
    assert checker.calls == []


def test_project_history_is_defensively_redacted():
    commands, repository, checker = make_commands()

    result = commands.project_history(PROJECT_ID, limit=25)

    assert result[0]["new_values"]["contact_email"] == (
        REDACTED_VALUE
    )
    assert repository.calls == [
        ("project_history", PROJECT_ID, 25)
    ]
    assert checker.calls == []


def test_project_alerts_returns_every_calculated_alert():
    commands, repository, checker = make_commands()
    business_date = date(2026, 9, 5)

    result = commands.project_alerts(
        PROJECT_ID,
        business_date=business_date,
    )

    assert [alert["alert_type"] for alert in result] == [
        "OVERDUE",
        "BLOCKED",
        "MISSING_GATE",
        "DUE_SOON",
    ]
    assert repository.calls == [
        ("alert_candidates", None, PROJECT_ID, 100),
        ("project_detail", PROJECT_ID),
    ]
    assert checker.calls == [(repository.detail, business_date)]


def test_project_blockers_filters_deadline_only_alerts():
    commands, repository, checker = make_commands()
    business_date = date(2026, 9, 5)

    result = commands.project_blockers(
        PROJECT_ID,
        business_date=business_date,
    )

    assert [alert["alert_type"] for alert in result] == [
        "BLOCKED",
        "MISSING_GATE",
    ]
    assert repository.calls == [("project_detail", PROJECT_ID)]
    assert checker.calls == [(repository.detail, business_date)]
