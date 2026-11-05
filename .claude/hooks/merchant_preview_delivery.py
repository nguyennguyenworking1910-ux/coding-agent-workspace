"""Trusted database target and lossless delivery of a Project preview.

P1: every ``agent_cli.py`` read by merchant-manager must hit the run's trusted
database target (the user's scope, or the intent gate's reading of the user's
own request). A runtime run cannot read the test database and a test run
cannot fall back to runtime; ``completeness check`` touches no database.

P4: the Project preview's ``requested_operation`` is captured from the CLI's
exact stdout after the call (PostToolUse, verified teammate pane, exact
``agent_cli.py project preview`` invocation) and bound to the run/task. The
teammate's report to the lead must then carry that object exactly once,
after ``MERCHANT_PREVIEW_OPERATION_JSON:``; a truncated, re-encoded,
reconstructed, duplicated or unbacked block never reaches the lead.

Both checks only restrict. The captured operation is preview data with
status NOT_AUTHORIZED; it never grants execution authority.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

PREVIEW_OPERATION_MARKER = "MERCHANT_PREVIEW_OPERATION_JSON:"
EVIDENCE_FIELD = "project_preview_evidence"
PREVIEW_DELIVERY_FAILED = "PREVIEW_DELIVERY_FAILED"
READY = "READY_FOR_CONFIRMATION"
VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"

# CP12H.NL4A: the read-only Project status result, delivered the same way.
STATUS_RESULT_MARKER = "MERCHANT_PROJECT_STATUS_JSON:"
STATUS_EVIDENCE_FIELD = "project_status_evidence"
STATUS_DELIVERY_FAILED = "STATUS_DELIVERY_FAILED"
# Reads that may name the Merchant test database (mirrors agent_cli).
TEST_DATABASE_READS = frozenset({("project", "preview"), ("project", "status")})

MERCHANT_MANAGER_AGENT = "merchant-manager"
AGENT_CLI_SCRIPT = ".claude/agents/tools/merchant/agent_cli.py"
TEST_DATABASE_OPTION = "--test-database"
# Commands that never open a Merchant database.
DATABASE_FREE_COMMANDS = frozenset({("completeness", "check")})

Deny = Callable[[str], dict[str, Any]]


def _agent_cli_arguments(command: Any) -> tuple[str, ...] | None:
    """Arguments of one exact, literal ``agent_cli.py`` invocation."""

    from claude.hooks.policy_gate import exact_merchant_manager_command

    tokens = exact_merchant_manager_command(command)

    if tokens is None:
        return None

    script = tokens[1][2:] if tokens[1].startswith("./") else tokens[1]

    return tokens[2:] if script == AGENT_CLI_SCRIPT else None


def command_target(arguments: tuple[str, ...]) -> str | None:
    """The database an agent_cli.py read opens; None if it opens none."""

    if tuple(arguments[:2]) in DATABASE_FREE_COMMANDS:
        return None

    if tuple(arguments[:2]) in TEST_DATABASE_READS and (
        TEST_DATABASE_OPTION in arguments
    ):
        return "test"

    return "runtime"


def _owner_binding() -> tuple[str, dict[str, Any], str | None] | None:
    """(owner session, teammate record, trusted target) of the live task."""

    binding = _owner_run()

    if binding is None:
        return None

    owner, record, state = binding

    return owner, record, (
        merchant_database_target_of(state) if state is not None else None
    )


def merchant_database_target_of(state: dict[str, Any]) -> str | None:
    from claude.hooks.runtime_state import merchant_database_target

    return merchant_database_target(state)


def _owner_run() -> tuple[str, dict[str, Any], dict[str, Any] | None] | None:
    """(owner session, teammate record, run state of that task or None)."""

    from claude.hooks.runtime_state import load_state
    from claude.hooks.team_lifecycle import find_unique_active_teammate_owner

    owner, record, resolution = find_unique_active_teammate_owner(
        MERCHANT_MANAGER_AGENT
    )

    if resolution != "FOUND" or not owner or not isinstance(record, dict):
        return None

    run_id = record.get("current_run_id")
    state = load_state(owner)

    if not run_id or not record.get("current_task_id"):
        return None

    if not isinstance(state, dict) or state.get("run_id") != run_id:
        return owner, record, None

    return owner, record, state


def _is_merchant_manager(payload: dict[str, Any], *tools: str) -> bool:
    return (
        str(payload.get("agent_type") or "").strip() == MERCHANT_MANAGER_AGENT
        and str(payload.get("tool_name") or "") in tools
    )


def _tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("tool_input")
    return value if isinstance(value, dict) else {}


# --------------------------------------------------------------- P1 (Pre)


def teammate_target_decision(payload: dict[str, Any], deny: Deny) -> dict[str, Any] | None:
    """PreToolUse(Bash): the read's database must be the trusted target."""

    if not _is_merchant_manager(payload, "Bash", "PowerShell"):
        return None

    arguments = _agent_cli_arguments(_tool_input(payload).get("command"))

    if arguments is None:
        return None  # not agent_cli.py; the allowlist gate decides

    target = command_target(arguments)

    if target is None:
        return None

    binding = _owner_binding()
    trusted = binding[2] if binding is not None else None

    if trusted is None:
        if target == "test":
            return deny(
                "Blocked: this read targets the Merchant test database but "
                "the run's trusted database target cannot be verified. "
                "Nothing was read."
            )
        return None

    if target != trusted:
        return deny(
            f"Blocked: this read targets the {target} Merchant database but "
            f"the run's trusted database_target is {trusted!r}. The target "
            "comes from the user's request, not from the assignment or the "
            "teammate. Nothing was read; use the trusted target."
        )

    return None


# --------------------------------------------------------------- P4 (Post)


def _preview_arguments(
    payload: dict[str, Any], action: str = "preview"
) -> tuple[str, ...] | None:
    """Arguments of merchant-manager's exact ``agent_cli.py project <action>``."""

    if not _is_merchant_manager(payload, "Bash"):
        return None

    arguments = _agent_cli_arguments(_tool_input(payload).get("command"))

    if arguments is None or tuple(arguments[:2]) != ("project", action):
        return None

    return arguments


def record_status_evidence(payload: dict[str, Any]) -> bool:
    """PostToolUse(Bash): bind a ``project status`` result to the live task.

    VERIFIED only for the exact CLI JSON of a read-only status result on the
    trusted target, printed in the teammate's verified pane; anything else is
    an UNVERIFIED marker, so its report can only be a delivery failure.
    """

    from claude.hooks.harness_team_identity import verified_teammate_pane
    from claude.hooks.merchant_tool_result_contract import _exact_json_object
    from claude.hooks.team_lifecycle import locked_team_state

    arguments = _preview_arguments(payload, "status")
    binding = _owner_binding() if arguments is not None else None

    if binding is None:
        return False

    owner, record, trusted = binding
    target = command_target(arguments)
    output = _exact_json_object(payload)
    verified = (
        isinstance(output, dict)
        and output.get("mode") == "PROJECT_STATUS"
        and output.get("database_target") == target == trusted
        and output.get("read_only") is True
        and output.get("authorization") is None
        and verified_teammate_pane(owner, MERCHANT_MANAGER_AGENT) is not None
    )

    with locked_team_state(owner) as state:
        current = (
            (state or {}).get("teammates", {}).get(MERCHANT_MANAGER_AGENT)
            if isinstance(state, dict)
            else None
        )

        if (
            not isinstance(current, dict)
            or current.get("current_run_id") != record.get("current_run_id")
            or current.get("current_task_id") != record.get("current_task_id")
        ):
            return False

        current[STATUS_EVIDENCE_FIELD] = {
            "run_id": current["current_run_id"],
            "task_id": current["current_task_id"],
            "status": VERIFIED if verified else UNVERIFIED,
            "database_target": target,
            "result": output if verified else None,
        }

    return verified


def preview_from_tool_response(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The exact, internally consistent preview a verified CLI call printed."""

    from claude.agents.tools.merchant.project_preview import (
        validate_requested_operation,
    )
    from claude.hooks.merchant_tool_result_contract import _exact_json_object

    arguments = _preview_arguments(payload)

    if arguments is None:
        return None

    output = _exact_json_object(payload)
    target = command_target(arguments)

    if (
        not isinstance(output, dict)
        or output.get("mode") != "PROJECT_PREVIEW"
        or output.get("database_target") != target
    ):
        return None

    operation = output.get("requested_operation")

    if operation is not None:
        try:
            validate_requested_operation(operation)
        except ValueError:
            return None

        if operation.get("database_target") != target:
            return None

    if (output.get("outcome") == READY) != (operation is not None):
        return None  # READY needs an operation; only READY may carry one

    return {
        "status": VERIFIED,
        "database_target": target,
        "outcome": output.get("outcome"),
        "requested_operation": operation,
    }


def record_preview_evidence(payload: dict[str, Any]) -> bool:
    """PostToolUse(Bash): bind the preview's verification result to the task.

    A verified preview stores its exact operation. A preview call whose
    output cannot be verified stores an UNVERIFIED marker, so its report can
    only be a non-actionable delivery failure. Returns True when verified.
    """

    from claude.hooks.harness_team_identity import verified_teammate_pane
    from claude.hooks.team_lifecycle import locked_team_state

    if _preview_arguments(payload, "status") is not None:
        return record_status_evidence(payload)

    arguments = _preview_arguments(payload)

    if arguments is None:
        return False

    preview = preview_from_tool_response(payload)
    binding = _owner_binding()

    if binding is None:
        return False

    owner, record, trusted = binding

    if preview is None or trusted != preview["database_target"]:
        preview = {
            "status": UNVERIFIED,
            "database_target": command_target(arguments),
            "outcome": None,
            "requested_operation": None,
        }
    elif verified_teammate_pane(owner, MERCHANT_MANAGER_AGENT) is None:
        preview = dict(preview, status=UNVERIFIED, requested_operation=None)

    with locked_team_state(owner) as state:
        current = (
            (state or {}).get("teammates", {}).get(MERCHANT_MANAGER_AGENT)
            if isinstance(state, dict)
            else None
        )

        if (
            not isinstance(current, dict)
            or current.get("current_run_id") != record.get("current_run_id")
            or current.get("current_task_id") != record.get("current_task_id")
        ):
            return False

        current[EVIDENCE_FIELD] = {
            "run_id": current["current_run_id"],
            "task_id": current["current_task_id"],
            **preview,
        }

    if preview["status"] == VERIFIED and preview["requested_operation"] is not None:
        # CP12H.NL3: the only creator of a pending conversational confirmation.
        from claude.hooks.merchant_pending_confirmation import record_pending

        record_pending(
            owner,
            preview["requested_operation"],
            run_id=record["current_run_id"],
            task_id=record["current_task_id"],
        )

    return preview["status"] == VERIFIED


# --------------------------------------------------------------- P4 (Pre)


def _operation_blocks(message: str, marker: str = PREVIEW_OPERATION_MARKER) -> list[Any]:
    blocks: list[Any] = []
    decoder = json.JSONDecoder()

    for part in message.split(marker)[1:]:
        try:
            value, _ = decoder.raw_decode(part.lstrip())
        except ValueError:
            value = None
        blocks.append(value)

    return blocks


_READY_CLAIM = re.compile(r"ready[\s_-]*for[\s_-]*confirmation", re.IGNORECASE)
# "the outcome is not READY_FOR_CONFIRMATION" states the opposite of a claim.
_NEGATED_READY = re.compile(
    r"\b(?:not|never|no|isn't|không|chưa|khong|chua)\s+(?:\w+\s+){0,2}?"
    r"ready[\s_-]*for[\s_-]*confirmation",
    re.IGNORECASE,
)
# Operation text a teammate could only have retyped or rebuilt.
_OPERATION_TEXT = re.compile(
    r"--merchant-scope|confirmation_command|\"--merchant-id\"|\[\s*\"project\"\s*,\s*\"create\"",
    re.IGNORECASE,
)

DELIVERY_FAILED_INSTRUCTION = (
    f"Send the report again ONCE as a non-actionable delivery failure: begin it "
    f"with `{PREVIEW_DELIVERY_FAILED}:` and the reason, keep the read-only "
    "findings, and do not include READY_FOR_CONFIRMATION, any "
    f"{PREVIEW_OPERATION_MARKER} block, argv, --merchant-scope or confirmation "
    "command. Do not run the preview again."
)


def _current_evidence(record: Any, field: str = EVIDENCE_FIELD) -> dict[str, Any] | None:
    evidence = record.get(field) if isinstance(record, dict) else None

    if (
        isinstance(evidence, dict)
        and evidence.get("run_id") == record.get("current_run_id")
        and evidence.get("task_id") == record.get("current_task_id")
    ):
        return evidence

    return None


# ------------------------------------------------- contract routing (NL2F)

EXECUTE_REQUEST_MARKER = "MERCHANT_EXECUTE_REQUEST_JSON:"
MERCHANT_EXECUTE = "merchant_execute"
_PREVIEW_CONTRACT = object()


def trusted_run_operation(state: dict[str, Any] | None) -> str | None:
    """``merchant_execute`` for a scoped run, ``merchant_read`` otherwise.

    Derived only from trusted run state written by the intent gate: a
    user-typed scope is the sole write authority. None when the run of the
    live task cannot be verified.
    """

    if not isinstance(state, dict):
        return None

    if state.get("merchant_scope") is not None:
        return MERCHANT_EXECUTE

    return "merchant_read"


def _message_contract_decision(
    message: str, state: dict[str, Any] | None, deny: Deny
) -> Any:
    """Route a merchant-manager message to the contract of its trusted run.

    Returns ``_PREVIEW_CONTRACT`` when the Project preview delivery contract
    applies, None when another gate owns the message, or a denial.

    - A message may carry at most one contract: an execute request and a
      preview block (or a preview delivery failure) together are ambiguous.
    - An execute request belongs only to a scoped (merchant_execute) run.
      It is validated after the call against the persisted user scope,
      pane, task and completeness by the trusted staging gate; it is never
      judged by read-only preview evidence.
    - In a scoped run, no message may present itself as a preview result.
    """

    execute = EXECUTE_REQUEST_MARKER in message
    preview = (
        PREVIEW_OPERATION_MARKER in message
        or PREVIEW_DELIVERY_FAILED in message
        or "confirmation_command" in message
    )
    operation = trusted_run_operation(state)

    if execute and preview:
        return deny(
            "Blocked: this message mixes a MERCHANT_EXECUTE_REQUEST_JSON "
            "execute request with Project preview content. Send exactly one "
            "contract per message. Nothing was sent or executed."
        )

    if operation == MERCHANT_EXECUTE:
        if preview:
            return deny(
                "Blocked: this run is a scoped merchant_execute run, so a "
                "message cannot carry a Project preview operation, a "
                "confirmation command or a preview delivery failure. Report "
                "the execute outcome with TEAM_RESULT_JSON instead. Nothing "
                "was sent."
            )
        return None  # the execute request / terminal gates decide

    if execute:
        return deny(
            "Blocked: MERCHANT_EXECUTE_REQUEST_JSON is valid only in a run "
            "with a user-authorized --merchant-scope, and this run has none"
            + ("" if operation else " that can be verified")
            + ". No write is possible; report the read-only result. "
            "Nothing was sent or executed."
        )

    return _PREVIEW_CONTRACT


def _status_delivery_decision(message: str, record: Any, deny: Deny) -> dict[str, Any] | None:
    """CP12H.NL4A: a status report carries exactly the captured CLI result.

    - VERIFIED capture: the exact object once, after STATUS_RESULT_MARKER.
    - UNVERIFIED capture: no status object; a STATUS_DELIVERY_FAILED report.
    - No status capture for the task: no status object at all.
    """

    blocks = _operation_blocks(message, STATUS_RESULT_MARKER)
    evidence = _current_evidence(record, STATUS_EVIDENCE_FIELD)
    resend = " Resend the report once; do not run the status read again."

    if evidence is not None and evidence.get("status") == VERIFIED:
        if len(blocks) != 1 or blocks[0] != evidence.get("result"):
            return deny(
                "Blocked: the Project status report must contain the CLI's status "
                f"result exactly once, after {STATUS_RESULT_MARKER}, as the complete "
                "JSON object it printed (same fields, values and Unicode). It was "
                "missing, duplicated, truncated or altered." + resend
            )
        return None

    if evidence is not None:
        if blocks or STATUS_DELIVERY_FAILED not in message:
            return deny(
                "Blocked: the Project status output could not be verified from the "
                f"CLI for this task. Begin the report with `{STATUS_DELIVERY_FAILED}:` "
                f"and the reason, without any {STATUS_RESULT_MARKER} block or step "
                "state presented as database fact." + resend
            )
        return None

    if blocks:
        return deny(
            "Blocked: no Project status read ran for this task, so the report "
            f"cannot carry a {STATUS_RESULT_MARKER} block. Status is never rebuilt "
            "from prose." + resend
        )

    return None


def preview_delivery_decision(payload: dict[str, Any], deny: Deny) -> dict[str, Any] | None:
    """PreToolUse(SendMessage): an actionable preview needs its verified operation.

    - Verified READY evidence: the report must carry that exact operation once.
    - Otherwise (no capture, UNVERIFIED capture, or a non-READY preview) the
      report may not claim READY_FOR_CONFIRMATION nor carry any operation
      block, argv or confirmation command; it must be a non-actionable
      ``PREVIEW_DELIVERY_FAILED`` report (when a preview ran) or a plain
      non-READY result. Each denial states one satisfiable correction, so the
      teammate resends once instead of looping.
    """

    if not _is_merchant_manager(payload, "SendMessage"):
        return None

    tool_input = _tool_input(payload)
    message = tool_input.get("message", tool_input.get("content"))

    if not isinstance(message, str):
        return None

    run = _owner_run()
    routed = _message_contract_decision(
        message, run[2] if run is not None else None, deny
    )

    if routed is not _PREVIEW_CONTRACT:
        return routed

    status_decision = _status_delivery_decision(
        message, run[1] if run is not None else None, deny
    )

    if status_decision is not None:
        return status_decision

    blocks = _operation_blocks(message)
    evidence = _current_evidence(run[1] if run is not None else None)
    expected = (
        evidence.get("requested_operation")
        if evidence is not None and evidence.get("status") == VERIFIED
        else None
    )

    if expected is not None:
        if len(blocks) != 1 or blocks[0] != expected:
            return deny(
                "Blocked: the report must contain the preview's requested_operation "
                f"exactly once, after {PREVIEW_OPERATION_MARKER}, as the complete "
                "JSON object the CLI printed (same fields, argv order and Unicode "
                "title). It was missing, duplicated, truncated or altered. Resend "
                "the report with the exact object; do not run the preview again."
            )
        return None

    claims_ready = _READY_CLAIM.search(
        _NEGATED_READY.sub("", message.replace(PREVIEW_DELIVERY_FAILED, ""))
    )
    actionable = blocks or claims_ready or _OPERATION_TEXT.search(message)

    # CP12H.NL3A: a verified non-READY preview (NEEDS_CLARIFICATION, BLOCKED)
    # was delivered correctly; it is that outcome, never a delivery failure.
    if evidence is not None and evidence.get("status") == VERIFIED:
        outcome = evidence.get("outcome")
        if actionable or PREVIEW_DELIVERY_FAILED in message:
            return deny(
                f"Blocked: the verified preview outcome is {outcome}. It was "
                "captured correctly, so this is not a delivery failure and not an "
                f"actionable result. Send the report again ONCE as the {outcome} "
                "result: relay its clarifications or conflicts and the read-only "
                f"findings, without `{PREVIEW_DELIVERY_FAILED}`, a "
                "READY_FOR_CONFIRMATION claim, any "
                f"{PREVIEW_OPERATION_MARKER} block, argv, --merchant-scope or "
                "confirmation command. Do not run the preview again."
            )
        return None

    if actionable:
        reason = (
            "the preview output could not be verified from the CLI for this task"
            if evidence is not None and evidence.get("status") == UNVERIFIED
            else "no verified Project preview operation exists for this task"
            if evidence is None or evidence.get("outcome") == READY
            else f"the verified preview outcome is {evidence.get('outcome')}"
        )
        return deny(
            f"Blocked: {reason}, so this report cannot present an actionable "
            "READY_FOR_CONFIRMATION result or any operation. Operations are "
            "never rebuilt from prose. " + DELIVERY_FAILED_INSTRUCTION
        )

    return None
