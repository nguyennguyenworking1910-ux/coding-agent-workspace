"""Atomic persistence for Merchant integration identifiers."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from claude.agents.tools.merchant.identifier_engine import (
    IdentifierConflictError,
    IdentifierMutationPlan,
    IdentifierVersionConflictError,
    propose_identifier_mutation,
)
from claude.clients.merchant.repository import MerchantRepository


class IdentifierPersistenceError(RuntimeError):
    """Base error for identifier persistence."""


class IdentifierMerchantNotFoundError(
    IdentifierPersistenceError
):
    """Raised when the selected Merchant does not exist."""


class IdentifierProjectNotFoundError(
    IdentifierPersistenceError
):
    """Raised when a project does not belong to the Merchant."""


class IdentifierBindingConflictError(
    IdentifierPersistenceError
):
    """Raised when stored identifier uniqueness is violated."""


@dataclass(frozen=True, slots=True)
class IdentifierMutationResult:
    """Sensitive-value-free identifier mutation result."""

    identifier_id: str
    merchant_id: str
    project_id: str | None
    identifier_type: str
    scope: str
    is_active: bool
    previous_version: int | None
    current_version: int
    operation: str
    event_id: str
    event_type: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MerchantIdentifierRepository:
    """Insert or optimistically update one identifier binding."""

    def __init__(self, repository: MerchantRepository) -> None:
        self.repository = repository

    def set_identifier(
        self,
        *,
        merchant_id: str,
        project_id: str | None,
        identifier_type: str,
        identifier_value: str,
        scope: str,
        identifier_id: str | None = None,
        is_active: bool = True,
        expected_version: int | None = None,
        triggered_by: str | None = None,
    ) -> IdentifierMutationResult:
        merchant_uuid = _uuid(merchant_id, "merchant_id")
        project_uuid = (
            _uuid(project_id, "project_id")
            if project_id is not None
            else None
        )
        event_id = uuid.uuid4()

        try:
            with self.repository.connection() as connection:
                with connection.transaction():
                    with connection.cursor(
                        row_factory=dict_row,
                    ) as cursor:
                        self._require_merchant(
                            cursor,
                            merchant_uuid,
                        )

                        if project_uuid is not None:
                            self._require_project(
                                cursor,
                                merchant_uuid,
                                project_uuid,
                            )

                        current = self._lock_identifier(
                            cursor,
                            merchant_uuid,
                            project_uuid,
                            identifier_type,
                            scope,
                        )
                        candidate_identifier_id = identifier_id

                        if (
                            current is None
                            and candidate_identifier_id is None
                        ):
                            candidate_identifier_id = str(
                                uuid.uuid4()
                            )

                        plan = propose_identifier_mutation(
                            merchant_id=str(merchant_uuid),
                            project_id=(
                                str(project_uuid)
                                if project_uuid is not None
                                else None
                            ),
                            identifier_type=identifier_type,
                            identifier_value=identifier_value,
                            scope=scope,
                            current_identifier=current,
                            identifier_id=candidate_identifier_id,
                            is_active=is_active,
                            expected_version=expected_version,
                            triggered_by=triggered_by,
                        )

                        if plan.operation == "INSERT":
                            self._insert_identifier(cursor, plan)
                        else:
                            self._update_identifier(cursor, plan)

                        self._insert_event(
                            cursor,
                            plan,
                            event_id,
                        )
        except errors.UniqueViolation as error:
            raise IdentifierBindingConflictError(
                "Integration identifier conflicts with stored data"
            ) from error

        return IdentifierMutationResult(
            identifier_id=plan.identifier_id,
            merchant_id=plan.merchant_id,
            project_id=plan.project_id,
            identifier_type=plan.identifier_type,
            scope=plan.scope,
            is_active=plan.is_active,
            previous_version=plan.current_version,
            current_version=plan.new_version,
            operation=plan.operation,
            event_id=str(event_id),
            event_type=plan.event_type,
        )

    @staticmethod
    def _require_merchant(
        cursor: Any,
        merchant_id: uuid.UUID,
    ) -> None:
        cursor.execute(
            """
            SELECT merchant.id
            FROM merchant_ops.merchants AS merchant
            WHERE merchant.id = %s
            FOR SHARE OF merchant
            """,
            (merchant_id,),
        )

        if cursor.fetchone() is None:
            raise IdentifierMerchantNotFoundError(
                f"Merchant not found: {merchant_id}"
            )

    @staticmethod
    def _require_project(
        cursor: Any,
        merchant_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        cursor.execute(
            """
            SELECT project.id
            FROM merchant_ops.projects AS project
            WHERE project.id = %s
              AND project.merchant_id = %s
            FOR SHARE OF project
            """,
            (project_id, merchant_id),
        )

        if cursor.fetchone() is None:
            raise IdentifierProjectNotFoundError(
                "Project was not found for Merchant: "
                f"{project_id}"
            )

    @staticmethod
    def _lock_identifier(
        cursor: Any,
        merchant_id: uuid.UUID,
        project_id: uuid.UUID | None,
        identifier_type: str,
        scope: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT
                identifier.id,
                identifier.merchant_id,
                identifier.project_id,
                identifier.identifier_type,
                identifier.identifier_value,
                identifier.scope,
                identifier.is_active,
                identifier.version
            FROM merchant_ops.integration_identifiers AS identifier
            WHERE identifier.merchant_id = %s
              AND identifier.project_id IS NOT DISTINCT FROM %s
              AND identifier.identifier_type = %s
              AND identifier.scope = %s
            ORDER BY identifier.id
            FOR UPDATE OF identifier
            """,
            (
                merchant_id,
                project_id,
                str(identifier_type).strip().upper(),
                str(scope).strip().upper(),
            ),
        )
        records = [dict(record) for record in cursor.fetchall()]

        if len(records) > 1:
            raise IdentifierBindingConflictError(
                "Multiple integration identifiers exist for one binding"
            )

        return records[0] if records else None

    @staticmethod
    def _insert_identifier(
        cursor: Any,
        plan: IdentifierMutationPlan,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO merchant_ops.integration_identifiers (
                id,
                project_id,
                merchant_id,
                identifier_type,
                identifier_value,
                scope,
                is_active,
                created_at,
                updated_at,
                version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                %s
            )
            """,
            (
                uuid.UUID(plan.identifier_id),
                (
                    uuid.UUID(plan.project_id)
                    if plan.project_id is not None
                    else None
                ),
                uuid.UUID(plan.merchant_id),
                plan.identifier_type,
                plan.identifier_value,
                plan.scope,
                plan.is_active,
                plan.new_version,
            ),
        )

    @staticmethod
    def _update_identifier(
        cursor: Any,
        plan: IdentifierMutationPlan,
    ) -> None:
        cursor.execute(
            """
            UPDATE merchant_ops.integration_identifiers
            SET
                identifier_value = %s,
                is_active = %s,
                updated_at = CURRENT_TIMESTAMP,
                version = %s
            WHERE id = %s
              AND merchant_id = %s
              AND project_id IS NOT DISTINCT FROM %s
              AND identifier_type = %s
              AND scope = %s
              AND version = %s
            """,
            (
                plan.identifier_value,
                plan.is_active,
                plan.new_version,
                uuid.UUID(plan.identifier_id),
                uuid.UUID(plan.merchant_id),
                (
                    uuid.UUID(plan.project_id)
                    if plan.project_id is not None
                    else None
                ),
                plan.identifier_type,
                plan.scope,
                plan.current_version,
            ),
        )

        if cursor.rowcount != 1:
            raise IdentifierVersionConflictError(
                "Integration identifier changed before the "
                "mutation could be committed"
            )

    @staticmethod
    def _insert_event(
        cursor: Any,
        plan: IdentifierMutationPlan,
        event_id: uuid.UUID,
    ) -> None:
        merchant_id = uuid.UUID(plan.merchant_id)
        project_id = (
            uuid.UUID(plan.project_id)
            if plan.project_id is not None
            else None
        )
        entity_type = (
            "PROJECT"
            if project_id is not None
            else "MERCHANT"
        )
        entity_id = project_id or merchant_id
        cursor.execute(
            """
            INSERT INTO merchant_ops.project_events (
                id,
                merchant_id,
                project_id,
                event_type,
                entity_type,
                entity_id,
                change_summary,
                old_values,
                new_values,
                triggered_by,
                created_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                CURRENT_TIMESTAMP
            )
            """,
            (
                event_id,
                merchant_id,
                project_id,
                plan.event_type,
                entity_type,
                entity_id,
                plan.change_summary,
                Jsonb(plan.old_values),
                Jsonb(plan.new_values),
                (
                    uuid.UUID(plan.triggered_by)
                    if plan.triggered_by is not None
                    else None
                ),
            ),
        )


def _uuid(value: Any, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise IdentifierPersistenceError(
            f"{field_name} must be a valid UUID"
        ) from error
