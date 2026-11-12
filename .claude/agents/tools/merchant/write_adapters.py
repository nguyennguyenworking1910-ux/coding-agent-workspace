"""Repository adapters for Merchant CLI write payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import uuid
from typing import Any

from .cli_contract import (
    normalize_database_target,
    repository_role_for_target,
)
from .merchant_engine import (
    propose_merchant_activation,
    propose_merchant_batch_activation,
)
from .project_preview import verify_project_create
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
        TransactionPreviewReader,
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
        TransactionPreviewReader,
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
    # CP12H.MASTER: operator-attested signing (defaulted for older callers).
    signing: Any = None

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
            signing=_signing_repository(repository),
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
            "document sign": self.sign_document,
            "integration identifier-set": self.set_identifier,
            "merchant activate": self.activate_merchant,
            "merchant activate-all": self.activate_merchants_batch,
            "merchant create": self.create_merchant,
            "procurement update": self.update_procurement,
            "project create": self.create_project,
            "project update": self.update_project,
            "step update": self.update_step,
        }

    def activate_merchant(self, payload: dict[str, Any]) -> Any:
        return self.repositories.merchants.activate_merchant(
            merchant_id=payload["merchant_id"],
            expected_version=payload["expected_version"],
            reason=payload["reason"],
            triggered_by=payload.get("triggered_by"),
        )

    def activate_merchants_batch(
        self,
        payload: dict[str, Any],
    ) -> Any:
        return self.repositories.merchants.activate_merchants_batch(
            from_status=payload["from_status"],
            expected_count=payload["expected_count"],
            reason=payload["reason"],
            triggered_by=payload.get("triggered_by"),
            manifest=payload.get("manifest"),
        )

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
            precondition=_confirmed_preview_precondition(payload),
        )

    def update_project(self, payload: dict[str, Any]) -> Any:
        if _lifecycle().is_confirmed_payload(payload):
            return self._confirmed_lifecycle("project update", payload)
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
        precondition = _confirmed_step_precondition(self.repositories.steps, payload)
        extra = {} if precondition is None else {"precondition": precondition}
        if payload.get("gate_attestation") is not None:
            # CP12H.MASTER: only the confirmed operation of a verified preview
            # carries an attestation; it is recorded by the trusted operator.
            from claude.clients.merchant.operator_identity import trusted_operator_id

            if precondition is None:
                raise WriteAdapterError(
                    "A gate attestation runs only as a confirmed Step Update preview"
                )
            extra["gate_attestation"] = payload["gate_attestation"]
            payload = {**payload, "triggered_by": trusted_operator_id()}
        return self.repositories.steps.transition_step(
            **extra,
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
        if _lifecycle().is_confirmed_payload(payload):
            return self._confirmed_lifecycle("document revision-create", payload)
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
        if _lifecycle().is_confirmed_payload(payload):
            return self._confirmed_lifecycle("document approve", payload)
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
        from .purchase_request import is_confirmed_payload

        if is_confirmed_payload(payload):
            # CP12H.MASTER: a confirmed Purchase Order or Payment Request is a
            # lifecycle operation; a Purchase Request keeps its NL4D4A path.
            if _lifecycle().kind_of("procurement update", payload) is not None:
                return self._confirmed_lifecycle("procurement update", payload)
            return self._record_confirmed_purchase_request(payload)
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

    def _record_confirmed_purchase_request(self, payload: dict[str, Any]) -> Any:
        """CP12H.NL4D4A: record exactly one previewed Purchase Request.

        The operator is the trusted local configuration, required to equal the
        one the preview was bound to (never taken from the payload); the
        preview is re-judged under the Project and procurement locks, so a
        changed basis, operator, Merchant, reference holder or existing record
        refuses the whole transaction.
        """

        from claude.clients.merchant.operator_identity import require_operator
        from claude.clients.merchant.read_repository import (
            MerchantReadRepository,
            TransactionDetailReader,
        )

        from .purchase_request import verify_purchase_request

        procurement = self.repositories.procurement
        operator = require_operator(payload.get("operator_id"))
        verify_fields = {k: v for k, v in payload.items() if v is not None}

        def precondition(connection: Any) -> None:
            verify_purchase_request(
                TransactionDetailReader(MerchantReadRepository(procurement.repository), connection),
                verify_fields,
                require_operator(operator),
            )

        return procurement.record_procurement(
            project_id=verify_fields.get("project_id"),
            procurement_type=verify_fields.get("procurement_type"),
            external_id=verify_fields.get("external_id"),
            triggered_by=operator,
            procurement_id=verify_fields.get("procurement_id"),
            precondition=precondition,
        )

    def sign_document(self, payload: dict[str, Any]) -> Any:
        """CP12H.MASTER: signing runs only as a confirmed, operator-attested
        operation; there is no unconfirmed signing write."""

        if not _lifecycle().is_confirmed_payload(payload):
            raise WriteAdapterError(
                "document sign runs only as the confirmed operation of a verified preview"
            )
        return self._confirmed_lifecycle("document sign", payload)

    def _confirmed_lifecycle(self, command: str, payload: dict[str, Any]) -> Any:
        """CP12H.MASTER: run exactly one confirmed lifecycle operation.

        The recorder is the trusted local operator, required to equal the one
        the preview was bound to (never taken from the payload alone). The
        whole preview is re-judged inside the write transaction after the
        repository locks (``lifecycle_operation.verify``), so a changed basis,
        operator, Merchant, decision, gate or reference refuses it.
        """

        from claude.clients.merchant.operator_identity import require_operator
        from claude.clients.merchant.read_repository import (
            MerchantReadRepository,
            TransactionDetailReader,
        )

        lifecycle = _lifecycle()
        operator = require_operator(payload.get("operator_id"))
        fields = {k: v for k, v in payload.items() if v is not None}
        kind = lifecycle.kind_of(command, fields)
        params = lifecycle.params_from_payload(kind, fields)
        repository = self.repositories.documents.repository

        def precondition(connection: Any) -> None:
            lifecycle.verify(
                TransactionDetailReader(MerchantReadRepository(repository), connection),
                command,
                fields,
                require_operator(operator),
            )

        if kind == lifecycle.CREATE_REVISION:
            return self.repositories.documents.create_revision(
                project_id=fields["project_id"],
                document_type=params["document_type"],
                content_hash=lifecycle.metadata_only_hash(params["revision_id"]),
                effective_date=_optional_date(params["effective_date"]),
                expiry_date=_optional_date(params["expiry_date"]),
                created_by=operator,
                revision_id=params["revision_id"],
                evidence_status=lifecycle.METADATA_ONLY,
                precondition=precondition,
            )
        if kind == lifecycle.RECORD_DECISION:
            return self.repositories.approvals.record_approval(
                document_revision_id=params["revision_id"],
                approver_role=params["role"],
                approval_status=params["decision"],
                expected_status=params["expected_status"],
                occurred_at=_optional_datetime(fields.get("occurred_at")),
                notes=params["decision_note"],
                approval_id=params["approval_id"],
                recorded_by=operator,
                precondition=precondition,
            )
        if kind == lifecycle.SIGN:
            signing = self.repositories.signing or _signing_repository(repository)
            return signing.sign_document(
                document_revision_id=params["revision_id"],
                occurred_at=_optional_datetime(fields.get("signed_at")),
                attestation=lifecycle.OPERATOR_ATTESTED_SIGNED,
                recorded_by=operator,
                precondition=precondition,
            )
        if kind in lifecycle.PROCUREMENT_TYPES:
            return self.repositories.procurement.record_procurement(
                project_id=fields["project_id"],
                procurement_type=lifecycle.PROCUREMENT_TYPES[kind],
                external_id=params["reference"],
                triggered_by=operator,
                procurement_id=fields.get("procurement_id"),
                precondition=precondition,
            )
        return self.repositories.projects.transition_project(
            project_id=fields["project_id"],
            target_status=lifecycle.PROJECT_TARGETS[kind],
            expected_version=params["expected_version"],
            triggered_by=operator,
            precondition=precondition,
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

    def preflight_activate_merchant(
        self,
        payload: dict[str, Any],
    ) -> Any:
        """Read-only preflight validation for single merchant activation."""
        merchant = self.repositories.merchants.read_merchant(
            merchant_id=payload["merchant_id"]
        )
        propose_merchant_activation(
            merchant,
            expected_version=payload["expected_version"],
            reason=payload["reason"],
            triggered_by=payload.get("triggered_by"),
        )
        return {
            "merchant_id": str(merchant.get("id", "")),
            "code": str(merchant.get("code", "")),
            "account_status": str(merchant.get("account_status", "")),
            "version": int(merchant.get("version", 0)),
        }

    def preflight_activate_merchants_batch(
        self,
        payload: dict[str, Any],
    ) -> Any:
        """Read-only preflight validation for batch merchant activation."""
        merchants = self.repositories.merchants.read_merchants_by_ids(
            merchant_ids=payload.get("merchant_ids", [])
        )
        plan = propose_merchant_batch_activation(
            merchants,
            reason=payload["reason"],
            triggered_by=payload.get("triggered_by"),
        )
        manifest_entries = []
        for merchant in plan.merchants:
            manifest_entries.append({
                "merchant_id": merchant.merchant_id,
                "code": merchant.__dict__.get("code", ""),
                "account_status": merchant.current_status,
                "version": merchant.expected_version,
            })
        return manifest_entries


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
    commands = MerchantWriteCommands(adapters.handlers())

    commands.register_preflight_validator(
        "merchant activate",
        adapters.preflight_activate_merchant,
    )
    commands.register_preflight_validator(
        "merchant activate-all",
        adapters.preflight_activate_merchants_batch,
    )

    return commands


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


def execute_protected_merchant_create(
    *,
    database: str,
    operation_key: str,
    payload: dict[str, Any],
    execution_attempt_id: uuid.UUID | None = None,
    repository: MerchantRepository | None = None,
) -> dict[str, Any]:
    """Execute an atomic Merchant create from a trusted caller.

    This function does not authenticate the caller.
    It must not be exposed directly to agent-supplied CLI arguments.
    """
    from claude.clients.merchant.atomic_create import (
        atomic_create_merchant,
    )

    normalized_database = normalize_database_target(database)

    if not isinstance(operation_key, str) or not operation_key.strip():
        raise WriteAdapterError("Protected execution key is required")

    if (
        execution_attempt_id is not None
        and not isinstance(execution_attempt_id, uuid.UUID)
    ):
        raise WriteAdapterError("Invalid execution attempt identity")

    if not isinstance(payload, dict):
        raise WriteAdapterError("Payload must be a dictionary")

    allowed = {
        "merchant_id",
        "code",
        "name",
        "region_code",
        "created_by",
    }

    if set(payload) - allowed:
        raise WriteAdapterError(
            "Unexpected protected Merchant create fields"
        )

    if not all(
        isinstance(payload.get(field), str)
        and payload[field].strip()
        for field in ("code", "name")
    ):
        raise WriteAdapterError(
            "Merchant code and name are required"
        )

    base_repository = repository or MerchantRepository(
        role=repository_role_for_target(normalized_database)
    )

    entity_repository = MerchantEntityRepository(base_repository)

    result, replayed = atomic_create_merchant(
        base_repository,
        entity_repository,
        operation_key=operation_key,
        execution_attempt_id=execution_attempt_id,
        merchant_id=payload.get("merchant_id"),
        code=payload["code"],
        name=payload["name"],
        region_code=payload.get("region_code"),
        created_by=payload.get("created_by"),
    )

    return {
        "contract_version": 1,
        "success": True,
        "mode": "EXECUTE",
        "command": "merchant create",
        "database": normalized_database,
        "result": result,
        "replayed": replayed,
    }


def _confirmed_preview_precondition(payload: dict[str, Any]) -> Any:
    """Re-check a confirmed preview inside the creating transaction."""

    if payload.get("expected_basis_hash") is None:
        return None

    def precondition(cursor: Any) -> None:
        reader = TransactionPreviewReader(cursor)
        reader.lock_merchant(payload["merchant_id"])
        verify_project_create(reader, payload)

    return precondition


def _confirmed_step_precondition(steps: Any, payload: dict[str, Any]) -> Any:
    """CP12H.NL4C1: re-judge a confirmed Step preview under the step locks."""

    if payload.get("expected_basis_hash") is None:
        return None

    from claude.clients.merchant.read_repository import (
        MerchantReadRepository,
        TransactionDetailReader,
    )

    from .step_preview import verify_step_update

    def precondition(connection: Any) -> None:
        verify_step_update(
            TransactionDetailReader(MerchantReadRepository(steps.repository), connection),
            payload,
        )

    return precondition


def _lifecycle() -> Any:
    from . import lifecycle_operation

    return lifecycle_operation


def _signing_repository(repository: Any) -> Any:
    try:
        from claude.clients.merchant.signing_repository import (
            MerchantSigningRepository,
        )
    except ModuleNotFoundError:  # pragma: no cover - script layout
        from clients.merchant.signing_repository import (  # type: ignore
            MerchantSigningRepository,
        )
    return MerchantSigningRepository(repository)
