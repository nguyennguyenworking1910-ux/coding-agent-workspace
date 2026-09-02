"""PostgreSQL forward-only migration runner for Merchant database.

This module implements the merchant migration framework with:
- Versioned, checksummed migrations
- Advisory lock-based concurrency control
- Full transaction semantics (all-or-nothing)
- Strict validation with fail-closed behavior
- JSON output for machine parsing

Modes:
- --status: Read-only check of applied migrations
- --plan: Read-only check of pending migrations
- --apply: Execute pending migrations atomically

Safety constraints:
- Refuse to target coding_agent_rag or MERCHANT_ADMIN_DB
- Refuse database name not matching selected configuration
- No apply-both mode
- No down migrations
- Read-only for --status and --plan using default_transaction_read_only=on
- No password CLI options
- No secret output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg
    from psycopg import sql
except ImportError:
    raise ImportError(
        "psycopg 3 is required for Merchant migrations. "
        "Install it with: pip install psycopg[binary]"
    )


# ============================================================================
# Configuration & Constants
# ============================================================================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5434

RUNTIME_DB_NAME = "coding_agent_merchant"
TEST_DB_NAME = "coding_agent_merchant_test"
SCHEMA_NAME = "merchant_ops"
MIGRATIONS_TABLE = "schema_migrations"

# Migration directory (relative to this file's directory)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Advisory lock ID for migrations (different from bootstrap lock)
MIGRATION_ADVISORY_LOCK_ID = 0x6d696772617465  # 'migrate' in hex

# Lock retry configuration
LOCK_RETRY_COUNT = 5
LOCK_RETRY_DELAY_SECONDS = 1


# ============================================================================
# Utilities
# ============================================================================

def _redact_connection_string(host: str, port: int, dbname: str, user: str) -> str:
    """Return a redacted connection string for logging (no password)."""
    return f"postgresql://{user}@{host}:{port}/{dbname}"


def _get_env_or_fail(key: str, description: str = None) -> str:
    """Get environment variable or fail-closed."""
    value = os.environ.get(key, "").strip()
    if not value:
        desc = description or key
        raise ValueError(f"{desc} not set or empty (env var: {key})")
    return value


def _validate_fail_closed(
    host: str,
    port: int,
    dbname: str,
    user: str,
    mode: str,
) -> None:
    """Validate inputs and fail closed."""
    # Reject non-127.0.0.1 hosts by default
    if host != DEFAULT_HOST:
        raise ValueError(f"Host must be {DEFAULT_HOST} for safety. Got: {host}")

    # Reject invalid port
    if not (1 <= port <= 65535):
        raise ValueError(f"Port must be 1-65535. Got: {port}")

    # Reject coding_agent_rag
    if dbname == "coding_agent_rag":
        raise ValueError("Cannot target coding_agent_rag (reserved for RAG system)")

    # Reject MERCHANT_ADMIN_DB (not a data database)
    admin_db = os.environ.get("MERCHANT_ADMIN_DB", "").strip()
    if admin_db and dbname == admin_db:
        raise ValueError(f"Cannot target {admin_db} (admin/maintenance database)")

    # Validate mode
    if mode not in ("status", "plan", "apply"):
        raise ValueError(f"Invalid mode: {mode}. Must be status, plan, or apply.")


def _validate_database_name(dbname: str, expected: str) -> None:
    """Validate that database name matches expected configuration."""
    if dbname != expected:
        raise ValueError(
            f"Database name mismatch. Expected {expected}, got {dbname}. "
            f"Verify --database and environment configuration."
        )


# ============================================================================
# Migration File Discovery and Validation
# ============================================================================

def _discover_migrations() -> list[tuple[int, str, str]]:
    """Discover migration files in migrations directory.

    Returns:
        List of (version, description, file_path) sorted by version.

    Raises:
        ValueError: If any validation fails (fail-closed).
    """
    if not MIGRATIONS_DIR.exists():
        return []

    migrations = {}

    for migration_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        # Validate filename format: ^\d+_[a-z0-9_]+\.sql$
        match = re.match(r"^(\d+)_([a-z0-9_]+)\.sql$", migration_file.name)
        if not match:
            raise ValueError(
                f"Malformed migration filename: {migration_file.name}. "
                f"Must match: ^\d+_[a-z0-9_]+\.sql$"
            )

        version_str, description = match.groups()
        version = int(version_str)

        # Reject duplicate versions
        if version in migrations:
            raise ValueError(
                f"Duplicate migration version: {version} "
                f"({MIGRATIONS_DIR / migrations[version][0]} and {migration_file.name})"
            )

        # Reject empty files
        content = migration_file.read_bytes()
        if len(content) == 0:
            raise ValueError(f"Empty migration file: {migration_file.name}")

        # Reject invalid UTF-8
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"Invalid UTF-8 in migration file {migration_file.name}: {e}")

        # Reject symlinks escaping the directory
        if migration_file.is_symlink():
            resolved = migration_file.resolve()
            if not str(resolved).startswith(str(MIGRATIONS_DIR.resolve())):
                raise ValueError(
                    f"Symlink escapes migrations directory: {migration_file.name}"
                )

        migrations[version] = (migration_file.name, description, str(migration_file))

    return [(v, desc, path) for v, (_, desc, path) in sorted(migrations.items())]


def _calculate_checksum(file_path: str) -> str:
    """Calculate SHA-256 checksum from exact file bytes."""
    content = Path(file_path).read_bytes()
    return hashlib.sha256(content).hexdigest()


# ============================================================================
# SQL Parsing
# ============================================================================

def _split_sql_statements(sql_text: str) -> list[str]:
    """Split SQL text into individual statements.

    Handles:
    - Quoted strings: 'test; string' (semicolons inside single quotes)
    - Block comments: /* ... */
    - Line comments: -- comment
    - Dollar-quoted strings: $$ ... $$ or $tag$ ... $tag$
    - Escape sequences in strings

    Returns:
        List of non-empty, stripped SQL statements.
    """
    statements = []
    current = []
    i = 0
    length = len(sql_text)

    while i < length:
        char = sql_text[i]

        # Dollar-quoted string: $tag$ ... $tag$
        if char == "$":
            # Find the closing tag
            tag_start = i
            tag_match = re.match(r"\$([a-zA-Z0-9_]*)\$", sql_text[i:])
            if tag_match:
                tag = tag_match.group(1)
                tag_pattern = f"${tag}$"
                tag_len = len(tag_pattern)
                i += tag_len
                current.append(tag_pattern)

                # Find closing tag
                while i < length:
                    if sql_text[i:i + tag_len] == tag_pattern:
                        current.append(tag_pattern)
                        i += tag_len
                        break
                    current.append(sql_text[i])
                    i += 1
            else:
                current.append(char)
                i += 1
            continue

        # Single-quoted string: 'text' with escaped quotes ''
        if char == "'":
            current.append(char)
            i += 1
            while i < length:
                if sql_text[i] == "'":
                    current.append(char)
                    i += 1
                    # Check for escaped quote ''
                    if i < length and sql_text[i] == "'":
                        current.append(char)
                        i += 1
                    else:
                        break
                else:
                    current.append(sql_text[i])
                    i += 1
            continue

        # Block comment: /* ... */
        if char == "/" and i + 1 < length and sql_text[i + 1] == "*":
            i += 2
            while i + 1 < length:
                if sql_text[i] == "*" and sql_text[i + 1] == "/":
                    i += 2
                    break
                i += 1
            continue

        # Line comment: -- ...
        if char == "-" and i + 1 < length and sql_text[i + 1] == "-":
            i += 2
            while i < length and sql_text[i] not in ("\n", "\r"):
                i += 1
            if i < length:
                i += 1  # consume newline
            continue

        # Semicolon - statement terminator
        if char == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        # Regular character
        current.append(char)
        i += 1

    # Add any remaining statement
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


# ============================================================================
# Database Operations
# ============================================================================

def _try_acquire_lock(conn: psycopg.Connection, lock_id: int) -> bool:
    """Try to acquire an advisory lock. Returns True if acquired."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT pg_try_advisory_lock(%s)"), (lock_id,))
        result = cur.fetchone()
        return result[0] if result else False


def _release_lock(conn: psycopg.Connection, lock_id: int) -> None:
    """Release an advisory lock."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT pg_advisory_unlock(%s)"), (lock_id,))


def _get_applied_migrations(
    conn: psycopg.Connection,
) -> dict[int, tuple[str, str, str]]:
    """Get all applied migrations from database.

    Returns:
        Dict mapping version -> (checksum, description, executed_at_iso)
    """
    applied = {}
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT version, checksum, description, executed_at FROM {}.{} ORDER BY version").format(
                sql.Identifier(SCHEMA_NAME),
                sql.Identifier(MIGRATIONS_TABLE),
            )
        )
        for row in cur.fetchall():
            version, checksum, description, executed_at = row
            executed_at_iso = executed_at.isoformat() if executed_at else ""
            applied[version] = (checksum, description, executed_at_iso)

    return applied


def _validate_history(
    applied: dict[int, tuple[str, str, str]],
    available: list[tuple[int, str, str]],
) -> tuple[list[str], list[int]]:
    """Validate migration history for gaps and checksums.

    Returns:
        (errors, missing_versions) where:
        - errors: List of validation error messages
        - missing_versions: List of applied versions not in available files
    """
    errors = []
    missing_versions = []

    if not applied:
        return errors, missing_versions

    # Check for gaps in applied history
    applied_versions = sorted(applied.keys())
    expected_versions = list(range(1, applied_versions[-1] + 1))
    if applied_versions != expected_versions:
        gaps = [v for v in expected_versions if v not in applied_versions]
        errors.append(
            f"Gapped migration history. Missing versions: {gaps}"
        )

    # Check for checksum mismatches and missing files
    for version, (applied_checksum, description, executed_at) in applied.items():
        # Find the file for this version
        file_info = next(((v, d, p) for v, d, p in available if v == version), None)
        if file_info is None:
            missing_versions.append(version)
            errors.append(
                f"Applied migration {version} not found in local files"
            )
        else:
            _, _, file_path = file_info
            file_checksum = _calculate_checksum(file_path)
            if file_checksum != applied_checksum:
                errors.append(
                    f"Checksum mismatch for migration {version}. "
                    f"Applied: {applied_checksum}, File: {file_checksum}. "
                    f"Applied migration file may have been modified."
                )

    return errors, missing_versions


# ============================================================================
# Migration Execution
# ============================================================================

def _execute_migration(
    conn: psycopg.Connection,
    version: int,
    description: str,
    file_path: str,
) -> tuple[bool, int, str]:
    """Execute a single migration within a transaction.

    Returns:
        (success, execution_time_ms, error_message)
    """
    import time

    start_time = time.time()
    error_msg = ""

    try:
        # Read migration file
        migration_sql = Path(file_path).read_text(encoding="utf-8")
        checksum = _calculate_checksum(file_path)

        # Split into statements
        statements = _split_sql_statements(migration_sql)
        if not statements:
            return False, 0, f"Migration file {file_path} contains no SQL statements"

        # Execute within a transaction
        try:
            conn.autocommit = False
            with conn.cursor() as cur:
                # Execute all migration statements
                for stmt in statements:
                    cur.execute(sql.SQL(stmt))

                # Insert tracking row in same transaction
                executed_at = "CURRENT_TIMESTAMP"
                execution_time_ms = int((time.time() - start_time) * 1000)
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {}.{} (version, checksum, description, executed_at, execution_time_ms) "
                        "VALUES (%s, %s, %s, {}, %s)"
                    ).format(
                        sql.Identifier(SCHEMA_NAME),
                        sql.Identifier(MIGRATIONS_TABLE),
                        sql.SQL(executed_at),
                    ),
                    (version, checksum, description, execution_time_ms),
                )

            # Commit the transaction
            conn.commit()
            execution_time_ms = int((time.time() - start_time) * 1000)
            return True, execution_time_ms, ""

        except Exception as e:
            # Rollback on any error
            conn.rollback()
            error_msg = f"Migration {version} failed: {str(e)}"
            return False, 0, error_msg

    except Exception as e:
        return False, 0, f"Failed to execute migration {version}: {str(e)}"


# ============================================================================
# Main Operations
# ============================================================================

def get_status(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
) -> dict[str, Any]:
    """Get status of applied migrations (read-only).

    Returns:
        Dict with applied_migrations, pending_migrations, errors, success
    """
    result = {
        "mode": "status",
        "selected_target": "runtime" if dbname == RUNTIME_DB_NAME else "test",
        "redacted_connection": _redact_connection_string(host, port, dbname, user),
        "applied_migrations": [],
        "pending_migrations": [],
        "checksum_conflicts": [],
        "missing_local_versions": [],
        "success": False,
        "errors": [],
    }

    try:
        # Discover local migrations
        try:
            available = _discover_migrations()
        except ValueError as e:
            result["errors"].append(f"Migration discovery failed: {str(e)}")
            return result

        # Connect with read-only enforcement
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            autocommit=True,
            options="-c default_transaction_read_only=on",
        )

        try:
            # Get applied migrations
            applied = _get_applied_migrations(conn)

            # Validate history
            validation_errors, missing_versions = _validate_history(applied, available)
            result["errors"].extend(validation_errors)
            result["missing_local_versions"] = missing_versions

            # Build applied list
            for version in sorted(applied.keys()):
                checksum, description, executed_at = applied[version]
                result["applied_migrations"].append({
                    "version": version,
                    "description": description,
                    "checksum": checksum,
                    "executed_at": executed_at,
                })

            # Build pending list
            applied_versions = set(applied.keys())
            for version, description, file_path in available:
                if version not in applied_versions:
                    checksum = _calculate_checksum(file_path)
                    result["pending_migrations"].append({
                        "version": version,
                        "description": description,
                        "checksum": checksum,
                    })

            result["success"] = len(result["errors"]) == 0
            return result

        finally:
            conn.close()

    except Exception as e:
        result["errors"].append(f"Status check failed: {str(e)}")
        return result


def get_plan(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
) -> dict[str, Any]:
    """Get plan of pending migrations (read-only).

    Returns:
        Dict with applied_migrations, pending_migrations, errors, success
    """
    result = {
        "mode": "plan",
        "selected_target": "runtime" if dbname == RUNTIME_DB_NAME else "test",
        "redacted_connection": _redact_connection_string(host, port, dbname, user),
        "applied_migrations": [],
        "pending_migrations": [],
        "checksum_conflicts": [],
        "missing_local_versions": [],
        "success": False,
        "errors": [],
    }

    try:
        # Discover local migrations
        try:
            available = _discover_migrations()
        except ValueError as e:
            result["errors"].append(f"Migration discovery failed: {str(e)}")
            return result

        # Connect with read-only enforcement
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            autocommit=True,
            options="-c default_transaction_read_only=on",
        )

        try:
            # Get applied migrations
            applied = _get_applied_migrations(conn)

            # Validate history
            validation_errors, missing_versions = _validate_history(applied, available)
            result["errors"].extend(validation_errors)
            result["missing_local_versions"] = missing_versions

            # Build applied list
            for version in sorted(applied.keys()):
                checksum, description, executed_at = applied[version]
                result["applied_migrations"].append({
                    "version": version,
                    "description": description,
                    "checksum": checksum,
                    "executed_at": executed_at,
                })

            # Build pending list
            applied_versions = set(applied.keys())
            for version, description, file_path in available:
                if version not in applied_versions:
                    checksum = _calculate_checksum(file_path)
                    result["pending_migrations"].append({
                        "version": version,
                        "description": description,
                        "checksum": checksum,
                    })

            result["success"] = len(result["errors"]) == 0
            return result

        finally:
            conn.close()

    except Exception as e:
        result["errors"].append(f"Plan failed: {str(e)}")
        return result


def apply_migrations(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
) -> dict[str, Any]:
    """Apply pending migrations atomically.

    Returns:
        Dict with applied_migrations, pending_migrations, errors, success
    """
    result = {
        "mode": "apply",
        "selected_target": "runtime" if dbname == RUNTIME_DB_NAME else "test",
        "redacted_connection": _redact_connection_string(host, port, dbname, user),
        "applied_migrations": [],
        "pending_migrations": [],
        "checksum_conflicts": [],
        "missing_local_versions": [],
        "success": False,
        "errors": [],
    }

    try:
        # Discover local migrations
        try:
            available = _discover_migrations()
        except ValueError as e:
            result["errors"].append(f"Migration discovery failed: {str(e)}")
            return result

        # Connect to database
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            autocommit=True,
        )

        try:
            # Try to acquire lock with retries
            lock_acquired = False
            for attempt in range(LOCK_RETRY_COUNT):
                if _try_acquire_lock(conn, MIGRATION_ADVISORY_LOCK_ID):
                    lock_acquired = True
                    break
                if attempt < LOCK_RETRY_COUNT - 1:
                    time.sleep(LOCK_RETRY_DELAY_SECONDS)

            if not lock_acquired:
                result["errors"].append(
                    f"Cannot acquire migration lock after {LOCK_RETRY_COUNT} retries. "
                    f"Another migration may be in progress."
                )
                return result

            try:
                # Get applied migrations
                applied = _get_applied_migrations(conn)

                # Validate history
                validation_errors, missing_versions = _validate_history(applied, available)
                result["errors"].extend(validation_errors)
                result["missing_local_versions"] = missing_versions

                # If history is invalid, refuse to proceed
                if validation_errors:
                    return result

                # Build applied list
                for version in sorted(applied.keys()):
                    checksum, description, executed_at = applied[version]
                    result["applied_migrations"].append({
                        "version": version,
                        "description": description,
                        "checksum": checksum,
                        "executed_at": executed_at,
                    })

                # Find and execute pending migrations
                applied_versions = set(applied.keys())
                pending_to_apply = [(v, d, p) for v, d, p in available if v not in applied_versions]

                for version, description, file_path in pending_to_apply:
                    success, exec_time_ms, error_msg = _execute_migration(
                        conn, version, description, file_path
                    )

                    if success:
                        checksum = _calculate_checksum(file_path)
                        result["applied_migrations"].append({
                            "version": version,
                            "description": description,
                            "checksum": checksum,
                            "executed_at": None,  # Will be current timestamp from DB
                        })
                    else:
                        result["errors"].append(error_msg)
                        # Stop on first failure (no further migrations)
                        break

                # Rebuild pending list
                applied_versions_after = set(m["version"] for m in result["applied_migrations"])
                for version, description, file_path in available:
                    if version not in applied_versions_after:
                        checksum = _calculate_checksum(file_path)
                        result["pending_migrations"].append({
                            "version": version,
                            "description": description,
                            "checksum": checksum,
                        })

                result["success"] = len(result["errors"]) == 0

            finally:
                # Always release lock
                try:
                    _release_lock(conn, MIGRATION_ADVISORY_LOCK_ID)
                except Exception:
                    pass

        finally:
            conn.close()

    except Exception as e:
        result["errors"].append(f"Apply failed: {str(e)}")

    return result


# ============================================================================
# CLI Interface
# ============================================================================

def main() -> int:
    """Command-line interface for migration operations.

    Supports three modes:
    - --status: Check applied migrations (read-only)
    - --plan: Check pending migrations (read-only)
    - --apply: Execute pending migrations

    Returns:
        0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="PostgreSQL forward-only migration runner for Merchant database",
        prog="migrate",
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--status",
        action="store_true",
        help="Check applied migrations (read-only)",
    )
    mode_group.add_argument(
        "--plan",
        action="store_true",
        help="Check pending migrations (read-only)",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Execute pending migrations",
    )

    # Database selection (required)
    parser.add_argument(
        "--database",
        choices=["runtime", "test"],
        required=True,
        help="Target database (runtime or test)",
    )

    args = parser.parse_args()

    try:
        # Determine mode
        if args.status:
            mode = "status"
        elif args.plan:
            mode = "plan"
        else:
            mode = "apply"

        # Resolve database configuration
        if args.database == "runtime":
            dbname = _get_env_or_fail("MERCHANT_DB_NAME", "Runtime database name")
            user = _get_env_or_fail("MERCHANT_DB_USER", "Runtime database user")
            password = os.environ.get("MERCHANT_DB_PASSWORD", "")
            expected_db = RUNTIME_DB_NAME
        else:  # test
            dbname = _get_env_or_fail("MERCHANT_TEST_DB_NAME", "Test database name")
            user = os.environ.get("MERCHANT_TEST_USER", "merchant_test")
            password = os.environ.get("MERCHANT_TEST_PASSWORD", "")
            expected_db = TEST_DB_NAME

        # Get other configuration
        host = os.environ.get("MERCHANT_DB_HOST", DEFAULT_HOST)
        port = int(os.environ.get("MERCHANT_DB_PORT", DEFAULT_PORT))

        # Validate configuration
        _validate_fail_closed(host, port, dbname, user, mode)
        _validate_database_name(dbname, expected_db)

        # Execute operation
        if mode == "status":
            result = get_status(host, port, dbname, user, password)
        elif mode == "plan":
            result = get_plan(host, port, dbname, user, password)
        else:
            result = apply_migrations(host, port, dbname, user, password)

        # Output JSON result
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success") else 1

    except ValueError as e:
        error_result = {
            "success": False,
            "error": str(e),
            "mode": "error",
        }
        print(json.dumps(error_result, indent=2), file=sys.stderr)
        return 1

    except Exception as e:
        error_result = {
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "mode": "error",
        }
        print(json.dumps(error_result, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
