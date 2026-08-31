"""Read-only verification of Merchant database bootstrap state."""

from __future__ import annotations

from typing import Any, Optional

try:
    import psycopg
    from psycopg import sql
except ImportError:
    raise ImportError(
        "psycopg 3 is required for Merchant bootstrap. "
        "Install it with: pip install psycopg[binary]"
    )


# ============================================================================
# Configuration & Constants
# ============================================================================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5434
DEFAULT_ADMIN_USER = "rag_user"

RUNTIME_DB_NAME = "coding_agent_merchant"
TEST_DB_NAME = "coding_agent_merchant_test"
SCHEMA_NAME = "merchant_ops"

ROLE_OWNER = "merchant_owner"
ROLE_APP = "merchant_app"
ROLE_ALERT = "merchant_alert"
ROLE_TEST = "merchant_test"

ALL_ROLES = {ROLE_OWNER, ROLE_APP, ROLE_ALERT, ROLE_TEST}


# ============================================================================
# Utilities
# ============================================================================

def _redact_connection_string(host: str, port: int, user: str) -> str:
    """Return a redacted connection string for logging (no password)."""
    return f"postgresql://{user}@{host}:{port}"


# ============================================================================
# Verification Functions
# ============================================================================

def _role_exists(conn: psycopg.Connection, role_name: str) -> bool:
    """Check if a PostgreSQL role exists."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT 1 FROM pg_roles WHERE rolname = %s"),
            (role_name,),
        )
        return cur.fetchone() is not None


def _database_exists(conn: psycopg.Connection, db_name: str) -> bool:
    """Check if a database exists."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT 1 FROM pg_database WHERE datname = %s"),
            (db_name,),
        )
        return cur.fetchone() is not None


def _get_database_owner(conn: psycopg.Connection, db_name: str) -> Optional[str]:
    """Get the owner of a database, or None if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT rolname FROM pg_database "
                "JOIN pg_roles ON pg_database.datdba = pg_roles.oid "
                "WHERE datname = %s"
            ),
            (db_name,),
        )
        result = cur.fetchone()
        return result[0] if result else None


def _get_database_encoding(conn: psycopg.Connection, db_name: str) -> Optional[str]:
    """Get the encoding of a database."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = %s"),
            (db_name,),
        )
        result = cur.fetchone()
        return result[0] if result else None


def _schema_exists(
    conn: psycopg.Connection,
    schema_name: str,
) -> bool:
    """Check if a schema exists in the current database."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT 1 FROM pg_namespace WHERE nspname = %s"),
            (schema_name,),
        )
        return cur.fetchone() is not None


def _get_schema_owner(
    conn: psycopg.Connection,
    schema_name: str,
) -> Optional[str]:
    """Get the owner of a schema in the current database, or None."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT rolname FROM pg_namespace "
                "JOIN pg_roles ON pg_namespace.nspowner = pg_roles.oid "
                "WHERE nspname = %s"
            ),
            (schema_name,),
        )
        result = cur.fetchone()
        return result[0] if result else None


def _table_exists(
    conn: psycopg.Connection,
    schema_name: str,
    table_name: str,
) -> bool:
    """Check if a table exists in a schema."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s"
            ),
            (schema_name, table_name),
        )
        return cur.fetchone() is not None


def _has_public_privileges_on_database(
    conn: psycopg.Connection,
    db_name: str,
) -> bool:
    """Check if PUBLIC has any privileges on a database.

    Returns False if no public privileges found (secure), True if found.
    NULL ACL is secure (no public privileges).
    """
    with conn.cursor() as cur:
        # PostgreSQL ACL format can be NULL (secure) or contain text like "{=Tc/postgres}"
        # PUBLIC appears as empty grantee followed by =privileges (e.g., "=Tc/...")
        # We check if the ACL text contains "=" at the start or after comma
        cur.execute(
            sql.SQL(
                "SELECT 1 FROM pg_database WHERE datname = %s "
                "AND datacl IS NOT NULL "
                "AND datacl::text ~ '(^|,)='"
            ),
            (db_name,),
        )
        return cur.fetchone() is not None


def _has_public_privileges_on_schema(
    db_conn: psycopg.Connection,
    schema_name: str,
) -> bool:
    """Check if PUBLIC has any privileges on a schema in the connected database.

    Returns False if no public privileges found (secure), True if found.
    NULL ACL is secure (no public privileges).
    """
    with db_conn.cursor() as cur:
        # PostgreSQL ACL format can be NULL (secure) or contain text like "{owner=UC/owner,public=U/owner}"
        # PUBLIC appears as empty grantee followed by =privileges
        cur.execute(
            sql.SQL(
                "SELECT 1 FROM pg_namespace "
                "WHERE nspname = %s "
                "AND nspacl IS NOT NULL "
                "AND nspacl::text ~ '(^|,)='"
            ),
            (schema_name,),
        )
        return cur.fetchone() is not None


def _role_has_connect_on_database(
    conn: psycopg.Connection,
    role_name: str,
    db_name: str,
) -> bool:
    """Check if a role has CONNECT privilege on a database."""
    with conn.cursor() as cur:
        # Check if role has CONNECT privilege
        cur.execute(
            sql.SQL(
                "SELECT 1 FROM information_schema.role_table_grants "
                "WHERE grantee = %s AND table_catalog = %s AND privilege_type = 'CONNECT'"
            ),
            (role_name, db_name),
        )
        result = cur.fetchone()
        return result is not None


def _role_has_usage_on_schema(
    db_conn: psycopg.Connection,
    role_name: str,
    schema_name: str,
) -> bool:
    """Check if a role has USAGE privilege on a schema in the connected database."""
    with db_conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT 1 FROM information_schema.role_usage_grants "
                "WHERE grantee = %s AND table_schema = %s"
            ),
            (role_name, schema_name),
        )
        result = cur.fetchone()
        return result is not None


# ============================================================================
# Main Verification Function
# ============================================================================

def verify_bootstrap(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    admin_user: str = DEFAULT_ADMIN_USER,
    admin_password: str = "",
    runtime_db: str = RUNTIME_DB_NAME,
    test_db: str = TEST_DB_NAME,
) -> dict[str, Any]:
    """Verify the Merchant database bootstrap (read-only).

    Checks that:
    - Server is reachable
    - Both databases exist with correct owners
    - UTF-8 encoding is set
    - merchant_ops schema exists in both databases
    - schema_migrations table exists
    - PUBLIC privileges are revoked
    - Grant constraints are verified
    - Test database isolation is verified
    - RAG database still exists

    Args:
        host: PostgreSQL server hostname (default: 127.0.0.1)
        port: PostgreSQL server port (default: 5434)
        admin_user: Admin user to connect as (default: rag_user)
        admin_password: Password for admin user
        runtime_db: Runtime database name (default: coding_agent_merchant)
        test_db: Test database name (default: coding_agent_merchant_test)

    Returns:
        dict with keys:
        - "success": True if all checks pass
        - "connection": Redacted connection string (no passwords)
        - "server_reachable": bool
        - "merchant_owner_exists": bool
        - "merchant_app_exists": bool
        - "merchant_alert_exists": bool
        - "merchant_test_exists": bool
        - "runtime_db_exists": bool
        - "runtime_db_owner": str or None
        - "runtime_db_encoding_utf8": bool
        - "test_db_exists": bool
        - "test_db_owner": str or None
        - "test_db_encoding_utf8": bool
        - "runtime_schema_exists": bool
        - "runtime_schema_owner": str or None
        - "test_schema_exists": bool
        - "test_schema_owner": str or None
        - "runtime_schema_migrations_exists": bool
        - "test_schema_migrations_exists": bool
        - "runtime_db_no_public_privileges": bool
        - "test_db_no_public_privileges": bool
        - "runtime_schema_no_public_privileges": bool
        - "test_schema_no_public_privileges": bool
        - "merchant_owner_has_runtime_connect": bool
        - "merchant_app_has_runtime_connect": bool
        - "merchant_alert_has_runtime_connect": bool
        - "merchant_test_has_test_connect": bool
        - "merchant_app_lacks_test_connect": bool
        - "merchant_alert_lacks_test_connect": bool
        - "runtime_app_has_schema_usage": bool
        - "runtime_alert_has_schema_usage": bool
        - "test_role_has_schema_usage": bool
        - "rag_database_exists": bool
        - "errors": List of error messages if any

    Note: This function is read-only and never modifies anything.
    """
    result = {
        "success": False,
        "connection": _redact_connection_string(host, port, admin_user),
        "server_reachable": False,
        "merchant_owner_exists": False,
        "merchant_app_exists": False,
        "merchant_alert_exists": False,
        "merchant_test_exists": False,
        "runtime_db_exists": False,
        "runtime_db_owner": None,
        "runtime_db_encoding_utf8": False,
        "test_db_exists": False,
        "test_db_owner": None,
        "test_db_encoding_utf8": False,
        "runtime_schema_exists": False,
        "runtime_schema_owner": None,
        "test_schema_exists": False,
        "test_schema_owner": None,
        "runtime_schema_migrations_exists": False,
        "test_schema_migrations_exists": False,
        "runtime_db_no_public_privileges": False,
        "test_db_no_public_privileges": False,
        "runtime_schema_no_public_privileges": False,
        "test_schema_no_public_privileges": False,
        "merchant_owner_has_runtime_connect": False,
        "merchant_app_has_runtime_connect": False,
        "merchant_alert_has_runtime_connect": False,
        "merchant_test_has_test_connect": False,
        "merchant_app_lacks_test_connect": False,
        "merchant_alert_lacks_test_connect": False,
        "runtime_app_has_schema_usage": False,
        "runtime_alert_has_schema_usage": False,
        "test_role_has_schema_usage": False,
        "rag_database_exists": False,
        "errors": [],
    }

    try:
        # Connect to the server as admin (read-only, will use REPEATABLE READ)
        conn = psycopg.connect(
            host=host,
            port=port,
            user=admin_user,
            password=admin_password,
            autocommit=False,
        )

        try:
            # Set read-only mode
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")

            result["server_reachable"] = True

            # Check roles
            result["merchant_owner_exists"] = _role_exists(conn, ROLE_OWNER)
            result["merchant_app_exists"] = _role_exists(conn, ROLE_APP)
            result["merchant_alert_exists"] = _role_exists(conn, ROLE_ALERT)
            result["merchant_test_exists"] = _role_exists(conn, ROLE_TEST)

            # Check runtime database
            result["runtime_db_exists"] = _database_exists(conn, runtime_db)
            if result["runtime_db_exists"]:
                result["runtime_db_owner"] = _get_database_owner(conn, runtime_db)
                encoding = _get_database_encoding(conn, runtime_db)
                result["runtime_db_encoding_utf8"] = encoding == "UTF8"

                # Check if runtime database has no public privileges
                result["runtime_db_no_public_privileges"] = not _has_public_privileges_on_database(
                    conn, runtime_db
                )

            # Check test database
            result["test_db_exists"] = _database_exists(conn, test_db)
            if result["test_db_exists"]:
                result["test_db_owner"] = _get_database_owner(conn, test_db)
                encoding = _get_database_encoding(conn, test_db)
                result["test_db_encoding_utf8"] = encoding == "UTF8"

                # Check if test database has no public privileges
                result["test_db_no_public_privileges"] = not _has_public_privileges_on_database(
                    conn, test_db
                )

            # Check RAG database
            result["rag_database_exists"] = _database_exists(conn, "coding_agent_rag")

            # Check schema and tables in runtime database
            if result["runtime_db_exists"]:
                try:
                    with psycopg.connect(
                        host=host,
                        port=port,
                        user=admin_user,
                        password=admin_password,
                        dbname=runtime_db,
                        autocommit=False,
                    ) as db_conn:
                        # Set read-only
                        with db_conn.cursor() as cur:
                            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")

                        result["runtime_schema_exists"] = _schema_exists(db_conn, SCHEMA_NAME)
                        if result["runtime_schema_exists"]:
                            result["runtime_schema_owner"] = _get_schema_owner(db_conn, SCHEMA_NAME)
                            result["runtime_schema_migrations_exists"] = _table_exists(
                                db_conn, SCHEMA_NAME, "schema_migrations"
                            )
                            result["runtime_schema_no_public_privileges"] = not _has_public_privileges_on_schema(
                                db_conn, SCHEMA_NAME
                            )

                            # Check grant status for app and alert
                            result["runtime_app_has_schema_usage"] = _role_has_usage_on_schema(db_conn, ROLE_APP, SCHEMA_NAME)
                            result["runtime_alert_has_schema_usage"] = _role_has_usage_on_schema(db_conn, ROLE_ALERT, SCHEMA_NAME)

                except Exception as e:
                    result["errors"].append(f"Error checking runtime database: {str(e)}")

            # Check schema and tables in test database
            if result["test_db_exists"]:
                try:
                    with psycopg.connect(
                        host=host,
                        port=port,
                        user=admin_user,
                        password=admin_password,
                        dbname=test_db,
                        autocommit=False,
                    ) as db_conn:
                        # Set read-only
                        with db_conn.cursor() as cur:
                            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")

                        result["test_schema_exists"] = _schema_exists(db_conn, SCHEMA_NAME)
                        if result["test_schema_exists"]:
                            result["test_schema_owner"] = _get_schema_owner(db_conn, SCHEMA_NAME)
                            result["test_schema_migrations_exists"] = _table_exists(
                                db_conn, SCHEMA_NAME, "schema_migrations"
                            )
                            result["test_schema_no_public_privileges"] = not _has_public_privileges_on_schema(
                                db_conn, SCHEMA_NAME
                            )

                            # Check grant status for test role
                            result["test_role_has_schema_usage"] = _role_has_usage_on_schema(db_conn, ROLE_TEST, SCHEMA_NAME)

                except Exception as e:
                    result["errors"].append(f"Error checking test database: {str(e)}")

            # Check CONNECT privileges on databases
            result["merchant_owner_has_runtime_connect"] = _role_has_connect_on_database(conn, ROLE_OWNER, runtime_db)
            result["merchant_app_has_runtime_connect"] = _role_has_connect_on_database(conn, ROLE_APP, runtime_db)
            result["merchant_alert_has_runtime_connect"] = _role_has_connect_on_database(conn, ROLE_ALERT, runtime_db)
            result["merchant_test_has_test_connect"] = _role_has_connect_on_database(conn, ROLE_TEST, test_db)

            # Check that app and alert do NOT have CONNECT on test database
            result["merchant_app_lacks_test_connect"] = not _role_has_connect_on_database(conn, ROLE_APP, test_db)
            result["merchant_alert_lacks_test_connect"] = not _role_has_connect_on_database(conn, ROLE_ALERT, test_db)

            # Check overall success
            all_checks = [
                result["server_reachable"],
                result["merchant_owner_exists"],
                result["merchant_app_exists"],
                result["merchant_alert_exists"],
                result["merchant_test_exists"],
                result["runtime_db_exists"],
                result["runtime_db_owner"] == ROLE_OWNER,
                result["runtime_db_encoding_utf8"],
                result["test_db_exists"],
                result["test_db_owner"] == ROLE_TEST,
                result["test_db_encoding_utf8"],
                result["runtime_schema_exists"],
                result["runtime_schema_owner"] == ROLE_OWNER,
                result["runtime_schema_migrations_exists"],
                result["runtime_db_no_public_privileges"],
                result["test_schema_exists"],
                result["test_schema_owner"] == ROLE_TEST,
                result["test_schema_migrations_exists"],
                result["test_db_no_public_privileges"],
                result["rag_database_exists"],
                result["merchant_owner_has_runtime_connect"],
                result["merchant_app_has_runtime_connect"],
                result["merchant_alert_has_runtime_connect"],
                result["merchant_test_has_test_connect"],
                result["merchant_app_lacks_test_connect"],
                result["merchant_alert_lacks_test_connect"],
                result["runtime_app_has_schema_usage"],
                result["runtime_alert_has_schema_usage"],
                result["test_role_has_schema_usage"],
            ]

            result["success"] = all(all_checks)

            conn.commit()
        finally:
            conn.close()

    except Exception as e:
        result["errors"].append(str(e))
        result["success"] = False

    return result
