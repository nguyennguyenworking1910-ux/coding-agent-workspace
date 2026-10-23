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
import hashlib
import io
import json
import re
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
    build_write_payload,
    main as merchant_cli_main,
)
from claude.agents.tools.merchant.cli_contract import (
    WRITE_COMMANDS,
    RuntimeWriteDeniedError,
    build_confirmation_envelope,
    issue_runtime_apply_authorization,
    normalize_command,
)
from claude.hooks.merchant_confirmation_preferences import (
    MODE_LOCAL_AUTO,
    MODE_MANUAL,
    consume_receipt,
)
from claude.hooks.runtime_state import (
    MERCHANT_CONFIRMATION_MODE_FIELD,
    MERCHANT_CONFIRMATION_MODES,
    locked_state,
)


MERCHANT_APPLY_OPERATION = "merchant_apply"
MERCHANT_MANAGER_AGENT = "merchant-manager"
AUTHORIZED_RISKS = frozenset(
    {"external_write", "destructive"}
)
_HANDOFF_LOCK = threading.Lock()


class MerchantRuntimeHandoffError(RuntimeWriteDeniedError):
    """Raised before CLI dispatch when trusted run state is unusable."""

class MerchantRuntimeHandoffStageError(MerchantRuntimeHandoffError):
    """Bounded stage-aware failure for trusted session apply."""

    def __init__(
        self,
        stage: str,
        cause: Exception | None = None,
    ) -> None:
        self.stage = stage

        message = (
            f"Merchant runtime handoff failed at stage {stage}"
        )

        if cause is not None:
            detail = str(cause).strip()

            if detail:
                message = f"{message}: {detail}"

        super().__init__(message)

def invoke_confirmed_merchant_session_apply(
    session_id: str,
    arguments: Sequence[str],
    *,
    write_command_factory: WriteCommandFactory | None = None,
) -> int:
    """Consume one policy-accepted persisted session and invoke its apply."""

    if not isinstance(session_id, str) or not session_id.strip():
        raise MerchantRuntimeHandoffStageError(
            "SESSION_ID"
        )

    try:
        prepared = _prepare_exact_apply(arguments)
    except Exception as exc:
        raise MerchantRuntimeHandoffStageError("PREPARE", exc) from exc

    confirmation: dict[str, Any] | None = None
    dispatch_receipt: dict[str, Any] | None = None
    confirmation_mode = MODE_MANUAL
    target_mismatch_error = None

    try:
        with locked_state(session_id) as persisted_state:
            if persisted_state is None:
                raise MerchantRuntimeHandoffError(
                    "No trusted Merchant run state exists for this session"
                )

            state = _validated_state(
                persisted_state
            )

            confirmation_mode = _confirmation_mode(
                state
            )

            confirmation, dispatch_receipt = (
                _reserve_authorization(state)
            )

            # A target mismatch must spend the one-use reservation.
            # Do not raise before locked_state persists the marker.
            try:
                _require_user_named_targets_bound(state, arguments)
            except MerchantRuntimeHandoffError as exc:
                target_mismatch_error = exc

    except Exception as exc:
        raise MerchantRuntimeHandoffStageError(
            "RESERVE_AUTHORIZATION",
            exc,
        ) from exc

    # The state lock has exited normally and persisted the reservation.
    # Reject before receipt consumption, authorization issuance or CLI.
    if target_mismatch_error is not None:
        raise MerchantRuntimeHandoffStageError(
            "RESERVE_AUTHORIZATION",
            target_mismatch_error,
        ) from target_mismatch_error

    if confirmation_mode == MODE_LOCAL_AUTO:
        try:
            consumption = consume_receipt(
                session_id,
                confirmation["confirmation_hash"],
            )

            if not consumption.accepted:
                raise MerchantRuntimeHandoffError(
                    "Local auto-confirm proposal receipt "
                    "could not be consumed"
                )
        except Exception as exc:
            raise MerchantRuntimeHandoffStageError("CONSUME_RECEIPT", exc) from exc

    try:
        authorization = issue_runtime_apply_authorization(
            confirmation,
            dispatch_receipt,
        )
    except Exception as exc:
        raise MerchantRuntimeHandoffStageError("ISSUE_AUTHORIZATION", exc) from exc

    try:
        return _invoke_authorized_apply(
            prepared,
            authorization,
            write_command_factory=write_command_factory,
        )
    except Exception as exc:
        raise MerchantRuntimeHandoffStageError("CLI_INVOKE", exc) from exc


_UUID_TOKEN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _require_user_named_targets_bound(
    state: Mapping[str, Any],
    arguments: Sequence[str],
) -> None:
    """Fail closed when the user named an entity the apply does not target.

    Every UUID the user wrote in the request must appear as an exact
    argument of the apply. This is a rejection rule, not target inference:
    a request that names no UUID relies on the exact confirmed proposal.
    """

    named = {
        match.lower()
        for match in _UUID_TOKEN.findall(str(state.get("request") or ""))
    }
    bound = {
        str(token).lower()
        for token in arguments
        if _UUID_TOKEN.fullmatch(str(token))
    }

    if not named <= bound:
        raise MerchantRuntimeHandoffError(
            "Runtime apply target does not match the user's request"
        )


MERCHANT_SCOPE_STATE_KEY = "merchant_scope"
DIRECT_SCOPE_FORBIDDEN_TOKENS = frozenset(
    {"--apply", "--propose", "--execute", "--proposal-hash"}
)


def validate_direct_scope(argv: Sequence[str]) -> dict[str, Any]:
    """Validate one exact user-typed Merchant write and derive its scope.

    The scope is the exact argv the user authorized. It must name one
    allowlisted write on the runtime target, with no mode, proposal hash or
    database override, and every entity identifier must be an exact UUID.
    Names are rejected so an ambiguous target cannot become authority.
    """

    if isinstance(argv, (str, bytes, bytearray)) or not isinstance(
        argv, Sequence
    ):
        raise MerchantRuntimeHandoffError(
            "Direct Merchant scope must be a list of tokens"
        )

    tokens = list(argv)

    if not tokens or not all(
        isinstance(token, str) and token for token in tokens
    ):
        raise MerchantRuntimeHandoffError(
            "Direct Merchant scope must be non-empty string tokens"
        )

    for token in tokens:
        option = token.split("=", 1)[0]

        if (
            option in DIRECT_SCOPE_FORBIDDEN_TOKENS
            or option in CREDENTIAL_OR_TARGET_OPTIONS
        ):
            raise MerchantRuntimeHandoffError(
                "Direct Merchant scope must not name a mode, proposal "
                "hash or database target"
            )

    try:
        args = build_argument_parser().parse_args(
            ["--database", RUNTIME_DATABASE_TARGET, *tokens]
        )
        command = normalize_command(
            f"{args.resource} {args.action}"
        )

        if command not in WRITE_COMMANDS:
            raise MerchantRuntimeHandoffError(
                "Direct Merchant scope must name one allowlisted write"
            )

        payload = build_write_payload(args, command)
    except (SystemExit, ValueError, TypeError) as exc:
        raise MerchantRuntimeHandoffError(
            "Direct Merchant scope does not match the Merchant CLI contract"
        ) from exc

    for field, value in payload.items():
        if (
            field.endswith("_id")
            and value is not None
            and _UUID_TOKEN.fullmatch(str(value)) is None
        ):
            raise MerchantRuntimeHandoffError(
                "Direct Merchant scope targets must be exact UUIDs, "
                "not names or ambiguous references"
            )

    envelope = build_confirmation_envelope(
        command,
        RUNTIME_DATABASE_TARGET,
        payload,
    )

    return {
        "argv": tokens,
        "command": command,
        "database_target": RUNTIME_DATABASE_TARGET,
        "scope_hash": _direct_scope_hash(tokens),
        "confirmation": envelope.to_dict(),
        "confirmation_hash": envelope.confirmation_hash,
        "proposal_hash": envelope.proposal_hash,
    }


def _direct_scope_hash(tokens: Sequence[str]) -> str:
    canonical = json.dumps(
        list(tokens),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(canonical).hexdigest()


def _validated_direct_state(
    state: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    scope = state.get(MERCHANT_SCOPE_STATE_KEY)

    if not isinstance(scope, Mapping):
        raise MerchantRuntimeHandoffError(
            "Trusted run state has no user-authorized scope"
        )

    if state.get("merchant_confirmation") is not None:
        raise MerchantRuntimeHandoffError(
            "Direct scope must not be mixed with a proposal confirmation"
        )

    if state.get("confirmed") is not True:
        raise MerchantRuntimeHandoffError(
            "Trusted run state is not exactly confirmed"
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

    if state.get("merchant_dispatch_spent") is not True:
        raise MerchantRuntimeHandoffError(
            "Merchant dispatch was not accepted by the policy gate"
        )

    dispatch = state.get("merchant_dispatch")

    if not isinstance(dispatch, Mapping):
        raise MerchantRuntimeHandoffError(
            "Trusted run state has no Merchant dispatch receipt"
        )

    run_id = scope.get("run_id")

    if not isinstance(run_id, str) or not run_id or run_id != state.get(
        "run_id"
    ):
        raise MerchantRuntimeHandoffError(
            "User-authorized scope belongs to another run"
        )

    tokens = scope.get("argv")

    if not isinstance(tokens, list):
        raise MerchantRuntimeHandoffError(
            "User-authorized scope is malformed"
        )

    recomputed = validate_direct_scope(tokens)

    if scope.get("scope_hash") != recomputed["scope_hash"]:
        raise MerchantRuntimeHandoffError(
            "User-authorized scope failed its integrity check"
        )

    if dispatch.get("confirmation_hash") != recomputed["confirmation_hash"]:
        raise MerchantRuntimeHandoffError(
            "Policy dispatch does not match the user-authorized scope"
        )

    return recomputed, dict(dispatch)


def _reserve_direct_authorization(
    state: MutableMapping[str, Any],
) -> None:
    # Shares the proposal path's one-use marker, so a direct scope and a
    # proposal confirmation can never both authorize the same dispatch.
    with _HANDOFF_LOCK:
        if "merchant_runtime_authorization_issued" in state:
            raise MerchantRuntimeHandoffError(
                "Merchant runtime authorization was already issued for this dispatch"
            )

        state["merchant_runtime_authorization_issued"] = True

def invoke_authorized_scope_apply(
    session_id: str,
    arguments: Sequence[str],
    *,
    write_command_factory: WriteCommandFactory | None = None,
) -> int:
    """Apply one trusted user-authorized write exactly once.

    An attempted argument mismatch consumes the authorization before
    it is rejected. The reservation must be persisted before raising.
    """

    if not isinstance(session_id, str) or not session_id.strip():
        raise MerchantRuntimeHandoffStageError("SESSION_ID")

    if isinstance(arguments, (str, bytes, bytearray)):
        raise MerchantRuntimeHandoffError(
            "Merchant runtime arguments must be a sequence of tokens"
        )

    presented = tuple(arguments)
    scope_mismatch = False
    scope = None
    authorization = None

    try:
        with locked_state(session_id) as persisted_state:
            if persisted_state is None:
                raise MerchantRuntimeHandoffError(
                    "No trusted Merchant run state exists for this session"
                )

            scope, dispatch_receipt = _validated_direct_state(
                persisted_state
            )

            # Reserve the one-use authorization under the session lock.
            _reserve_direct_authorization(persisted_state)

            scope_mismatch = presented != tuple(scope["argv"])

            # IMPORTANT:
            # Do not raise on scope_mismatch inside this block.
            # locked_state() must persist the one-use marker first.

    except Exception as exc:
        raise MerchantRuntimeHandoffStageError(
            "RESERVE_AUTHORIZATION",
            exc,
        ) from exc

    if scope_mismatch:
        raise MerchantRuntimeHandoffStageError(
            "RESERVE_AUTHORIZATION",
            MerchantRuntimeHandoffError(
                "Runtime apply does not match the user-authorized scope"
            ),
        )

    if scope is None:
        raise MerchantRuntimeHandoffStageError(
            "RESERVE_AUTHORIZATION",
            MerchantRuntimeHandoffError(
                "Merchant runtime scope unavailable"
            ),
        )

    # At this point locked_state() has exited normally.
    # The one-use reservation has been persisted.
    # Issuance failure can no longer restore the spent authorization.
    try:
        authorization = issue_runtime_apply_authorization(
            scope["confirmation"],
            dispatch_receipt,
        )
    except Exception as exc:
        raise MerchantRuntimeHandoffStageError(
            "ISSUE_AUTHORIZATION",
            exc,
        ) from exc

    try:
        return _invoke_authorized_apply(
            (
                *scope["argv"],
                "--execute",
            ),
            authorization,
            write_command_factory=write_command_factory,
        )
    except Exception as exc:
        raise MerchantRuntimeHandoffStageError(
            "CLI_INVOKE", exc
        ) from exc

def invoke_trusted_merchant_session_apply(
    session_id: str,
    arguments: Sequence[str],
    *,
    write_command_factory: WriteCommandFactory | None = None,
) -> int:
    """Select the apply path from persisted owner state, never agent input.

    This is an orchestration entrypoint, not a CLI command. Each selected
    authorization path still performs its own full validation and one-use
    reservation. Release the owner lock before invoking either handler.
    """
    if not isinstance(session_id, str) or not session_id.strip():
        raise MerchantRuntimeHandoffStageError("SESSION_ID")

    try:
        with locked_state(session_id) as owner_state:
            if owner_state is None:
                raise MerchantRuntimeHandoffError(
                    "Merchant handoff owner state unavailable"
                )
            direct_mode = owner_state.get("merchant_scope") is not None
    except Exception as exc:
        raise MerchantRuntimeHandoffStageError(
            "SELECT_AUTHORIZATION", exc
        ) from exc

    if direct_mode:
        return invoke_authorized_scope_apply(
            session_id,
            arguments,
            write_command_factory=write_command_factory,
        )

    raise MerchantRuntimeHandoffStageError(
        "SELECT_AUTHORIZATION",
        MerchantRuntimeHandoffError(
            "Direct Merchant scope is required; "
            "legacy confirmation/apply fallback is disabled"
        ),
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

    if (
        state.get(MERCHANT_CONFIRMATION_MODE_FIELD, MODE_MANUAL)
        not in MERCHANT_CONFIRMATION_MODES
    ):
        raise MerchantRuntimeHandoffError(
            "Trusted run state carries an unknown confirmation mode"
        )

    return state


def _confirmation_mode(state: Mapping[str, Any]) -> str:
    """Return how this run was confirmed; an absent field means MANUAL."""

    return str(
        state.get(MERCHANT_CONFIRMATION_MODE_FIELD) or MODE_MANUAL
    )


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
