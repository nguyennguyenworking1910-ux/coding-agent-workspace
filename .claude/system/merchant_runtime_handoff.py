"""Trusted in-process bridge for one confirmed Merchant runtime apply.

This module intentionally has no command-line entry point. The ordinary
Merchant Manager adapter remains read/propose-only. Controlled orchestration
uses ``invoke_confirmed_merchant_session_apply`` to reserve the persisted,
policy-accepted session before the resulting opaque capability crosses the
same-process call chain. It is never represented as text, a flag, an
environment variable, or JSON.
"""

from __future__ import annotations

import argparse
import io
import threading
from collections.abc import Mapping, MutableMapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from claude.agents.tools.merchant.agent_cli import (
    CREDENTIAL_OR_TARGET_OPTIONS,
    RUNTIME_DATABASE_TARGET,
)
from claude.agents.tools.merchant.cli import (
    WriteCommandFactory,
    build_argument_parser,
    main as merchant_cli_main,
)
from claude.agents.tools.merchant.cli_contract import (
    WRITE_COMMANDS,
    RuntimeWriteDeniedError,
    issue_runtime_apply_authorization,
    normalize_command,
)
from claude.hooks.runtime_state import locked_state


MERCHANT_APPLY_OPERATION = "merchant_apply"
MERCHANT_MANAGER_AGENT = "merchant-manager"
AUTHORIZED_RISKS = frozenset(
    {"external_write", "destructive"}
)
_HANDOFF_LOCK = threading.Lock()


class MerchantRuntimeHandoffError(RuntimeWriteDeniedError):
    """Raised before CLI dispatch when trusted run state is unusable."""


def invoke_confirmed_merchant_apply(
    arguments: Sequence[str],
    *,
    trusted_state: MutableMapping[str, Any],
    write_command_factory: WriteCommandFactory | None = None,
) -> int:
    """Invoke one exact runtime apply from a policy-accepted run state.

    ``trusted_state`` is the in-memory document loaded by controlled
    orchestration after the Gate 7.3 policy hook accepted and consumed the
    corresponding Agent dispatch. It is not accepted by any CLI parser.
    """

    prepared = _prepare_exact_apply(arguments)
    confirmation, dispatch_receipt = _reserve_authorization(
        _validated_state(trusted_state)
    )
    authorization = issue_runtime_apply_authorization(
        confirmation,
        dispatch_receipt,
    )

    return _invoke_authorized_apply(
        prepared,
        authorization,
        write_command_factory=write_command_factory,
    )


def invoke_confirmed_merchant_session_apply(
    session_id: str,
    arguments: Sequence[str],
    *,
    write_command_factory: WriteCommandFactory | None = None,
) -> int:
    """Consume one policy-accepted persisted session and invoke its apply.

    The issuance slot is saved under the session file lock before an opaque
    capability is issued or a repository adapter can run. A process failure
    can therefore lose an intended apply, but it cannot make an uncertain
    apply replayable. This deliberately provides at-most-once execution.
    """

    if not isinstance(session_id, str) or not session_id.strip():
        raise MerchantRuntimeHandoffError(
            "Trusted Merchant handoff requires an exact session id"
        )

    prepared = _prepare_exact_apply(arguments)
    confirmation: dict[str, Any] | None = None
    dispatch_receipt: dict[str, Any] | None = None

    # Persist the spend before constructing the capability or entering the
    # database adapter. Holding the file lock only for reservation keeps other
    # hooks responsive during the potentially slower repository call.
    with locked_state(session_id) as persisted_state:
        if persisted_state is None:
            raise MerchantRuntimeHandoffError(
                "No trusted Merchant run state exists for this session"
            )

        confirmation, dispatch_receipt = _reserve_authorization(
            _validated_state(persisted_state)
        )

    authorization = issue_runtime_apply_authorization(
        confirmation,
        dispatch_receipt,
    )

    return _invoke_authorized_apply(
        prepared,
        authorization,
        write_command_factory=write_command_factory,
    )


def _prepare_exact_apply(arguments: Sequence[str]) -> tuple[str, ...]:
    prepared, args = _prepare_runtime_apply(arguments)
    command = normalize_command(
        f"{args.resource} {args.action}"
    )

    if command not in WRITE_COMMANDS or args.mode != "APPLY":
        raise MerchantRuntimeHandoffError(
            "Trusted Merchant handoff accepts only an apply command"
        )

    if args.proposal_hash is None:
        raise MerchantRuntimeHandoffError(
            "Trusted Merchant handoff requires the confirmed proposal hash"
        )

    return prepared


def _reserve_authorization(
    state: MutableMapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    with _HANDOFF_LOCK:
        if "merchant_runtime_authorization_issued" in state:
            if state["merchant_runtime_authorization_issued"] is True:
                raise MerchantRuntimeHandoffError(
                    "Merchant runtime authorization was already issued for this dispatch"
                )

            raise MerchantRuntimeHandoffError(
                "Merchant runtime authorization state is malformed"
            )

        # Reservation is itself the one allowed attempt. Mark it before
        # returning immutable snapshots so malformed or stale state cannot be
        # corrected and retried after issuance validation fails.
        state["merchant_runtime_authorization_issued"] = True
        confirmation = dict(state["merchant_confirmation"])
        dispatch_receipt = dict(state["merchant_dispatch"])

    return confirmation, dispatch_receipt


def _invoke_authorized_apply(
    prepared: Sequence[str],
    authorization: Any,
    *,
    write_command_factory: WriteCommandFactory | None,
) -> int:
    return merchant_cli_main(
        prepared,
        write_command_factory=write_command_factory,
        runtime_authorization=authorization,
    )


def _validated_state(
    trusted_state: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    if not isinstance(trusted_state, MutableMapping):
        raise MerchantRuntimeHandoffError(
            "Trusted Merchant run state must be a mutable in-process document"
        )

    state = trusted_state

    if "confirmation_token" in state:
        raise MerchantRuntimeHandoffError(
            "Confirmation tokens must not enter runtime handoff state"
        )

    if state.get("operations") != [MERCHANT_APPLY_OPERATION]:
        raise MerchantRuntimeHandoffError(
            "Trusted run state is not an exact merchant_apply operation"
        )

    if state.get("selected_agents") != [MERCHANT_MANAGER_AGENT]:
        raise MerchantRuntimeHandoffError(
            "Trusted run state lacks exclusive merchant-manager authority"
        )

    if state.get("risk_level") not in AUTHORIZED_RISKS:
        raise MerchantRuntimeHandoffError(
            "Trusted run state lacks mutating risk authority"
        )

    if state.get("confirmed") is not True:
        raise MerchantRuntimeHandoffError(
            "Trusted run state is not exactly confirmed"
        )

    if state.get("merchant_dispatch_spent") is not True:
        raise MerchantRuntimeHandoffError(
            "Merchant dispatch was not accepted by the policy gate"
        )

    if not isinstance(
        state.get("merchant_confirmation"),
        Mapping,
    ):
        raise MerchantRuntimeHandoffError(
            "Trusted run state has no Merchant confirmation"
        )

    if not isinstance(state.get("merchant_dispatch"), Mapping):
        raise MerchantRuntimeHandoffError(
            "Trusted run state has no Merchant dispatch receipt"
        )

    return state


def _prepare_runtime_apply(
    arguments: Sequence[str],
) -> tuple[tuple[str, ...], argparse.Namespace]:
    if isinstance(arguments, (str, bytes, bytearray)):
        raise MerchantRuntimeHandoffError(
            "Merchant runtime arguments must be a sequence of tokens"
        )

    values = tuple(arguments)

    if not values:
        raise MerchantRuntimeHandoffError(
            "Merchant runtime apply command is required"
        )

    if any(not isinstance(value, str) for value in values):
        raise MerchantRuntimeHandoffError(
            "Merchant runtime arguments must be strings"
        )

    if any(not value or "\x00" in value for value in values):
        raise MerchantRuntimeHandoffError(
            "Merchant runtime arguments must be non-empty text"
        )

    for value in values:
        option = value.split("=", 1)[0].strip().lower()

        if option in CREDENTIAL_OR_TARGET_OPTIONS:
            raise MerchantRuntimeHandoffError(
                "Database target and credential arguments are forbidden"
            )

    prepared = (
        "--database",
        RUNTIME_DATABASE_TARGET,
        *values,
    )
    parser = build_argument_parser()
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            args = parser.parse_args(prepared)
    except SystemExit as error:
        raise MerchantRuntimeHandoffError(
            "Merchant runtime arguments do not match the allowlisted CLI contract"
        ) from error

    return prepared, args
