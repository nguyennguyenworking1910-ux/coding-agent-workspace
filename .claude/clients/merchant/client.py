"""Low-level PostgreSQL client for the Merchant domain.

The client provides:

- Explicit transaction boundaries
- Read-only database connections
- Dictionary-shaped query results
- Parameterized query execution
- Statement, lock, and connection timeouts
- Controlled ``merchant_ops`` search path
- Password-safe representations

Configuration is supplied by an object compatible with
``RepositoryConfig``. The client never builds SQL using user values.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Callable, Protocol, TypeAlias

import psycopg
from psycopg.rows import dict_row
from psycopg.sql import Composable


SCHEMA_NAME = "merchant_ops"
RUNTIME_DATABASE = "coding_agent_merchant"
TEST_DATABASE = "coding_agent_merchant_test"

ALLOWED_DATABASES = {
    RUNTIME_DATABASE,
    TEST_DATABASE,
}


class MerchantConnectionConfig(Protocol):
    """Configuration required to open a Merchant connection."""

    host: str
    port: int
    database: str
    user: str
    password: str
    statement_timeout_ms: int
    lock_timeout_ms: int
    connect_timeout_seconds: int
    application_name: str


Query: TypeAlias = str | Composable
Parameters: TypeAlias = (
    Sequence[Any]
    | Mapping[str, Any]
    | None
)
ParameterSet: TypeAlias = (
    Sequence[Any]
    | Mapping[str, Any]
)


class MerchantClientError(RuntimeError):
    """Base error raised by the Merchant PostgreSQL client."""


class MerchantClientConfigurationError(
    MerchantClientError,
    ValueError,
):
    """Raised when connection configuration is unsafe or invalid."""


class MerchantDatabaseClient:
    """Small PostgreSQL client with explicit transaction semantics.

    ``connection()`` never commits automatically. If callers need to
    persist changes, they must use ``transaction()`` or one of the
    write helpers such as ``execute()``.

    This prevents an accidental successful context exit from silently
    committing partially completed work.
    """

    def __init__(
        self,
        config: MerchantConnectionConfig,
        *,
        connect_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self._connect_fn = connect_fn or psycopg.connect

        self._validate_config()

    def __repr__(self) -> str:
        """Return a representation that never includes the password."""

        return (
            f"{type(self).__name__}("
            f"host={self.config.host!r}, "
            f"port={self.config.port!r}, "
            f"database={self.config.database!r}, "
            f"user={self.config.user!r}, "
            f"application_name="
            f"{self.config.application_name!r}"
            ")"
        )

    def _validate_config(self) -> None:
        """Fail closed when connection configuration is unsafe."""

        host = str(self.config.host).strip()
        database = str(self.config.database).strip()
        user = str(self.config.user).strip()
        password = str(self.config.password)
        application_name = str(
            self.config.application_name
        ).strip()

        if not host:
            raise MerchantClientConfigurationError(
                "Merchant database host cannot be empty"
            )

        if not isinstance(self.config.port, int):
            raise MerchantClientConfigurationError(
                "Merchant database port must be an integer"
            )

        if not 1 <= self.config.port <= 65535:
            raise MerchantClientConfigurationError(
                "Merchant database port must be between 1 and 65535"
            )

        if database not in ALLOWED_DATABASES:
            raise MerchantClientConfigurationError(
                "Merchant client may only connect to "
                f"{RUNTIME_DATABASE!r} or {TEST_DATABASE!r}; "
                f"received {database!r}"
            )

        if not user:
            raise MerchantClientConfigurationError(
                "Merchant database user cannot be empty"
            )

        if not password.strip():
            raise MerchantClientConfigurationError(
                "Merchant database password cannot be empty"
            )

        if (
            not isinstance(
                self.config.statement_timeout_ms,
                int,
            )
            or self.config.statement_timeout_ms <= 0
        ):
            raise MerchantClientConfigurationError(
                "statement_timeout_ms must be greater than zero"
            )

        if (
            not isinstance(
                self.config.lock_timeout_ms,
                int,
            )
            or self.config.lock_timeout_ms < 0
        ):
            raise MerchantClientConfigurationError(
                "lock_timeout_ms cannot be negative"
            )

        if (
            not isinstance(
                self.config.connect_timeout_seconds,
                int,
            )
            or self.config.connect_timeout_seconds <= 0
        ):
            raise MerchantClientConfigurationError(
                "connect_timeout_seconds must be greater than zero"
            )

        if not application_name:
            raise MerchantClientConfigurationError(
                "application_name cannot be empty"
            )

        if any(
            character in application_name
            for character in "\r\n\t"
        ):
            raise MerchantClientConfigurationError(
                "application_name cannot contain control whitespace"
            )

    def _connection_options(
        self,
        *,
        read_only: bool,
    ) -> str:
        """Build libpq options only from validated numeric constants."""

        options = [
            f"-c search_path={SCHEMA_NAME},pg_catalog",
            (
                "-c statement_timeout="
                f"{self.config.statement_timeout_ms}"
            ),
            (
                "-c lock_timeout="
                f"{self.config.lock_timeout_ms}"
            ),
        ]

        if read_only:
            options.append(
                "-c default_transaction_read_only=on"
            )

        return " ".join(options)

    def _open_connection(
        self,
        *,
        read_only: bool,
    ) -> Any:
        """Open one configured Psycopg connection."""

        return self._connect_fn(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.database,
            user=self.config.user,
            password=self.config.password,
            connect_timeout=(
                self.config.connect_timeout_seconds
            ),
            application_name=self.config.application_name,
            options=self._connection_options(
                read_only=read_only
            ),
            autocommit=False,
            row_factory=dict_row,
        )

    @contextmanager
    def connection(
        self,
        *,
        read_only: bool = False,
    ) -> Iterator[Any]:
        """Yield one connection and always close it.

        An unfinished transaction is rolled back when the context
        exits. Use ``transaction()`` when writes should be committed.
        """

        connection = self._open_connection(
            read_only=read_only
        )

        try:
            yield connection

        except Exception:
            if not connection.closed:
                connection.rollback()

            raise

        finally:
            if not connection.closed:
                try:
                    connection.rollback()
                except psycopg.Error:
                    # Closing the connection still guarantees that
                    # PostgreSQL discards any unfinished transaction.
                    pass

                connection.close()

    @contextmanager
    def transaction(
        self,
        *,
        read_only: bool = False,
    ) -> Iterator[Any]:
        """Run work inside one atomic PostgreSQL transaction."""

        with self.connection(
            read_only=read_only
        ) as connection:
            with connection.transaction():
                yield connection

    @staticmethod
    def _execute_cursor(
        cursor: Any,
        query: Query,
        parameters: Parameters,
    ) -> None:
        """Execute a query while preserving parameterization."""

        if parameters is None:
            cursor.execute(query)
        else:
            cursor.execute(query, parameters)

    def fetch_one(
        self,
        query: Query,
        parameters: Parameters = None,
    ) -> dict[str, Any] | None:
        """Execute one read-only query and return one row."""

        with self.transaction(
            read_only=True
        ) as connection:
            with connection.cursor() as cursor:
                self._execute_cursor(
                    cursor,
                    query,
                    parameters,
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return dict(row)

    def fetch_all(
        self,
        query: Query,
        parameters: Parameters = None,
    ) -> list[dict[str, Any]]:
        """Execute one read-only query and return all rows."""

        with self.transaction(
            read_only=True
        ) as connection:
            with connection.cursor() as cursor:
                self._execute_cursor(
                    cursor,
                    query,
                    parameters,
                )
                rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def execute(
        self,
        query: Query,
        parameters: Parameters = None,
    ) -> int:
        """Execute one write statement atomically.

        Returns the number of affected rows reported by PostgreSQL.
        """

        with self.transaction() as connection:
            with connection.cursor() as cursor:
                self._execute_cursor(
                    cursor,
                    query,
                    parameters,
                )
                affected_rows = cursor.rowcount

        return affected_rows

    def execute_many(
        self,
        query: Query,
        parameter_sets: Sequence[ParameterSet],
    ) -> int:
        """Execute a parameterized statement for multiple records."""

        if not parameter_sets:
            return 0

        with self.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    query,
                    parameter_sets,
                )
                affected_rows = cursor.rowcount

        return affected_rows

    def execute_returning_one(
        self,
        query: Query,
        parameters: Parameters = None,
    ) -> dict[str, Any] | None:
        """Execute one write query and return its first result row."""

        with self.transaction() as connection:
            with connection.cursor() as cursor:
                self._execute_cursor(
                    cursor,
                    query,
                    parameters,
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return dict(row)

    def health_check(self) -> dict[str, Any]:
        """Verify database identity and read-only query execution."""

        row = self.fetch_one(
            """
            SELECT
                current_database() AS database,
                current_user AS database_user,
                current_schema() AS current_schema,
                current_setting(
                    'transaction_read_only'
                ) AS transaction_read_only
            """
        )

        if row is None:
            raise MerchantClientError(
                "Merchant database health check returned no row"
            )

        expected_database = self.config.database

        if row["database"] != expected_database:
            raise MerchantClientError(
                "Merchant database identity mismatch: "
                f"expected {expected_database!r}, "
                f"received {row['database']!r}"
            )

        return row


# Short compatibility name for callers that prefer MerchantClient.
MerchantClient = MerchantDatabaseClient


__all__ = [
    "ALLOWED_DATABASES",
    "MerchantClient",
    "MerchantClientConfigurationError",
    "MerchantClientError",
    "MerchantConnectionConfig",
    "MerchantDatabaseClient",
    "RUNTIME_DATABASE",
    "SCHEMA_NAME",
    "TEST_DATABASE",
]