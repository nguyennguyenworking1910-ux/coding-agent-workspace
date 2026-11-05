#!/usr/bin/env python3
"""UserPromptSubmit hook: classify a controlled run, or refuse to start one.

Fires on every prompt but acts only on `/solve` and `/schedule-agent`. For those
it runs the intent parser, writes the run state the other hooks enforce against,
and injects the `INTENT_ENVELOPE_JSON` block the commands require.

Fails closed everywhere. If classification cannot be completed, the prompt is
blocked rather than passed through unclassified — an unclassified `/solve` is a
run with no roster and no budget, which is exactly what the envelope exists to
prevent.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import sys
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from dotenv import load_dotenv

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime_state import (  # noqa: E402
        CLAUDE_DIR,
        configure_utf8_output,
        read_hook_payload,
        locked_state,
        new_state,
        redact_secrets,
        save_state,
    )
    from team_lifecycle import (  # noqa: E402
        load_team_state,
    )
    from intent_envelope_bridge import (
        load_intent_envelope,
        save_intent_envelope,
    )
else:
    from .runtime_state import (
        CLAUDE_DIR,
        configure_utf8_output,
        read_hook_payload,
        locked_state,
        new_state,
        redact_secrets,
        save_state,
    )
    from .team_lifecycle import (
        load_team_state,
    )
    from .intent_envelope_bridge import (
        load_intent_envelope,
        save_intent_envelope,
    )

HOOK_EVENT_NAME = "UserPromptSubmit"

HOOK_EVENT_NAMES = frozenset(
    {
        "UserPromptSubmit",
        "UserPromptExpansion",
    }
)

CONTROLLED_COMMANDS = ("solve", "schedule-agent")

CONFIRM_FLAG = "--confirm"
MERCHANT_CONFIRM_FLAG = "--merchant-confirmation"
MERCHANT_SCOPE_FLAG = "--merchant-scope"
# User-typed, before the scope: `--merchant-target test --merchant-scope [...]`.
# Only the test target can be named; runtime is the default.
MERCHANT_TARGET_FLAG = "--merchant-target"
MERCHANT_TEST_TARGET = "test"

MERCHANT_EXECUTE_OPERATION = "merchant_execute"
MERCHANT_READ_OPERATION = "merchant_read"
LEGACY_MERCHANT_OPERATIONS = frozenset(
    {"merchant_propose", "merchant_apply"}
)


# The trusted fields of a persisted envelope. Only this hook sets them.
TRUSTED_ENVELOPE_FIELDS = (
    "run_id",
    "merchant_scope",
    "merchant_database_target",
    "confirmed",
)

INTENT_CLAIM_FIELD = "intent_claim"

# Expansion follows Submit within milliseconds; the bridge follows Expansion.
INTENT_CLAIM_TTL_SECONDS = 30.0


def prompt_digest(parsed: tuple[Any, ...]) -> str:
    """Bind a claim to the exact parsed controlled prompt."""
    return hashlib.sha256(
        json.dumps(list(parsed), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def claim_matches_run(
    claim: Any,
    state: dict[str, Any],
    envelope: Any,
) -> bool:
    """The claim, the run state and the persisted envelope name one run."""
    run_id = str(state.get("run_id") or "").strip()

    return bool(
        run_id
        and isinstance(claim, dict)
        and isinstance(envelope, dict)
        and claim.get("run_id") == run_id
        and envelope.get("run_id") == run_id
        and claim.get("request_id") == envelope.get("request_id")
        and envelope.get("merchant_scope") == state.get("merchant_scope")
    )


def consume_intent_claim(session_id: Any, digest: str) -> bool:
    """Spend Submit's claim for this exact prompt once; False fails closed."""
    now = time.time()

    with locked_state(session_id) as state:
        if state is None:
            return False

        claim = state.get(INTENT_CLAIM_FIELD)

        if not (
            claim_matches_run(claim, state, load_intent_envelope(session_id))
            and claim.get("issued_by") == "UserPromptSubmit"
            and claim.get("consumed_at") is None
            and claim.get("prompt_sha256") == digest
            and isinstance(claim.get("issued_at"), (int, float))
            and 0 <= now - claim["issued_at"] <= INTENT_CLAIM_TTL_SECONDS
        ):
            return False

        claim["consumed_at"] = now
        return True


def revoke_intent_claim(session_id: Any) -> None:
    with locked_state(session_id) as state:
        if state is not None:
            state.pop(INTENT_CLAIM_FIELD, None)


def split_merchant_scope(request: str) -> tuple[list[str], str]:
    """Extract one JSON argv array from a user-authored request."""
    prefix = MERCHANT_SCOPE_FLAG

    if not (
        request.startswith(prefix + " ")
        or request.startswith(prefix + "\\t")
    ):
        raise ValueError("Missing --merchant-scope argument")

    body = request[len(prefix):].lstrip()

    try:
        argv, end = json.JSONDecoder().raw_decode(body)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid Merchant scope JSON") from exc

    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(token, str) and token for token in argv)
    ):
        raise ValueError(
            "Merchant scope must be a non-empty JSON array of strings"
        )

    remaining = body[end:].strip()

    if not remaining:
        raise ValueError("Merchant scope requires a task description")

    if remaining.startswith(MERCHANT_SCOPE_FLAG):
        raise ValueError("Duplicate Merchant scope")

    return argv, remaining

# A pre-parsed envelope lets a caller (a test harness, a replay, a wrapper that
# already paid for classification) skip the API call. It is only honoured when it
# describes the request actually being submitted.
PREPARSED_ENV_VAR = "CLAUDE_PREPARSED_INTENT_JSON"

_COMMAND_PATTERN = re.compile(
    r"^/(?P<command>" + "|".join(CONTROLLED_COMMANDS) + r")(?P<rest>[\s\S]*)$"
)

PROJECT_DIR = Path(
    os.environ.get(
        "CLAUDE_PROJECT_DIR",
        Path(__file__).resolve().parents[2],
    )
)

load_dotenv(
    dotenv_path=PROJECT_DIR / ".env",
    override=False,
    encoding="utf-8",
)

def parse_prompt(
    prompt: str,
) -> tuple[str, bool, str | None, str] | None:
    """Split a controlled prompt into flags and the exact classified request.

    Returns None when the prompt is not one of the controlled commands, which is
    the common case — the hook then stays silent.
    """
    match = _COMMAND_PATTERN.match(prompt.strip())

    if match is None:
        return None

    rest = match.group("rest")

    # `/solvent something` must not read as `/solve`.
    if rest and not rest[0].isspace():
        return None

    remainder = rest.strip()
    confirmed = False
    merchant_confirmation_token = None

    if remainder == CONFIRM_FLAG:
        confirmed = True
        remainder = ""
    elif remainder.startswith(CONFIRM_FLAG) and remainder[len(CONFIRM_FLAG)].isspace():
        confirmed = True
        remainder = remainder[len(CONFIRM_FLAG) :].strip()

    if remainder == MERCHANT_CONFIRM_FLAG:
        merchant_confirmation_token = ""
        remainder = ""
    elif (
        remainder.startswith(MERCHANT_CONFIRM_FLAG)
        and remainder[len(MERCHANT_CONFIRM_FLAG)].isspace()
    ):
        confirmation_and_request = remainder[
            len(MERCHANT_CONFIRM_FLAG) :
        ].strip()
        confirmation_parts = confirmation_and_request.split(
            None,
            1,
        )
        merchant_confirmation_token = (
            confirmation_parts[0]
            if confirmation_parts
            else ""
        )
        remainder = (
            confirmation_parts[1].strip()
            if len(confirmation_parts) == 2
            else ""
        )

    if confirmed and merchant_confirmation_token is not None:
        raise ValueError(
            f"{CONFIRM_FLAG} and {MERCHANT_CONFIRM_FLAG} cannot be combined"
        )

    if confirmed and remainder.startswith(MERCHANT_CONFIRM_FLAG):
        raise ValueError(
            f"{CONFIRM_FLAG} and {MERCHANT_CONFIRM_FLAG} cannot be combined"
        )

    if (
        merchant_confirmation_token is not None
        and remainder.startswith(CONFIRM_FLAG)
    ):
        raise ValueError(
            f"{CONFIRM_FLAG} and {MERCHANT_CONFIRM_FLAG} cannot be combined"
        )

    return (
        match.group("command"),
        confirmed,
        merchant_confirmation_token,
        remainder,
    )


def block(reason: str) -> dict[str, Any]:
    """Refuse the prompt. `decision: block` is the UserPromptSubmit form."""
    return {
        "decision": "block",
        "reason": reason,
        "systemMessage": reason,
    }


def envelope_to_payload(envelope: Any) -> dict[str, Any]:
    """Serialize an intent envelope without importing the parser module.

    Keeps this hook importable — and testable — on a machine where `openai` and
    `pydantic` are not installed, since only the real parser needs them.
    """
    if dataclasses.is_dataclass(envelope) and not isinstance(envelope, type):
        payload = dataclasses.asdict(envelope)
    elif isinstance(envelope, dict):
        payload = dict(envelope)
    else:
        raise TypeError(f"Unsupported envelope type: {type(envelope)!r}")

    return {
        key: value.value if isinstance(value, Enum) else value
        for key, value in payload.items()
    }


def build_parser() -> Any:
    """Construct the real IntentParser.

    Imported lazily so that a caller supplying a pre-parsed envelope — or a test
    injecting a fake — never pays for the OpenAI and pydantic imports.
    """
    sys.path.insert(0, str(CLAUDE_DIR / "system"))

    from intent_parser import IntentParser  # noqa: PLC0415  (deliberately lazy)

    return IntentParser()


def build_team_state_snapshot(
    session_id: Any,
    selected_agents: list[str],
) -> dict[str, Any] | None:
    """Read session-scoped team state and extract status for selected agents.

    Returns a snapshot showing which canonical teammates already exist for each
    selected agent, or None if team state cannot be read.
    """
    try:
        team_state = load_team_state(session_id)
    except Exception:
        return None

    if team_state is None:
        # A new local session has no state file yet.
        # An unreadable existing file must still fail closed.
        if __package__ in (None, ""):
            from team_lifecycle import team_state_path
        else:
            from .team_lifecycle import team_state_path

        if team_state_path(session_id).exists():
            return None

        return {
            agent_id: {"exists": False}
            for agent_id in selected_agents
        }

    teammates = team_state.get("teammates", {})
    snapshot = {}

    for agent_id in selected_agents:
        for teammate_name, record in teammates.items():
            if record.get("role") == agent_id:
                snapshot[agent_id] = {
                    "canonical_name": teammate_name,
                    "status": record.get("status", "UNKNOWN"),
                    "exists": True,
                }
                break
        else:
            snapshot[agent_id] = {"exists": False}

    return snapshot


def load_preparsed_envelope(request: str, env: dict[str, str]) -> dict[str, Any] | None:
    """Return a pre-parsed envelope for this exact request, if one was supplied.

    Raises ValueError when the variable is present but unusable, so the caller
    fails closed instead of quietly falling back to a fresh API call the operator
    was trying to avoid.
    """
    raw = env.get(PREPARSED_ENV_VAR)

    if not raw or not raw.strip():
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{PREPARSED_ENV_VAR} is not valid JSON: {error}") from error

    if not isinstance(payload, dict):
        raise ValueError(f"{PREPARSED_ENV_VAR} must be a JSON object")

    preparsed_request = payload.get("raw_request")

    if not isinstance(preparsed_request, str):
        raise ValueError(f"{PREPARSED_ENV_VAR} is missing raw_request")

    if preparsed_request.strip() != request.strip():
        raise ValueError(
            f"{PREPARSED_ENV_VAR} was issued for a different request and cannot "
            "authorize this one"
        )

    return payload


def _limits_to_dict(limits: Any) -> dict[str, Any]:
    if limits is None:
        return {}

    if isinstance(limits, dict):
        return dict(limits)

    if dataclasses.is_dataclass(limits) and not isinstance(limits, type):
        return dataclasses.asdict(limits)

    raise ValueError("Envelope limits are missing or malformed")


def confirm_pending_project(
    session_id: Any,
    command: str,
    request: str,
    run_id: str,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]] | None:
    """CP12H.NL3: the user's own "/solve Xác nhận tạo" spends one pending create.

    None: the request is not exactly a confirmation phrase (classify as usual).
    A dict: the hook output refusing or cancelling; nothing is dispatched.
    A tuple: (merchant_scope, envelope) of the trusted pending operation, the
    same authority shape as a typed --merchant-scope. No model classifies it.
    """
    from claude.hooks import merchant_pending_confirmation as pending

    parsed = pending.parse_confirmation(request)

    if parsed is None:
        return None

    if command != "solve":
        return block(
            "A Project confirmation is accepted only as `/solve Xác nhận tạo`. "
            "Nothing was created."
        )

    action, code = parsed
    record, refusal = pending.resolve(session_id, action, code, run_id)

    if refusal is not None:
        return block(refusal)

    operation = record["operation"]

    if action == pending.CANCEL:
        return block(
            f"Cancelled the pending Project create {operation.get('title')!r} "
            f"({record['project_id'][:8]}). Nothing was created."
        )

    try:
        from claude.agents.tools.merchant.project_preview import (
            validate_requested_operation,
        )
        from claude.system.merchant_runtime_handoff import validate_direct_scope

        validate_requested_operation(operation)

        if (
            operation["project_id"] != record["project_id"]
            or operation["database_target"] != record["database_target"]
        ):
            raise ValueError("pending record fields disagree")

        validated = validate_direct_scope(
            operation["argv"], operation["database_target"]
        )
    except Exception:  # noqa: BLE001 - a damaged record never runs
        return block(
            "The pending Project create could not be verified, so it was not "
            "confirmed. Nothing was created. Preview the Project again."
        )

    merchant_scope = {
        "argv": list(validated["argv"]),
        "command": validated["command"],
        "database_target": validated["database_target"],
        "scope_hash": validated["scope_hash"],
    }

    orchestration = json.loads(
        (CLAUDE_DIR / "agents.json").read_text(encoding="utf-8")
    )["orchestration"]
    task_class = orchestration["default_task_class"]

    envelope = {
        "request_id": str(uuid.uuid4()),
        "raw_request": request,
        "task_class": task_class,
        "risk_level": "external_write",
        "confidence": 1.0,
        "complexity_score": 0,
        "score_breakdown": {},
        "domains": ["merchant"],
        "operations": [MERCHANT_EXECUTE_OPERATION],
        "candidate_agents": ["merchant-manager"],
        "selected_agents": ["merchant-manager"],
        "limits": dict(orchestration["task_classes"][task_class]),
        "reasons": [
            "The user confirmed the trusted pending Project create "
            f"{record['project_id']} in their own prompt; the operation comes "
            "from verified preview evidence, not from a model."
        ],
        "requires_clarification": False,
        "requires_confirmation": True,
        "conversational_confirmation": {
            "project_id": record["project_id"],
            "title": operation["title"],
            "merchant_code": operation["merchant_code"],
            "source_run_id": record["source_run_id"],
            "pending_created_at": record["created_at"],
        },
    }

    return merchant_scope, envelope


def run(
    payload: dict[str, Any],
    *,
    parser_factory: Callable[[], Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate one UserPromptSubmit event and return the hook output.

    An empty dict means "say nothing" — the prompt is not ours.
    """
    environment = os.environ if env is None else env
    hook_event_name = str(
        payload.get(
            "hook_event_name"
        )
        or HOOK_EVENT_NAME
    ).strip()

    if (
        hook_event_name
        not in HOOK_EVENT_NAMES
    ):
        hook_event_name = (
            HOOK_EVENT_NAME
        )

    prompt = payload.get("prompt")

    if not isinstance(prompt, str):
        return {}

    # The proposal-confirmation preference switch was removed with the
    # proposal workflow. Reject it explicitly instead of passing it on.
    if re.match(r"^\s*/merchant-confirmation(?:\s|$)", prompt):
        return block(
            "/merchant-confirmation has been removed: Merchant writes use "
            "Direct EXECUTE with /solve --confirm --merchant-scope [...]. "
            "Nothing was changed."
        )

    try:
        parsed = parse_prompt(prompt)
    except ValueError as error:
        return block(
            f"Invalid controlled-command confirmation syntax: {error}. "
            "Nothing was dispatched."
        )

    if parsed is None:
        # CP12H.NL3: a bare "Xác nhận tạo" is never a confirmation; when one
        # is pending, say how to confirm instead of letting the model act.
        if hook_event_name == HOOK_EVENT_NAME:
            try:
                from claude.hooks.merchant_pending_confirmation import (
                    bare_phrase_guidance,
                )

                guidance = bare_phrase_guidance(payload.get("session_id"), prompt.strip())
            except Exception:  # noqa: BLE001 - an ordinary prompt stays ordinary
                guidance = None

            if guidance:
                return block(guidance)

        return {}

    (
        command,
        confirmed,
        merchant_confirmation_token,
        request,
    ) = parsed

    if not request:
        return block(
            f"/{command} needs a request. Resubmit as "
            f"`/{command} <what you want done>`. Nothing was dispatched."
        )

    if redact_secrets(request) != request:
        return block(
            f"/{command} requests must not contain credentials or secrets. "
            "Remove the sensitive value and resubmit. Nothing was dispatched."
        )

    merchant_scope = None
    merchant_target = "runtime"

    if request == MERCHANT_TARGET_FLAG or request.startswith(
        MERCHANT_TARGET_FLAG + " "
    ):
        target, _, request = (
            request[len(MERCHANT_TARGET_FLAG):].lstrip().partition(" ")
        )
        request = request.lstrip()

        if target != MERCHANT_TEST_TARGET or not request.startswith(
            MERCHANT_SCOPE_FLAG + " "
        ):
            return block(
                "--merchant-target accepts only `test` and must be followed "
                "by --merchant-scope [...]. Nothing was dispatched."
            )

        merchant_target = MERCHANT_TEST_TARGET

    if (
        request == MERCHANT_SCOPE_FLAG
        or request.startswith(MERCHANT_SCOPE_FLAG + " ")
        or request.startswith(MERCHANT_SCOPE_FLAG + "\\t")
    ):
        if (
            command != "solve"
            or confirmed is not True
            or merchant_confirmation_token is not None
        ):
            return block(
                "Direct Merchant scope requires /solve --confirm "
                "without proposal confirmation. Nothing was dispatched."
            )

        try:
            from claude.system.merchant_runtime_handoff import (
                validate_direct_scope,
            )

            scope_argv, request = split_merchant_scope(request)
            validated_scope = validate_direct_scope(
                scope_argv,
                merchant_target,
            )

            merchant_scope = {
                "argv": list(validated_scope["argv"]),
                "command": validated_scope["command"],
                "database_target": validated_scope["database_target"],
                "scope_hash": validated_scope["scope_hash"],
            }
        except Exception:
            return block(
                "Direct Merchant scope is invalid or unauthorized. "
                "Nothing was dispatched."
            )

        if redact_secrets(request) != request:
            return block(
                "Merchant scope description contains sensitive information. "
                "Nothing was dispatched."
            )

    session_id = payload.get("session_id")
    digest = prompt_digest(parsed)

    # One owner per prompt. Claude Code fires UserPromptSubmit before the
    # /solve expansion (a blocked Submit stops the command and its dynamic
    # context), so Submit is the only event that classifies and creates the
    # run. Expansion never classifies: it consumes the exact single-use claim
    # Submit issued for this prompt, or blocks.
    if hook_event_name == "UserPromptExpansion":
        if consume_intent_claim(session_id, digest):
            return {}

        return block(
            f"/{command} has no matching UserPromptSubmit classification for "
            "this exact prompt (missing, stale, consumed or inconsistent run "
            "state). Nothing was dispatched. Resubmit the request."
        )

    # A new submission never reuses an earlier run: revoke its claim before
    # classifying, so a failed Submit cannot leave a consumable claim behind.
    revoke_intent_claim(session_id)

    run_id = str(uuid.uuid4())
    conversational = None

    if merchant_scope is None and merchant_confirmation_token is None:
        conversational = confirm_pending_project(
            session_id, command, request, run_id
        )

    if isinstance(conversational, dict):
        return conversational  # refused or cancelled; nothing dispatched

    if conversational is not None:
        merchant_scope, envelope_payload = conversational
        confirmed = True
    else:
        try:
            preparsed = load_preparsed_envelope(request, dict(environment))

            if preparsed is not None:
                envelope_payload = envelope_to_payload(preparsed)
            else:
                factory = parser_factory or build_parser
                envelope_payload = envelope_to_payload(factory().parse(request))

            # Run identity, scope, target and confirmation are set only
            # below, by this hook; a parsed or pre-parsed envelope cannot
            # supply them.
            for trusted_field in TRUSTED_ENVELOPE_FIELDS:
                envelope_payload.pop(trusted_field, None)
        except Exception as error:  # noqa: BLE001 - fail closed on anything
            return block(
                f"Intent classification failed, so /{command} did not run: {error} "
                "No agents were dispatched. Fix the cause and resubmit."
            )

    if envelope_payload.get("requires_clarification"):
        reasons = envelope_payload.get("reasons") or []
        detail = f" Parser notes: {'; '.join(str(r) for r in reasons[:3])}" if reasons else ""

        return block(
            f"/{command} needs a clearer request before it can run: the intent "
            "parser flagged missing information that would change what gets "
            f"done.{detail} Resubmit with the target and expected outcome stated. "
            f"`{CONFIRM_FLAG}` does not substitute for this."
        )

    operations = {
        str(operation)
        for operation in envelope_payload.get("operations") or []
    }
    selected_for_confirmation = [
        str(agent)
        for agent in envelope_payload.get("selected_agents") or []
    ]
    if operations & LEGACY_MERCHANT_OPERATIONS:
        return block(
            "Merchant proposal/apply operations have been removed. "
            "Nothing was dispatched."
        )

    if merchant_scope is not None:
        if (
            operations != {MERCHANT_EXECUTE_OPERATION}
            or selected_for_confirmation != ["merchant-manager"]
            or envelope_payload.get("risk_level")
            not in {"external_write", "destructive"}
        ):
            return block(
                "Direct Merchant scope conflicts with classified intent. "
                "Nothing was dispatched."
            )

    # Proposal confirmation tokens no longer authorize anything. Direct
    # EXECUTE authority is the exact user-typed --merchant-scope.
    if merchant_confirmation_token is not None:
        return block(
            f"{MERCHANT_CONFIRM_FLAG} is no longer supported: Merchant "
            "proposal confirmation has been removed. Resubmit as "
            f"`/solve {CONFIRM_FLAG} {MERCHANT_SCOPE_FLAG} [...] "
            "<description>`. Nothing was dispatched."
        )

    # CP12H.NL3: an unscoped Project create request ("Tạo project mở rạp ...")
    # can only be previewed in this run, so it runs as the read-only preview
    # without --confirm. Strictly a downgrade: creating needs the user's
    # separate "/solve Xác nhận tạo" of the verified preview.
    if (
        merchant_scope is None
        and conversational is None
        and selected_for_confirmation == ["merchant-manager"]
        and operations
        and operations <= {MERCHANT_EXECUTE_OPERATION, MERCHANT_READ_OPERATION}
    ):
        from claude.agents.tools.merchant.project_nl import (
            PROJECT_CREATE,
            interpret_project_request,
        )

        if interpret_project_request(request).kind == PROJECT_CREATE:
            operations = {MERCHANT_READ_OPERATION}
            envelope_payload.update(
                operations=[MERCHANT_READ_OPERATION],
                risk_level="read_only",
                requires_confirmation=False,
            )
            envelope_payload["reasons"] = list(
                envelope_payload.get("reasons") or []
            ) + [
                "Unscoped Project create request runs as the read-only "
                "preview; creating needs the user's separate confirmation."
            ]

    if envelope_payload.get("requires_confirmation") and not confirmed:
        risk_level = envelope_payload.get("risk_level", "unknown")

        return block(
            f"/{command} needs explicit confirmation before running: risk_level is "
            f"{risk_level}. Nothing was dispatched. To authorize it, resubmit as "
            f"`/{command} {CONFIRM_FLAG} {request}`"
        )

    try:
        limits = _limits_to_dict(envelope_payload.get("limits"))
        selected_agents = list(envelope_payload.get("selected_agents") or [])
    except ValueError as error:
        return block(f"/{command} received an unusable envelope: {error}")

    envelope_payload["limits"] = limits
    envelope_payload["confirmed"] = confirmed

    if merchant_scope is not None:
        merchant_scope["run_id"] = run_id
        envelope_payload["merchant_scope"] = dict(merchant_scope)

    # Trusted database target of an unscoped Merchant run: from the user's
    # own words only (P1). A scope carries its own user-typed target.
    merchant_read_target = None

    if merchant_scope is None and operations & {
        MERCHANT_READ_OPERATION,
        MERCHANT_EXECUTE_OPERATION,
    }:
        from claude.agents.tools.merchant.project_nl import (
            requests_test_database,
        )

        merchant_read_target = (
            "test" if requests_test_database(request) else "runtime"
        )

    if merchant_scope is not None or merchant_read_target is not None:
        envelope_payload["merchant_database_target"] = (
            merchant_scope["database_target"]
            if merchant_scope is not None
            else merchant_read_target
        )

    envelope_payload["run_id"] = run_id

    state = new_state(
        request=request,
        task_class=str(envelope_payload.get("task_class", "")),
        risk_level=str(envelope_payload.get("risk_level", "")),
        selected_agents=selected_agents,
        limits=limits,
        confirmed=confirmed,
        operations=[
            str(operation)
            for operation in envelope_payload.get("operations") or []
        ],
        run_id=run_id,
        merchant_scope=merchant_scope,
        merchant_read_target=merchant_read_target,
    )
    state[INTENT_CLAIM_FIELD] = {
        "run_id": run_id,
        "request_id": envelope_payload.get("request_id"),
        "prompt_sha256": digest,
        "issued_by": "UserPromptSubmit",
        "issued_at": time.time(),
        "consumed_at": None,
    }

    # Envelope first, state (carrying the claim) last: the state write is the
    # commit point, and a crash between them leaves run ids that disagree,
    # which Expansion and the bridge refuse.
    save_intent_envelope(session_id, envelope_payload)
    save_state(session_id, state)

    envelope_json = json.dumps(envelope_payload, ensure_ascii=False, indent=2)

    additional_context = (
        "INTENT_ENVELOPE_JSON\n"
        "```json\n"
        f"{envelope_json}\n"
        "```\n"
        "This envelope is the authority for this run. Dispatch only from "
        "selected_agents, stay inside limits, and do not re-classify the "
        "request yourself."
    )

    team_snapshot = build_team_state_snapshot(
        payload.get("session_id"),
        selected_agents,
    )

    if team_snapshot is not None:
        team_snapshot_json = json.dumps(team_snapshot, ensure_ascii=False, indent=2)
        additional_context += (
            "\n\nTEAM_STATE_SNAPSHOT_JSON\n"
            "```json\n"
            f"{team_snapshot_json}\n"
            "```\n"
            "Canonical teammate status for this session's selected_agents. "
            "Use this to determine whether to create or reuse teammates."
        )

    hook_specific_output = {
        "hookEventName": (
            hook_event_name
        ),
    }

    # Older/direct UserPromptSubmit runtimes can still
    # use additionalContext. UserPromptExpansion uses
    # the deterministic /solve dynamic-context bridge.
    if (
        hook_event_name
        != "UserPromptExpansion"
    ):
        hook_specific_output[
            "additionalContext"
        ] = additional_context

    output: dict[str, Any] = {
        "hookSpecificOutput": (
            hook_specific_output
        )
    }

    if conversational is not None:
        # Shown to the user by this hook, not rendered by the model.
        detail = envelope_payload["conversational_confirmation"]
        output["systemMessage"] = (
            f"Confirmed Project create {detail['title']!r} for Merchant "
            f"{detail['merchant_code']} (project_id {detail['project_id']}) on the "
            f"{merchant_scope['database_target']} database. It runs once now."
        )

    return output

def main() -> int:
    configure_utf8_output()

    try:
        payload = read_hook_payload()
    except UnicodeDecodeError:
        # The prompt cannot be read exactly. Refuse it rather than classify
        # a guessed decoding: an envelope must bind the user's exact text.
        print(json.dumps(block(
            "The prompt is not valid UTF-8, so it cannot be classified "
            "exactly. Nothing was dispatched. Resubmit the request."
        ), ensure_ascii=False))
        return 0
    except (json.JSONDecodeError, ValueError):
        # No usable hook input: stay silent rather than block every prompt.
        return 0

    if not isinstance(payload, dict):
        return 0

    try:
        output = run(payload)
    except Exception:  # noqa: BLE001 - hook infrastructure fails closed
        output = block(
            "Controlled request denied because authorization state could not "
            "be persisted safely. No agents were dispatched. Fix the local "
            "hook state directory and resubmit."
        )

    if output:
        print(json.dumps(output, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
