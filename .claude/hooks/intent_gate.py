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
import json
import os
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from dotenv import load_dotenv

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_state import (  # noqa: E402  (path shim must run first)
    CLAUDE_DIR,
    new_state,
    save_state,
)

HOOK_EVENT_NAME = "UserPromptSubmit"

CONTROLLED_COMMANDS = ("solve", "schedule-agent")

CONFIRM_FLAG = "--confirm"

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

def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(
                encoding="utf-8",
                errors="strict",
            )

def parse_prompt(prompt: str) -> tuple[str, bool, str] | None:
    """Split a controlled prompt into (command, confirmed, request).

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

    if remainder == CONFIRM_FLAG:
        confirmed = True
        remainder = ""
    elif remainder.startswith(CONFIRM_FLAG) and remainder[len(CONFIRM_FLAG)].isspace():
        confirmed = True
        remainder = remainder[len(CONFIRM_FLAG) :].strip()

    return match.group("command"), confirmed, remainder


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

    prompt = payload.get("prompt")

    if not isinstance(prompt, str):
        return {}

    parsed = parse_prompt(prompt)

    if parsed is None:
        return {}

    command, confirmed, request = parsed

    if not request:
        return block(
            f"/{command} needs a request. Resubmit as "
            f"`/{command} <what you want done>`. Nothing was dispatched."
        )

    try:
        preparsed = load_preparsed_envelope(request, dict(environment))

        if preparsed is not None:
            envelope_payload = envelope_to_payload(preparsed)
        else:
            factory = parser_factory or build_parser
            envelope_payload = envelope_to_payload(factory().parse(request))
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

    save_state(
        payload.get("session_id"),
        new_state(
            request=request,
            task_class=str(envelope_payload.get("task_class", "")),
            risk_level=str(envelope_payload.get("risk_level", "")),
            selected_agents=selected_agents,
            limits=limits,
            confirmed=confirmed,
        ),
    )

    envelope_json = json.dumps(envelope_payload, ensure_ascii=False, indent=2)

    return {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT_NAME,
            "additionalContext": (
                "INTENT_ENVELOPE_JSON\n"
                "```json\n"
                f"{envelope_json}\n"
                "```\n"
                "This envelope is the authority for this run. Dispatch only from "
                "selected_agents, stay inside limits, and do not re-classify the "
                "request yourself."
            ),
        }
    }


def main() -> int:
    configure_utf8_output()

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # No usable hook input: stay silent rather than block every prompt.
        return 0

    if not isinstance(payload, dict):
        return 0

    output = run(payload)

    if output:
        print(json.dumps(output, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
