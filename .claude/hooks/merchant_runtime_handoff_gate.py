#!/usr/bin/env python3
"""Gate 12H trusted Merchant runtime-handoff request state.

This module does not perform a Merchant runtime mutation.

Responsibilities:
- parse the exact non-terminal handoff request emitted by merchant-manager;
- validate the request against trusted run state;
- reserve exactly one handoff attempt before runtime execution;
- record the bounded SUCCESS / FAILED outcome;
- expose matching evidence for later terminal-result validation.

The actual runtime mutation remains owned by
claude.system.merchant_runtime_handoff.
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


MERCHANT_APPLY_HANDOFF_MARKER = (
    "MERCHANT_APPLY_HANDOFF_REQUEST_JSON:"
)

# Backward-compatible public name used by the earlier Gate 7.4 test
# contract. Keep both names bound to the exact same wire marker.
MERCHANT_APPLY_HANDOFF_REQUEST_MARKER = (
    MERCHANT_APPLY_HANDOFF_MARKER
)

HANDOFF_CONTRACT_VERSION = 1

MERCHANT_APPLY_OPERATION = "merchant_apply"
MERCHANT_MANAGER_AGENT = "merchant-manager"
RUNTIME_DATABASE_TARGET = "runtime"

HANDOFF_STATE_KEY = "merchant_runtime_handoff"

HANDOFF_PENDING = "PENDING"
HANDOFF_SUCCESS = "SUCCESS"
HANDOFF_FAILED = "FAILED"

HANDOFF_STATES = frozenset(
    {
        HANDOFF_PENDING,
        HANDOFF_SUCCESS,
        HANDOFF_FAILED,
    }
)

_HANDOFF_FIELDS = frozenset(
    {
        "contract_version",
        "operation",
        "database_target",
        "confirmation_hash",
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
    """One exact staged handoff request kept in memory by orchestration."""

    owner_session_id: str
    teammate_name: str
    run_id: str
    task_id: str
    confirmation_hash: str
    command: str
    proposal_hash: str
    arguments: tuple[str, ...]
    arguments_hash: str


def contains_handoff_marker(
    message: Any,
) -> bool:
    """Return True when a teammate message attempts the handoff contract."""

    if not isinstance(
        message,
        str,
    ):
        return False

    return (
        MERCHANT_APPLY_HANDOFF_MARKER
        in message
    )


def handoff_candidate_from_message(
    message: Any,
) -> dict[str, Any] | None:
    """Parse one strict non-terminal Merchant apply handoff request.

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
            MERCHANT_APPLY_HANDOFF_MARKER
        )
        != 1
    ):
        return None

    if not report.startswith(
        MERCHANT_APPLY_HANDOFF_MARKER
    ):
        return None

    _, encoded = report.split(
        MERCHANT_APPLY_HANDOFF_MARKER,
        1,
    )

    encoded = encoded.strip()

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

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    if set(candidate) != _HANDOFF_FIELDS:
        return None

    contract_version = candidate.get(
        "contract_version"
    )

    if (
        isinstance(
            contract_version,
            bool,
        )
        or contract_version
        != HANDOFF_CONTRACT_VERSION
    ):
        return None

    if (
        candidate.get(
            "operation"
        )
        != MERCHANT_APPLY_OPERATION
    ):
        return None

    if (
        candidate.get(
            "database_target"
        )
        != RUNTIME_DATABASE_TARGET
    ):
        return None

    confirmation_hash = candidate.get(
        "confirmation_hash"
    )

    if (
        not isinstance(
            confirmation_hash,
            str,
        )
        or _SHA256_PATTERN.fullmatch(
            confirmation_hash
        )
        is None
    ):
        return None

    arguments = candidate.get(
        "arguments"
    )

    if (
        not isinstance(
            arguments,
            list,
        )
        or not arguments
        or len(arguments)
        > MAX_ARGUMENT_COUNT
    ):
        return None

    normalized_arguments: list[str] = []

    for value in arguments:
        if not isinstance(
            value,
            str,
        ):
            return None

        if (
            not value
            or "\x00" in value
            or len(value)
            > MAX_ARGUMENT_LENGTH
        ):
            return None

        option = (
            value.split(
                "=",
                1,
            )[0]
            .strip()
            .lower()
        )

        if (
            option
            in CREDENTIAL_OR_TARGET_OPTIONS
        ):
            return None

        normalized_arguments.append(
            value
        )

    return {
        "contract_version": (
            HANDOFF_CONTRACT_VERSION
        ),
        "operation": (
            MERCHANT_APPLY_OPERATION
        ),
        "database_target": (
            RUNTIME_DATABASE_TARGET
        ),
        "confirmation_hash": (
            confirmation_hash
        ),
        "arguments": (
            tuple(
                normalized_arguments
            )
        ),
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
    """Validate and atomically stage one PENDING runtime handoff.

    The caller must already hold the owner run-state lock.

    Once HANDOFF_STATE_KEY exists, this run/task cannot stage a second
    attempt regardless of whether the prior state is PENDING, SUCCESS,
    or FAILED.
    """

    owner_session_id = str(
        owner_session_id
        or ""
    ).strip()

    teammate_name = str(
        teammate_name
        or ""
    ).strip()

    run_id = str(
        run_id
        or ""
    ).strip()

    task_id = str(
        task_id
        or ""
    ).strip()

    if not (
        owner_session_id
        and run_id
        and task_id
    ):
        return (
            None,
            "owner session, run, or task binding is missing",
        )

    if (
        teammate_name
        != MERCHANT_MANAGER_AGENT
    ):
        return (
            None,
            "handoff sender is not merchant-manager",
        )

    if (
        state.get(
            "run_id"
        )
        != run_id
    ):
        return (
            None,
            "run binding does not match trusted state",
        )

    if (
        state.get(
            "operations"
        )
        != [
            MERCHANT_APPLY_OPERATION
        ]
    ):
        return (
            None,
            "trusted run is not an exact merchant_apply operation",
        )

    if (
        state.get(
            "selected_agents"
        )
        != [
            MERCHANT_MANAGER_AGENT
        ]
    ):
        return (
            None,
            "trusted run lacks exclusive merchant-manager authority",
        )

    if (
        state.get(
            "confirmed"
        )
        is not True
    ):
        return (
            None,
            "trusted run is not confirmed",
        )

    if (
        state.get(
            "merchant_dispatch_spent"
        )
        is not True
    ):
        return (
            None,
            "Gate 7.3 dispatch has not been accepted",
        )

    confirmation = state.get(
        "merchant_confirmation"
    )

    if not isinstance(
        confirmation,
        Mapping,
    ):
        return (
            None,
            "trusted Merchant confirmation is absent",
        )

    confirmation_command = str(
        confirmation.get(
            "command"
        )
        or ""
    ).strip()

    confirmation_proposal_hash = str(
        confirmation.get(
            "proposal_hash"
        )
        or ""
    ).strip()

    if not (
        confirmation_command
        and _SHA256_PATTERN.fullmatch(
            confirmation_proposal_hash
        )
    ):
        return (
            None,
            "trusted confirmation command or proposal hash is malformed",
        )

    dispatch = state.get(
        "merchant_dispatch"
    )

    if not isinstance(
        dispatch,
        Mapping,
    ):
        return (
            None,
            "trusted Merchant dispatch receipt is absent",
        )

    if (
        confirmation.get(
            "operation"
        )
        != MERCHANT_APPLY_OPERATION
    ):
        return (
            None,
            "confirmation operation is not merchant_apply",
        )

    if (
        confirmation.get(
            "database_target"
        )
        != RUNTIME_DATABASE_TARGET
    ):
        return (
            None,
            "confirmation database target is not runtime",
        )

    candidate_confirmation_hash = (
        candidate.get(
            "confirmation_hash"
        )
    )

    if (
        not isinstance(
            candidate_confirmation_hash,
            str,
        )
        or candidate_confirmation_hash
        != confirmation.get(
            "confirmation_hash"
        )
    ):
        return (
            None,
            "handoff confirmation hash does not match trusted confirmation",
        )

    if (
        dispatch.get(
            "operation"
        )
        != MERCHANT_APPLY_OPERATION
        or dispatch.get(
            "subagent_type"
        )
        != MERCHANT_MANAGER_AGENT
        or dispatch.get(
            "teammate_name"
        )
        != MERCHANT_MANAGER_AGENT
        or dispatch.get(
            "confirmation_hash"
        )
        != candidate_confirmation_hash
    ):
        return (
            None,
            "Gate 7.3 dispatch receipt does not match the handoff",
        )

    if (
        state.get(
            "merchant_runtime_authorization_issued"
        )
        is True
    ):
        return (
            None,
            "runtime authorization was already issued for this run",
        )

    existing = state.get(
        HANDOFF_STATE_KEY
    )

    if existing is not None:
        if isinstance(
            existing,
            Mapping,
        ):
            existing_status = str(
                existing.get(
                    "status"
                )
                or ""
            ).strip()

            if existing_status in HANDOFF_STATES:
                return (
                    None,
                    "runtime handoff attempt is already "
                    f"{existing_status}",
                )

        return (
            None,
            "runtime handoff state already exists and is not reusable",
        )

    raw_arguments = candidate.get(
        "arguments"
    )

    if not isinstance(
        raw_arguments,
        tuple,
    ):
        return (
            None,
            "handoff arguments were not normalized by the trusted parser",
        )

    digest = arguments_hash(
        raw_arguments
    )

    state[
        HANDOFF_STATE_KEY
    ] = {
        "contract_version": (
            HANDOFF_CONTRACT_VERSION
        ),
        "status": (
            HANDOFF_PENDING
        ),
        "owner_session_id": (
            owner_session_id
        ),
        "run_id": (
            run_id
        ),
        "task_id": (
            task_id
        ),
        "teammate_name": (
            teammate_name
        ),
        "confirmation_hash": (
            candidate_confirmation_hash
        ),
        "arguments_hash": (
            digest
        ),
    }

    return (
        PreparedRuntimeHandoff(
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                teammate_name
            ),
            run_id=(
                run_id
            ),
            task_id=(
                task_id
            ),
            confirmation_hash=(
                candidate_confirmation_hash
            ),
            command=(
                confirmation_command
            ),
            proposal_hash=(
                confirmation_proposal_hash
            ),
            arguments=(
                raw_arguments
            ),
            arguments_hash=(
                digest
            ),
        ),
        "",
    )


def bounded_runtime_apply_result(
    stdout_text: Any,
    attempt: PreparedRuntimeHandoff,
) -> dict[str, Any] | None:
    """Validate CLI APPLY output and return only bounded trusted evidence.

    Raw repository result data is never persisted. Only its deterministic
    SHA-256 digest plus the non-sensitive APPLY identity fields survive.
    """

    if not isinstance(
        stdout_text,
        str,
    ):
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

    if encoded[
        end:
    ].strip():
        return None

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    if (
        isinstance(
            candidate.get(
                "contract_version"
            ),
            bool,
        )
        or not isinstance(
            candidate.get(
                "contract_version"
            ),
            int,
        )
    ):
        return None

    if (
        candidate.get(
            "success"
        )
        is not True
    ):
        return None

    if (
        candidate.get(
            "mode"
        )
        != "APPLY"
    ):
        return None

    if (
        candidate.get(
            "command"
        )
        != attempt.command
    ):
        return None

    if (
        candidate.get(
            "database"
        )
        != RUNTIME_DATABASE_TARGET
    ):
        return None

    if (
        candidate.get(
            "proposal_hash"
        )
        != attempt.proposal_hash
    ):
        return None

    if (
        "result"
        not in candidate
    ):
        return None

    try:
        canonical_result = (
            json.dumps(
                candidate[
                    "result"
                ],
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
                sort_keys=True,
            )
            .encode(
                "utf-8"
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    result_digest = (
        hashlib.sha256(
            canonical_result
        )
        .hexdigest()
    )

    return {
        "contract_version": (
            candidate[
                "contract_version"
            ]
        ),
        "success": True,
        "mode": "APPLY",
        "command": (
            attempt.command
        ),
        "database": (
            RUNTIME_DATABASE_TARGET
        ),
        "proposal_hash": (
            attempt.proposal_hash
        ),
        "result_sha256": (
            result_digest
        ),
    }


def record_runtime_handoff_result(
    state: dict[str, Any],
    attempt: PreparedRuntimeHandoff,
    *,
    succeeded: bool,
    exit_code: int | None,
    runtime_result: Mapping[str, Any] | None = None,
) -> bool:
    """Move the exact PENDING attempt to SUCCESS or FAILED."""

    receipt = state.get(
        HANDOFF_STATE_KEY
    )

    if not isinstance(
        receipt,
        dict,
    ):
        return False

    if (
        receipt.get(
            "status"
        )
        != HANDOFF_PENDING
    ):
        return False

    expected = {
        "owner_session_id": (
            attempt.owner_session_id
        ),
        "run_id": (
            attempt.run_id
        ),
        "task_id": (
            attempt.task_id
        ),
        "teammate_name": (
            attempt.teammate_name
        ),
        "confirmation_hash": (
            attempt.confirmation_hash
        ),
        "arguments_hash": (
            attempt.arguments_hash
        ),
    }

    for field, value in (
        expected.items()
    ):
        if (
            receipt.get(
                field
            )
            != value
        ):
            return False

    bounded_result = None

    if succeeded:
        if not isinstance(
            runtime_result,
            Mapping,
        ):
            return False

        if (
            runtime_result.get(
                "success"
            )
            is not True
            or runtime_result.get(
                "mode"
            )
            != "APPLY"
            or runtime_result.get(
                "command"
            )
            != attempt.command
            or runtime_result.get(
                "database"
            )
            != RUNTIME_DATABASE_TARGET
            or runtime_result.get(
                "proposal_hash"
            )
            != attempt.proposal_hash
        ):
            return False

        result_sha256 = (
            runtime_result.get(
                "result_sha256"
            )
        )

        if (
            not isinstance(
                result_sha256,
                str,
            )
            or _SHA256_PATTERN.fullmatch(
                result_sha256
            )
            is None
        ):
            return False

        bounded_result = dict(
            runtime_result
        )

    receipt[
        "status"
    ] = (
        HANDOFF_SUCCESS
        if succeeded
        else HANDOFF_FAILED
    )

    if (
        isinstance(
            exit_code,
            int,
        )
        and not isinstance(
            exit_code,
            bool,
        )
    ):
        receipt[
            "exit_code"
        ] = exit_code

        if (
            succeeded
            and bounded_result
            is not None
        ):
            receipt[
                "runtime_result"
            ] = bounded_result

    return True


def successful_runtime_handoff_matches(
    state: Mapping[str, Any],
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    confirmation_hash: str,
) -> bool:
    """Return True only for exact bounded Gate 7.4 SUCCESS evidence."""

    receipt = state.get(
        HANDOFF_STATE_KEY
    )

    if not isinstance(
        receipt,
        Mapping,
    ):
        return False

    if not (
        receipt.get(
            "status"
        )
        == HANDOFF_SUCCESS
        and receipt.get(
            "owner_session_id"
        )
        == str(
            owner_session_id
        ).strip()
        and receipt.get(
            "teammate_name"
        )
        == str(
            teammate_name
        ).strip()
        and receipt.get(
            "run_id"
        )
        == str(
            run_id
        ).strip()
        and receipt.get(
            "task_id"
        )
        == str(
            task_id
        ).strip()
        and receipt.get(
            "confirmation_hash"
        )
        == str(
            confirmation_hash
        ).strip()
    ):
        return False

    runtime_result = (
        receipt.get(
            "runtime_result"
        )
    )

    if not isinstance(
        runtime_result,
        Mapping,
    ):
        return False

    result_sha256 = (
        runtime_result.get(
            "result_sha256"
        )
    )

    return (
        runtime_result.get(
            "success"
        )
        is True
        and runtime_result.get(
            "mode"
        )
        == "APPLY"
        and runtime_result.get(
            "database"
        )
        == RUNTIME_DATABASE_TARGET
        and isinstance(
            result_sha256,
            str,
        )
        and _SHA256_PATTERN.fullmatch(
            result_sha256
        )
        is not None
    )


def failed_runtime_handoff_matches(
    state: Mapping[str, Any],
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    confirmation_hash: str,
) -> bool:
    """Return True only for exact Gate 7.4 FAILED evidence."""

    receipt = state.get(
        HANDOFF_STATE_KEY
    )

    if not isinstance(
        receipt,
        Mapping,
    ):
        return False

    return (
        receipt.get(
            "status"
        )
        == HANDOFF_FAILED
        and receipt.get(
            "owner_session_id"
        )
        == str(
            owner_session_id
        ).strip()
        and receipt.get(
            "teammate_name"
        )
        == str(
            teammate_name
        ).strip()
        and receipt.get(
            "run_id"
        )
        == str(
            run_id
        ).strip()
        and receipt.get(
            "task_id"
        )
        == str(
            task_id
        ).strip()
        and receipt.get(
            "confirmation_hash"
        )
        == str(
            confirmation_hash
        ).strip()
    )