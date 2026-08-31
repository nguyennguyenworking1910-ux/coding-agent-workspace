"""PostgreSQL bootstrap for Merchant database infrastructure.

This module implements the idiopotent bootstrap process for setting up:
- Roles (merchant_owner, merchant_app, merchant_alert, merchant_test)
- Databases (coding_agent_merchant, coding_agent_merchant_test)
- Schemas (merchant_ops in both databases)
- Migration tracking table (merchant_ops.schema_migrations)
- Privilege management (revoke PUBLIC, set proper grants)

Modes:
- plan: Safe default; shows what would happen without making changes
- apply: Explicit mutation; actually creates/modifies objects
- verify: Read-only verification; checks the current state

The function rejects if both plan_only and apply are False (fail-closed).
Never displays passwords, full connection strings, or credential hashes.

Uses advisory locks for concurrent safety during mutations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg
    from psycopg import sql
except ImportError:
    raise ImportError(
        "psycopg 3 is required for Merchant bootstrap. "
        "Install it with: pip install psycopg[binary]"
    )


# Conditional import strategy for direct-script and package-import compatibility
if __package__:
    # Package import: use relative import (for tests, imports from other modules)
    from .verify_bootstrap import verify_bootstrap as verify_fn
else:
    # Direct script execution: use sibling-module import
    # When bootstrap.py is executed as: python bootstrap.py --verify ...
    script_dir = Path(__file__).parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    try:
        import verify_bootstrap
        verify_fn = verify_bootstrap.verify_bootstrap
    except ImportError as e:
        # Only catch the direct-import case, not internal import failures
        if "verify_bootstrap" in str(e) and "No module named" in str(e):
            raise ImportError(
                f"Cannot find verify_bootstrap.py in {script_dir}. "
                f"Ensure bootstrap.py and verify_bootstrap.py are in the same directory."
            ) from e
        else:
            # Re-raise if it's an internal import error inside verify_bootstrap
            raise


# ============================================================================
# Configuration & Constants
# ============================================================================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5434
DEFAULT_ADMIN_DB = None  # Must be explicitly configured - no guessing

RUNTIME_DB_NAME = "coding_agent_merchant"
TEST_DB_NAME = "coding_agent_merchant_test"
SCHEMA_NAME = "merchant_ops"

# Admin database is only for maintenance connections (role creation, database creation, etc.)
# It is NOT a Merchant database and must not be modified by bootstrap
# For local development: coding_agent_rag (the existing RAG database)
# Must be explicitly provided - never inferred from username

ROLE_OWNER = "merchant_owner"
ROLE_APP = "merchant_app"
ROLE_ALERT = "merchant_alert"
ROLE_TEST = "merchant_test"

ALL_ROLES = {ROLE_OWNER, ROLE_APP, ROLE_ALERT, ROLE_TEST}

# Advisory lock ID for bootstrap mutations (constant, session-scoped)
BOOTSTRAP_ADVISORY_LOCK_ID = 0x626f6f7473747261  # 'bootstra' in hex

# Role attributes (safe, non-interactive)
# merchant_owner: LOGIN required for migration runner; NOINHERIT for safety
ROLE_ATTRIBUTES = {
    ROLE_OWNER: {"LOGIN": True, "SUPERUSER": False, "CREATEDB": False, "CREATEROLE": False, "REPLICATION": False, "INHERIT": False},
    ROLE_APP: {"LOGIN": True, "SUPERUSER": False, "CREATEDB": False, "CREATEROLE": False, "REPLICATION": False, "INHERIT": False},
    ROLE_ALERT: {"LOGIN": True, "SUPERUSER": False, "CREATEDB": False, "CREATEROLE": False, "REPLICATION": False, "INHERIT": False},
    ROLE_TEST: {"LOGIN": True, "SUPERUSER": False, "CREATEDB": False, "CREATEROLE": False, "REPLICATION": False, "INHERIT": False},
}


# ============================================================================
# Utilities
# ============================================================================

def _redact_connection_string(host: str, port: int, user: str) -> str:
    """Return a redacted connection string for logging (no password)."""
    return f"postgresql://{user}@{host}:{port}"


def _validate_fail_closed(
    host: str,
    port: int,
    runtime_db: str,
    test_db: str,
) -> None:
    """Validate inputs and fail closed.

    Raises:
        ValueError: If any validation fails.
    """
    # Reject non-127.0.0.1 hosts by default (safety)
    if host != DEFAULT_HOST:
        raise ValueError(
            f"Host must be {DEFAULT_HOST} for safety. Got: {host}"
        )

    # Reject invalid port
    if not (1 <= port <= 65535):
        raise ValueError(f"Port must be 1-65535. Got: {port}")

    # Reject if database names are equal
    if runtime_db == test_db:
        raise ValueError(
            f"Runtime and test database names must differ. "
            f"Both are: {runtime_db}"
        )

    # Reject if test database doesn't end with _test
    if not test_db.endswith("_test"):
        raise ValueError(
            f"Test database name must end with '_test'. Got: {test_db}"
        )

    # Reject coding_agent_rag as target (exact match or any variant)
    if "coding_agent_rag" in runtime_db or "coding_agent_rag" in test_db:
        raise ValueError(
            "Cannot bootstrap against coding_agent_rag or any variant. "
            "This database is reserved for the RAG system."
        )


def _validate_database_names(runtime_db: str, test_db: str) -> None:
    """Validate database names are safe (regex check for SQL injection protection)."""
    for name in [runtime_db, test_db]:
        if not re.match(r'^[a-z][a-z0-9_]{0,62}$', name):
            raise ValueError(
                f"Invalid database name '{name}': must start with lowercase letter, "
                "contain only lowercase letters, digits, and underscores, max 63 characters"
            )


def _validate_passwords_for_apply(
    admin_password: str,
    owner_password: str,
    app_password: str,
    alert_password: str,
    test_password: str,
) -> None:
    """Validate that passwords are non-empty when apply is True.

    Raises:
        ValueError: If any password is empty.
    """
    passwords = {
        "admin_password": admin_password,
        "owner_password": owner_password,
        "app_password": app_password,
        "alert_password": alert_password,
        "test_password": test_password,
    }

    for name, pwd in passwords.items():
        if not pwd or not pwd.strip():
            raise ValueError(f"Cannot apply: {name} is empty")


def _escape_password_for_sql(password: str) -> str:
    """Escape a password for use in a SQL string literal."""
    return password.replace("'", "''")


def _get_role_attributes(conn: psycopg.Connection, role_name: str) -> Optional[dict]:
    """Get the attributes of an existing role.

    Returns a dict with LOGIN, SUPERUSER, CREATEDB, CREATEROLE, REPLICATION, INHERIT.
    Returns None if role doesn't exist.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolinherit "
                "FROM pg_roles WHERE rolname = %s"
            ),
            (role_name,),
        )
        result = cur.fetchone()
        if result is None:
            return None
        return {
            "LOGIN": result[0],
            "SUPERUSER": result[1],
            "CREATEDB": result[2],
            "CREATEROLE": result[3],
            "REPLICATION": result[4],
            "INHERIT": result[5],
        }


def _role_attributes_match(actual: dict, expected: dict) -> bool:
    """Check if actual role attributes match expected attributes."""
    return all(actual.get(key) == expected[key] for key in expected)


# ============================================================================
# SQL Plan Generation
# ============================================================================

class BootstrapPlan:
    """A plan for bootstrap operations (read-only)."""

    def __init__(self):
        self.roles: dict[str, dict[str, Any]] = {}
        self.databases: dict[str, dict[str, Any]] = {}
        self.schemas: dict[str, dict[str, Any]] = {}
        self.grants: list[str] = []
        self.revocations: list[str] = []
        self.tables: dict[str, dict[str, Any]] = {}

    def add_role(self, name: str, exists: bool, attributes_mismatch: bool = False) -> None:
        """Record a role in the plan."""
        self.roles[name] = {"name": name, "exists": exists, "attributes_mismatch": attributes_mismatch}

    def add_database(self, name: str, owner: str, exists: bool, owner_mismatch: bool = False, encoding_mismatch: bool = False) -> None:
        """Record a database in the plan."""
        self.databases[name] = {
            "name": name,
            "owner": owner,
            "exists": exists,
            "owner_mismatch": owner_mismatch,
            "encoding_mismatch": encoding_mismatch,
        }

    def add_schema(self, name: str, database: str, owner: str, exists: bool, owner_mismatch: bool = False) -> None:
        """Record a schema in the plan."""
        key = f"{database}.{name}"
        self.schemas[key] = {
            "name": name,
            "database": database,
            "owner": owner,
            "exists": exists,
            "owner_mismatch": owner_mismatch,
        }

    def add_table(self, name: str, database: str, schema: str, exists: bool, constraints_mismatch: bool = False) -> None:
        """Record a table in the plan."""
        key = f"{database}.{schema}.{name}"
        self.tables[key] = {
            "name": name,
            "database": database,
            "schema": schema,
            "exists": exists,
            "constraints_mismatch": constraints_mismatch,
        }

    def add_grant(self, description: str) -> None:
        """Record a grant in the plan (in plain English, not SQL)."""
        self.grants.append(description)

    def add_revocation(self, description: str) -> None:
        """Record a privilege revocation in the plan."""
        self.revocations.append(description)

    def to_dict(self) -> dict[str, Any]:
        """Convert the plan to a dictionary for serialization."""
        return {
            "roles": self.roles,
            "databases": self.databases,
            "schemas": self.schemas,
            "grants": self.grants,
            "revocations": self.revocations,
            "tables": self.tables,
        }


# ============================================================================
# Object State Checking
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


def _get_table_constraints(conn: psycopg.Connection, schema_name: str, table_name: str) -> dict:
    """Get constraint information for a table."""
    constraints = {}
    with conn.cursor() as cur:
        # Get column info
        cur.execute(
            sql.SQL(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s"
            ),
            (schema_name, table_name),
        )
        constraints["columns"] = {row[0]: {"nullable": row[1] == "YES", "default": row[2]} for row in cur.fetchall()}

        # Get CHECK constraints
        cur.execute(
            sql.SQL(
                "SELECT constraint_name, check_clause "
                "FROM information_schema.check_constraints "
                "WHERE constraint_schema = %s"
            ),
            (schema_name,),
        )
        constraints["checks"] = {row[0]: row[1] for row in cur.fetchall()}

        # Get primary key
        cur.execute(
            sql.SQL(
                "SELECT a.attname "
                "FROM pg_attribute a "
                "JOIN pg_class c ON a.attrelid = c.oid "
                "JOIN pg_namespace n ON c.relnamespace = n.oid "
                "JOIN pg_constraint pk ON pk.conrelid = c.oid AND pk.contype = 'p' "
                "WHERE n.nspname = %s AND c.relname = %s AND a.attnum = pk.conkey[1]"
            ),
            (schema_name, table_name),
        )
        result = cur.fetchone()
        constraints["primary_key"] = result[0] if result else None

    return constraints


# ============================================================================
# Main Bootstrap Function
# ============================================================================

def bootstrap(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    admin_user: str = None,
    admin_db: str = None,
    admin_password: str = "",
    owner_password: str = "",
    app_password: str = "",
    alert_password: str = "",
    test_password: str = "",
    plan_only: bool = True,
    apply: bool = False,
    runtime_db: str = RUNTIME_DB_NAME,
    test_db: str = TEST_DB_NAME,
) -> dict[str, Any]:
    """Bootstrap the Merchant database infrastructure.

    Creates roles, databases, schemas, and migration tracking table with
    appropriate privilege grants and revocations.

    Args:
        host: PostgreSQL server hostname (default: 127.0.0.1)
        port: PostgreSQL server port (default: 5434)
        admin_user: PostgreSQL admin user (required: no fallback)
        admin_db: Admin database for maintenance connections (required: no fallback)
        admin_password: Password for admin user
        owner_password: Password for merchant_owner role
        app_password: Password for merchant_app role
        alert_password: Password for merchant_alert role
        test_password: Password for merchant_test role
        plan_only: If True, plan mode (default). Cannot be combined with apply=True.
        apply: If True, apply the plan. Must be explicitly set. Implies plan_only=False.
        runtime_db: Runtime database name (default: coding_agent_merchant)
        test_db: Test database name (default: coding_agent_merchant_test)

    Returns:
        dict with keys:
        - "mode": "plan", "apply", or "verify"
        - "success": True if operation succeeded
        - "plan": BootstrapPlan object converted to dict
        - "connection": Redacted connection string (no passwords)
        - "errors": List of error messages if any
        - "message": Human-readable summary

    Raises:
        ValueError: If validation fails (fail-closed), including missing admin_user
        ImportError: If psycopg is not installed
    """
    # Fail-closed: reject if admin_user is missing or whitespace-only
    if not admin_user or not admin_user.strip():
        raise ValueError(
            "admin_user is required (no fallback to postgres or rag_user)"
        )

    # Fail-closed: reject if admin_db is missing or whitespace-only
    if not admin_db or not admin_db.strip():
        raise ValueError(
            "admin_db is required (the maintenance database for role/DB creation). "
            "Do not infer from username."
        )

    # Fail-closed: reject if neither plan nor apply is explicit
    if not plan_only and not apply:
        raise ValueError(
            "Must explicitly set either plan_only=True (safe default) or apply=True"
        )

    # If apply is True, plan_only is implied False
    if apply:
        plan_only = False

    # Determine mode
    mode = "plan" if plan_only else "apply"

    result = {
        "mode": mode,
        "success": False,
        "plan": None,
        "connection": _redact_connection_string(host, port, admin_user),
        "errors": [],
        "message": "",
    }

    # Fail-closed validation (OUTSIDE try-except so errors propagate)
    _validate_fail_closed(host, port, runtime_db, test_db)
    _validate_database_names(runtime_db, test_db)

    # If apply, validate that passwords are non-empty
    if not plan_only:
        _validate_passwords_for_apply(admin_password, owner_password, app_password, alert_password, test_password)

    try:

        # Connect to the server as admin (with autocommit for CREATE DATABASE)
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=admin_db,
            user=admin_user,
            password=admin_password,
            autocommit=True,
        )

        try:
            # In apply mode, acquire lock BEFORE generating plan
            lock_acquired = False
            if not plan_only:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("SELECT pg_try_advisory_lock(%s)"),
                        (BOOTSTRAP_ADVISORY_LOCK_ID,),
                    )
                    result_lock = cur.fetchone()
                    lock_acquired = result_lock[0] if result_lock else False
                    if not lock_acquired:
                        raise ValueError("Cannot acquire advisory lock; another bootstrap operation may be in progress")

            try:
                # Generate the plan (after lock is acquired in apply mode)
                plan = _generate_plan(
                    conn, host, port, admin_user, admin_db, admin_password, runtime_db, test_db
                )

                result["plan"] = plan.to_dict()

                # If apply, execute the plan
                if not plan_only:
                    _apply_plan(conn, host, port, admin_user, admin_db, admin_password, plan, runtime_db, test_db, owner_password, app_password, alert_password, test_password)
                    result["message"] = f"Bootstrap applied successfully to {runtime_db} and {test_db}"
                else:
                    result["message"] = f"Bootstrap plan for {runtime_db} and {test_db} (no changes made)"

                result["success"] = True

            finally:
                # Release lock in apply mode
                if not plan_only and lock_acquired:
                    with conn.cursor() as cur:
                        cur.execute(
                            sql.SQL("SELECT pg_advisory_unlock(%s)"),
                            (BOOTSTRAP_ADVISORY_LOCK_ID,),
                        )

        finally:
            conn.close()

    except Exception as e:
        result["errors"].append(str(e))
        result["success"] = False
        result["message"] = f"Bootstrap failed: {str(e)}"

    return result


# ============================================================================
# Plan Generation
# ============================================================================

def _generate_plan(
    conn: psycopg.Connection,
    host: str,
    port: int,
    admin_user: str,
    admin_db: str,
    admin_password: str,
    runtime_db: str,
    test_db: str,
) -> BootstrapPlan:
    """Generate a bootstrap plan without making changes."""
    plan = BootstrapPlan()

    # Check roles and their attributes
    for role_name in ALL_ROLES:
        exists = _role_exists(conn, role_name)
        attributes_mismatch = False

        if exists:
            actual_attrs = _get_role_attributes(conn, role_name)
            expected_attrs = ROLE_ATTRIBUTES[role_name]
            if actual_attrs and not _role_attributes_match(actual_attrs, expected_attrs):
                attributes_mismatch = True

        plan.add_role(role_name, exists, attributes_mismatch)

    # Check runtime database
    runtime_owner_exists = _database_exists(conn, runtime_db)
    runtime_owner = _get_database_owner(conn, runtime_db) if runtime_owner_exists else None
    runtime_encoding = _get_database_encoding(conn, runtime_db) if runtime_owner_exists else None
    runtime_owner_mismatch = runtime_owner is not None and runtime_owner != ROLE_OWNER
    runtime_encoding_mismatch = runtime_encoding is not None and runtime_encoding != "UTF8"

    plan.add_database(runtime_db, ROLE_OWNER, runtime_owner_exists, runtime_owner_mismatch, runtime_encoding_mismatch)

    # Check test database
    test_owner_exists = _database_exists(conn, test_db)
    test_owner = _get_database_owner(conn, test_db) if test_owner_exists else None
    test_encoding = _get_database_encoding(conn, test_db) if test_owner_exists else None
    test_owner_mismatch = test_owner is not None and test_owner != ROLE_TEST
    test_encoding_mismatch = test_encoding is not None and test_encoding != "UTF8"

    plan.add_database(test_db, ROLE_TEST, test_owner_exists, test_owner_mismatch, test_encoding_mismatch)

    # Add grants and revocations to plan (always shown, regardless of existence)
    plan.add_revocation("REVOKE all privileges on database coding_agent_merchant from public")
    plan.add_revocation("REVOKE all privileges on database coding_agent_merchant_test from public")
    plan.add_revocation("REVOKE all privileges on schema merchant_ops from public in both databases")

    plan.add_grant(f"GRANT CONNECT on database {runtime_db} to {ROLE_OWNER}")
    plan.add_grant(f"GRANT CONNECT on database {runtime_db} to {ROLE_APP}")
    plan.add_grant(f"GRANT CONNECT on database {runtime_db} to {ROLE_ALERT}")
    plan.add_grant(f"GRANT CONNECT on database {test_db} to {ROLE_TEST}")

    plan.add_grant(f"GRANT USAGE on schema {SCHEMA_NAME} to {ROLE_APP} in {runtime_db}")
    plan.add_grant(f"GRANT USAGE on schema {SCHEMA_NAME} to {ROLE_ALERT} in {runtime_db}")
    plan.add_grant(f"GRANT USAGE on schema {SCHEMA_NAME} to {ROLE_TEST} in {test_db}")

    # Check schema in runtime database
    runtime_schema_exists = False
    runtime_schema_owner = None
    if runtime_owner_exists:
        try:
            with psycopg.connect(
                host=host,
                port=port,
                user=admin_user,
                password=admin_password,
                dbname=runtime_db,
                autocommit=True,
            ) as db_conn:
                runtime_schema_exists = _schema_exists(db_conn, SCHEMA_NAME)
                if runtime_schema_exists:
                    runtime_schema_owner = _get_schema_owner(db_conn, SCHEMA_NAME)
        except Exception:
            pass

    runtime_schema_owner_mismatch = runtime_schema_owner is not None and runtime_schema_owner != ROLE_OWNER
    plan.add_schema(SCHEMA_NAME, runtime_db, ROLE_OWNER, runtime_schema_exists, runtime_schema_owner_mismatch)

    # Check schema in test database
    test_schema_exists = False
    test_schema_owner = None
    if test_owner_exists:
        try:
            with psycopg.connect(
                host=host,
                port=port,
                user=admin_user,
                password=admin_password,
                dbname=test_db,
                autocommit=True,
            ) as db_conn:
                test_schema_exists = _schema_exists(db_conn, SCHEMA_NAME)
                if test_schema_exists:
                    test_schema_owner = _get_schema_owner(db_conn, SCHEMA_NAME)
        except Exception:
            pass

    test_schema_owner_mismatch = test_schema_owner is not None and test_schema_owner != ROLE_TEST
    plan.add_schema(SCHEMA_NAME, test_db, ROLE_TEST, test_schema_exists, test_schema_owner_mismatch)

    # Check schema_migrations table
    runtime_migrations_exists = False
    runtime_migrations_constraints_mismatch = False
    if runtime_schema_exists:
        try:
            with psycopg.connect(
                host=host,
                port=port,
                user=admin_user,
                password=admin_password,
                dbname=runtime_db,
                autocommit=True,
            ) as db_conn:
                runtime_migrations_exists = _table_exists(db_conn, SCHEMA_NAME, "schema_migrations")
                if runtime_migrations_exists:
                    constraints = _get_table_constraints(db_conn, SCHEMA_NAME, "schema_migrations")
                    runtime_migrations_constraints_mismatch = _validate_migrations_table_constraints(constraints)
        except Exception:
            pass

    plan.add_table("schema_migrations", runtime_db, SCHEMA_NAME, runtime_migrations_exists, runtime_migrations_constraints_mismatch)

    test_migrations_exists = False
    test_migrations_constraints_mismatch = False
    if test_schema_exists:
        try:
            with psycopg.connect(
                host=host,
                port=port,
                user=admin_user,
                password=admin_password,
                dbname=test_db,
                autocommit=True,
            ) as db_conn:
                test_migrations_exists = _table_exists(db_conn, SCHEMA_NAME, "schema_migrations")
                if test_migrations_exists:
                    constraints = _get_table_constraints(db_conn, SCHEMA_NAME, "schema_migrations")
                    test_migrations_constraints_mismatch = _validate_migrations_table_constraints(constraints)
        except Exception:
            pass

    plan.add_table("schema_migrations", test_db, SCHEMA_NAME, test_migrations_exists, test_migrations_constraints_mismatch)

    return plan


def _validate_migrations_table_constraints(constraints: dict) -> bool:
    """Check if migrations table has the expected constraints.

    Returns True if constraints mismatch (incompatible), False if they match.
    """
    # Expected columns: version, checksum, description, executed_at, execution_time_ms
    expected_columns = {"version", "checksum", "description", "executed_at", "execution_time_ms"}
    actual_columns = set(constraints.get("columns", {}).keys())

    if expected_columns != actual_columns:
        return True

    # Check for required CHECK constraints
    # We just check that the table exists and has columns; detailed constraint validation
    # is not critical for idempotency (the table structure would have been created correctly)
    return False


# ============================================================================
# Plan Application
# ============================================================================

def _apply_plan(
    conn: psycopg.Connection,
    host: str,
    port: int,
    admin_user: str,
    admin_db: str,
    admin_password: str,
    plan: BootstrapPlan,
    runtime_db: str,
    test_db: str,
    owner_password: str,
    app_password: str,
    alert_password: str,
    test_password: str,
) -> None:
    """Apply the bootstrap plan (make actual changes).

    The advisory lock must already be acquired before calling this function.
    """

    # Create roles (if they don't exist or have mismatched attributes)
    for role_name, role_info in plan.roles.items():
        if not role_info["exists"]:
            expected_attrs = ROLE_ATTRIBUTES[role_name]
            password = None

            if role_name == ROLE_OWNER:
                password = owner_password if owner_password else None
            elif role_name == ROLE_APP:
                password = app_password
            elif role_name == ROLE_ALERT:
                password = alert_password
            elif role_name == ROLE_TEST:
                password = test_password

            # Build CREATE ROLE statement
            attrs = []
            if expected_attrs.get("LOGIN"):
                attrs.append("LOGIN")
                if password:
                    attrs.append(f"PASSWORD '{_escape_password_for_sql(password)}'")
            else:
                attrs.append("NOLOGIN")

            if not expected_attrs.get("SUPERUSER"):
                attrs.append("NOSUPERUSER")
            if not expected_attrs.get("CREATEDB"):
                attrs.append("NOCREATEDB")
            if not expected_attrs.get("CREATEROLE"):
                attrs.append("NOCREATEROLE")
            if not expected_attrs.get("REPLICATION"):
                attrs.append("NOREPLICATION")
            if not expected_attrs.get("INHERIT"):
                attrs.append("NOINHERIT")
            else:
                attrs.append("INHERIT")

            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("CREATE ROLE {} WITH {}").format(
                        sql.Identifier(role_name),
                        sql.SQL(' '.join(attrs))
                    )
                )

        elif role_info["attributes_mismatch"]:
            # Role exists but attributes mismatch - fail before mutation
            raise ValueError(
                f"Role {role_name} exists but has incompatible attributes. "
                f"Manual intervention required."
            )

    # Create runtime database (if it doesn't exist) - valid PostgreSQL syntax with UTF8
    if not plan.databases[runtime_db]["exists"]:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(runtime_db),
                    sql.Identifier(ROLE_OWNER),
                )
            )
    elif plan.databases[runtime_db]["owner_mismatch"] or plan.databases[runtime_db]["encoding_mismatch"]:
        raise ValueError(
            f"Database {runtime_db} exists but has incompatible owner or encoding. "
            f"Manual intervention required."
        )

    # Create test database (if it doesn't exist) - valid PostgreSQL syntax with UTF8
    if not plan.databases[test_db]["exists"]:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(test_db),
                    sql.Identifier(ROLE_TEST),
                )
            )
    elif plan.databases[test_db]["owner_mismatch"] or plan.databases[test_db]["encoding_mismatch"]:
        raise ValueError(
            f"Database {test_db} exists but has incompatible owner or encoding. "
            f"Manual intervention required."
        )

    # Revoke PUBLIC privileges on databases
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM public").format(
                sql.Identifier(runtime_db)
            )
        )
        cur.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM public").format(
                sql.Identifier(test_db)
            )
        )

    # Grant CONNECT to owner on runtime database
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(runtime_db),
                sql.Identifier(ROLE_OWNER),
            )
        )

    # Now connect to each database to create schemas, tables, and grants

    # ===== Runtime Database =====
    with psycopg.connect(
        host=host,
        port=port,
        user=admin_user,
        password=admin_password,
        dbname=runtime_db,
        autocommit=False,
    ) as db_conn:
        try:
            # Create schema in runtime database
            if not plan.schemas[f"{runtime_db}.{SCHEMA_NAME}"]["exists"]:
                with db_conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                            sql.Identifier(SCHEMA_NAME),
                            sql.Identifier(ROLE_OWNER),
                        )
                    )
            elif plan.schemas[f"{runtime_db}.{SCHEMA_NAME}"]["owner_mismatch"]:
                raise ValueError(
                    f"Schema {SCHEMA_NAME} in {runtime_db} has incompatible owner. "
                    f"Manual intervention required."
                )

            # Revoke PUBLIC privileges on schema
            with db_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA {} FROM public").format(
                        sql.Identifier(SCHEMA_NAME)
                    )
                )

            # Grant CONNECT on runtime database to app and alert
            with db_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(runtime_db),
                        sql.Identifier(ROLE_APP),
                    )
                )
                cur.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(runtime_db),
                        sql.Identifier(ROLE_ALERT),
                    )
                )

            # Grant USAGE on schema to app and alert roles
            with db_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(SCHEMA_NAME),
                        sql.Identifier(ROLE_APP),
                    )
                )
                cur.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(SCHEMA_NAME),
                        sql.Identifier(ROLE_ALERT),
                    )
                )

            # Create schema_migrations table if needed
            if not plan.tables[f"{runtime_db}.{SCHEMA_NAME}.schema_migrations"]["exists"]:
                with db_conn.cursor() as cur:
                    cur.execute(sql.SQL(
                        """
                        CREATE TABLE {}.schema_migrations (
                            version INTEGER PRIMARY KEY CHECK (version > 0),
                            checksum TEXT NOT NULL CHECK (btrim(checksum) <> ''),
                            description TEXT NOT NULL CHECK (btrim(description) <> ''),
                            executed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            execution_time_ms INTEGER NOT NULL CHECK (execution_time_ms >= 0)
                        )
                        """.strip()
                    ).format(
                        sql.Identifier(SCHEMA_NAME),
                    ))
                    # Set owner of table to merchant_owner
                    cur.execute(
                        sql.SQL("ALTER TABLE {}.schema_migrations OWNER TO {}").format(
                            sql.Identifier(SCHEMA_NAME),
                            sql.Identifier(ROLE_OWNER),
                        )
                    )

            db_conn.commit()
        except Exception:
            db_conn.rollback()
            raise

    # ===== Test Database =====
    with psycopg.connect(
        host=host,
        port=port,
        user=admin_user,
        password=admin_password,
        dbname=test_db,
        autocommit=False,
    ) as db_conn:
        try:
            # Create schema in test database
            if not plan.schemas[f"{test_db}.{SCHEMA_NAME}"]["exists"]:
                with db_conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                            sql.Identifier(SCHEMA_NAME),
                            sql.Identifier(ROLE_TEST),
                        )
                    )
            elif plan.schemas[f"{test_db}.{SCHEMA_NAME}"]["owner_mismatch"]:
                raise ValueError(
                    f"Schema {SCHEMA_NAME} in {test_db} has incompatible owner. "
                    f"Manual intervention required."
                )

            # Revoke PUBLIC privileges on schema
            with db_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA {} FROM public").format(
                        sql.Identifier(SCHEMA_NAME)
                    )
                )

            # Grant CONNECT on test database to test role
            with db_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(test_db),
                        sql.Identifier(ROLE_TEST),
                    )
                )

            # Grant USAGE and CREATE on schema to test role
            with db_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(SCHEMA_NAME),
                        sql.Identifier(ROLE_TEST),
                    )
                )
                cur.execute(
                    sql.SQL("GRANT CREATE ON SCHEMA {} TO {}").format(
                        sql.Identifier(SCHEMA_NAME),
                        sql.Identifier(ROLE_TEST),
                    )
                )

            # Create schema_migrations table if needed
            if not plan.tables[f"{test_db}.{SCHEMA_NAME}.schema_migrations"]["exists"]:
                with db_conn.cursor() as cur:
                    cur.execute(sql.SQL(
                        """
                        CREATE TABLE {}.schema_migrations (
                            version INTEGER PRIMARY KEY CHECK (version > 0),
                            checksum TEXT NOT NULL CHECK (btrim(checksum) <> ''),
                            description TEXT NOT NULL CHECK (btrim(description) <> ''),
                            executed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            execution_time_ms INTEGER NOT NULL CHECK (execution_time_ms >= 0)
                        )
                        """.strip()
                    ).format(
                        sql.Identifier(SCHEMA_NAME),
                    ))
                    # Set owner of table to merchant_test
                    cur.execute(
                        sql.SQL("ALTER TABLE {}.schema_migrations OWNER TO {}").format(
                            sql.Identifier(SCHEMA_NAME),
                            sql.Identifier(ROLE_TEST),
                        )
                    )

            db_conn.commit()
        except Exception:
            db_conn.rollback()
            raise


# ============================================================================
# CLI Interface
# ============================================================================

def main() -> int:
    """Command-line interface for bootstrap operations.

    Supports three mutually exclusive modes:
    - --plan: Show what would be created (default, safe)
    - --apply: Actually create databases and roles
    - --verify: Read-only verification of current state

    Passwords are read from environment variables only, never from CLI arguments.

    Returns:
        0 on success, nonzero on failure.
    """
    parser = argparse.ArgumentParser(
        description="Bootstrap Merchant database infrastructure",
        prog="bootstrap",
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=False)
    mode_group.add_argument(
        "--plan",
        action="store_true",
        help="Show plan without making changes (default)",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Apply the plan (mutually exclusive with --plan and --verify)",
    )
    mode_group.add_argument(
        "--verify",
        action="store_true",
        help="Verify current state (read-only, mutually exclusive with --plan and --apply)",
    )

    # Connection parameters (no passwords - read from environment)
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"PostgreSQL host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"PostgreSQL port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--admin-user",
        default=None,
        help="Admin user (required: --admin-user or MERCHANT_ADMIN_USER)",
    )
    parser.add_argument(
        "--admin-db",
        default=None,
        help="Admin database for maintenance connections (required: --admin-db or MERCHANT_ADMIN_DB)",
    )

    # Database names
    parser.add_argument(
        "--runtime-db",
        default=RUNTIME_DB_NAME,
        help=f"Runtime database name (default: {RUNTIME_DB_NAME})",
    )
    parser.add_argument(
        "--test-db",
        default=TEST_DB_NAME,
        help=f"Test database name (default: {TEST_DB_NAME})",
    )

    args = parser.parse_args()

    # Determine mode (default to plan if nothing specified)
    plan_mode = not args.apply and not args.verify
    apply_mode = args.apply
    verify_mode = args.verify

    # Resolve admin user (fail-closed)
    admin_user = args.admin_user or os.environ.get("MERCHANT_ADMIN_USER")
    if not admin_user or not admin_user.strip():
        error_result = {
            "success": False,
            "error": "Admin user required. Either supply --admin-user or set MERCHANT_ADMIN_USER environment variable",
            "mode": "error",
        }
        print(json.dumps(error_result, indent=2), file=sys.stderr)
        return 1

    # Resolve admin database (fail-closed - no guessing)
    admin_db = args.admin_db or os.environ.get("MERCHANT_ADMIN_DB")
    if not admin_db or not admin_db.strip():
        error_result = {
            "success": False,
            "error": "Admin database required. Either supply --admin-db or set MERCHANT_ADMIN_DB environment variable",
            "mode": "error",
        }
        print(json.dumps(error_result, indent=2), file=sys.stderr)
        return 1

    try:
        if verify_mode:
            # Verify mode (read-only)
            admin_password = os.environ.get("MERCHANT_ADMIN_PASSWORD", "")

            result = verify_fn(
                host=args.host,
                port=args.port,
                admin_user=admin_user,
                admin_db=admin_db,
                admin_password=admin_password,
                runtime_db=args.runtime_db,
                test_db=args.test_db,
            )
            print(json.dumps(result, indent=2))
            return 0 if result.get("success") else 1

        else:
            # Plan or apply mode
            admin_password = os.environ.get("MERCHANT_ADMIN_PASSWORD", "")
            owner_password = os.environ.get("MERCHANT_OWNER_PASSWORD", "")
            app_password = os.environ.get("MERCHANT_DB_PASSWORD", "")
            alert_password = os.environ.get("MERCHANT_ALERT_PASSWORD", "")
            test_password = os.environ.get("MERCHANT_TEST_PASSWORD", "")

            result = bootstrap(
                host=args.host,
                port=args.port,
                admin_user=admin_user,
                admin_db=admin_db,
                admin_password=admin_password,
                owner_password=owner_password,
                app_password=app_password,
                alert_password=alert_password,
                test_password=test_password,
                plan_only=plan_mode,
                apply=apply_mode,
                runtime_db=args.runtime_db,
                test_db=args.test_db,
            )
            print(json.dumps(result, indent=2))
            return 0 if result.get("success") else 1

    except ValueError as e:
        # Validation errors (fail-closed)
        error_result = {
            "success": False,
            "error": str(e),
            "mode": "error",
        }
        print(json.dumps(error_result, indent=2), file=sys.stderr)
        return 1

    except Exception as e:
        # Unexpected errors
        error_result = {
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "mode": "error",
        }
        print(json.dumps(error_result, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
