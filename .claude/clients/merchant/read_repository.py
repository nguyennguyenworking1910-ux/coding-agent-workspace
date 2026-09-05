"""Read-only PostgreSQL projections for the Merchant CLI.

The repository returns trusted internal records. Public redaction belongs to
the CLI boundary so proposal hashing and persistence never use masked values.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from typing import Any

from claude.clients.merchant.repository import (
    MerchantRepository,
    ProjectNotFoundError,
)


MERCHANT_ACCOUNT_STATUSES = frozenset(
    {
        "ONBOARDING",
        "ACTIVE",
        "INACTIVE",
        "SUSPENDED",
    }
)

PROJECT_STATUSES = frozenset(
    {
        "PLANNED",
        "IN_PROGRESS",
        "BLOCKED",
        "ON_HOLD",
        "COMPLETED",
        "CANCELLED",
    }
)

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 500


class MerchantReadRepository:
    """Serve deterministic CLI reads through one repository connection."""

    def __init__(self, repository: MerchantRepository) -> None:
        self.repository = repository

    def list_merchants(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List merchants without exposing contact values."""

        normalized_status = _optional_choice(
            status,
            "status",
            MERCHANT_ACCOUNT_STATUSES,
        )
        query = """
            SELECT
                merchant.id,
                merchant.code,
                merchant.name,
                merchant.region_code,
                merchant.account_status,
                merchant.created_at,
                merchant.updated_at,
                merchant.version,
                (
                    SELECT COUNT(*)
                    FROM merchant_ops.merchant_contacts AS contact
                    WHERE contact.merchant_id = merchant.id
                ) AS contact_count
            FROM merchant_ops.merchants AS merchant
            WHERE (
                %s::text IS NULL
                OR merchant.account_status = %s
            )
            ORDER BY merchant.code, merchant.id
        """

        with self.repository.connection(
            read_only=True
        ) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            normalized_status,
                            normalized_status,
                        ),
                    )
                    return _records(cursor.fetchall())

    def list_projects(
        self,
        *,
        merchant_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List project summaries with optional fixed filters."""

        normalized_merchant_id = (
            _uuid(merchant_id, "merchant_id")
            if merchant_id is not None
            else None
        )
        normalized_status = _optional_choice(
            status,
            "status",
            PROJECT_STATUSES,
        )
        query = """
            SELECT
                project.id,
                project.merchant_id,
                merchant.code AS merchant_code,
                merchant.name AS merchant_name,
                project.project_type,
                project.workflow_variant,
                project.title,
                project.status,
                project.requires_procurement,
                project.payment_period_number,
                project.started_at,
                project.completed_at,
                project.created_at,
                project.updated_at,
                project.version
            FROM merchant_ops.projects AS project
            JOIN merchant_ops.merchants AS merchant
              ON merchant.id = project.merchant_id
            WHERE (
                %s::uuid IS NULL
                OR project.merchant_id = %s
            )
              AND (
                %s::text IS NULL
                OR project.status = %s
              )
            ORDER BY project.created_at, project.id
        """
        parameters = (
            normalized_merchant_id,
            normalized_merchant_id,
            normalized_status,
            normalized_status,
        )

        with self.repository.connection(
            read_only=True
        ) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(query, parameters)
                    return _records(cursor.fetchall())

    def get_project_detail(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        """Return complete project state for later redacted rendering."""

        project_uuid = _uuid(project_id, "project_id")

        with self.repository.connection(
            read_only=True
        ) as connection:
            with connection.transaction():
                project = self._get_project(
                    connection,
                    project_uuid,
                )

                if project is None:
                    raise ProjectNotFoundError(
                        "Merchant project not found: "
                        f"{project_id}"
                    )

                merchant_id = project["merchant_id"]

                return {
                    "project": project,
                    "merchant_contacts": self._get_contacts(
                        connection,
                        merchant_id,
                    ),
                    "steps": (
                        self.repository._get_project_steps(
                            connection,
                            project_uuid,
                        )
                    ),
                    "dependencies": (
                        self.repository._get_dependencies(
                            connection,
                            project_uuid,
                        )
                    ),
                    "document_revisions": (
                        self.repository._get_document_revisions(
                            connection,
                            project_uuid,
                        )
                    ),
                    "document_approvals": (
                        self.repository._get_document_approvals(
                            connection,
                            project_uuid,
                        )
                    ),
                    "procurement_records": (
                        self.repository._get_procurement_records(
                            connection,
                            project_uuid,
                        )
                    ),
                    "integration_identifiers": (
                        self._get_integration_identifiers(
                            connection,
                            merchant_id,
                            project_uuid,
                        )
                    ),
                }

    def get_project_history(
        self,
        project_id: str,
        *,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> list[dict[str, Any]]:
        """Return append-only project events in chronological order."""

        project_uuid = _uuid(project_id, "project_id")
        normalized_limit = _history_limit(limit)

        with self.repository.connection(
            read_only=True
        ) as connection:
            with connection.transaction():
                self._require_project(
                    connection,
                    project_uuid,
                    project_id,
                )
                return self._get_project_history(
                    connection,
                    project_uuid,
                    normalized_limit,
                )

    @staticmethod
    def _get_project(
        connection: Any,
        project_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        query = """
            SELECT
                project.id,
                project.merchant_id,
                merchant.code AS merchant_code,
                merchant.name AS merchant_name,
                merchant.region_code AS merchant_region_code,
                merchant.account_status AS merchant_account_status,
                project.project_type,
                project.workflow_variant,
                project.workflow_template_version_id,
                project.reused_document_revision_id,
                project.title,
                project.status,
                project.requires_procurement,
                project.payment_period_number,
                project.started_at,
                project.completed_at,
                project.created_at,
                project.updated_at,
                project.version
            FROM merchant_ops.projects AS project
            JOIN merchant_ops.merchants AS merchant
              ON merchant.id = project.merchant_id
            WHERE project.id = %s
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id,))
            row = cursor.fetchone()
            return dict(row) if row is not None else None

    @staticmethod
    def _get_contacts(
        connection: Any,
        merchant_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                contact.id,
                contact.merchant_id,
                contact.contact_type,
                contact.name AS contact_name,
                contact.email AS contact_email,
                contact.phone AS contact_phone,
                contact.privacy_classification,
                contact.is_primary,
                contact.created_at,
                contact.version
            FROM merchant_ops.merchant_contacts AS contact
            WHERE contact.merchant_id = %s
            ORDER BY
                contact.is_primary DESC,
                contact.contact_type NULLS LAST,
                contact.id
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (merchant_id,))
            return _records(cursor.fetchall())

    @staticmethod
    def _get_integration_identifiers(
        connection: Any,
        merchant_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                identifier.id,
                identifier.project_id,
                identifier.merchant_id,
                identifier.identifier_type,
                identifier.identifier_value,
                identifier.scope,
                identifier.is_active,
                identifier.created_at,
                identifier.updated_at,
                identifier.version
            FROM merchant_ops.integration_identifiers AS identifier
            WHERE identifier.merchant_id = %s
              AND (
                  identifier.project_id = %s
                  OR identifier.project_id IS NULL
              )
            ORDER BY
                identifier.project_id NULLS FIRST,
                identifier.identifier_type,
                identifier.scope,
                identifier.id
        """

        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (merchant_id, project_id),
            )
            return _records(cursor.fetchall())

    @staticmethod
    def _require_project(
        connection: Any,
        project_id: uuid.UUID,
        original_project_id: str,
    ) -> None:
        query = """
            SELECT 1
            FROM merchant_ops.projects
            WHERE id = %s
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id,))

            if cursor.fetchone() is None:
                raise ProjectNotFoundError(
                    "Merchant project not found: "
                    f"{original_project_id}"
                )

    @staticmethod
    def _get_project_history(
        connection: Any,
        project_id: uuid.UUID,
        limit: int,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                event.id,
                event.merchant_id,
                event.project_id,
                event.event_type,
                event.entity_type,
                event.entity_id,
                event.change_summary,
                event.old_values,
                event.new_values,
                event.triggered_by,
                event.created_at
            FROM merchant_ops.project_events AS event
            WHERE event.project_id = %s
            ORDER BY event.created_at, event.id
            LIMIT %s
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id, limit))
            return _records(cursor.fetchall())


def _records(rows: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _uuid(value: Any, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be a valid UUID"
        ) from error


def _optional_choice(
    value: Any,
    field_name: str,
    choices: Collection[str],
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} must be one of: "
            f"{', '.join(sorted(choices))}"
        )

    normalized = value.strip().upper()

    if normalized not in choices:
        raise ValueError(
            f"{field_name} must be one of: "
            f"{', '.join(sorted(choices))}"
        )

    return normalized


def _history_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")

    if not 1 <= value <= MAX_HISTORY_LIMIT:
        raise ValueError(
            f"limit must be between 1 and {MAX_HISTORY_LIMIT}"
        )

    return value
