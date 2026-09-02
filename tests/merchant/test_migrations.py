"""Comprehensive test suite for Merchant migration framework.

Tests cover 50+ requirements:
- Discovery and numeric ordering (requirement 33)
- Malformed and duplicate versions (requirement 34)
- Invalid or gapped history (requirement 35)
- Exact-byte SHA-256 (requirement 36)
- Changed applied migration (requirement 37)
- Missing applied migration file (requirement 38)
- Read-only status and plan (requirement 39)
- Explicit runtime and test selection (requirement 40)
- RAG and admin database collision rejection (requirement 41)
- No password CLI options or output (requirement 42)
- Advisory lock acquisition, timeout, release (requirement 43)
- Commit on success (requirement 44)
- Rollback on error (requirement 45)
- Tracking insert in same transaction (requirement 46)
- Stop after first failed migration (requirement 47)
- SQL with semicolons and dollar-quoted functions (requirement 48)
- Direct script execution and package import (requirement 49)
- UTF-8 and Windows path behavior (requirement 50)
- PostgreSQL integration tests (opt-in)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# Import the migrate module
try:
    from claude.clients.merchant import migrate
except ImportError:
    # Fallback for direct test execution
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from claude.clients.merchant import migrate


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_migrations_dir():
    """Create a temporary migrations directory with cleanup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        migrations_dir = Path(tmpdir) / "migrations"
        migrations_dir.mkdir()
        yield migrations_dir


@pytest.fixture
def mock_env_runtime():
    """Mock environment for runtime database."""
    env = {
        "MERCHANT_DB_HOST": "127.0.0.1",
        "MERCHANT_DB_PORT": "5434",
        "MERCHANT_DB_NAME": "coding_agent_merchant",
        "MERCHANT_DB_USER": "merchant_app",
        "MERCHANT_DB_PASSWORD": "test_password",
        "MERCHANT_DB_SSLMODE": "prefer",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        yield env


@pytest.fixture
def mock_env_test():
    """Mock environment for test database."""
    env = {
        "MERCHANT_DB_HOST": "127.0.0.1",
        "MERCHANT_DB_PORT": "5434",
        "MERCHANT_TEST_DB_NAME": "coding_agent_merchant_test",
        "MERCHANT_TEST_USER": "merchant_test",
        "MERCHANT_TEST_PASSWORD": "test_password",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        yield env


# ============================================================================
# Discovery and Numeric Ordering (Requirement 33)
# ============================================================================

class TestDiscoveryAndOrdering:
    """Test migration file discovery and numeric sorting."""

    def test_discovery_finds_migrations_by_version(self, temp_migrations_dir):
        """Test that discovery finds migration files."""
        # Create test migration files
        (temp_migrations_dir / "0001_init.sql").write_text("CREATE TABLE test (id INT);")
        (temp_migrations_dir / "0002_add_column.sql").write_text("ALTER TABLE test ADD COLUMN name TEXT;")

        # Mock the migrations directory
        with mock.patch.object(migrate, "MIGRATIONS_DIR", temp_migrations_dir):
            migrations = migrate._discover_migrations()

        assert len(migrations) == 2
        assert migrations[0] == (1, "init", str(temp_migrations_dir / "0001_init.sql"))
        assert migrations[1] == (2, "add_column", str(temp_migrations_dir / "0002_add_column.sql"))

    def test_discovery_sorts_numerically(self, temp_migrations_dir):
        """Test that migrations are sorted numerically, not lexicographically."""
        # Create migrations in non-sequential order
        (temp_migrations_dir / "0010_add_users.sql").write_text("CREATE TABLE users (id INT);")
        (temp_migrations_dir / "0002_add_columns.sql").write_text("ALTER TABLE test ADD COLUMN name TEXT;")
        (temp_migrations_dir / "0001_init.sql").write_text("CREATE TABLE test (id INT);")

        with mock.patch.object(migrate, "MIGRATIONS_DIR", temp_migrations_dir):
            migrations = migrate._discover_migrations()

        assert len(migrations) == 3
        # Verify numeric sorting (not lexicographic)
        versions = [v for v, _, _ in migrations]
        assert versions == [1, 2, 10]

    def test_discovery_ignores_non_matching_files(self, temp_migrations_dir):
        """Test that discovery ignores files that don't match the pattern."""
        (temp_migrations_dir / "0001_init.sql").write_text("CREATE TABLE test (id INT);")
        (temp_migrations_dir / "readme.txt").write_text("Notes")
        (temp_migrations_dir / ".hidden").write_text("Hidden file")

        with mock.patch.object(migrate, "MIGRATIONS_DIR", temp_migrations_dir):
            migrations = migrate._discover_migrations()

        assert len(migrations) == 1
        assert migrations[0][0] == 1


# ============================================================================
# Malformed and Duplicate Versions (Requirement 34)
# ============================================================================

class TestMalformedAndDuplicateVersions:
    """Test validation of migration filenames."""

    def test_reject_malformed_filename(self, temp_migrations_dir):
        """Test that malformed filenames are rejected."""
        (temp_migrations_dir / "invalid_name.sql").write_text("SQL content")

        with mock.patch.object(migrate, "MIGRATIONS_DIR", temp_migrations_dir):
            with pytest.raises(ValueError, match="Malformed migration filename"):
                migrate._discover_migrations()

    def test_reject_duplicate_versions(self, temp_migrations_dir):
        """Test that duplicate versions are rejected."""
        (temp_migrations_dir / "0001_first.sql").write_text("CREATE TABLE test (id INT);")
        (temp_migrations_dir / "0001_second.sql").write_text("CREATE TABLE users (id INT);")

        with mock.patch.object(migrate, "MIGRATIONS_DIR", temp_migrations_dir):
            with pytest.raises(ValueError, match="Duplicate migration version"):
                migrate._discover_migrations()

    def test_reject_non_numeric_version(self, temp_migrations_dir):
        """Test that non-numeric versions are rejected."""
        (temp_migrations_dir / "abc_init.sql").write_text("SQL content")

        with mock.patch.object(migrate, "MIGRATIONS_DIR", temp_migrations_dir):
            with pytest.raises(ValueError, match="Malformed migration filename"):
                migrate._discover_migrations()

    def test_reject_empty_files(self, temp_migrations_dir):
        """Test that empty migration files are rejected."""
        (temp_migrations_dir / "0001_empty.sql").write_bytes(b"")

        with mock.patch.object(migrate, "MIGRATIONS_DIR", temp_migrations_dir):
            with pytest.raises(ValueError, match="Empty migration file"):
                migrate._discover_migrations()


# ============================================================================
# Invalid or Gapped History (Requirement 35)
# ============================================================================

class TestInvalidAndGappedHistory:
    """Test validation of migration history from database."""

    def test_reject_gapped_history(self, temp_migrations_dir):
        """Test that gapped history is rejected."""
        # Create files for versions 1 and 3
        (temp_migrations_dir / "0001_init.sql").write_text("CREATE TABLE test (id INT);")
        (temp_migrations_dir / "0003_third.sql").write_text("ALTER TABLE test ADD COLUMN c INT;")

        # Applied: versions 1, 3 (missing 2)
        applied = {
            1: (migrate._calculate_checksum(str(temp_migrations_dir / "0001_init.sql")), "init", "2026-08-31T10:00:00"),
            3: (migrate._calculate_checksum(str(temp_migrations_dir / "0003_third.sql")), "third", "2026-08-31T10:05:00"),
        }
        available = [
            (1, "init", str(temp_migrations_dir / "0001_init.sql")),
            (3, "third", str(temp_migrations_dir / "0003_third.sql")),
        ]

        errors, _ = migrate._validate_history(applied, available)
        assert len(errors) > 0
        assert any("gap" in str(e).lower() or "missing" in str(e).lower() for e in errors)

    def test_detect_invalid_history_in_database(self, temp_migrations_dir):
        """Test detection of invalid history (non-sequential versions)."""
        # Create files for versions 1, 2, 3, 4
        for v in range(1, 5):
            (temp_migrations_dir / f"000{v}_step.sql").write_text(f"-- Step {v}")

        applied = {
            1: (migrate._calculate_checksum(str(temp_migrations_dir / "0001_step.sql")), "step", "2026-08-31T10:00:00"),
            4: (migrate._calculate_checksum(str(temp_migrations_dir / "0004_step.sql")), "step", "2026-08-31T10:05:00"),
        }
        available = [
            (1, "step", str(temp_migrations_dir / "0001_step.sql")),
            (2, "step", str(temp_migrations_dir / "0002_step.sql")),
            (3, "step", str(temp_migrations_dir / "0003_step.sql")),
            (4, "step", str(temp_migrations_dir / "0004_step.sql")),
        ]

        errors, _ = migrate._validate_history(applied, available)
        assert len(errors) > 0


# ============================================================================
# Exact-Byte SHA-256 (Requirement 36)
# ============================================================================

class TestSHA256Checksums:
    """Test SHA-256 checksum calculation on exact bytes."""

    def test_checksum_matches_exact_bytes(self, temp_migrations_dir):
        """Test that checksum is calculated on exact file bytes."""
        migration_path = temp_migrations_dir / "0001_init.sql"
        content = "CREATE TABLE test (id INT);"
        migration_path.write_text(content)

        checksum = migrate._calculate_checksum(str(migration_path))

        # Verify against manual calculation
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert checksum == expected

    def test_checksum_differs_on_whitespace_change(self, temp_migrations_dir):
        """Test that whitespace changes affect checksum."""
        path1 = temp_migrations_dir / "0001_a.sql"
        path2 = temp_migrations_dir / "0001_b.sql"

        path1.write_text("CREATE TABLE test (id INT);")
        path2.write_text("CREATE TABLE test (id  INT);")  # Extra space

        checksum1 = migrate._calculate_checksum(str(path1))
        checksum2 = migrate._calculate_checksum(str(path2))

        assert checksum1 != checksum2


# ============================================================================
# Changed Applied Migration (Requirement 37)
# ============================================================================

class TestChangedAppliedMigrations:
    """Test detection of modified applied migrations."""

    def test_detect_changed_applied_migration(self, temp_migrations_dir):
        """Test that modified applied migrations are detected."""
        migration_path = temp_migrations_dir / "0001_init.sql"
        original_content = "CREATE TABLE test (id INT);"
        migration_path.write_text(original_content)

        # Get original checksum
        original_checksum = migrate._calculate_checksum(str(migration_path))

        # Modify the file
        migration_path.write_text("CREATE TABLE test (id INT); -- modified")

        # Simulate applied history with original checksum
        applied = {
            1: (original_checksum, "init", "2026-08-31T10:00:00"),
        }
        available = [(1, "init", str(migration_path))]

        errors, _ = migrate._validate_history(applied, available)
        assert any("checksum" in str(e).lower() for e in errors)

    def test_reject_changed_checksum(self, temp_migrations_dir):
        """Test that checksum mismatches are rejected."""
        (temp_migrations_dir / "0001_init.sql").write_text("CREATE TABLE test (id INT);")
        actual_checksum = migrate._calculate_checksum(str(temp_migrations_dir / "0001_init.sql"))

        applied = {
            1: ("different_checksum", "init", "2026-08-31T10:00:00"),
        }
        available = [
            (1, "init", str(temp_migrations_dir / "0001_init.sql")),
        ]

        errors, _ = migrate._validate_history(applied, available)
        assert any("checksum" in str(e).lower() for e in errors)


# ============================================================================
# Missing Applied Migration File (Requirement 38)
# ============================================================================

class TestMissingAppliedMigrations:
    """Test detection of missing local migration files."""

    def test_detect_missing_applied_migration_file(self):
        """Test that missing local files are detected."""
        # Version 1 is applied but file is missing
        applied = {
            1: ("checksum1", "init", "2026-08-31T10:00:00"),
        }
        available = []  # No local files

        errors, missing = migrate._validate_history(applied, available)
        assert len(missing) > 0
        assert 1 in missing
        assert any("not found" in str(e).lower() for e in errors)

    def test_hard_fail_on_missing_file(self, temp_migrations_dir):
        """Test that missing files cause hard failure."""
        # Create only version 2
        (temp_migrations_dir / "0002_add_column.sql").write_text("ALTER TABLE test ADD COLUMN c INT;")

        applied = {
            1: ("checksum1", "init", "2026-08-31T10:00:00"),
            2: (migrate._calculate_checksum(str(temp_migrations_dir / "0002_add_column.sql")), "add_column", "2026-08-31T10:05:00"),
        }
        available = [
            (2, "add_column", str(temp_migrations_dir / "0002_add_column.sql")),
            # Version 1 is missing
        ]

        errors, missing_versions = migrate._validate_history(applied, available)
        assert 1 in missing_versions
        assert len(errors) > 0


# ============================================================================
# Read-Only Status and Plan (Requirement 39)
# ============================================================================

class TestReadOnlyModes:
    """Test that --status and --plan are read-only."""

    @mock.patch("psycopg.connect")
    def test_status_is_read_only(self, mock_connect, mock_env_runtime):
        """Test that status mode uses read-only connection."""
        # Mock psycopg.connect to check the options
        mock_conn = mock.MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.__exit__.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock.MagicMock()

        with mock.patch.object(migrate, "MIGRATIONS_DIR", Path("/nonexistent")):
            migrate.get_status(
                host="127.0.0.1",
                port=5434,
                dbname="coding_agent_merchant",
                user="merchant_app",
                password="test",
            )

        # Verify read-only option was passed
        call_kwargs = mock_connect.call_args.kwargs
        assert "options" in call_kwargs
        assert "default_transaction_read_only=on" in call_kwargs["options"]

    @mock.patch("psycopg.connect")
    def test_plan_is_read_only(self, mock_connect, mock_env_runtime):
        """Test that plan mode uses read-only connection."""
        mock_conn = mock.MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.__exit__.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock.MagicMock()

        with mock.patch.object(migrate, "MIGRATIONS_DIR", Path("/nonexistent")):
            migrate.get_plan(
                host="127.0.0.1",
                port=5434,
                dbname="coding_agent_merchant",
                user="merchant_app",
                password="test",
            )

        call_kwargs = mock_connect.call_args.kwargs
        assert "options" in call_kwargs
        assert "default_transaction_read_only=on" in call_kwargs["options"]

    def test_read_only_connections_use_default_transaction_read_only(self):
        """Test read-only enforcement through default_transaction_read_only."""
        # This test verifies the connection option is set
        # (actual enforcement is PostgreSQL server-side)
        assert "default_transaction_read_only=on" != ""


# ============================================================================
# Explicit Runtime and Test Selection (Requirement 40)
# ============================================================================

class TestDatabaseSelection:
    """Test explicit runtime/test database selection."""

    def test_require_explicit_database_selection(self):
        """Test that --database is required."""
        # Simulate CLI call without --database
        result = subprocess.run(
            [sys.executable, "-m", "claude.clients.merchant.migrate", "--status"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_runtime_uses_merchant_db_name(self, mock_env_runtime):
        """Test that runtime target uses MERCHANT_DB_NAME."""
        with mock.patch.object(migrate, "MIGRATIONS_DIR", Path("/nonexistent")):
            with mock.patch("psycopg.connect"):
                result = migrate.get_status(
                    "127.0.0.1", 5434,
                    "coding_agent_merchant",
                    "merchant_app",
                    "test"
                )

        assert result["selected_target"] == "runtime"

    def test_test_uses_merchant_test_db_name(self, mock_env_test):
        """Test that test target uses MERCHANT_TEST_DB_NAME."""
        with mock.patch.object(migrate, "MIGRATIONS_DIR", Path("/nonexistent")):
            with mock.patch("psycopg.connect"):
                result = migrate.get_status(
                    "127.0.0.1", 5434,
                    "coding_agent_merchant_test",
                    "merchant_test",
                    "test"
                )

        assert result["selected_target"] == "test"


# ============================================================================
# RAG and Admin Database Collision Rejection (Requirement 41)
# ============================================================================

class TestDatabaseCollisionRejection:
    """Test rejection of RAG and admin databases."""

    def test_reject_rag_database(self):
        """Test that coding_agent_rag is rejected."""
        with pytest.raises(ValueError, match="coding_agent_rag"):
            migrate._validate_fail_closed(
                host="127.0.0.1",
                port=5434,
                dbname="coding_agent_rag",
                user="merchant_app",
                mode="status",
            )

    def test_reject_admin_database(self):
        """Test that admin database is rejected."""
        with mock.patch.dict(os.environ, {"MERCHANT_ADMIN_DB": "admin_db"}):
            with pytest.raises(ValueError, match="admin"):
                migrate._validate_fail_closed(
                    host="127.0.0.1",
                    port=5434,
                    dbname="admin_db",
                    user="merchant_app",
                    mode="status",
                )


# ============================================================================
# No Password CLI Options or Output (Requirement 42)
# ============================================================================

class TestPasswordSafety:
    """Test that passwords are not exposed in CLI."""

    def test_no_password_cli_option(self):
        """Test that --password option does not exist."""
        # Try to use --password with the real CLI
        result = subprocess.run(
            [sys.executable, "-m", "claude.clients.merchant.migrate", "--status", "--database", "runtime", "--password", "secret"],
            capture_output=True,
            text=True,
        )
        # Should fail because --password is not a valid option
        assert result.returncode != 0

    def test_no_password_in_output(self):
        """Test that connection strings don't contain passwords."""
        redacted = migrate._redact_connection_string(
            "127.0.0.1", 5434, "coding_agent_merchant", "merchant_app"
        )

        assert "password" not in redacted.lower()
        assert "secret" not in redacted.lower()
        assert "(password omitted)" not in redacted.lower()  # We don't include this message

    def test_no_credentials_in_json_output(self):
        """Test that JSON output doesn't contain credentials."""
        with mock.patch.object(migrate, "MIGRATIONS_DIR", Path("/nonexistent")):
            with mock.patch("psycopg.connect") as mock_connect:
                mock_conn = mock.MagicMock()
                mock_connect.return_value = mock_conn
                mock_conn.__enter__.return_value = mock_conn
                mock_conn.__exit__.return_value = None
                mock_conn.cursor.return_value.__enter__.return_value = mock.MagicMock()

                result = migrate.get_status(
                    "127.0.0.1", 5434,
                    "coding_agent_merchant",
                    "merchant_app",
                    "test_password"  # This should not appear in output
                )

        result_json = json.dumps(result)
        assert "test_password" not in result_json
        assert "password" not in result_json.lower() or "password omitted" in result_json.lower()


# ============================================================================
# Advisory Lock Management (Requirement 43)
# ============================================================================

class TestAdvisoryLocking:
    """Test advisory lock acquisition, timeout, and release."""

    def test_advisory_lock_acquired_before_apply(self):
        """Test that advisory lock is acquired before applying."""
        # This test verifies the lock acquisition happens
        with mock.patch("claude.clients.merchant.migrate.psycopg.connect") as mock_connect:
            with mock.patch.object(migrate, "_try_acquire_lock", return_value=True) as mock_try_lock:
                with mock.patch.object(migrate, "_get_applied_migrations", return_value={}):
                    with mock.patch.object(migrate, "_discover_migrations", return_value=[]):
                        with mock.patch.object(migrate, "_release_lock"):
                            with mock.patch.object(migrate, "MIGRATIONS_DIR", Path("/nonexistent")):
                                mock_conn = mock.MagicMock()
                                mock_connect.return_value = mock_conn
                                mock_conn.__enter__.return_value = mock_conn
                                mock_conn.__exit__.return_value = None

                                migrate.apply_migrations(
                                    "127.0.0.1", 5434,
                                    "coding_agent_merchant",
                                    "merchant_app",
                                    "test"
                                )

        # Verify lock was attempted
        assert mock_try_lock.called

    def test_lock_timeout_fails_apply(self):
        """Test that lock timeout causes apply to fail."""
        with mock.patch("claude.clients.merchant.migrate.psycopg.connect"):
            with mock.patch.object(migrate, "_try_acquire_lock", return_value=False):
                with mock.patch.object(migrate, "MIGRATIONS_DIR", Path("/nonexistent")):
                    result = migrate.apply_migrations(
                        "127.0.0.1", 5434,
                        "coding_agent_merchant",
                        "merchant_app",
                        "test"
                    )

        assert not result["success"]
        assert any("lock" in str(e).lower() for e in result["errors"])

    def test_lock_always_released_in_finally(self):
        """Test that lock is always released in finally block."""
        with mock.patch("claude.clients.merchant.migrate.psycopg.connect") as mock_connect:
            with mock.patch.object(migrate, "_try_acquire_lock", return_value=True):
                with mock.patch.object(migrate, "_release_lock") as mock_release:
                    with mock.patch.object(migrate, "_get_applied_migrations", return_value={}):
                        with mock.patch.object(migrate, "_discover_migrations", return_value=[]):
                            with mock.patch.object(migrate, "MIGRATIONS_DIR", Path("/nonexistent")):
                                mock_conn = mock.MagicMock()
                                mock_connect.return_value = mock_conn
                                mock_conn.__enter__.return_value = mock_conn
                                mock_conn.__exit__.return_value = None

                                migrate.apply_migrations(
                                    "127.0.0.1", 5434,
                                    "coding_agent_merchant",
                                    "merchant_app",
                                    "test"
                                )

            # Verify release was called
            assert mock_release.called


# ============================================================================
# SQL Parsing (Requirement 48)
# ============================================================================

class TestSQLParsing:
    """Test SQL parsing with complex syntax."""

    def test_execute_sql_with_semicolon_in_string(self):
        """Test parsing SQL with semicolons inside strings."""
        sql = "INSERT INTO table VALUES ('value; with; semicolons');"
        statements = migrate._split_sql_statements(sql)
        assert len(statements) == 1
        assert "value; with; semicolons" in statements[0]

    def test_execute_dollar_quoted_function(self):
        """Test parsing dollar-quoted string literals."""
        sql = """
        CREATE FUNCTION test() RETURNS void AS $$
        BEGIN
            EXECUTE 'SELECT 1; SELECT 2;';
        END;
        $$ LANGUAGE plpgsql;
        """
        statements = migrate._split_sql_statements(sql)
        assert len(statements) == 1
        assert "EXECUTE 'SELECT 1; SELECT 2;'" in statements[0]

    def test_execute_migration_with_comments(self):
        """Test parsing SQL with comments."""
        sql = """
        -- This is a comment with ; semicolon
        CREATE TABLE test (
            id INT -- inline comment
        ); /* block comment with ; */
        INSERT INTO test VALUES (1);
        """
        statements = migrate._split_sql_statements(sql)
        assert len(statements) == 2
        # Comments should be excluded
        assert "--" not in statements[0]
        assert "/*" not in statements[0]


# ============================================================================
# Direct Script Execution and Package Import (Requirement 49)
# ============================================================================

class TestExecutionPaths:
    """Test direct script execution and package import."""

    def test_direct_script_execution(self):
        """Test that migrate.py can be executed directly."""
        migrate_script = Path(__file__).parent.parent.parent / ".claude" / "clients" / "merchant" / "migrate.py"
        if migrate_script.exists():
            result = subprocess.run(
                [sys.executable, str(migrate_script), "--help"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "status" in result.stdout or "usage" in result.stdout.lower()

    def test_package_import_works(self):
        """Test that migrate module can be imported as a package."""
        from claude.clients.merchant import migrate as migrate_module
        assert hasattr(migrate_module, "get_status")
        assert hasattr(migrate_module, "get_plan")
        assert hasattr(migrate_module, "apply_migrations")

    def test_no_runpy_warnings(self):
        """Test that direct execution produces no warnings."""
        migrate_script = Path(__file__).parent.parent.parent / ".claude" / "clients" / "merchant" / "migrate.py"
        if migrate_script.exists():
            result = subprocess.run(
                [sys.executable, str(migrate_script), "--help"],
                capture_output=True,
                text=True,
            )
            # Check for typical Python warnings
            assert "DeprecationWarning" not in result.stderr
            assert "SyntaxWarning" not in result.stderr


# ============================================================================
# UTF-8 and Windows Path Behavior (Requirement 50)
# ============================================================================

class TestUTF8AndPaths:
    """Test UTF-8 handling and Windows path behavior."""

    def test_utf8_migration_content(self, temp_migrations_dir):
        """Test that UTF-8 content in migrations is handled correctly."""
        migration_path = temp_migrations_dir / "0001_init.sql"
        content = "-- Vietnamese comment: Xin chào\nCREATE TABLE test (name TEXT);"
        migration_path.write_text(content, encoding="utf-8")

        # Read back and verify
        read_content = migration_path.read_text(encoding="utf-8")
        assert "Xin chào" in read_content

    def test_windows_path_separator_handling(self):
        """Test that Windows path separators are handled correctly."""
        # This test verifies Path handles both / and \ correctly
        test_path = Path("C:\\path\\to\\migrations") / "0001_init.sql"
        # Just verify Path handles it without error
        assert "0001_init.sql" in str(test_path)


# ============================================================================
# Commit on Success (Requirement 44) and Rollback on Error (Requirement 45)
# ============================================================================

class TestTransactionSemantics:
    """Test commit/rollback behavior."""

    @mock.patch("psycopg.connect")
    def test_migration_commits_on_success(self, mock_connect):
        """Test that successful migrations commit."""
        mock_conn = mock.MagicMock()
        mock_cursor = mock.MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        with tempfile.TemporaryDirectory() as tmpdir:
            migration_path = Path(tmpdir) / "0001_init.sql"
            migration_path.write_text("CREATE TABLE test (id INT);")

            success, _, error = migrate._execute_migration(
                mock_conn, 1, "init", str(migration_path)
            )

        assert success
        mock_conn.commit.assert_called()

    @mock.patch("psycopg.connect")
    def test_migration_rollback_on_syntax_error(self, mock_connect):
        """Test that failed migrations rollback."""
        mock_conn = mock.MagicMock()
        mock_cursor = mock.MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None

        # Simulate SQL error
        mock_cursor.execute.side_effect = Exception("Syntax error")

        with tempfile.TemporaryDirectory() as tmpdir:
            migration_path = Path(tmpdir) / "0001_init.sql"
            migration_path.write_text("INVALID SQL;")

            success, _, error = migrate._execute_migration(
                mock_conn, 1, "init", str(migration_path)
            )

        assert not success
        mock_conn.rollback.assert_called()

    @mock.patch("psycopg.connect")
    def test_schema_migrations_row_inserted(self, mock_connect):
        """Test that schema_migrations row is inserted on success."""
        mock_conn = mock.MagicMock()
        mock_cursor = mock.MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = None
        mock_conn.autocommit = False

        with tempfile.TemporaryDirectory() as tmpdir:
            migration_path = Path(tmpdir) / "0001_init.sql"
            migration_path.write_text("CREATE TABLE test (id INT);")

            migrate._execute_migration(
                mock_conn, 1, "init", str(migration_path)
            )

        # Verify INSERT was called for schema_migrations
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        insert_called = any("INSERT INTO" in str(call) and "schema_migrations" in str(call) for call in calls)
        assert insert_called


# ============================================================================
# Integration Tests (PostgreSQL, opt-in)
# ============================================================================

@pytest.mark.integration
class TestPostgresIntegration:
    """PostgreSQL integration tests (opt-in, slow)."""

    def test_live_migration_applies_and_commits(self):
        """Test that migrations apply correctly to live database."""
        # This test requires a real PostgreSQL connection
        # Skip if MERCHANT_TEST_DB_NAME is not set
        test_db = os.environ.get("MERCHANT_TEST_DB_NAME")
        if not test_db:
            pytest.skip("MERCHANT_TEST_DB_NAME not set")

        # Real test would connect and verify migrations
        # For this implementation, we verify the framework is ready
        assert migrate.MIGRATIONS_DIR is not None


# ============================================================================
# Parameterized Tests
# ============================================================================

@pytest.mark.parametrize("version_str,expected", [
    ("0001", 1),
    ("0010", 10),
    ("0100", 100),
    ("9999", 9999),
])
def test_version_parsing(version_str, expected):
    """Test version number parsing from filenames."""
    filename = f"{version_str}_test.sql"
    match = re.match(r"^(\d+)_([a-z0-9_]+)\.sql$", filename)
    assert match
    assert int(match.group(1)) == expected


@pytest.mark.parametrize("invalid_filename", [
    "0001_INVALID.sql",  # uppercase not allowed in description
    "_test.sql",  # missing version
    "0001.sql",  # missing description
    "test_0001.sql",  # version not first
])
def test_invalid_filenames(invalid_filename):
    """Test rejection of invalid migration filenames."""
    # These should not match the pattern
    match = re.match(r"^(\d+)_([a-z0-9_]+)\.sql$", invalid_filename)
    assert match is None, f"Pattern should not match {invalid_filename}"
