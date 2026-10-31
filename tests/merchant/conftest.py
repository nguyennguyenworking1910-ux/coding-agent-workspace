import pytest

from claude.clients.merchant import attempt_evidence


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
