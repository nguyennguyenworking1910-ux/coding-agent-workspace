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
DELIVERY_CHANNELS = frozenset({"INTERNAL", "EMAIL", "SLACK"})
MAX_ALERT_PROJECT_LIMIT = 500
MAX_DELIVERY_CLAIM_LIMIT = 100
MAX_DELIVERY_ATTEMPTS = 10
MIN_DELIVERY_LEASE_SECONDS = 30
MAX_DELIVERY_LEASE_SECONDS = 900
MAX_DELIVERY_RETRY_SECONDS = 86_400
SAFE_DELIVERY_ERROR_CODES = frozenset(
    {
        "ATTEMPTS_EXHAUSTED",
        "CLAIM_LOST",
        "CONFIGURATION_INVALID",
        "PROVIDER_REJECTED",
        "PROVIDER_RESPONSE_INVALID",
        "TRANSPORT_TIMEOUT",
        "TRANSPORT_UNAVAILABLE",
        "UNEXPECTED_FAILURE",
    }
)

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


class AlertClaimLostError(MerchantRepositoryError):
    """Raised when a worker no longer owns an alert delivery claim."""


class ProjectScanLimitExceededError(MerchantRepositoryError):
    """Raised instead of silently truncating open-project discovery."""


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

    def list_open_project_ids(self, *, limit: int = 100) -> list[str]:
        _validated_bounded_int(
            limit,
            field_name="limit",
            minimum=1,
            maximum=MAX_ALERT_PROJECT_LIMIT,
        )
        query = """
            SELECT id
            FROM merchant_ops.projects
            WHERE status NOT IN ('COMPLETED', 'CANCELLED')
            ORDER BY created_at, id
            LIMIT %s
        """

        with self.connection(read_only=True) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(query, (limit + 1,))
                    rows = cursor.fetchall()

                    if len(rows) > limit:
                        raise ProjectScanLimitExceededError(
                            "Open project scan exceeds configured limit"
                        )

                    return [str(row["id"]) for row in rows]

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
                p.workflow_template_version_id,
                p.reused_document_revision_id,
                p.title,
                p.status,
                p.requires_procurement,
                p.payment_period_number,
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
            FROM merchant_ops.document_revisions AS revision
            WHERE revision.project_id = %s
               OR revision.id = (
                    SELECT project.reused_document_revision_id
                    FROM merchant_ops.projects AS project
                    WHERE project.id = %s
               )
            ORDER BY
                revision.document_type,
                revision.revision_number,
                revision.id
        """

        with connection.cursor() as cursor:
            cursor.execute(query, (project_id, project_id))
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

        normalized_channel = _validated_delivery_channel(
            delivery_channel
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
        lease_seconds: int = 120,
    ) -> list[dict[str, Any]]:
        normalized_channel = _validated_delivery_channel(
            delivery_channel
        )
        _validated_bounded_int(
            limit,
            field_name="limit",
            minimum=1,
            maximum=MAX_DELIVERY_CLAIM_LIMIT,
        )
        _validated_bounded_int(
            max_attempts,
            field_name="max_attempts",
            minimum=1,
            maximum=MAX_DELIVERY_ATTEMPTS,
        )
        _validated_bounded_int(
            lease_seconds,
            field_name="lease_seconds",
            minimum=MIN_DELIVERY_LEASE_SECONDS,
            maximum=MAX_DELIVERY_LEASE_SECONDS,
        )
        claim_token = uuid.uuid4()

        query = """
            WITH terminal_candidates AS (
                SELECT id
                FROM merchant_ops.alert_deliveries
                WHERE delivery_channel = %s
                  AND delivery_attempt_count >= %s
                  AND (
                      (
                          delivery_status IN ('PENDING', 'FAILED')
                          AND (
                              next_attempt_at IS NULL
                              OR next_attempt_at <= CURRENT_TIMESTAMP
                          )
                      )
                      OR (
                          delivery_status = 'CLAIMED'
                          AND claim_expires_at <= CURRENT_TIMESTAMP
                      )
                  )
                ORDER BY updated_at, created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            ),
            exhausted AS (
                UPDATE merchant_ops.alert_deliveries AS delivery
                SET
                    delivery_status = 'DEAD_LETTER',
                    claim_token = NULL,
                    claim_expires_at = NULL,
                    next_attempt_at = NULL,
                    last_error_summary = 'ATTEMPTS_EXHAUSTED',
                    updated_at = CURRENT_TIMESTAMP
                FROM terminal_candidates
                WHERE delivery.id = terminal_candidates.id
                RETURNING delivery.id
            ),
            candidates AS (
                SELECT id
                FROM merchant_ops.alert_deliveries
                WHERE delivery_channel = %s
                  AND delivery_attempt_count < %s
                  AND (
                      (
                          delivery_status IN ('PENDING', 'FAILED')
                          AND (
                              next_attempt_at IS NULL
                              OR next_attempt_at <= CURRENT_TIMESTAMP
                          )
                      )
                      OR (
                          delivery_status = 'CLAIMED'
                          AND claim_expires_at <= CURRENT_TIMESTAMP
                      )
                  )
                ORDER BY
                    COALESCE(next_attempt_at, created_at),
                    created_at,
                    id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE merchant_ops.alert_deliveries AS delivery
            SET
                delivery_status = 'CLAIMED',
                delivery_attempt_count =
                    delivery.delivery_attempt_count + 1,
                claim_token = %s,
                claim_expires_at = (
                    CURRENT_TIMESTAMP
                    + (%s * INTERVAL '1 second')
                ),
                next_attempt_at = NULL,
                last_attempt_at = CURRENT_TIMESTAMP,
                last_error_summary = NULL,
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
                delivery.claim_token,
                delivery.claim_expires_at,
                delivery.next_attempt_at,
                delivery.last_attempt_at,
                delivery.provider_message_id,
                delivery.created_at
        """

        with self.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            normalized_channel,
                            max_attempts,
                            limit,
                            normalized_channel,
                            max_attempts,
                            limit,
                            claim_token,
                            lease_seconds,
                        ),
                    )
                    return _records(cursor.fetchall())

    def mark_alert_sent(
        self,
        alert_id: str,
        claim_token: str,
        *,
        provider_message_id: str | None = None,
    ) -> None:
        safe_provider_message_id = _validated_provider_message_id(
            provider_message_id
        )
        self._update_claimed_delivery(
            alert_id,
            claim_token,
            """
                UPDATE merchant_ops.alert_deliveries
                SET
                    delivery_status = 'SENT',
                    claim_token = NULL,
                    claim_expires_at = NULL,
                    next_attempt_at = NULL,
                    last_error_summary = NULL,
                    provider_message_id = %s,
                    delivered_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                  AND delivery_status = 'CLAIMED'
                  AND claim_token = %s
            """,
            (safe_provider_message_id,),
        )

    def mark_alert_failed(
        self,
        alert_id: str,
        claim_token: str,
        error_summary: str,
        *,
        retry_after_seconds: int | None,
    ) -> None:
        safe_summary = _validated_error_code(error_summary)

        if retry_after_seconds is None:
            self._update_claimed_delivery(
                alert_id,
                claim_token,
                """
                    UPDATE merchant_ops.alert_deliveries
                    SET
                        delivery_status = 'DEAD_LETTER',
                        claim_token = NULL,
                        claim_expires_at = NULL,
                        next_attempt_at = NULL,
                        last_error_summary = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND delivery_status = 'CLAIMED'
                      AND claim_token = %s
                """,
                (safe_summary,),
            )
            return

        _validated_bounded_int(
            retry_after_seconds,
            field_name="retry_after_seconds",
            minimum=1,
            maximum=MAX_DELIVERY_RETRY_SECONDS,
        )
        self._update_claimed_delivery(
            alert_id,
            claim_token,
            """
                UPDATE merchant_ops.alert_deliveries
                SET
                    delivery_status = 'FAILED',
                    claim_token = NULL,
                    claim_expires_at = NULL,
                    next_attempt_at = (
                        CURRENT_TIMESTAMP
                        + (%s * INTERVAL '1 second')
                    ),
                    last_error_summary = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                  AND delivery_status = 'CLAIMED'
                  AND claim_token = %s
            """,
            (retry_after_seconds, safe_summary),
        )

    def get_alert_queue_status(
        self,
        *,
        delivery_channel: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_channel = (
            _validated_delivery_channel(delivery_channel)
            if delivery_channel is not None
            else None
        )
        query = """
            SELECT
                delivery_channel,
                COUNT(*) AS total_count,
                COUNT(*) FILTER (
                    WHERE delivery_status IN ('PENDING', 'FAILED')
                      AND (
                          next_attempt_at IS NULL
                          OR next_attempt_at <= CURRENT_TIMESTAMP
                      )
                ) AS ready_count,
                COUNT(*) FILTER (
                    WHERE delivery_status = 'CLAIMED'
                      AND claim_expires_at > CURRENT_TIMESTAMP
                ) AS active_claim_count,
                COUNT(*) FILTER (
                    WHERE delivery_status = 'CLAIMED'
                      AND claim_expires_at <= CURRENT_TIMESTAMP
                ) AS expired_claim_count,
                COUNT(*) FILTER (
                    WHERE delivery_status = 'FAILED'
                ) AS retryable_failure_count,
                COUNT(*) FILTER (
                    WHERE delivery_status = 'DEAD_LETTER'
                ) AS dead_letter_count,
                MIN(created_at) FILTER (
                    WHERE delivery_status IN ('PENDING', 'FAILED')
                ) AS oldest_pending_at,
                MAX(delivered_at) FILTER (
                    WHERE delivery_status IN ('SENT', 'ACKNOWLEDGED')
                ) AS most_recent_delivery_at
            FROM merchant_ops.alert_deliveries
            WHERE (
                CAST(%s AS VARCHAR) IS NULL
                OR delivery_channel = %s
            )
            GROUP BY delivery_channel
            ORDER BY delivery_channel
        """

        with self.connection(read_only=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query,
                    (normalized_channel, normalized_channel),
                )
                return _records(cursor.fetchall())

    def get_alert_worker_health_snapshot(self) -> dict[str, Any]:
        """Read only non-business state required by ``--health-check``."""
        identity_query = """
            SELECT
                current_database() AS database,
                current_user AS user,
                current_setting('transaction_read_only') AS read_only,
                current_setting('server_encoding') AS encoding
        """
        columns_query = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'alert_deliveries'
              AND column_name IN (
                  'claim_token',
                  'claim_expires_at',
                  'next_attempt_at',
                  'last_attempt_at',
                  'provider_message_id'
              )
            ORDER BY column_name
        """
        constraints_query = """
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_schema = %s
              AND table_name = 'alert_deliveries'
              AND constraint_name IN (
                  'alert_deliveries_status_check',
                  'alert_deliveries_claim_state_check',
                  'alert_deliveries_next_attempt_state_check',
                  'alert_deliveries_dead_letter_state_check',
                  'alert_deliveries_provider_message_state_check'
              )
            ORDER BY constraint_name
        """
        index_query = """
            SELECT indexdef
            FROM pg_catalog.pg_indexes
            WHERE schemaname = %s
              AND tablename = 'alert_deliveries'
              AND indexname = 'alert_deliveries_claim_idx'
        """
        privilege_query = """
            SELECT
                has_table_privilege(
                    current_user,
                    'merchant_ops.alert_deliveries',
                    'SELECT'
                ) AS can_select,
                has_table_privilege(
                    current_user,
                    'merchant_ops.alert_deliveries',
                    'INSERT'
                ) AS can_insert,
                has_table_privilege(
                    current_user,
                    'merchant_ops.alert_deliveries',
                    'UPDATE'
                ) AS can_update
        """

        with self.connection(read_only=True) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(identity_query, ())
                    identity = _record(cursor.fetchone()) or {}

                    cursor.execute(columns_query, (SCHEMA_NAME,))
                    lease_columns = tuple(
                        str(row["column_name"])
                        for row in cursor.fetchall()
                    )

                    cursor.execute(constraints_query, (SCHEMA_NAME,))
                    lease_constraints = tuple(
                        str(row["constraint_name"])
                        for row in cursor.fetchall()
                    )

                    cursor.execute(index_query, (SCHEMA_NAME,))
                    index_row = _record(cursor.fetchone())

                    cursor.execute(privilege_query, ())
                    privileges = _record(cursor.fetchone()) or {}

        return {
            **identity,
            "lease_columns": lease_columns,
            "lease_constraints": lease_constraints,
            "claim_index_definition": (
                str(index_row["indexdef"])
                if index_row is not None
                else None
            ),
            "alert_table_privileges": {
                "select": bool(privileges.get("can_select")),
                "insert": bool(privileges.get("can_insert")),
                "update": bool(privileges.get("can_update")),
            },
        }

    def _update_claimed_delivery(
        self,
        alert_id: str,
        claim_token: str,
        query: str,
        leading_parameters: Sequence[Any],
    ) -> None:
        delivery_uuid = _validated_uuid(alert_id, "alert_id")
        claim_uuid = _validated_uuid(claim_token, "claim_token")

        with self.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            *leading_parameters,
                            delivery_uuid,
                            claim_uuid,
                        ),
                    )

                    if cursor.rowcount != 1:
                        raise AlertClaimLostError(
                            "Alert delivery claim is no longer current"
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


def _validated_delivery_channel(value: Any) -> str:
    normalized = str(value).strip().upper()

    if normalized not in DELIVERY_CHANNELS:
        raise ValueError("delivery_channel is not supported")

    return normalized


def _validated_bounded_int(
    value: Any,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ValueError(
            f"{field_name} must be between {minimum} and {maximum}"
        )

    return value


def _validated_provider_message_id(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()

    if (
        not normalized
        or len(normalized) > 255
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("provider_message_id is invalid")

    return normalized


def _validated_error_code(value: Any) -> str:
    normalized = str(value).strip().upper()

    if normalized not in SAFE_DELIVERY_ERROR_CODES:
        raise ValueError("error_summary must be a safe reason code")

    return normalized
