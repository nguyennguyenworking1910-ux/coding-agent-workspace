"""Trusted local recording operator (CP12H.NL4D4A, DEC-A0).

The operator who records Merchant evidence is read only from controlled
local configuration: the ``MERCHANT_OPERATOR_ID`` variable of the process
environment or of the repository's untracked ``.env`` (loaded the same way,
and with the same trust, as the Merchant database credentials). It never
comes from a request, a teammate message, a model or a free CLI argument: a
confirmed write may only *name* the operator it was previewed with, and
trusted code refuses unless that equals this configuration.

The value must be one canonical lowercase UUID (not the nil UUID), because
it is stored as ``project_events.triggered_by``. It is attribution only: it
says which local operator recorded the evidence, never that an external
approver authorized anything. Any process running as the same OS user can
change ``.env``; this is a workstation boundary, not authentication.
"""

from __future__ import annotations

import os
import uuid

# Imported for its side effect: the repository's .env is loaded (never
# overriding the process environment) exactly as for the DB credentials.
from claude.clients.merchant import repository as _repository  # noqa: F401

OPERATOR_ENV = "MERCHANT_OPERATOR_ID"

OPERATOR_IDENTITY_UNAVAILABLE = "OPERATOR_IDENTITY_UNAVAILABLE"
OPERATOR_IDENTITY_INVALID = "OPERATOR_IDENTITY_INVALID"
OPERATOR_IDENTITY_CHANGED = "OPERATOR_IDENTITY_CHANGED"


class OperatorIdentityError(PermissionError):
    """No trusted recording operator; nothing may be recorded."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def trusted_operator_id() -> str:
    """The configured operator UUID, or OperatorIdentityError."""

    value = os.environ.get(OPERATOR_ENV)
    if value is None or not value.strip():
        raise OperatorIdentityError(OPERATOR_IDENTITY_UNAVAILABLE)
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise OperatorIdentityError(OPERATOR_IDENTITY_INVALID) from None
    # Exactly canonical: no whitespace, braces, urn: prefix or uppercase.
    if value != canonical or canonical == str(uuid.UUID(int=0)):
        raise OperatorIdentityError(OPERATOR_IDENTITY_INVALID)
    return canonical


def operator_status() -> dict[str, str | None]:
    """{"status": TRUSTED, "operator_id": ...} or {"status": <reason>, "operator_id": None}."""

    try:
        return {"status": "TRUSTED", "operator_id": trusted_operator_id()}
    except OperatorIdentityError as error:
        return {"status": error.reason, "operator_id": None}


def require_operator(expected: object) -> str:
    """The trusted operator, refusing unless it is exactly ``expected``."""

    operator = trusted_operator_id()
    if expected != operator:
        raise OperatorIdentityError(OPERATOR_IDENTITY_CHANGED)
    return operator
