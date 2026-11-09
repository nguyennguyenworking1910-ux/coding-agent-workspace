import atexit
import os

import pytest

from claude.clients.merchant import attempt_evidence
from claude.clients.merchant.repository import MerchantRepository


@pytest.fixture(autouse=True)
def no_fence_outside_pytest_keys(monkeypatch):
    """A fence writes a REVOKED claim; tests may fence only pytest keys."""
    original = attempt_evidence.resolve_attempt

    def guarded(repository, identity, *, fence):
        if fence and not identity.operation_key.startswith("pytest:"):
            raise AssertionError(
                f"test attempted to fence {identity.operation_key!r}"
            )
        return original(repository, identity, fence=fence)

    monkeypatch.setattr(attempt_evidence, "resolve_attempt", guarded)


# CP12H.NL4C2A: one pytest process at a time on the Merchant test database.
# The first test-role repository of a process takes a session-level
# PostgreSQL advisory lock on its own connection and holds it until the
# process exits. A second process aborts instead of interleaving its
# fixtures with ours (fail closed). It does not serialize threads inside
# one process, which the concurrency tests rely on.
TEST_DATABASE_LOCK_KEY = 0x4E4C3443
_lock = {}


def _test_database_configured():
    return (
        os.environ.get("MERCHANT_TEST_DB_NAME") == "coding_agent_merchant_test"
        and bool(os.environ.get("MERCHANT_TEST_PASSWORD"))
    )


def _hold_test_database_lock():
    if _lock or not _test_database_configured():
        return
    _lock["state"] = "acquiring"  # constructing the holder re-enters here
    try:
        manager = MerchantRepository(role="test").connection()
        connection = manager.__enter__()
        connection.autocommit = True
        acquired = connection.execute(
            "SELECT pg_try_advisory_lock(%s) AS ok", (TEST_DATABASE_LOCK_KEY,)
        ).fetchone()["ok"]
    except Exception:  # noqa: BLE001 - no database here: the test sees its own error
        _lock.clear()  # retried by the next test-role repository
        return
    if not acquired:
        manager.__exit__(None, None, None)
        pytest.exit(
            "Another pytest process is using the Merchant test database "
            "(advisory lock held). PostgreSQL tests must run sequentially.",
            returncode=3,
        )
    _lock["state"] = "held"
    atexit.register(manager.__exit__, None, None, None)


_original_init = MerchantRepository.__init__


def _locked_init(self, *args, role="app", **kwargs):
    _original_init(self, *args, role=role, **kwargs)
    if role == "test":
        _hold_test_database_lock()


MerchantRepository.__init__ = _locked_init
