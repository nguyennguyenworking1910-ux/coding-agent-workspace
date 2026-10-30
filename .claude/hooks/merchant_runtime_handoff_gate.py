#!/usr/bin/env python3
"""Gate 12H trusted Merchant Direct EXECUTE request state.

This module does not perform a Merchant runtime mutation.

Responsibilities:
- parse the exact non-terminal execute request emitted by merchant-manager;
- validate the request against the trusted, user-authorized run scope;
- reserve exactly one handoff attempt before runtime execution;
- record the bounded SUCCESS / FAILED outcome.

The request carries no authority. The command, arguments and binding hash
are re-derived from the user-typed --merchant-scope persisted in run state.
The actual runtime mutation remains owned by
claude.system.merchant_runtime_handoff and the reserved Create executor.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from claude.agents.tools.merchant.agent_cli import (
    CREDENTIAL_OR_TARGET_OPTIONS,
)


MERCHANT_EXECUTE_REQUEST_MARKER = (
    "MERCHANT_EXECUTE_REQUEST_JSON:"
)

HANDOFF_CONTRACT_VERSION = 1

MERCHANT_EXECUTE_OPERATION = "merchant_execute"
MERCHANT_MANAGER_AGENT = "merchant-manager"
RUNTIME_DATABASE_TARGET = "runtime"

# Databases an executed write may report. The target itself is fixed by
# trusted orchestration; this only validates reported evidence.
EXECUTION_DATABASES = frozenset({"runtime", "test"})

HANDOFF_STATE_KEY = "merchant_runtime_handoff"

HANDOFF_PENDING = "PENDING"
HANDOFF_SUCCESS = "SUCCESS"
HANDOFF_FAILED = "FAILED"

_HANDOFF_FIELDS = frozenset(
    {
        "contract_version",
        "operation",
        "database_target",
        "arguments",
    }
)

_SHA256_PATTERN = re.compile(
    r"^[0-9a-f]{64}$"
)

MAX_ARGUMENT_COUNT = 128
MAX_ARGUMENT_LENGTH = 4096


@dataclass(frozen=True)
class PreparedRuntimeHandoff:
    """One exact staged execute request kept in memory by orchestration."""

    owner_session_id: str
    teammate_name: str
    run_id: str
    task_id: str
    confirmation_hash: str
    command: str
    scope_hash: str
    arguments: tuple[str, ...]
    arguments_hash: str


def contains_handoff_marker(
    message: Any,
) -> bool:
    """Return True when a teammate message attempts the execute contract."""

    if not isinstance(
        message,
        str,
    ):
        return False

    return (
        MERCHANT_EXECUTE_REQUEST_MARKER
        in message
    )


def handoff_candidate_from_message(
    message: Any,
) -> dict[str, Any] | None:
    """Parse one strict non-terminal Merchant execute request.

    The marker must be the start of the message and exactly one JSON object
    must follow it. No prose or second object is allowed after the payload.
    """

    if not isinstance(
        message,
        str,
    ):
        return None

    report = message.strip()

    if (
        report.count(
            MERCHANT_EXECUTE_REQUEST_MARKER
        )
        != 1
        or not report.startswith(
            MERCHANT_EXECUTE_REQUEST_MARKER
        )
    ):
        return None

    encoded = report[
        len(MERCHANT_EXECUTE_REQUEST_MARKER):
    ].strip()

    if not encoded:
        return None

    try:
        candidate, end = (
            json.JSONDecoder().raw_decode(
                encoded
            )
        )
    except json.JSONDecodeError:
        return None

    if encoded[end:].strip():
        return None

    if (
        not isinstance(candidate, dict)
        or set(candidate) != _HANDOFF_FIELDS
    ):
        return None

    contract_version = candidate.get(
        "contract_version"
    )

    if (
        isinstance(contract_version, bool)
        or contract_version != HANDOFF_CONTRACT_VERSION
    ):
        return None

    if (
        candidate.get("operation")
        != MERCHANT_EXECUTE_OPERATION
        or candidate.get("database_target")
        != RUNTIME_DATABASE_TARGET
    ):
        return None

    arguments = candidate.get(
        "arguments"
    )

    if (
        not isinstance(arguments, list)
        or not arguments
        or len(arguments) > MAX_ARGUMENT_COUNT
    ):
        return None

    normalized_arguments: list[str] = []

    for value in arguments:
        if (
            not isinstance(value, str)
            or not value
            or "\x00" in value
            or len(value) > MAX_ARGUMENT_LENGTH
        ):
            return None

        option = (
            value.split("=", 1)[0]
            .strip()
            .lower()
        )

        if option in CREDENTIAL_OR_TARGET_OPTIONS:
            return None

        normalized_arguments.append(
            value
        )

    return {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "operation": MERCHANT_EXECUTE_OPERATION,
        "database_target": RUNTIME_DATABASE_TARGET,
        "arguments": tuple(normalized_arguments),
    }


def arguments_hash(
    arguments: tuple[str, ...],
) -> str:
    """Return deterministic evidence without persisting raw CLI arguments."""

    canonical = json.dumps(
        list(arguments),
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        canonical
    ).hexdigest()


def stage_runtime_handoff_attempt(
    state: dict[str, Any],
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    candidate: Mapping[str, Any],
) -> tuple[
    PreparedRuntimeHandoff | None,
    str,
]:
    """Validate and atomically stage one PENDING execute attempt.

    The caller must already hold the owner run-state lock.

    Once HANDOFF_STATE_KEY exists, this run/task cannot stage a second
    attempt regardless of whether the prior state is PENDING, SUCCESS,
    or FAILED.
    """

    owner_session_id = str(owner_session_id or "").strip()
    teammate_name = str(teammate_name or "").strip()
    run_id = str(run_id or "").strip()
    task_id = str(task_id or "").strip()

    if not (
        owner_session_id
        and run_id
        and task_id
    ):
        return (
            None,
            "owner session, run, or task binding is missing",
        )

    if teammate_name != MERCHANT_MANAGER_AGENT:
        return (
            None,
            "handoff sender is not merchant-manager",
        )

    if state.get("run_id") != run_id:
        return (
            None,
            "run binding does not match trusted state",
        )

    if state.get("operations") != [MERCHANT_EXECUTE_OPERATION]:
        return (
            None,
            "trusted run is not an exact merchant_execute operation",
        )

    if state.get("selected_agents") != [MERCHANT_MANAGER_AGENT]:
        return (
            None,
            "trusted run lacks exclusive merchant-manager authority",
        )

    if state.get("confirmed") is not True:
        return (
            None,
            "trusted run is not confirmed",
        )

    if state.get("merchant_dispatch_spent") is not True:
        return (
            None,
            "Merchant dispatch has not been accepted",
        )

    # Direct scope originates from the trusted owner state, never the
    # teammate-authored request.
    direct_scope = state.get("merchant_scope")

    if not isinstance(direct_scope, dict):
        return (
            None,
            "Direct EXECUTE requires a user-authorized --merchant-scope",
        )

    if state.get("merchant_confirmation") is not None:
        return None, "proposal confirmation cannot coexist with a scope"

    if state.get("merchant_runtime_authorization_issued") is True:
        return None, "runtime authorization was already issued"

    if state.get(HANDOFF_STATE_KEY) is not None:
        return None, "runtime handoff state already exists"

    from claude.system.merchant_runtime_handoff import (
        completeness_evidence,
        validate_direct_scope,
    )

    try:
        trusted_scope = validate_direct_scope(
            direct_scope.get("argv")
        )
    except (ValueError, TypeError, RuntimeError):
        return None, "trusted direct scope validation failed"

    if not isinstance(trusted_scope, dict):
        return None, "trusted direct scope validation failed"

    if (
        direct_scope.get("run_id") != run_id
        or direct_scope.get("scope_hash")
        != trusted_scope.get("scope_hash")
        or direct_scope.get("command")
        != trusted_scope.get("command")
        or direct_scope.get("database_target") != RUNTIME_DATABASE_TARGET
        or trusted_scope.get("database_target") != RUNTIME_DATABASE_TARGET
    ):
        return None, "direct scope does not match trusted run"

    raw_arguments = candidate.get("arguments")

    if (
        not isinstance(raw_arguments, tuple)
        or raw_arguments
        != tuple(trusted_scope.get("argv") or ())
    ):
        return None, "execute arguments do not match direct scope"

    confirmation_hash = trusted_scope.get(
        "confirmation_hash"
    )

    dispatch = state.get("merchant_dispatch")

    if (
        not isinstance(dispatch, Mapping)
        or dispatch.get("operation") != MERCHANT_EXECUTE_OPERATION
        or dispatch.get("subagent_type") != MERCHANT_MANAGER_AGENT
        or dispatch.get("teammate_name") != MERCHANT_MANAGER_AGENT
        or dispatch.get("confirmation_hash") != confirmation_hash
    ):
        return None, "trusted direct dispatch receipt mismatch"

    digest = arguments_hash(raw_arguments)

    state[HANDOFF_STATE_KEY] = {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "status": HANDOFF_PENDING,
        "owner_session_id": owner_session_id,
        "run_id": run_id,
        "task_id": task_id,
        "teammate_name": teammate_name,
        "confirmation_hash": confirmation_hash,
        "arguments_hash": digest,
        # Trusted completeness of the exact payload, re-verified where
        # authority is spent.
        "completeness": completeness_evidence(
            trusted_scope,
            run_id=run_id,
            task_id=task_id,
        ),
    }

    return (
        PreparedRuntimeHandoff(
            owner_session_id=owner_session_id,
            teammate_name=teammate_name,
            run_id=run_id,
            task_id=task_id,
            confirmation_hash=confirmation_hash,
            command=trusted_scope["command"],
            scope_hash=trusted_scope["scope_hash"],
            arguments=raw_arguments,
            arguments_hash=digest,
        ),
        "",
    )


def bounded_runtime_apply_result(
    stdout_text: Any,
    attempt: PreparedRuntimeHandoff,
) -> dict[str, Any] | None:
    """Validate EXECUTE output and return only bounded trusted evidence.

    Raw repository result data is never persisted. Only its deterministic
    SHA-256 digest plus the non-sensitive EXECUTE identity fields survive.
    """

    if not isinstance(stdout_text, str):
        return None

    encoded = stdout_text.strip()

    if not encoded:
        return None

    try:
        candidate, end = (
            json.JSONDecoder().raw_decode(
                encoded
            )
        )
    except json.JSONDecodeError:
        return None

    if encoded[end:].strip():
        return None

    if not isinstance(candidate, dict):
        return None

    contract_version = candidate.get("contract_version")

    if (
        isinstance(contract_version, bool)
        or not isinstance(contract_version, int)
    ):
        return None

    if (
        candidate.get("success") is not True
        or candidate.get("mode") != "EXECUTE"
        or candidate.get("command") != attempt.command
        or candidate.get("database") not in EXECUTION_DATABASES
        or "result" not in candidate
    ):
        return None

    try:
        canonical_result = json.dumps(
            candidate["result"],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None

    return {
        "contract_version": contract_version,
        "success": True,
        "mode": "EXECUTE",
        "command": attempt.command,
        "database": candidate["database"],
        "result_sha256": hashlib.sha256(
            canonical_result
        ).hexdigest(),
    }


def bounded_runtime_apply_failure(
    stderr_text: str,
) -> str | None:
    """Extract only the bounded Merchant CLI error type."""

    if not isinstance(stderr_text, str):
        return None

    text = stderr_text.strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    error = payload.get("error")

    if not isinstance(error, dict):
        return None

    error_type = error.get("type")

    if not isinstance(error_type, str):
        return None

    error_type = error_type.strip()[:128]

    return error_type or None


def record_runtime_handoff_result(
    state: dict[str, Any],
    attempt: PreparedRuntimeHandoff,
    *,
    succeeded: bool,
    exit_code: int | None,
    runtime_result: Mapping[str, Any] | None = None,
    failure_type: str | None = None,
) -> bool:
    """Move the exact PENDING attempt to SUCCESS or FAILED.

    This run-state receipt informs the teammate only. Lifecycle completion
    uses team-state execution evidence and committed PostgreSQL evidence.
    """

    receipt = state.get(HANDOFF_STATE_KEY)

    if (
        not isinstance(receipt, dict)
        or receipt.get("status") != HANDOFF_PENDING
    ):
        return False

    expected = {
        "owner_session_id": attempt.owner_session_id,
        "run_id": attempt.run_id,
        "task_id": attempt.task_id,
        "teammate_name": attempt.teammate_name,
        "confirmation_hash": attempt.confirmation_hash,
        "arguments_hash": attempt.arguments_hash,
    }

    if any(
        receipt.get(field) != value
        for field, value in expected.items()
    ):
        return False

    bounded_result = None

    if succeeded:
        if not isinstance(runtime_result, Mapping):
            return False

        result_sha256 = runtime_result.get("result_sha256")

        if (
            runtime_result.get("success") is not True
            or runtime_result.get("mode") != "EXECUTE"
            or runtime_result.get("command") != attempt.command
            or runtime_result.get("database") not in EXECUTION_DATABASES
            or not isinstance(result_sha256, str)
            or _SHA256_PATTERN.fullmatch(result_sha256) is None
        ):
            return False

        bounded_result = dict(runtime_result)

    receipt["status"] = (
        HANDOFF_SUCCESS
        if succeeded
        else HANDOFF_FAILED
    )

    if (
        isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
    ):
        receipt["exit_code"] = exit_code

        if succeeded and bounded_result is not None:
            receipt["runtime_result"] = bounded_result

    if (
        not succeeded
        and isinstance(failure_type, str)
    ):
        bounded_failure_type = failure_type.strip()[:128]

        if bounded_failure_type:
            receipt["failure_type"] = bounded_failure_type

    return True
