"""Trusted in-process bridge for one user-scoped Merchant Direct EXECUTE.

This module intentionally has no command-line entry point. The ordinary
Merchant Manager adapter remains read-only for runtime. Controlled
orchestration reserves the persisted, policy-accepted user scope exactly
once before the resulting opaque capability crosses the same-process call
chain. It is never represented as text, a flag, an environment variable,
or JSON.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping, MutableMapping, Sequence
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
from claude.agents.tools.merchant.completeness import (
    validate_write_completeness,
)
from claude.agents.tools.merchant.cli_contract import (
    WRITE_COMMANDS,
    RuntimeWriteDeniedError,
    build_confirmation_envelope,
    issue_runtime_apply_authorization,
    normalize_command,
)
from claude.hooks.runtime_state import (
    locked_state,
)


MERCHANT_EXECUTE_OPERATION = "merchant_execute"
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

_UUID_TOKEN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


MERCHANT_SCOPE_STATE_KEY = "merchant_scope"
# Targets a user may select for one scope. The physical database and role
# for each are pinned by merchant_reserved_execution.DATABASE_IDENTITIES.
DIRECT_DATABASE_TARGETS = frozenset({RUNTIME_DATABASE_TARGET, "test"})
DIRECT_SCOPE_FORBIDDEN_TOKENS = frozenset(
    {"--apply", "--propose", "--execute", "--proposal-hash"}
)


def validate_direct_scope(
    argv: Sequence[str],
    database_target: str = RUNTIME_DATABASE_TARGET,
) -> dict[str, Any]:
    """Validate one exact user-typed Merchant write and derive its scope.

    The scope is the exact argv the user authorized plus the database target
    the user selected with the request (``runtime`` unless the user typed
    ``--merchant-target test``). The argv must name one allowlisted write,
    with no mode, proposal hash or database override, and every entity
    identifier must be an exact UUID. Names are rejected so an ambiguous
    target cannot become authority. The target is bound into the scope hash
    and the confirmation hash, so it cannot change after authorization.
    """

    if database_target not in DIRECT_DATABASE_TARGETS:
        raise MerchantRuntimeHandoffError(
            "Direct Merchant scope database target is not approved"
        )

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

    # Trusted deterministic completeness of the exact payload. The CLI
    # parser requires options to be present; this contract also rejects
    # blank required values. A teammate result is never accepted here.
    completeness = validate_write_completeness(command, payload)

    if not completeness.complete:
        raise MerchantRuntimeHandoffError(
            "Direct Merchant scope is incomplete; missing: "
            + ", ".join(completeness.missing_fields)
        )

    envelope = build_confirmation_envelope(
        command,
        database_target,
        payload,
    )

    return {
        "argv": tokens,
        "command": command,
        "database_target": database_target,
        "scope_hash": _direct_scope_hash(tokens, database_target),
        "confirmation": envelope.to_dict(),
        "confirmation_hash": envelope.confirmation_hash,
        "proposal_hash": envelope.proposal_hash,
        "payload_sha256": _payload_hash(payload),
    }


def _payload_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(canonical).hexdigest()


def completeness_evidence(
    scope: Mapping[str, Any],
    *,
    run_id: Any,
    task_id: Any,
) -> dict[str, Any]:
    """Trusted completeness evidence for one staged request.

    ``scope`` must come from validate_direct_scope, which refuses an
    incomplete payload, so the evidence is always complete and bound to
    the exact command, payload, run and task.
    """

    return {
        "contract": "required_write_fields_v1",
        "command": scope["command"],
        "payload_sha256": scope["payload_sha256"],
        "complete": True,
        "run_id": run_id,
        "task_id": task_id,
    }


def _direct_scope_hash(tokens: Sequence[str], database_target: str) -> str:
    canonical = json.dumps(
        {"argv": list(tokens), "database_target": database_target},
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

    if state.get("operations") != [MERCHANT_EXECUTE_OPERATION]:
        raise MerchantRuntimeHandoffError(
            "Trusted run state is not an exact merchant_execute operation"
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

    recomputed = validate_direct_scope(tokens, scope.get("database_target"))

    if scope.get("scope_hash") != recomputed["scope_hash"]:
        raise MerchantRuntimeHandoffError(
            "User-authorized scope failed its integrity check"
        )

    if dispatch.get("confirmation_hash") != recomputed["confirmation_hash"]:
        raise MerchantRuntimeHandoffError(
            "Policy dispatch does not match the user-authorized scope"
        )

    return recomputed, dict(dispatch)


AUTHORITY_STATE_KEY = "merchant_runtime_authorization"
HANDOFF_STATE_KEY = "merchant_runtime_handoff"
RESERVATION_KINDS = frozenset({"scope", "create"})


def _reserve_direct_authorization(
    state: MutableMapping[str, Any],
    authority: Mapping[str, Any],
) -> None:
    # One-use marker for this dispatch; never cleared once set.
    with _HANDOFF_LOCK:
        if "merchant_runtime_authorization_issued" in state:
            raise MerchantRuntimeHandoffError(
                "Merchant runtime authorization was already issued for this dispatch"
            )

        state["merchant_runtime_authorization_issued"] = True
        # Durable binding of the spent authority to its reservation.
        state[AUTHORITY_STATE_KEY] = dict(authority)


def _reservation_identity(reservation: Any) -> tuple[str, str]:
    if not isinstance(reservation, Mapping):
        raise MerchantRuntimeHandoffError("Execution reservation is required")

    kind = reservation.get("kind")
    key = "execution_attempt_id" if kind == "scope" else "write_id"
    identity = reservation.get(key)

    if kind not in RESERVATION_KINDS or not (
        isinstance(identity, str) and identity.strip()
    ):
        raise MerchantRuntimeHandoffError("Execution reservation is malformed")

    return kind, identity


def _scope_payload(scope: Mapping[str, Any]) -> dict[str, Any]:
    args = build_argument_parser().parse_args(
        ["--database", RUNTIME_DATABASE_TARGET, *scope["argv"]]
    )
    return build_write_payload(args, scope["command"])


def _verify_team_reservation(
    session_id: str,
    *,
    teammate_name: str,
    run_id: Any,
    task_id: str,
    scope: Mapping[str, Any],
    kind: str,
    identity: str,
) -> None:
    """Require the durable team-state reservation for this exact write.

    Trusted orchestration persists the reservation before any authority is
    spent, so every write leaves a footprint that the lifecycle must settle
    from trusted evidence.
    """

    from claude.hooks.team_lifecycle import locked_team_state

    with locked_team_state(session_id) as team:
        record = (team or {}).get("teammates", {}).get(teammate_name)

        if (
            not isinstance(record, dict)
            or not run_id
            or record.get("canonical_name") != teammate_name
            or record.get("status") != "RUNNING"
            or record.get("current_run_id") != run_id
            or record.get("current_task_id") != task_id
            or record.get("authorized_operations")
            != [MERCHANT_EXECUTE_OPERATION]
            or record.get("authorized_selected_agents") != [teammate_name]
            or record.get("result_received") is True
            or "direct_no_write_terminal" in record
            or not str(record.get("trusted_pane_session_id") or "").strip()
        ):
            raise MerchantRuntimeHandoffError(
                "Execution reservation lacks active lifecycle authority"
            )

        if kind == "scope":
            execution = record.get("direct_scope_execution")
            expected = {
                "run_id": run_id,
                "task_id": task_id,
                "command": scope["command"],
                "scope_hash": scope["scope_hash"],
                "confirmation_hash": scope["confirmation_hash"],
                "execution_attempt_id": identity,
                "status": "EXECUTING",
            }
        else:
            from claude.hooks.merchant_direct_write_state import (
                create_payload_hash,
            )

            if scope["command"] != "merchant create":
                raise MerchantRuntimeHandoffError(
                    "Create reservation does not match the user scope"
                )

            execution = (record.get("direct_writes") or {}).get(identity)
            expected = {
                "run_id": run_id,
                "task_id": task_id,
                "command": "merchant create",
                "write_id": identity,
                "payload_hash": create_payload_hash(_scope_payload(scope)),
                "status": "RESERVED",
            }

        if not isinstance(execution, dict) or any(
            execution.get(field) != value for field, value in expected.items()
        ):
            raise MerchantRuntimeHandoffError(
                "Execution reservation does not match the user scope"
            )


def _verify_staged_handoff(
    state: Mapping[str, Any],
    *,
    teammate_name: str,
    task_id: str,
    scope: Mapping[str, Any],
) -> None:
    handoff = state.get(HANDOFF_STATE_KEY)

    if (
        not isinstance(handoff, Mapping)
        or handoff.get("status") != "PENDING"
        or handoff.get("run_id") != state.get("run_id")
        or handoff.get("task_id") != task_id
        or handoff.get("teammate_name") != teammate_name
        or handoff.get("confirmation_hash") != scope["confirmation_hash"]
        or handoff.get("database_target") != scope["database_target"]
    ):
        raise MerchantRuntimeHandoffError(
            "No trusted staged execute request matches this task"
        )

    if handoff.get("completeness") != completeness_evidence(
        scope,
        run_id=state.get("run_id"),
        task_id=task_id,
    ):
        raise MerchantRuntimeHandoffError(
            "Staged request lacks exact trusted completeness evidence"
        )


def reserve_direct_scope_authorization(
    session_id: str,
    arguments: Sequence[str],
    *,
    teammate_name: str,
    task_id: str,
    reservation: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Spend the one-use scope authorization for one reserved write.

    This is the single point where Direct EXECUTE authority is spent. It
    refuses unless trusted orchestration staged the request and persisted a
    team-state reservation bound to the exact owner, teammate, run, task,
    command, payload and execution attempt. The spend is recorded with that
    binding so the reserved executors and the no-write gate can verify it.
    An argument mismatch consumes the authorization before it is rejected.
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
    dispatch_receipt = None

    try:
        if teammate_name != MERCHANT_MANAGER_AGENT or not (
            isinstance(task_id, str) and task_id.strip()
        ):
            raise MerchantRuntimeHandoffError(
                "Execution reservation lacks an exact teammate task"
            )

        kind, identity = _reservation_identity(reservation)

        from claude.hooks.runtime_state import load_state

        snapshot = load_state(session_id)

        if snapshot is None:
            raise MerchantRuntimeHandoffError(
                "No trusted Merchant run state exists for this session"
            )

        expected_scope, _ = _validated_direct_state(snapshot)
        run_id = snapshot["run_id"]

        # Verified before the run-state lock; the two locks never nest.
        _verify_team_reservation(
            session_id,
            teammate_name=teammate_name,
            run_id=run_id,
            task_id=task_id,
            scope=expected_scope,
            kind=kind,
            identity=identity,
        )

        with locked_state(session_id) as persisted_state:
            if persisted_state is None:
                raise MerchantRuntimeHandoffError(
                    "No trusted Merchant run state exists for this session"
                )

            scope, dispatch_receipt = _validated_direct_state(
                persisted_state
            )

            if (
                persisted_state.get("run_id") != run_id
                or scope["scope_hash"] != expected_scope["scope_hash"]
            ):
                raise MerchantRuntimeHandoffError(
                    "Trusted run changed while reserving authority"
                )

            _verify_staged_handoff(
                persisted_state,
                teammate_name=teammate_name,
                task_id=task_id,
                scope=scope,
            )

            # Reserve the one-use authorization under the session lock.
            _reserve_direct_authorization(
                persisted_state,
                {
                    "run_id": run_id,
                    "task_id": task_id,
                    "teammate_name": teammate_name,
                    "command": scope["command"],
                    "database_target": scope["database_target"],
                    "scope_hash": scope["scope_hash"],
                    "confirmation_hash": scope["confirmation_hash"],
                    "reservation_kind": kind,
                    "reservation_id": identity,
                },
            )

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
                "Runtime execute does not match the user-authorized scope"
            ),
        )

    if scope is None or dispatch_receipt is None:
        raise MerchantRuntimeHandoffStageError(
            "RESERVE_AUTHORIZATION",
            MerchantRuntimeHandoffError(
                "Merchant runtime scope unavailable"
            ),
        )

    return scope, dispatch_receipt


def spent_authority_matches(
    session_id: str,
    *,
    teammate_name: str,
    run_id: Any,
    task_id: str,
    reservation_kind: str,
    reservation_id: str,
    database_target: str,
) -> bool:
    """True only if this run's authority was spent for this reservation."""

    from claude.hooks.runtime_state import load_state

    state = load_state(session_id)

    if not isinstance(state, Mapping) or state.get("run_id") != run_id:
        return False

    authority = state.get(AUTHORITY_STATE_KEY)

    return (
        state.get("merchant_runtime_authorization_issued") is True
        and isinstance(authority, Mapping)
        and authority.get("run_id") == run_id
        and authority.get("task_id") == task_id
        and authority.get("teammate_name") == teammate_name
        and authority.get("reservation_kind") == reservation_kind
        and authority.get("reservation_id") == reservation_id
        and authority.get("database_target") == database_target
    )


def invoke_authorized_scope_apply(
    session_id: str,
    arguments: Sequence[str],
    *,
    teammate_name: str,
    task_id: str,
    execution_attempt_id: str,
    write_command_factory: WriteCommandFactory | None = None,
) -> int:
    """Execute one trusted user-authorized write exactly once.

    The caller must already have persisted the EXECUTING team-state
    reservation for ``execution_attempt_id``. Merchant Create is denied by
    the CLI on runtime: it requires the protected reserved executor.
    """

    scope, dispatch_receipt = reserve_direct_scope_authorization(
        session_id,
        arguments,
        teammate_name=teammate_name,
        task_id=task_id,
        reservation={
            "kind": "scope",
            "execution_attempt_id": execution_attempt_id,
        },
    )

    def execution_guard() -> None:
        # Re-checked when the capability is consumed, immediately before
        # the repository mutation.
        from claude.hooks.runtime_state import load_state

        run_id = (load_state(session_id) or {}).get("run_id")

        _verify_team_reservation(
            session_id,
            teammate_name=teammate_name,
            run_id=run_id,
            task_id=task_id,
            scope=scope,
            kind="scope",
            identity=execution_attempt_id,
        )

        if not spent_authority_matches(
            session_id,
            teammate_name=teammate_name,
            run_id=run_id,
            task_id=task_id,
            reservation_kind="scope",
            reservation_id=execution_attempt_id,
            database_target=scope["database_target"],
        ):
            raise MerchantRuntimeHandoffError(
                "Spent authority does not match this reservation"
            )

    # At this point the one-use reservation has been persisted.
    # Issuance failure can no longer restore the spent authorization.
    try:
        authorization = issue_runtime_apply_authorization(
            scope["confirmation"],
            dispatch_receipt,
            execution_guard=execution_guard,
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
