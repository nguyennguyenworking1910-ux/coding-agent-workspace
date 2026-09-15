#!/usr/bin/env python3
"""Session-scoped Merchant confirmation preference and proposal receipt.

`/merchant-confirmation off` is a **local-development convenience only**. It
disables manual confirmation-token copy/paste and nothing else. Proposal
binding, payload hashing, expected-version checking, policy validation,
one-use authorization, and atomic persistence all remain exactly as they are
in MANUAL mode: the stored receipt carries the same redacted confirmation
metadata a pasted token would have carried, and the apply still travels the
one trusted path through `intent_gate`, `policy_gate`, and
`merchant_runtime_handoff.invoke_confirmed_merchant_session_apply`.

What this module owns:

- the session confirmation mode (`MANUAL` by default, in every new session);
- at most one validated proposal receipt per session, in state `AVAILABLE`,
  `RESERVED`, or `CONSUMED`.

What it deliberately never stores: the confirmation token, the raw proposal
payload, credentials, connection strings, or any other sensitive Merchant
value. Only the nine redacted confirmation fields, one hashed primary-entity
binding, their receipt state, and two timestamps reach disk.

Persistence mirrors `team_lifecycle.py`: one JSON document per session under
`.claude/runtime/merchant_confirmation/`, a `FileLock` around every
read-modify-write, a unique temporary file, `os.fsync`, and the bounded
Windows `os.replace` retry. Every failure path is fail-closed - an
unreadable, missing, malformed, or unlockable document means MANUAL mode with
no usable receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from filelock import FileLock, Timeout

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runtime_state import (  # noqa: E402
        CLAUDE_DIR,
        MERCHANT_CONFIRMATION_MODE_LOCAL_AUTO,
        MERCHANT_CONFIRMATION_MODE_MANUAL,
        sanitize_session_id,
    )
    from team_lifecycle import replace_with_retry  # noqa: E402
else:
    from .runtime_state import (
        CLAUDE_DIR,
        MERCHANT_CONFIRMATION_MODE_LOCAL_AUTO,
        MERCHANT_CONFIRMATION_MODE_MANUAL,
        sanitize_session_id,
    )
    from .team_lifecycle import replace_with_retry


MODE_MANUAL = MERCHANT_CONFIRMATION_MODE_MANUAL
MODE_LOCAL_AUTO = MERCHANT_CONFIRMATION_MODE_LOCAL_AUTO
MODES = (MODE_MANUAL, MODE_LOCAL_AUTO)

RECEIPT_AVAILABLE = "AVAILABLE"
RECEIPT_RESERVED = "RESERVED"
RECEIPT_CONSUMED = "CONSUMED"
RECEIPT_STATES = (
    RECEIPT_AVAILABLE,
    RECEIPT_RESERVED,
    RECEIPT_CONSUMED,
)

DEFAULT_PREFERENCES_DIR = CLAUDE_DIR / "runtime" / "merchant_confirmation"

# Tests point this at a temporary directory so a test run never touches the
# preference of the live session executing it.
PREFERENCES_DIR_ENV_VAR = "CLAUDE_MERCHANT_PREFERENCES_DIR"

LOCK_TIMEOUT_SECONDS = 10.0

SLASH_COMMAND = "/merchant-confirmation"
TOGGLE_ARGUMENTS = ("on", "off", "status")
USAGE = (
    "Usage: `/merchant-confirmation on` | `/merchant-confirmation off` | "
    "`/merchant-confirmation status`"
)

# Opt-in and host requirements for local auto-confirm. Both are read from the
# environment the hook already loaded; neither value is ever echoed back.
LOCAL_AUTO_ENV_VAR = "MERCHANT_ALLOW_LOCAL_AUTO_CONFIRM"
MERCHANT_HOST_ENV_VAR = "MERCHANT_DB_HOST"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
INTERACTIVE_ENV_VAR = "INTERACTIVE_MODE_ENABLED"
ENTRYPOINT_ENV_VAR = "CLAUDE_CODE_ENTRYPOINT"
NON_INTERACTIVE_ENTRYPOINT_MARKERS = ("print", "sdk", "headless")
NON_INTERACTIVE_ENV_VARS = (
    "CLAUDE_CODE_NON_INTERACTIVE",
    "CLAUDE_NON_INTERACTIVE",
)

# Only these three normalized commands may ever be auto-confirmed. Every other
# allowlisted write - including `merchant activate`, `merchant activate-all`,
# `merchant create`, `contact import`, `document revision-create`,
# `document approve`, `procurement update`, and `integration identifier-set` -
# keeps requiring a manual confirmation token.
LOCAL_AUTO_COMMANDS = frozenset(
    {
        "project create",
        "project update",
        "step update",
    }
)

# LOCAL_AUTO binds the user's apply request to the same primary entity as the
# proposal. Only a SHA-256 digest of the field/value pair reaches disk; the
# raw UUID stays in the proposal output and in the user's request.
LOCAL_AUTO_ENTITY_FIELDS = {
    "project create": "project_id",
    "project update": "project_id",
    "step update": "step_id",
}
ENTITY_BINDING_FIELDS = frozenset({"field", "sha256"})

CONFIRMATION_FIELDS = (
    "contract_version",
    "confirmation_version",
    "operation",
    "command",
    "database_target",
    "expected_version",
    "payload_hash",
    "proposal_hash",
    "confirmation_hash",
)

MERCHANT_MANAGER_AGENT = "merchant-manager"
MERCHANT_APPLY_OPERATION = "merchant_apply"
MERCHANT_PROPOSE_OPERATION = "merchant_propose"
RUNTIME_DATABASE_TARGET = "runtime"

_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_EXPECTED_VERSION_PATTERN = re.compile(
    r"(?i)\bexpected[ _-]?version\b\s*(?:is|are|=|:)?\s*"
    r"(?P<value>\d+|null|none)\b"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TOGGLE_PATTERN = re.compile(
    r"^" + re.escape(SLASH_COMMAND) + r"(?P<rest>[\s\S]*)$"
)


@dataclass(frozen=True)
class PrerequisiteResult:
    """Whether local auto-confirm may be used, and why not when it may not."""

    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class LocalAutoAuthorization:
    """One prompt-time local auto-confirm decision."""

    confirmation: dict[str, Any] | None
    reason: str = ""

    @property
    def authorized(self) -> bool:
        return self.confirmation is not None


@dataclass(frozen=True)
class ReceiptOutcome:
    """Result of a receipt capture, reservation, or consumption attempt."""

    accepted: bool
    reason: str = ""


def _contract() -> Any:
    """Import the Merchant CLI contract lazily, in script or package mode."""

    try:
        from claude.agents.tools.merchant import (  # noqa: PLC0415
            cli_contract,
        )

        return cli_contract
    except ModuleNotFoundError:
        merchant_tools_dir = CLAUDE_DIR / "agents" / "tools" / "merchant"

        if str(merchant_tools_dir) not in sys.path:
            sys.path.insert(0, str(merchant_tools_dir))

        import cli_contract  # type: ignore  # noqa: PLC0415

        return cli_contract


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def preferences_dir() -> Path:
    """Directory holding the per-session preference documents."""

    override = os.environ.get(PREFERENCES_DIR_ENV_VAR)

    return Path(override) if override else DEFAULT_PREFERENCES_DIR


def preferences_path(session_id: Any) -> Path:
    return preferences_dir() / f"{sanitize_session_id(session_id)}.json"


def preferences_lock_path(session_id: Any) -> Path:
    return preferences_dir() / f"{sanitize_session_id(session_id)}.json.lock"


def valid_session_id(session_id: Any) -> bool:
    """True when the harness supplied a session id state can be scoped to."""

    text = str(session_id or "").strip()

    return bool(text) and sanitize_session_id(text) != "unknown-session"


def new_preferences(session_id: Any) -> dict[str, Any]:
    """Build the default document: MANUAL mode, no receipt."""

    return {
        "session_id": sanitize_session_id(session_id),
        "mode": MODE_MANUAL,
        "updated_at": _now(),
        "receipt": None,
    }


def load_preferences(session_id: Any) -> dict[str, Any] | None:
    """Read the document, or None when this session has never set one.

    A corrupt or unreadable document is treated as absent, which means MANUAL
    mode with no receipt.
    """

    path = preferences_path(session_id)

    try:
        with path.open("r", encoding="utf-8") as document:
            loaded = json.load(document)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(loaded, dict) or loaded.get("mode") not in MODES:
        return None

    return loaded


def save_preferences(session_id: Any, document: dict[str, Any]) -> None:
    """Write the document atomically, the way `team_lifecycle` does."""

    path = preferences_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    # A unique name in the destination directory: a fixed scratch name lets a
    # retry or a second writer collide, and os.replace is only atomic within
    # one filesystem.
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    replaced = False

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())

        replace_with_retry(temporary, path)
        replaced = True
    finally:
        if not replaced:
            # Never mask the failure that brought us here.
            try:
                temporary.unlink()
            except OSError:
                pass


@contextmanager
def locked_preferences(
    session_id: Any,
    *,
    create: bool = False,
) -> Iterator[dict[str, Any] | None]:
    """Yield the document under an exclusive lock and persist any mutation.

    Yields None when there is nothing to work with - no document and
    ``create`` is False, an invalid session id, or a lock timeout. Callers
    treat None as "no usable preference", which is MANUAL with no receipt.

    A failure of the final atomic write propagates instead of being converted
    into a second yield. The previous document survives such a failure
    untouched, and each mutating caller turns the error into an explicit
    refusal.
    """

    if not valid_session_id(session_id):
        yield None
        return

    try:
        preferences_dir().mkdir(parents=True, exist_ok=True)
        lock = FileLock(
            str(preferences_lock_path(session_id)),
            timeout=LOCK_TIMEOUT_SECONDS,
        )
        lock.acquire(timeout=LOCK_TIMEOUT_SECONDS)
    except (Timeout, OSError):
        yield None
        return

    try:
        document = load_preferences(session_id)

        if document is None:
            if not create:
                yield None
                return

            document = new_preferences(session_id)

        yield document

        document["updated_at"] = _now()
        save_preferences(session_id, document)
    finally:
        lock.release()


def clear_preferences(session_id: Any) -> bool:
    """Remove the confirmation preference and proposal receipt.

    Called from the SessionEnd hook: a new session must start in MANUAL mode
    with no inherited receipt.
    """

    if not valid_session_id(session_id):
        return False

    try:
        preferences_dir().mkdir(parents=True, exist_ok=True)
        lock = FileLock(
            str(preferences_lock_path(session_id)),
            timeout=LOCK_TIMEOUT_SECONDS,
        )

        with lock:
            try:
                preferences_path(session_id).unlink()
            except FileNotFoundError:
                return False

            return True
    except (Timeout, OSError):
        # Leave the document untouched when exclusive cleanup cannot be
        # established. A later SessionEnd or manual-mode toggle can retry.
        return False


def current_mode(session_id: Any) -> str:
    """Return the session confirmation mode, defaulting to MANUAL."""

    document = load_preferences(session_id)

    if document is None:
        return MODE_MANUAL

    mode = document.get("mode")

    return mode if mode in MODES else MODE_MANUAL


def receipt_state(session_id: Any) -> str | None:
    """Return the stored receipt state, or None when there is no receipt."""

    document = load_preferences(session_id)

    if document is None:
        return None

    receipt = document.get("receipt")

    if not isinstance(receipt, dict):
        return None

    state = receipt.get("state")

    return state if state in RECEIPT_STATES else None


def available_confirmation(session_id: Any) -> dict[str, Any] | None:
    """Return the confirmation metadata of an unspent, valid receipt."""

    return _receipt_confirmation(
        load_preferences(session_id),
        RECEIPT_AVAILABLE,
    )


def _receipt_confirmation(
    document: Any,
    required_state: str,
) -> dict[str, Any] | None:
    validated = _validated_receipt(document, required_state)

    return None if validated is None else validated[0]


def _validated_receipt(
    document: Any,
    required_state: str,
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Return valid confirmation and entity binding for one receipt state."""

    if not isinstance(document, dict):
        return None

    receipt = document.get("receipt")

    if not isinstance(receipt, dict):
        return None

    if receipt.get("state") != required_state:
        return None

    confirmation = validate_confirmation_metadata(receipt.get("confirmation"))

    if confirmation is None:
        return None

    entity_binding = _validate_entity_binding(
        receipt.get("entity_binding"),
        confirmation["command"],
    )

    if entity_binding is None:
        return None

    return confirmation, entity_binding


def check_local_auto_prerequisites(
    session_id: Any,
    env: Mapping[str, str] | None = None,
) -> PrerequisiteResult:
    """Decide whether this machine and session may use local auto-confirm.

    Every condition is required and a missing value denies. No environment
    value is copied into the returned reason.
    """

    environment = os.environ if env is None else env

    if environment.get(LOCAL_AUTO_ENV_VAR) != "1":
        return PrerequisiteResult(
            False,
            f"{LOCAL_AUTO_ENV_VAR}=1 is not set for this environment",
        )

    host = str(environment.get(MERCHANT_HOST_ENV_VAR) or "").strip().lower()

    if host not in LOOPBACK_HOSTS:
        return PrerequisiteResult(
            False,
            "the configured Merchant host is not a loopback address "
            "(127.0.0.1 or localhost)",
        )

    if not _is_interactive(environment):
        return PrerequisiteResult(
            False,
            "Claude Code is not running interactively",
        )

    if not valid_session_id(session_id):
        return PrerequisiteResult(False, "no valid session id is present")

    return PrerequisiteResult(True)


def _is_interactive(environment: Mapping[str, str]) -> bool:
    for variable in NON_INTERACTIVE_ENV_VARS:
        if str(environment.get(variable) or "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            return False

    entrypoint = str(environment.get(ENTRYPOINT_ENV_VAR) or "").strip().lower()

    if any(
        marker in entrypoint
        for marker in NON_INTERACTIVE_ENTRYPOINT_MARKERS
    ):
        return False

    return environment.get(INTERACTIVE_ENV_VAR) == "1"


def parse_toggle_command(prompt: Any) -> tuple[bool, str | None]:
    """Split a `/merchant-confirmation` prompt into its single argument.

    Returns ``(False, None)`` when the prompt is not this command at all,
    ``(True, None)`` when it is this command with malformed arguments, and
    ``(True, argument)`` for exactly one recognized argument.
    """

    if not isinstance(prompt, str):
        return False, None

    match = _TOGGLE_PATTERN.match(prompt.strip())

    if match is None:
        return False, None

    rest = match.group("rest")

    # `/merchant-confirmations on` must not read as this command.
    if rest and not rest[0].isspace():
        return False, None

    arguments = rest.split()

    if len(arguments) != 1:
        return True, None

    argument = arguments[0].strip().lower()

    if argument not in TOGGLE_ARGUMENTS:
        return True, None

    return True, argument


def handle_toggle_command(
    prompt: Any,
    session_id: Any,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Apply one `/merchant-confirmation` command and report the outcome.

    Returns the message to show the user, or None when the prompt is not this
    command. This never classifies intent, never creates or dispatches a
    teammate, and never touches Merchant business data.
    """

    is_command, argument = parse_toggle_command(prompt)

    if not is_command:
        return None

    if argument is None:
        return (
            "Merchant confirmation toggle rejected: malformed arguments. "
            f"{USAGE}. The mode is unchanged and nothing was dispatched."
        )

    if argument == "status":
        return _status_message(session_id)

    if argument == "on":
        return _enable_manual(session_id)

    return _enable_local_auto(session_id, env)


def _status_message(session_id: Any) -> str:
    mode = current_mode(session_id)
    state = receipt_state(session_id)
    confirmation = available_confirmation(session_id)

    if confirmation is None:
        receipt_summary = (
            "no unspent proposal receipt"
            if state is None
            else f"no unspent proposal receipt (last receipt {state})"
        )
    else:
        receipt_summary = (
            "one unspent proposal receipt for "
            f"`{confirmation['command']}` on runtime, expected_version "
            f"{confirmation['expected_version']}"
        )

    return (
        f"Merchant confirmation mode: {mode}. Proposal receipt: "
        f"{receipt_summary}. Local auto-confirm never disables proposal "
        "binding, payload hashing, expected-version checking, policy "
        "validation, or one-use authorization. Nothing was dispatched."
    )


def _enable_manual(session_id: Any) -> str:
    if not valid_session_id(session_id):
        # MANUAL is the default, so there is nothing to persist or clear.
        return (
            f"Merchant confirmation mode: {MODE_MANUAL}. Manual "
            "confirmation-token entry is required. Nothing was dispatched."
        )

    try:
        with locked_preferences(session_id, create=True) as document:
            if document is None:
                return _lock_failure_message()

            document["mode"] = MODE_MANUAL
            # A manual session must not keep an auto-confirm receipt around.
            document["receipt"] = None
    except OSError:
        return _persist_failure_message()

    return (
        f"Merchant confirmation mode: {MODE_MANUAL}. Manual "
        "confirmation-token entry is required: run the proposal, then "
        "`/solve --merchant-confirmation <TOKEN> <exact apply request>`. Any "
        "stored proposal receipt was discarded. Nothing was dispatched."
    )


def _enable_local_auto(
    session_id: Any,
    env: Mapping[str, str] | None,
) -> str:
    prerequisite = check_local_auto_prerequisites(session_id, env)

    if not prerequisite.allowed:
        return (
            f"Merchant confirmation toggle denied: {prerequisite.reason}. "
            f"The session remains in {MODE_MANUAL} mode and nothing was "
            "dispatched."
        )

    try:
        with locked_preferences(session_id, create=True) as document:
            if document is None:
                return _lock_failure_message()

            document["mode"] = MODE_LOCAL_AUTO
            document["receipt"] = None
    except OSError:
        return _persist_failure_message()

    return (
        f"Merchant confirmation mode: {MODE_LOCAL_AUTO} (local development "
        "only). Manual confirmation-token entry is disabled for "
        f"{', '.join(sorted(LOCAL_AUTO_COMMANDS))} on the loopback runtime "
        "target. Proposal binding, payload hashing, expected-version "
        "checking, policy validation, one-use authorization, and the exact "
        "apply request all still apply. Every other write command still "
        "requires the manual token. Nothing was dispatched."
    )


def _lock_failure_message() -> str:
    return (
        "Merchant confirmation toggle rejected: the session preference could "
        f"not be locked. The session remains in {MODE_MANUAL} mode and "
        "nothing was dispatched."
    )


def _persist_failure_message() -> str:
    return (
        "Merchant confirmation toggle rejected: the session preference could "
        f"not be persisted. The session remains in {MODE_MANUAL} mode and "
        "nothing was dispatched."
    )


def _receipt_persist_failure() -> ReceiptOutcome:
    return ReceiptOutcome(
        False,
        "the session confirmation state could not be persisted",
    )


def validate_confirmation_metadata(
    confirmation: Any,
) -> dict[str, Any] | None:
    """Return canonical confirmation metadata, or None when it is unusable.

    Validation is delegated to the CLI contract rather than reimplemented: the
    mapping is re-encoded into its canonical token form and parsed back, so the
    nine fields, both versions, the runtime target, the hash shapes, and the
    confirmation-hash binding are checked by exactly the code that checks a
    pasted token.
    """

    if not isinstance(confirmation, Mapping):
        return None

    if set(confirmation) != set(CONFIRMATION_FIELDS):
        return None

    contract = _contract()

    try:
        envelope = contract.MerchantConfirmationEnvelope(
            **{key: confirmation[key] for key in CONFIRMATION_FIELDS}
        )

        return contract.parse_confirmation_token(
            envelope.to_token()
        ).to_dict()
    except Exception:  # noqa: BLE001 - any contract error fails closed
        return None


def validate_proposal_result(result: Any) -> dict[str, Any] | None:
    """Return the confirmation metadata of a trustworthy runtime proposal.

    ``result`` is the JSON object a successful ``--propose`` invocation of the
    registered Merchant CLI printed. Every field below is required, and the
    confirmation token is parsed only to prove that it matches the returned
    confirmation metadata. The token is never returned or stored.
    """

    if not isinstance(result, Mapping):
        return None

    contract = _contract()

    if result.get("success") is not True:
        return None

    if result.get("mode") != "PROPOSE":
        return None

    if result.get("database") != RUNTIME_DATABASE_TARGET:
        return None

    if (
        isinstance(result.get("contract_version"), bool)
        or result.get("contract_version") != contract.CONTRACT_VERSION
    ):
        return None

    if result.get("requires_confirmation") is not True:
        return None

    try:
        command = contract.normalize_command(result.get("command"))
    except Exception:  # noqa: BLE001 - malformed command fails closed
        return None

    if command not in contract.WRITE_COMMANDS:
        return None

    confirmation = validate_confirmation_metadata(result.get("confirmation"))

    if confirmation is None:
        return None

    token = result.get("confirmation_token")

    if not isinstance(token, str) or not token.strip():
        return None

    try:
        parsed = contract.parse_confirmation_token(token).to_dict()
    except Exception:  # noqa: BLE001 - malformed token fails closed
        return None

    if parsed != confirmation:
        return None

    if confirmation["command"] != command:
        return None

    if confirmation["database_target"] != RUNTIME_DATABASE_TARGET:
        return None

    if confirmation["proposal_hash"] != result.get("proposal_hash"):
        return None

    if not _redaction_is_consistent(contract, command, result.get("payload")):
        return None

    return confirmation


def _redaction_is_consistent(
    contract: Any,
    command: str,
    payload: Any,
) -> bool:
    """Reject a payload that is not redacted the way the CLI redacts it.

    The CLI has already replaced every sensitive value, so re-redacting a
    genuine proposal payload is a no-op. A hand-written or partially redacted
    payload changes under the same transformation and is refused.
    """

    if not isinstance(payload, Mapping):
        return False

    try:
        redacted = contract.redact_payload(
            dict(payload),
            extra_sensitive_fields=tuple(
                contract.COMMAND_SENSITIVE_FIELDS.get(command, ())
            ),
        )

        return redacted == contract.to_json_value(dict(payload))
    except Exception:  # noqa: BLE001 - unrenderable payload fails closed
        return False


def _canonical_uuid(value: Any) -> str | None:
    if isinstance(value, bool):
        return None

    try:
        return str(uuid.UUID(str(value).strip()))
    except (AttributeError, TypeError, ValueError):
        return None


def _entity_binding_digest(field: str, identifier: str) -> str:
    canonical = f"{field}:{identifier}".encode("ascii")

    return hashlib.sha256(canonical).hexdigest()


def _proposal_entity_binding(
    result: Any,
    confirmation: Mapping[str, Any],
) -> dict[str, str] | None:
    """Derive a non-reversible primary-entity binding from one proposal."""

    command = confirmation.get("command")
    field = LOCAL_AUTO_ENTITY_FIELDS.get(str(command))
    payload = result.get("payload") if isinstance(result, Mapping) else None

    if field is None or not isinstance(payload, Mapping):
        return None

    identifier = _canonical_uuid(payload.get(field))

    if identifier is None:
        return None

    return {
        "field": field,
        "sha256": _entity_binding_digest(field, identifier),
    }


def _validate_entity_binding(
    binding: Any,
    command: Any,
) -> dict[str, str] | None:
    """Validate the minimal entity binding stored beside a receipt."""

    if not isinstance(binding, Mapping):
        return None

    if set(binding) != ENTITY_BINDING_FIELDS:
        return None

    expected_field = LOCAL_AUTO_ENTITY_FIELDS.get(str(command))
    field = binding.get("field")
    digest = binding.get("sha256")

    if field != expected_field:
        return None

    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        return None

    return {"field": field, "sha256": digest}


def capture_proposal_receipt(
    session_id: Any,
    result: Any,
) -> ReceiptOutcome:
    """Store one validated proposal receipt for a LOCAL_AUTO session.

    Only the nine confirmation fields and a hashed primary-entity binding are
    persisted. Any older receipt for the session is replaced, so a newer
    proposal always supersedes an earlier one and no stale receipt can outlive
    it.
    """

    confirmation = validate_proposal_result(result)

    if confirmation is None:
        return ReceiptOutcome(
            False,
            "the proposal result is not a validated runtime proposal",
        )

    entity_binding = _proposal_entity_binding(result, confirmation)

    if entity_binding is None:
        return ReceiptOutcome(
            False,
            "the proposal has no valid primary-entity binding",
        )

    try:
        with locked_preferences(session_id) as document:
            if document is None:
                return ReceiptOutcome(
                    False,
                    "no lockable session confirmation preference exists",
                )

            if document.get("mode") != MODE_LOCAL_AUTO:
                return ReceiptOutcome(
                    False,
                    "the session is not in LOCAL_AUTO mode",
                )

            document["receipt"] = {
                "state": RECEIPT_AVAILABLE,
                "captured_at": _now(),
                "confirmation": confirmation,
                "entity_binding": entity_binding,
            }
    except OSError:
        return _receipt_persist_failure()

    return ReceiptOutcome(True)


def reserve_receipt(
    session_id: Any,
    confirmation_hash: Any,
) -> ReceiptOutcome:
    """Atomically move the receipt from AVAILABLE to RESERVED.

    Called once, from the policy gate, immediately before an accepted apply
    dispatch. The file lock plus the AVAILABLE precondition mean that at most
    one concurrent attempt can reserve a receipt.
    """

    if not isinstance(confirmation_hash, str) or not confirmation_hash:
        return ReceiptOutcome(False, "no confirmation hash was supplied")

    try:
        with locked_preferences(session_id) as document:
            if document is None:
                return ReceiptOutcome(
                    False,
                    "no lockable session confirmation preference exists",
                )

            if document.get("mode") != MODE_LOCAL_AUTO:
                return ReceiptOutcome(
                    False,
                    "the session is not in LOCAL_AUTO mode",
                )

            receipt = document.get("receipt")

            if not isinstance(receipt, dict):
                return ReceiptOutcome(False, "no proposal receipt exists")

            state = receipt.get("state")

            if state != RECEIPT_AVAILABLE:
                return ReceiptOutcome(
                    False,
                    f"the proposal receipt is already {state}",
                )

            confirmation = validate_confirmation_metadata(
                receipt.get("confirmation")
            )

            if confirmation is None:
                return ReceiptOutcome(
                    False,
                    "the stored confirmation metadata is malformed",
                )

            if _validate_entity_binding(
                receipt.get("entity_binding"),
                confirmation["command"],
            ) is None:
                return ReceiptOutcome(
                    False,
                    "the stored primary-entity binding is malformed",
                )

            if confirmation["confirmation_hash"] != confirmation_hash:
                return ReceiptOutcome(
                    False,
                    "the proposal receipt does not match this confirmation",
                )

            receipt["state"] = RECEIPT_RESERVED
    except OSError:
        return _receipt_persist_failure()

    return ReceiptOutcome(True)


def consume_receipt(
    session_id: Any,
    confirmation_hash: Any,
) -> ReceiptOutcome:
    """Spend the reserved receipt before the repository adapter can run.

    Consumption happens before dispatch, so success, mismatch, handler
    failure, timeout, crash, and any uncertain outcome all leave the receipt
    CONSUMED. A receipt that was never reserved is also consumed, and the
    attempt is still refused: reaching consumption without the policy gate
    means the dispatch did not travel the trusted path.
    """

    if not isinstance(confirmation_hash, str) or not confirmation_hash:
        return ReceiptOutcome(False, "no confirmation hash was supplied")

    try:
        with locked_preferences(session_id) as document:
            if document is None:
                return ReceiptOutcome(
                    False,
                    "no lockable session confirmation preference exists",
                )

            receipt = document.get("receipt")

            if not isinstance(receipt, dict):
                return ReceiptOutcome(False, "no proposal receipt exists")

            state = receipt.get("state")
            confirmation = validate_confirmation_metadata(
                receipt.get("confirmation")
            )

            if (
                confirmation is None
                or confirmation["confirmation_hash"] != confirmation_hash
            ):
                return ReceiptOutcome(
                    False,
                    "the proposal receipt does not match this confirmation",
                )

            if _validate_entity_binding(
                receipt.get("entity_binding"),
                confirmation["command"],
            ) is None:
                return ReceiptOutcome(
                    False,
                    "the stored primary-entity binding is malformed",
                )

            if state not in (RECEIPT_AVAILABLE, RECEIPT_RESERVED):
                return ReceiptOutcome(
                    False,
                    f"the proposal receipt is already {state}",
                )

            receipt["state"] = RECEIPT_CONSUMED

            if state != RECEIPT_RESERVED:
                return ReceiptOutcome(
                    False,
                    "the proposal receipt was not reserved before dispatch",
                )
    except OSError:
        return _receipt_persist_failure()

    return ReceiptOutcome(True)


def authorize_local_auto_apply(
    session_id: Any,
    request: Any,
    envelope: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
) -> LocalAutoAuthorization:
    """Decide whether an apply request may run without a pasted token.

    This is the prompt-time half of the check. It authorizes the confirmation
    metadata of exactly one unspent receipt, and only when the request itself
    still names the operation: the command and expected version are read from
    the request text and compared with the receipt. Raw payload fields are
    never reconstructed from the receipt - the receipt holds hashes only, and
    the payload the apply finally builds is bound by the existing proposal,
    payload, and confirmation hashes in the policy gate and the CLI contract.
    """

    if not valid_session_id(session_id):
        return LocalAutoAuthorization(
            None,
            "no valid session id is present",
        )

    if current_mode(session_id) != MODE_LOCAL_AUTO:
        return LocalAutoAuthorization(
            None,
            "the session is in MANUAL confirmation mode",
        )

    prerequisite = check_local_auto_prerequisites(session_id, env)

    if not prerequisite.allowed:
        return LocalAutoAuthorization(None, prerequisite.reason)

    operations = [
        str(operation) for operation in envelope.get("operations") or []
    ]

    if operations != [MERCHANT_APPLY_OPERATION]:
        return LocalAutoAuthorization(
            None,
            "the envelope is not an exact merchant_apply operation",
        )

    selected_agents = [
        str(agent) for agent in envelope.get("selected_agents") or []
    ]

    if selected_agents != [MERCHANT_MANAGER_AGENT]:
        return LocalAutoAuthorization(
            None,
            "the envelope lacks exclusive merchant-manager authority",
        )

    if envelope.get("risk_level") not in {"external_write", "destructive"}:
        return LocalAutoAuthorization(
            None,
            "the envelope lacks external_write or destructive risk",
        )

    document = load_preferences(session_id)
    receipt = document.get("receipt") if isinstance(document, dict) else None
    state = receipt.get("state") if isinstance(receipt, dict) else None
    validated = _validated_receipt(document, RECEIPT_AVAILABLE)

    if validated is None:
        return LocalAutoAuthorization(
            None,
            "no unspent proposal receipt exists for this session"
            if state is None
            else (
                "the session proposal receipt is malformed"
                if state == RECEIPT_AVAILABLE
                else f"the session proposal receipt is {state}"
            ),
        )

    confirmation, entity_binding = validated

    if confirmation["operation"] != MERCHANT_APPLY_OPERATION:
        return LocalAutoAuthorization(
            None,
            "the proposal receipt is not a merchant_apply confirmation",
        )

    if confirmation["database_target"] != RUNTIME_DATABASE_TARGET:
        return LocalAutoAuthorization(
            None,
            "the proposal receipt does not target runtime",
        )

    if confirmation["command"] not in LOCAL_AUTO_COMMANDS:
        return LocalAutoAuthorization(
            None,
            f"`{confirmation['command']}` is excluded from local "
            "auto-confirm and still requires the manual token",
        )

    return _match_request_to_receipt(
        request,
        confirmation,
        entity_binding,
    )


def _match_request_to_receipt(
    request: Any,
    confirmation: dict[str, Any],
    entity_binding: dict[str, str],
) -> LocalAutoAuthorization:
    text = request if isinstance(request, str) else ""

    requested_command, command_error = requested_command_from_request(text)

    if command_error is not None:
        return LocalAutoAuthorization(None, command_error)

    if requested_command != confirmation["command"]:
        return LocalAutoAuthorization(
            None,
            "the requested command does not match the proposal receipt",
        )

    identifier, identifier_error = requested_entity_identifier_from_request(
        text,
        requested_command,
        entity_binding["field"],
    )

    if identifier_error is not None:
        return LocalAutoAuthorization(None, identifier_error)

    if identifier is None:
        return LocalAutoAuthorization(
            None,
            "the apply request states no valid primary identifier",
        )

    if _entity_binding_digest(entity_binding["field"], identifier) != (
        entity_binding["sha256"]
    ):
        return LocalAutoAuthorization(
            None,
            "the requested primary identifier does not match the proposal "
            "receipt",
        )

    (
        requested_version,
        version_error,
    ) = requested_expected_version_from_request(text)

    if version_error is not None:
        return LocalAutoAuthorization(None, version_error)

    if requested_version != confirmation["expected_version"]:
        return LocalAutoAuthorization(
            None,
            "the requested expected_version does not match the proposal "
            "receipt",
        )

    return LocalAutoAuthorization(dict(confirmation))


def requested_entity_identifier_from_request(
    request: str,
    command: str,
    field: str,
) -> tuple[str | None, str | None]:
    """Read the command's exact primary UUID from an apply request.

    The preferred form is an explicit ``project_id``/``step_id`` label. For
    update commands, the CLI-shaped positional form immediately following the
    command is also accepted. Project creation has no positional project id,
    so its generated ``project_id`` must be labeled explicitly.
    """

    label = r"[ _-]?".join(re.escape(part) for part in field.split("_"))
    labeled = re.compile(
        rf"(?i)\b{label}\b\s*(?:is|=|:)?\s*(?P<value>{_UUID_PATTERN.pattern})"
    )
    values = {
        identifier
        for match in labeled.finditer(request)
        if (identifier := _canonical_uuid(match.group("value"))) is not None
    }

    if command in {"project update", "step update"}:
        command_pattern = r"\s+".join(
            re.escape(part) for part in command.split()
        )
        positional = re.compile(
            rf"(?i)\b{command_pattern}\b\s+(?P<value>{_UUID_PATTERN.pattern})"
        )
        values.update(
            identifier
            for match in positional.finditer(request)
            if (
                identifier := _canonical_uuid(match.group("value"))
            )
            is not None
        )

    if not values:
        return None, (
            f"the apply request does not state an exact {field}"
        )

    if len(values) > 1:
        return None, (
            f"the apply request states more than one {field}"
        )

    return values.pop(), None


def requested_command_from_request(
    request: str,
) -> tuple[str | None, str | None]:
    """Read exactly one normalized write command out of the request text.

    A vague request such as "Apply the proposal" names no command and is
    refused here, which is what keeps LOCAL_AUTO from applying something the
    user did not restate.
    """

    contract = _contract()
    matched = set()

    for command in contract.WRITE_COMMANDS:
        pattern = re.compile(
            r"(?i)\b" + r"\s+".join(
                re.escape(word) for word in command.split()
            ) + r"\b"
        )

        if pattern.search(request):
            matched.add(command)

    # "merchant activate-all" contains "merchant activate"; the longer
    # command is the one the request actually names.
    if "merchant activate-all" in matched:
        matched.discard("merchant activate")

    if not matched:
        return None, (
            "the apply request does not restate an exact allowlisted "
            "Merchant command"
        )

    if len(matched) > 1:
        return None, (
            "the apply request names more than one Merchant command"
        )

    return matched.pop(), None


def requested_expected_version_from_request(
    request: str,
) -> tuple[int | None, str | None]:
    """Read the explicitly stated expected version out of the request text."""

    values = {
        match.group("value").strip().lower()
        for match in _EXPECTED_VERSION_PATTERN.finditer(request)
    }

    if not values:
        return None, (
            "the apply request does not state an exact expected_version"
        )

    if len(values) > 1:
        return None, (
            "the apply request states more than one expected_version"
        )

    value = values.pop()

    if value in ("null", "none"):
        return None, None

    try:
        parsed = int(value)
    except ValueError:  # pragma: no cover - the pattern only matches digits
        return None, "the apply request states an invalid expected_version"

    if parsed <= 0:
        return None, "the apply request states an invalid expected_version"

    return parsed, None
