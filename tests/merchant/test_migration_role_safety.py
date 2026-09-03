"""Tests for Merchant migration role selection."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from claude.clients.merchant import migrate


def configure_runtime_environment(monkeypatch):
    monkeypatch.setenv(
        "MERCHANT_DB_HOST",
        "127.0.0.1",
    )
    monkeypatch.setenv(
        "MERCHANT_DB_PORT",
        "5434",
    )
    monkeypatch.setenv(
        "MERCHANT_DB_NAME",
        "coding_agent_merchant",
    )
    monkeypatch.setenv(
        "MERCHANT_DB_USER",
        "merchant_app",
    )
    monkeypatch.setenv(
        "MERCHANT_DB_PASSWORD",
        "app-secret",
    )
    monkeypatch.setenv(
        "MERCHANT_OWNER_USER",
        "merchant_owner",
    )
    monkeypatch.setenv(
        "MERCHANT_OWNER_PASSWORD",
        "owner-secret",
    )


def configure_test_environment(monkeypatch):
    monkeypatch.setenv(
        "MERCHANT_DB_HOST",
        "127.0.0.1",
    )
    monkeypatch.setenv(
        "MERCHANT_DB_PORT",
        "5434",
    )
    monkeypatch.setenv(
        "MERCHANT_TEST_DB_NAME",
        "coding_agent_merchant_test",
    )
    monkeypatch.setenv(
        "MERCHANT_TEST_USER",
        "merchant_test",
    )
    monkeypatch.setenv(
        "MERCHANT_TEST_PASSWORD",
        "test-secret",
    )


def successful_result(mode):
    return {
        "success": True,
        "mode": mode,
    }


def test_runtime_apply_uses_owner_role(
    monkeypatch,
    capsys,
):
    configure_runtime_environment(monkeypatch)

    apply_mock = MagicMock(
        return_value=successful_result("apply")
    )
    monkeypatch.setattr(
        migrate,
        "apply_migrations",
        apply_mock,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate",
            "--apply",
            "--database",
            "runtime",
        ],
    )

    exit_code = migrate.main()
    capsys.readouterr()

    assert exit_code == 0

    apply_mock.assert_called_once_with(
        "127.0.0.1",
        5434,
        "coding_agent_merchant",
        "merchant_owner",
        "owner-secret",
    )


def test_runtime_status_uses_application_role(
    monkeypatch,
    capsys,
):
    configure_runtime_environment(monkeypatch)

    status_mock = MagicMock(
        return_value=successful_result("status")
    )
    monkeypatch.setattr(
        migrate,
        "get_status",
        status_mock,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate",
            "--status",
            "--database",
            "runtime",
        ],
    )

    exit_code = migrate.main()
    capsys.readouterr()

    assert exit_code == 0

    status_mock.assert_called_once_with(
        "127.0.0.1",
        5434,
        "coding_agent_merchant",
        "merchant_app",
        "app-secret",
    )


def test_runtime_plan_uses_application_role(
    monkeypatch,
    capsys,
):
    configure_runtime_environment(monkeypatch)

    plan_mock = MagicMock(
        return_value=successful_result("plan")
    )
    monkeypatch.setattr(
        migrate,
        "get_plan",
        plan_mock,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate",
            "--plan",
            "--database",
            "runtime",
        ],
    )

    exit_code = migrate.main()
    capsys.readouterr()

    assert exit_code == 0

    plan_mock.assert_called_once_with(
        "127.0.0.1",
        5434,
        "coding_agent_merchant",
        "merchant_app",
        "app-secret",
    )


def test_runtime_apply_rejects_application_role_override(
    monkeypatch,
    capsys,
):
    configure_runtime_environment(monkeypatch)

    monkeypatch.setenv(
        "MERCHANT_OWNER_USER",
        "merchant_app",
    )

    apply_mock = MagicMock()
    monkeypatch.setattr(
        migrate,
        "apply_migrations",
        apply_mock,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate",
            "--apply",
            "--database",
            "runtime",
        ],
    )

    exit_code = migrate.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "must execute as merchant_owner" in captured.err
    apply_mock.assert_not_called()


def test_runtime_apply_requires_owner_password(
    monkeypatch,
    capsys,
):
    configure_runtime_environment(monkeypatch)

    monkeypatch.delenv(
        "MERCHANT_OWNER_PASSWORD",
        raising=False,
    )

    apply_mock = MagicMock()
    monkeypatch.setattr(
        migrate,
        "apply_migrations",
        apply_mock,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate",
            "--apply",
            "--database",
            "runtime",
        ],
    )

    exit_code = migrate.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "MERCHANT_OWNER_PASSWORD" in captured.err
    apply_mock.assert_not_called()


def test_test_apply_uses_test_role(
    monkeypatch,
    capsys,
):
    configure_test_environment(monkeypatch)

    apply_mock = MagicMock(
        return_value=successful_result("apply")
    )
    monkeypatch.setattr(
        migrate,
        "apply_migrations",
        apply_mock,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate",
            "--apply",
            "--database",
            "test",
        ],
    )

    exit_code = migrate.main()
    capsys.readouterr()

    assert exit_code == 0

    apply_mock.assert_called_once_with(
        "127.0.0.1",
        5434,
        "coding_agent_merchant_test",
        "merchant_test",
        "test-secret",
    )