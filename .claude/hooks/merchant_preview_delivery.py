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
from dataclasses import dataclass

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
# CP12H.NL4B: the read-only Step Update preview, delivered the same way.
STEP_PREVIEW_MARKER = "MERCHANT_STEP_PREVIEW_JSON:"
STEP_PREVIEW_EVIDENCE_FIELD = "step_preview_evidence"
STEP_PREVIEW_DELIVERY_FAILED = "STEP_UPDATE_DELIVERY_FAILED"
# Reads that may name the Merchant test database (mirrors agent_cli).
TEST_DATABASE_READS = frozenset(
    {("project", "preview"), ("project", "status"), ("step", "preview")}
)


@dataclass(frozen=True)
class ReadResultContract:
    """A read whose report must carry the exact CLI-captured result object."""

    command: tuple[str, str]
    mode: str
    marker: str
    field: str
    failed: str
    label: str
    # Output flags a VERIFIED capture must carry exactly.
    required: tuple[tuple[str, Any], ...]
    # True: a verified delivery ends the check, and the report may never carry
    # Project-preview, confirmation or argv content (NL4B has no confirmation).
    terminal: bool


READ_RESULT_CONTRACTS = (
    ReadResultContract(
        ("project", "status"), "PROJECT_STATUS", STATUS_RESULT_MARKER,
        STATUS_EVIDENCE_FIELD, STATUS_DELIVERY_FAILED, "Project status",
        (("read_only", True), ("authorization", None)), terminal=False,
    ),
    ReadResultContract(
        ("step", "preview"), "STEP_UPDATE_PREVIEW", STEP_PREVIEW_MARKER,
        STEP_PREVIEW_EVIDENCE_FIELD, STEP_PREVIEW_DELIVERY_FAILED, "Step Update preview",
        # confirmation_available is checked against the outcome and target
        # in _step_operation_consistent (CP12H.NL4C).
        (("read_only", True), ("authorization", None), ("executable", False)),
        terminal=True,
    ),
)
_DELIVERED = object()  # a terminal read contract accepted the report

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
    payload: dict[str, Any], command: tuple[str, str] = ("project", "preview")
) -> tuple[str, ...] | None:
    """Arguments of merchant-manager's exact ``agent_cli.py <resource> <action>``."""

    if not _is_merchant_manager(payload, "Bash"):
        return None

    arguments = _agent_cli_arguments(_tool_input(payload).get("command"))

    if arguments is None or tuple(arguments[:2]) != command:
        return None

    return arguments


def record_read_evidence(payload: dict[str, Any], contract: ReadResultContract) -> bool:
    """PostToolUse(Bash): bind a read contract's CLI result to the live task.

    VERIFIED only for the exact CLI JSON of that read (its mode and every
    required read-only flag) on the trusted target, printed in the teammate's
    verified pane; anything else is an UNVERIFIED marker, so its report can
    only be a delivery failure.

    CP12H.NL4C1: a Step preview is VERIFIED only when READY carries exactly
    one valid ``requested_operation`` on the trusted target (and no other
    outcome carries one); a VERIFIED READY capture is the only creator of a
    pending Step Update. No other read creates a pending confirmation.
    """

    from claude.hooks.harness_team_identity import verified_teammate_pane
    from claude.hooks.merchant_tool_result_contract import _exact_json_object
    from claude.hooks.team_lifecycle import locked_team_state

    arguments = _preview_arguments(payload, contract.command)
    binding = _owner_binding() if arguments is not None else None

    if binding is None:
        return False

    owner, record, trusted = binding
    target = command_target(arguments)
    output = _exact_json_object(payload)
    verified = (
        isinstance(output, dict)
        and output.get("mode") == contract.mode
        and output.get("database_target") == target == trusted
        and all(
            key in output and output[key] is value for key, value in contract.required
        )
        and verified_teammate_pane(owner, MERCHANT_MANAGER_AGENT) is not None
    )
    operation = None

    if verified and contract.command == ("step", "preview"):
        operation = output.get("requested_operation")
        verified = _step_operation_consistent(output, operation, target)

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

        current[contract.field] = {
            "run_id": current["current_run_id"],
            "task_id": current["current_task_id"],
            "status": VERIFIED if verified else UNVERIFIED,
            "database_target": target,
            "result": output if verified else None,
        }

    if verified and operation is not None:
        # CP12H.NL4C1: the only creator of a pending Step Update.
        from claude.hooks.merchant_pending_confirmation import record_pending_step

        record_pending_step(
            owner,
            operation,
            run_id=record["current_run_id"],
            task_id=record["current_task_id"],
        )

    return verified


def _step_operation_consistent(output: dict[str, Any], operation: Any, target: str | None) -> bool:
    """READY carries exactly one valid operation on the target; nothing else carries one.

    ``confirmation_available`` must be exactly true for a READY preview on a
    confirmable target and exactly false otherwise (CP12H.NL4C).
    """

    from claude.agents.tools.merchant.step_preview import (
        CONFIRMABLE_TARGETS,
        validate_step_operation,
    )

    if (output.get("outcome") == READY) != (operation is not None):
        return False
    confirmable = operation is not None and target in CONFIRMABLE_TARGETS
    if output.get("confirmation_available") is not confirmable:
        return False
    if operation is None:
        return True

    try:
        validate_step_operation(operation)
    except ValueError:
        return False
    return operation.get("database_target") == target


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

    for contract in READ_RESULT_CONTRACTS:
        # Read-only results: never reach the Project-preview branch below,
        # the only caller of record_pending.
        if _preview_arguments(payload, contract.command) is not None:
            return record_read_evidence(payload, contract)

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


def _without_blocks(message: str, marker: str) -> str:
    """The message with every ``marker`` + JSON object removed (the prose)."""

    decoder = json.JSONDecoder()
    parts = message.split(marker)
    prose = [parts[0]]

    for part in parts[1:]:
        stripped = part.lstrip()
        try:
            _, end = decoder.raw_decode(stripped)
        except ValueError:
            end = 0
        prose.append(stripped[end:])

    return "".join(prose)


def _read_delivery_decision(
    message: str, record: Any, contract: ReadResultContract, deny: Deny
) -> Any:
    """CP12H.NL4A/NL4B: a read report carries exactly the captured CLI result.

    - VERIFIED capture: the exact object once, after the contract marker.
    - UNVERIFIED capture: no object; a report naming the contract's failure.
    - No capture for the task: no object at all.

    A terminal contract (the Step Update preview) also refuses any Project
    preview operation, argv, scope or confirmation text, and a READY claim
    the captured outcome does not support; a report it accepts returns
    ``_DELIVERED`` and is judged by nothing else.
    """

    marker, failed, label = contract.marker, contract.failed, contract.label
    blocks = _operation_blocks(message, marker)
    evidence = _current_evidence(record, contract.field)
    resend = f" Resend the report once; do not run the {label} read again."

    if evidence is None:
        if blocks:
            return deny(
                f"Blocked: no {label} read ran for this task, so the report cannot "
                f"carry a {marker} block. A result is never rebuilt from prose." + resend
            )
        return None

    verified = evidence.get("status") == VERIFIED

    if verified and (len(blocks) != 1 or blocks[0] != evidence.get("result")):
        return deny(
            f"Blocked: the {label} report must contain the CLI's result exactly "
            f"once, after {marker}, as the complete JSON object it printed (same "
            "fields, values and Unicode). It was missing, duplicated, truncated or "
            "altered." + resend
        )

    if not verified and (blocks or failed not in message):
        return deny(
            f"Blocked: the {label} output could not be verified from the CLI for "
            f"this task. Begin the report with `{failed}:` and the reason, without "
            f"any {marker} block or state presented as database fact." + resend
        )

    if not contract.terminal:
        return None

    prose = _without_blocks(message, marker)
    outcome = (evidence.get("result") or {}).get("outcome") if verified else None
    claims_ready = _READY_CLAIM.search(_NEGATED_READY.sub("", prose))

    if (
        PREVIEW_OPERATION_MARKER in message
        or PREVIEW_DELIVERY_FAILED in message
        or "confirmation_command" in message
        or _OPERATION_TEXT.search(prose)
        or (claims_ready and outcome != READY)
    ):
        return deny(
            f"Blocked: a {label} is read-only and grants nothing. The "
            "report may not carry a Project preview operation, argv, "
            "--merchant-scope or confirmation command, nor claim "
            "READY_FOR_CONFIRMATION unless the captured outcome is exactly that "
            f"(captured: {outcome or 'none'})." + resend
        )

    return _DELIVERED


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

    for contract in READ_RESULT_CONTRACTS:
        decision = _read_delivery_decision(
            message, run[1] if run is not None else None, contract, deny
        )
        if decision is _DELIVERED:
            return None
        if decision is not None:
            return decision

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
