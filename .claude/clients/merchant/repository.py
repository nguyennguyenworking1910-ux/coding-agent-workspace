"""Data-access repository for Merchant projects and alert delivery.

This module contains PostgreSQL access only. It does not calculate alerts,
perform workflow transitions, or deliver notifications.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "psycopg 3 is required. Install it with: pip install psycopg[binary]"
    ) from exc


SCHEMA_NAME = "merchant_ops"
RUNTIME_DATABASE = "coding_agent_merchant"
TEST_DATABASE = "coding_agent_merchant_test"

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

try:
    from dotenv import load_dotenv

    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
except Exception:  # pragma: no cover
    pass


class MerchantRepositoryError(RuntimeError):
    """Base repository error."""


class ProjectNotFoundError(MerchantRepositoryError):
    """Raised when a project does not exist."""


@dataclass(frozen=True)
class RepositoryConfig:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    statement_timeout_ms: int = 15_000
    lock_timeout_ms: int = 5_000
    connect_timeout_seconds: int = 10
    application_name: str = "merchant-project-manager"

    @classmethod
    def from_env(cls, role: str = "app") -> "RepositoryConfig":
        normalized_role = role.strip().lower()

        role_configuration = {
            "app": (
                "MERCHANT_DB_NAME",
                RUNTIME_DATABASE,
                "MERCHANT_DB_USER",
                "merchant_app",
                "MERCHANT_DB_PASSWORD",
            ),
            "alert": (
                "MERCHANT_DB_NAME",
                RUNTIME_DATABASE,
                "MERCHANT_ALERT_USER",
                "merchant_alert",
                "MERCHANT_ALERT_PASSWORD",
            ),
            "owner": (
                "MERCHANT_DB_NAME",
                RUNTIME_DATABASE,
                "MERCHANT_OWNER_USER",
                "merchant_owner",
                "MERCHANT_OWNER_PASSWORD",
            ),
            "test": (
                "MERCHANT_TEST_DB_NAME",
                TEST_DATABASE,
                "MERCHANT_TEST_USER",
                "merchant_test",
                "MERCHANT_TEST_PASSWORD",
            ),
        }

        if normalized_role not in role_configuration:
            raise ValueError(
                f"Unsupported Merchant database role: {role}. "
                "Expected app, alert, owner, or test."
            )

        (
            database_variable,
            default_database,
            user_variable,
            default_user,
            password_variable,
        ) = role_configuration[normalized_role]

        database = os.environ.get(database_variable, default_database).strip()
        user = os.environ.get(user_variable, default_user).strip()
        password = os.environ.get(password_variable, "")

        if not database:
            raise ValueError(f"{database_variable} is empty")
        if not user:
            raise ValueError(f"{user_variable} is empty")
        if not password:
            raise ValueError(f"{password_variable} is empty")

        if normalized_role == "test":
            if database != TEST_DATABASE or not database.endswith("_test"):
                raise ValueError(
                    f"Test repository must target {TEST_DATABASE}, got {database}"
                )
        elif database != RUNTIME_DATABASE:
            raise ValueError(
                f"Runtime repository must target {RUNTIME_DATABASE}, got {database}"
            )

        return cls(
            host=os.environ.get("MERCHANT_DB_HOST", "127.0.0.1").strip(),
            port=_positive_int("MERCHANT_DB_PORT", 5434),
            database=database,
            user=user,
            password=password,
            statement_timeout_ms=_positive_int(
                "MERCHANT_STATEMENT_TIMEOUT_MS",
                15_000,
            ),
            lock_timeout_ms=_positive_int(
                "MERCHANT_LOCK_TIMEOUT_MS",
                5_000,
            ),
            connect_timeout_seconds=_positive_int(
                "MERCHANT_CONNECT_TIMEOUT_SECONDS",
                10,
            ),
        )


def _positive_int(variable: str, default: int) -> int:
    value = os.environ.get(variable, "").strip()

    if not value:
        return default

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{variable} must be an integer") from exc

    if parsed <= 0:
        raise ValueError(f"{variable} must be greater than zero")

    return parsed


def _record(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _records(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


class MerchantRepository:
    """Parameterized PostgreSQL repository for Merchant operational state."""

    def __init__(
        self,
        config: RepositoryConfig | None = None,
        *,
        role: str = "app",
        connect_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or RepositoryConfig.from_env(role)
        self._connect_fn = connect_fn or psycopg.connect

    @contextmanager
    def connection(
        self,
        *,
        read_only: bool = False,
    ) -> Iterator[psycopg.Connection]:
        options = [
            f"-c statement_timeout={self.config.statement_timeout_ms}",
            f"-c lock_timeout={self.config.lock_timeout_ms}",
            "-c timezone=Asia/Ho_Chi_Minh",
        ]

        if read_only:
            options.append("-c default_transaction_read_only=on")

        connection = self._connect_fn(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.database,
            user=self.config.user,
            password=self.config.password,
            connect_timeout=self.config.connect_timeout_seconds,
            application_name=self.config.application_name,
            options=" ".join(options),
            row_factory=dict_row,
            autocommit=False,
        )

        try:
            yield connection
        finally:
            connection.close()

    def list_open_project_ids(self) -> list[str]:
        query = """
            SELECT id
            FROM merchant_ops.projects
            WHERE status NOT IN ('COMPLETED', 'CANCELLED')
            ORDER BY created_at, id
        """

        with self.connection(read_only=True) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(query, ())
                    return [str(row["id"]) for row in cursor.fetchall()]

    def get_project_snapshot(self, project_id: str) -> dict[str, Any]:
        project_uuid = _validated_uuid(project_id, "project_id")

        with self.connection(read_only=True) as connection:
            with connection.transaction():
                project = self._get_project(connection, project_uuid)

                if project is None:
                    raise ProjectNotFoundError(
                        f"Merchant project not found: {project_id}"
                    )

                return {
                    "project": project,
                    "steps": self._get_project_steps(connection, project_uuid),
                    "dependencies": self._get_dependencies(
                        connection,
                        project_uuid,
                    ),
                    "document_revisions": self._get_document_revisions(
                        connection,
                        project_uuid,
                    ),
                    "document_approvals": self._get_document_approvals(
                        connection,
                        project_uuid,
                    ),
                    "procurement_records": self._get_procurement_records(
                        connection,
                        project_uuid,
                    ),
                }

    @staticmethod
    def _get_project(
        connection: psycopg.Connection,
        project_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        query = """
            SELECT
                p.id,
                p.merchant_id,
                m.code AS merchant_code,
                m.name AS merchant_name,
                p.project_type,
                p.workflow_variant,
                p.title,
                p.status,
                p.requires_procurement,
                p.started_at,
                p.completed_at,
                p.created_at,
                p.updated_at,
                p.version
            FROM merchant_ops.projects AS p
            JOIN merchant_ops.merchants AS m
              ON m.id = p.merchant_id
            WHERE p.id = %s
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id,))
            return _record(cursor.fetchone())

    @staticmethod
    def _get_project_steps(
        connection: psycopg.Connection,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                ps.id,
                ps.project_id,
                ps.template_step_id,
                ps.branch_key,
                ps.step_name,
                ps.status,
                ps.sequence_number,
                ps.scheduled_start,
                ps.scheduled_completion,
                ps.actual_start,
                ps.actual_completion,
                ps.notes,
                ps.version,
                wts.step_type,
                wts.condition_key,
                wts.is_optional
            FROM merchant_ops.project_steps AS ps
            LEFT JOIN merchant_ops.workflow_template_steps AS wts
              ON wts.id = ps.template_step_id
            WHERE ps.project_id = %s
            ORDER BY ps.sequence_number, ps.id
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id,))
            return _records(cursor.fetchall())

    @staticmethod
    def _get_dependencies(
        connection: psycopg.Connection,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                dependency.id,
                dependency.from_step_id,
                dependency.to_step_id,
                dependency.dependency_type
            FROM merchant_ops.project_step_dependencies AS dependency
            JOIN merchant_ops.project_steps AS destination
              ON destination.id = dependency.to_step_id
            WHERE destination.project_id = %s
            ORDER BY dependency.from_step_id, dependency.to_step_id
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id,))
            return _records(cursor.fetchall())

    @staticmethod
    def _get_document_revisions(
        connection: psycopg.Connection,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                id,
                project_id,
                document_type,
                revision_number,
                content_hash,
                signed,
                signed_at,
                effective_date,
                expiry_date,
                superseded_by,
                created_at
            FROM merchant_ops.document_revisions
            WHERE project_id = %s
            ORDER BY document_type, revision_number
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id,))
            return _records(cursor.fetchall())

    @staticmethod
    def _get_document_approvals(
        connection: psycopg.Connection,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                approval.id,
                approval.document_revision_id,
                approval.approver_role,
                approval.approval_status,
                approval.approved_at,
                approval.notes
            FROM merchant_ops.document_approvals AS approval
            JOIN merchant_ops.document_revisions AS revision
              ON revision.id = approval.document_revision_id
            WHERE revision.project_id = %s
            ORDER BY revision.revision_number, approval.approver_role
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id,))
            return _records(cursor.fetchall())

    @staticmethod
    def _get_procurement_records(
        connection: psycopg.Connection,
        project_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                id,
                project_id,
                procurement_type,
                external_id,
                status,
                created_at,
                updated_at,
                version
            FROM merchant_ops.procurement_records
            WHERE project_id = %s
            ORDER BY created_at, id
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id,))
            return _records(cursor.fetchall())

    def enqueue_alerts(
        self,
        alerts: Sequence[Mapping[str, Any]],
        *,
        delivery_channel: str = "INTERNAL",
    ) -> int:
        if not alerts:
            return 0

        normalized_channel = delivery_channel.strip().upper()

        if normalized_channel not in {"INTERNAL", "EMAIL", "SLACK"}:
            raise ValueError(
                f"Unsupported delivery channel: {delivery_channel}"
            )

        query = """
            INSERT INTO merchant_ops.alert_deliveries (
                id,
                project_id,
                project_step_id,
                alert_type,
                business_due_date,
                condition_fingerprint,
                deduplication_key,
                delivery_channel,
                delivery_status,
                delivery_attempt_count,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                'PENDING', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (deduplication_key, delivery_channel)
            DO NOTHING
        """

        inserted = 0

        with self.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    for alert in alerts:
                        cursor.execute(
                            query,
                            (
                                uuid.uuid4(),
                                _validated_uuid(
                                    str(alert["project_id"]),
                                    "project_id",
                                ),
                                _optional_uuid(
                                    alert.get("project_step_id"),
                                    "project_step_id",
                                ),
                                str(alert["alert_type"]),
                                alert.get("business_due_date"),
                                alert.get("condition_fingerprint"),
                                str(alert["deduplication_key"]),
                                normalized_channel,
                            ),
                        )

                        if cursor.rowcount > 0:
                            inserted += cursor.rowcount

        return inserted

    def claim_pending_alerts(
        self,
        *,
        delivery_channel: str = "INTERNAL",
        limit: int = 25,
        max_attempts: int = 5,
        retry_after_seconds: int = 300,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        query = """
            WITH candidates AS (
                SELECT id
                FROM merchant_ops.alert_deliveries
                WHERE delivery_channel = %s
                  AND delivery_status IN ('PENDING', 'FAILED')
                  AND delivery_attempt_count < %s
                  AND (
                      delivery_status = 'PENDING'
                      OR updated_at <= (
                          CURRENT_TIMESTAMP
                          - (%s * INTERVAL '1 second')
                      )
                  )
                ORDER BY created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE merchant_ops.alert_deliveries AS delivery
            SET
                delivery_status = 'FAILED',
                delivery_attempt_count =
                    delivery.delivery_attempt_count + 1,
                last_error_summary = 'Claimed for delivery',
                updated_at = CURRENT_TIMESTAMP
            FROM candidates
            WHERE delivery.id = candidates.id
            RETURNING
                delivery.id,
                delivery.project_id,
                delivery.project_step_id,
                delivery.alert_type,
                delivery.business_due_date,
                delivery.condition_fingerprint,
                delivery.deduplication_key,
                delivery.delivery_channel,
                delivery.delivery_status,
                delivery.delivery_attempt_count,
                delivery.created_at
        """

        with self.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            delivery_channel.strip().upper(),
                            max_attempts,
                            retry_after_seconds,
                            limit,
                        ),
                    )
                    return _records(cursor.fetchall())

    def mark_alert_sent(self, alert_id: str) -> None:
        self._update_delivery(
            alert_id,
            """
                UPDATE merchant_ops.alert_deliveries
                SET
                    delivery_status = 'SENT',
                    last_error_summary = NULL,
                    delivered_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """,
            (),
        )

    def mark_alert_failed(
        self,
        alert_id: str,
        error_summary: str,
    ) -> None:
        safe_summary = " ".join(error_summary.split())[:500]

        self._update_delivery(
            alert_id,
            """
                UPDATE merchant_ops.alert_deliveries
                SET
                    delivery_status = 'FAILED',
                    last_error_summary = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """,
            (safe_summary,),
        )

    def _update_delivery(
        self,
        alert_id: str,
        query: str,
        leading_parameters: Sequence[Any],
    ) -> None:
        delivery_uuid = _validated_uuid(alert_id, "alert_id")

        with self.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        query,
                        (*leading_parameters, delivery_uuid),
                    )

                    if cursor.rowcount != 1:
                        raise MerchantRepositoryError(
                            f"Alert delivery not found: {alert_id}"
                        )


def _validated_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc


def _optional_uuid(
    value: Any,
    field_name: str,
) -> uuid.UUID | None:
    if value in (None, ""):
        return None

    return _validated_uuid(str(value), field_name)