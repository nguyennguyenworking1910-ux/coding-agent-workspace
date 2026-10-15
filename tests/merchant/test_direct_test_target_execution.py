import json
import os
import uuid

import pytest

from claude.agents.tools.merchant.cli import main
from claude.clients.merchant.repository import (
    MerchantRepository,
    RepositoryConfig,
)


TEST_DATABASE = "coding_agent_merchant_test"
TEST_ROLE = "merchant_test"

live = pytest.mark.skipif(
    os.environ.get("MERCHANT_TEST_DB_NAME") != TEST_DATABASE
    or not os.environ.get("MERCHANT_TEST_PASSWORD"),
    reason="Merchant test database is not configured",
)


def _run(argv, capsys):
    exit_code = main(argv)
    captured = capsys.readouterr()
    return exit_code, captured


def _assert_effective_test_target(repository):
    # Verify the live connection before any write.
    with repository.connection(read_only=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS db, current_user AS usr"
            )
            row = cursor.fetchone()

    assert row["db"] == TEST_DATABASE
    assert row["usr"] == TEST_ROLE


def _cleanup_merchant(repository, merchant_id):
    merchant_uuid = uuid.UUID(merchant_id)

    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM merchant_ops.project_step_dependencies
                    WHERE from_step_id IN (
                        SELECT step.id
                        FROM merchant_ops.project_steps AS step
                        JOIN merchant_ops.projects AS project
                          ON project.id = step.project_id
                        WHERE project.merchant_id = %s
                    )
                    """,
                    (merchant_uuid,),
                )
                cursor.execute(
                    """
                    DELETE FROM merchant_ops.project_steps
                    WHERE project_id IN (
                        SELECT id FROM merchant_ops.projects
                        WHERE merchant_id = %s
                    )
                    """,
                    (merchant_uuid,),
                )
                cursor.execute(
                    "DELETE FROM merchant_ops.project_events "
                    "WHERE merchant_id = %s",
                    (merchant_uuid,),
                )
                cursor.execute(
                    "DELETE FROM merchant_ops.projects "
                    "WHERE merchant_id = %s",
                    (merchant_uuid,),
                )
                cursor.execute(
                    "DELETE FROM merchant_ops.merchants "
                    "WHERE id = %s",
                    (merchant_uuid,),
                )


@live
def test_direct_merchant_create_on_test_target(capsys):
    repository = MerchantRepository(role="test")
    _assert_effective_test_target(repository)

    code = f"DIR{uuid.uuid4().hex[:12].upper()}"
    exit_code, captured = _run(
        [
            "--database", "test",
            "merchant", "create",
            "--code", code,
            "--name", f"Direct create {code}",
        ],
        capsys,
    )

    try:
        assert exit_code == 0, captured.err
        merchant_id = json.loads(captured.out)["result"]["merchant_id"]

        with repository.connection(read_only=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT code, account_status "
                    "FROM merchant_ops.merchants WHERE id = %s",
                    (uuid.UUID(merchant_id),),
                )
                row = cursor.fetchone()

        assert row["code"] == code
    finally:
        if "merchant_id" in locals():
            _cleanup_merchant(repository, merchant_id)


@live
def test_direct_project_create_on_test_target(capsys):
    repository = MerchantRepository(role="test")
    _assert_effective_test_target(repository)

    merchant_id = str(uuid.uuid4())
    code = f"DPC{uuid.uuid4().hex[:12].upper()}"

    # Seed a test-owned ACTIVE merchant; the database has none.
    with repository.connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO merchant_ops.merchants (
                        id, code, name, account_status, version
                    )
                    VALUES (%s, %s, %s, 'ACTIVE', 1)
                    """,
                    (uuid.UUID(merchant_id), code, f"Direct {code}"),
                )

    try:
        exit_code, captured = _run(
            [
                "--database", "test",
                "project", "create",
                "--merchant-id", merchant_id,
                "--type", "OPENING_NEW_CINEMA",
                "--variant", "OPENING_NEW_CINEMA_STANDARD",
                "--title", f"Direct project {code}",
            ],
            capsys,
        )

        assert exit_code == 0, captured.err
        project_id = json.loads(captured.out)["result"]["project_id"]

        with repository.connection(read_only=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM merchant_ops.project_steps
                         WHERE project_id = %s) AS steps,
                        (SELECT COUNT(*) FROM merchant_ops.project_events
                         WHERE project_id = %s) AS events
                    """,
                    (uuid.UUID(project_id), uuid.UUID(project_id)),
                )
                counts = cursor.fetchone()

        assert counts["steps"] == 22
        assert counts["events"] == 1
    finally:
        _cleanup_merchant(repository, merchant_id)


def test_database_target_must_be_the_test_database(monkeypatch):
    monkeypatch.setenv("MERCHANT_TEST_DB_NAME", "coding_agent_merchant")
    monkeypatch.setenv("MERCHANT_TEST_PASSWORD", "unused")

    with pytest.raises(ValueError, match="Test repository must target"):
        RepositoryConfig.from_env("test")


def test_test_target_uses_test_role_and_runtime_uses_app_role():
    from claude.agents.tools.merchant.cli_contract import (
        repository_role_for_target,
    )

    assert repository_role_for_target("test") == "test"
    assert repository_role_for_target("runtime") == "app"


def test_cli_target_switch_to_production_database_is_refused(capsys):
    factory_calls = []

    def factory(database):
        factory_calls.append(database)
        raise AssertionError("Factory must not be called")

    # argparse limits --database to runtime or test, so a production
    # database name never reaches the write factory.
    with pytest.raises(SystemExit):
        main(
            [
                "--database", "coding_agent_merchant",
                "merchant", "create",
                "--code", "SWITCH",
                "--name", "Switched",
            ],
            write_command_factory=factory,
        )

    assert factory_calls == []
