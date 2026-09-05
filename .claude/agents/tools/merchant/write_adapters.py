"""Repository adapters for Merchant CLI write payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from .cli_contract import (
    normalize_database_target,
    repository_role_for_target,
)
from .workflow_templates import STANDARD_WORKFLOW_TEMPLATES
from .write_commands import MerchantWriteCommands

try:
    from claude.clients.merchant.approval_repository import (
        MerchantApprovalRepository,
    )
    from claude.clients.merchant.document_repository import (
        MerchantDocumentRepository,
    )
    from claude.clients.merchant.identifier_repository import (
        MerchantIdentifierRepository,
    )
    from claude.clients.merchant.merchant_repository import (
        MerchantEntityRepository,
    )
    from claude.clients.merchant.procurement_repository import (
        MerchantProcurementRepository,
    )
    from claude.clients.merchant.repository import (
        MerchantRepository,
    )
    from claude.clients.merchant.transition_repository import (
        MerchantProjectTransitionRepository,
        MerchantStepTransitionRepository,
    )
    from claude.clients.merchant.workflow_repository import (
        MerchantWorkflowRepository,
    )
except ModuleNotFoundError:
    from clients.merchant.approval_repository import (  # type: ignore
        MerchantApprovalRepository,
    )
    from clients.merchant.document_repository import (  # type: ignore
        MerchantDocumentRepository,
    )
    from clients.merchant.identifier_repository import (  # type: ignore
        MerchantIdentifierRepository,
    )
    from clients.merchant.merchant_repository import (  # type: ignore
        MerchantEntityRepository,
    )
    from clients.merchant.procurement_repository import (  # type: ignore
        MerchantProcurementRepository,
    )
    from clients.merchant.repository import (  # type: ignore
        MerchantRepository,
    )
    from clients.merchant.transition_repository import (  # type: ignore
        MerchantProjectTransitionRepository,
        MerchantStepTransitionRepository,
    )
    from clients.merchant.workflow_repository import (  # type: ignore
        MerchantWorkflowRepository,
    )


class WriteAdapterError(ValueError):
    """Raised when a bound CLI payload cannot be adapted safely."""


@dataclass(frozen=True, slots=True)
class MerchantWriteRepositories:
    """Specialized repositories sharing one database boundary."""

    merchants: Any
    workflows: Any
    projects: Any
    steps: Any
    documents: Any
    approvals: Any
    procurement: Any
    identifiers: Any

    @classmethod
    def from_repository(
        cls,
        repository: MerchantRepository,
    ) -> MerchantWriteRepositories:
        return cls(
            merchants=MerchantEntityRepository(repository),
            workflows=MerchantWorkflowRepository(repository),
            projects=MerchantProjectTransitionRepository(repository),
            steps=MerchantStepTransitionRepository(repository),
            documents=MerchantDocumentRepository(repository),
            approvals=MerchantApprovalRepository(repository),
            procurement=MerchantProcurementRepository(repository),
            identifiers=MerchantIdentifierRepository(repository),
        )


class MerchantRepositoryWriteAdapters:
    """Map canonical CLI payloads to explicit repository calls."""

    def __init__(
        self,
        repositories: MerchantWriteRepositories,
    ) -> None:
        self.repositories = repositories

    def handlers(self) -> dict[str, Any]:
        return {
            "contact import": self.import_contacts,
            "document approve": self.approve_document,
            "document revision-create": self.create_revision,
            "integration identifier-set": self.set_identifier,
            "merchant create": self.create_merchant,
            "procurement update": self.update_procurement,
            "project create": self.create_project,
            "project update": self.update_project,
            "step update": self.update_step,
        }

    def create_merchant(self, payload: dict[str, Any]) -> Any:
        return self.repositories.merchants.create_merchant(
            merchant_id=payload["merchant_id"],
            code=payload["code"],
            name=payload["name"],
            region_code=payload.get("region_code"),
            created_by=payload.get("created_by"),
        )

    def import_contacts(self, payload: dict[str, Any]) -> Any:
        return self.repositories.merchants.import_contacts(
            merchant_id=payload["merchant_id"],
            contacts=payload["contacts"],
            expected_version=payload["expected_version"],
            triggered_by=payload.get("triggered_by"),
        )

    def create_project(self, payload: dict[str, Any]) -> Any:
        template = _workflow_template(
            payload["project_type"],
            payload["workflow_variant"],
        )
        return self.repositories.workflows.create_project(
            merchant_id=payload["merchant_id"],
            template=template,
            requires_procurement=payload[
                "requires_procurement"
            ],
            payment_period_number=payload.get(
                "payment_period_number"
            ),
            reused_document_revision_id=payload.get(
                "reused_document_revision_id"
            ),
            title=payload.get("title"),
            created_by=payload.get("created_by"),
            project_id=payload.get("project_id"),
        )

    def update_project(self, payload: dict[str, Any]) -> Any:
        return self.repositories.projects.transition_project(
            project_id=payload["project_id"],
            target_status=payload["status"],
            expected_version=payload["expected_version"],
            occurred_at=_optional_datetime(
                payload.get("occurred_at")
            ),
            triggered_by=payload.get("triggered_by"),
            allow_reopen=payload.get("allow_reopen", False),
        )

    def update_step(self, payload: dict[str, Any]) -> Any:
        return self.repositories.steps.transition_step(
            step_id=payload["step_id"],
            target_status=payload["status"],
            assigned_to=payload.get("assigned_to"),
            expected_version=payload["expected_version"],
            occurred_at=_optional_datetime(
                payload.get("occurred_at")
            ),
            triggered_by=payload.get("triggered_by"),
            allow_reopen=payload.get("allow_reopen", False),
        )

    def create_revision(self, payload: dict[str, Any]) -> Any:
        return self.repositories.documents.create_revision(
            project_id=payload["project_id"],
            document_type=payload["document_type"],
            content_hash=payload["content_hash"],
            effective_date=_optional_date(
                payload.get("effective_date")
            ),
            expiry_date=_optional_date(
                payload.get("expiry_date")
            ),
            created_by=payload.get("created_by"),
            revision_id=payload.get("revision_id"),
        )

    def approve_document(self, payload: dict[str, Any]) -> Any:
        return self.repositories.approvals.record_approval(
            document_revision_id=payload[
                "document_revision_id"
            ],
            approver_role=payload["approver_role"],
            approval_status=payload["approval_status"],
            expected_status=payload.get("expected_status"),
            occurred_at=_optional_datetime(
                payload.get("occurred_at")
            ),
            acted_by=payload.get("acted_by"),
            notes=payload.get("notes"),
            approval_id=payload.get("approval_id"),
        )

    def update_procurement(self, payload: dict[str, Any]) -> Any:
        return self.repositories.procurement.record_procurement(
            project_id=payload["project_id"],
            procurement_type=payload["procurement_type"],
            external_id=payload.get("external_id"),
            status=payload.get("status"),
            expected_version=payload.get("expected_version"),
            document_type=payload.get("document_type"),
            triggered_by=payload.get("triggered_by"),
            procurement_id=payload.get("procurement_id"),
        )

    def set_identifier(self, payload: dict[str, Any]) -> Any:
        return self.repositories.identifiers.set_identifier(
            merchant_id=payload["merchant_id"],
            project_id=payload.get("project_id"),
            identifier_type=payload["identifier_type"],
            identifier_value=payload["value"],
            scope=payload["scope"],
            identifier_id=payload.get("identifier_id"),
            is_active=payload.get("is_active", True),
            expected_version=payload.get("expected_version"),
            triggered_by=payload.get("triggered_by"),
        )


def build_repository_write_commands(
    database: str,
    *,
    repository: MerchantRepository | None = None,
    repositories: MerchantWriteRepositories | None = None,
) -> MerchantWriteCommands:
    """Build every write handler for one explicit database target."""

    normalized_database = normalize_database_target(database)

    if repository is not None and repositories is not None:
        raise WriteAdapterError(
            "Pass repository or repositories, not both"
        )

    if repositories is None:
        base_repository = repository or MerchantRepository(
            role=repository_role_for_target(normalized_database)
        )
        repositories = MerchantWriteRepositories.from_repository(
            base_repository
        )

    adapters = MerchantRepositoryWriteAdapters(repositories)
    return MerchantWriteCommands(adapters.handlers())


def _workflow_template(
    project_type: Any,
    workflow_variant: Any,
) -> Any:
    normalized_type = str(project_type).strip().upper()
    normalized_variant = str(workflow_variant).strip().upper()
    matches = [
        template
        for template in STANDARD_WORKFLOW_TEMPLATES
        if template.variant == normalized_variant
    ]

    if len(matches) != 1:
        raise WriteAdapterError(
            "workflow_variant must identify one standard template"
        )

    template = matches[0]

    if template.project_type != normalized_type:
        raise WriteAdapterError(
            "project_type does not match workflow_variant"
        )

    return template


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        raise WriteAdapterError("date value cannot be a datetime")

    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        raise WriteAdapterError("date value must use YYYY-MM-DD")

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise WriteAdapterError(
            "date value must use YYYY-MM-DD"
        ) from error


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, str):
        candidate = value.strip()

        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise WriteAdapterError(
                "datetime value must be ISO-8601"
            ) from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise WriteAdapterError(
            "datetime value must be ISO-8601"
        )

    if parsed.tzinfo is None:
        raise WriteAdapterError(
            "datetime value must include a UTC offset"
        )

    return parsed.astimezone(timezone.utc)
