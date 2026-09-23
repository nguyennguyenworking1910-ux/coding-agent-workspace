#!/usr/bin/env python3
"""PostToolUse and TeammateIdle hooks: exact teammate result delivery.

`SendMessage` to `team-lead` is the single machine-verifiable result path.
`TeammateIdle` is only a lifecycle signal: it never invents a result. If a
teammate tries to become idle before sending its report, the hook exits with
code 2 and asks it to send the existing report without repeating the task.

Uses deduplication key: run_id + task_id + canonical_teammate_name.
- Repeated SendMessage delivery is one logical result
- TaskUpdate and TeammateIdle do not count as complete results
- Once result_received is true, no recovery request is allowed
- recovery_sent records that delivery recovery was initiated

Updates both run state (result ledger) and team state (lifecycle status).
When result is received, marks team state REPORT_RECEIVED.
When TeammateIdle fires after result received, marks team state IDLE_REUSABLE.

Gate 11I:
- exact Merchant proposal JSON is taken from the Merchant CLI PostToolUse
  response, never reconstructed from the teammate's SendMessage;
- exact CLI output is staged only after the current lead run authorizes
  exactly merchant_propose + merchant-manager;
- tmux PostToolUse role information is only a hint;
- TeammateIdle supplies the trusted canonical teammate identity;
- owner session + teammate + run + task must match before proposal capture;
- the raw confirmation token exists only in transient pending proposal state
  and is cleared after successful lifecycle reconciliation.

Stop hook clears run state only.
SessionEnd hook clears run state and session team state.
"""

from __future__ import annotations

import json
import sys
import shlex
import unicodedata
from pathlib import Path
from typing import Any


if __package__ in (None, ""):
    sys.path.insert(
        0,
        str(
            Path(__file__).resolve().parent
        ),
    )

    from runtime_state import (
        load_state,
        locked_state,
    )
    from team_lifecycle import (
        claim_terminal_recovery,
        find_unique_active_teammate_owner,
        load_team_state,
        mark_bound_report_received,
        mark_report_received,
        mark_teammate_failed,
        release_reported_teammate_to_idle,
    )
    from merchant_confirmation_preferences import (
        MERCHANT_MANAGER_AGENT,
        MERCHANT_PROPOSE_OPERATION,
        capture_proposal_receipt,
        validate_proposal_result,
    )
    from tmux_result_receipt import (
        clear_pending_result,
        load_pending_result,
        stage_pending_result,
    )
    from tmux_merchant_proposal import (
        clear_pending_merchant_proposal,
        load_pending_merchant_proposal,
        pending_merchant_proposal_matches,
        stage_pending_merchant_proposal,
    )
    from tmux_merchant_completeness import (
        clear_pending_merchant_completeness,
        load_pending_merchant_completeness,
        pending_merchant_completeness_matches,
        stage_pending_merchant_completeness,
        validate_completeness_result,
    )
    from merchant_completeness_gate import (
        validate_completeness_receipt_for_outcome,
    )
    from tmux_merchant_resolution import (  # noqa: E402
        stage_pending_merchant_resolution,
        validate_merchant_resolution_result,
        clear_pending_merchant_resolution,
    )

else:
    from .runtime_state import (
        load_state,
        locked_state,
    )
    from .team_lifecycle import (
        claim_terminal_recovery,
        find_unique_active_teammate_owner,
        load_team_state,
        mark_bound_report_received,
        mark_report_received,
        mark_teammate_failed,
        release_reported_teammate_to_idle,
    )
    from .merchant_confirmation_preferences import (
        MERCHANT_MANAGER_AGENT,
        MERCHANT_PROPOSE_OPERATION,
        capture_proposal_receipt,
        validate_proposal_result,
    )
    from .tmux_result_receipt import (
        clear_pending_result,
        load_pending_result,
        stage_pending_result,
    )
    from .tmux_merchant_proposal import (
        clear_pending_merchant_proposal,
        load_pending_merchant_proposal,
        pending_merchant_proposal_matches,
        stage_pending_merchant_proposal,
    )
    from .tmux_merchant_completeness import (
        clear_pending_merchant_completeness,
        load_pending_merchant_completeness,
        pending_merchant_completeness_matches,
        stage_pending_merchant_completeness,
        validate_completeness_result,
    )
    from .merchant_completeness_gate import (
        validate_completeness_receipt_for_outcome,
    )
    from .tmux_merchant_resolution import (
        stage_pending_merchant_resolution,
        validate_merchant_resolution_result,
        clear_pending_merchant_resolution,
    )


HOOK_EVENT_NAMES = (
    "PostToolUse",
    "TeammateIdle",
)

MISSING_RESULT_FEEDBACK = (
    "Your result was not delivered to the lead. Send your complete existing "
    "report now through SendMessage to team-lead; do not redo the task. "
    "After SendMessage succeeds, finish with only: RESULT_DELIVERED."
)

INVALID_TERMINAL_RESULT_FEEDBACK = (
    "Your report was delivered, but its machine-readable terminal "
    "result is invalid or incomplete. Do not redo the task. Send the "
    "same result once more through SendMessage to team-lead with exactly "
    "one valid TEAM_RESULT_JSON block describing the actual outcome, then "
    "finish with only: RESULT_DELIVERED."
)

PENDING_RESULT_FEEDBACK = (
    "Result delivery is still incomplete. Send the existing report once "
    "through SendMessage to team-lead; do not repeat the task."
)

MERCHANT_PROPOSAL_RESULT_MARKER = (
    "MERCHANT_PROPOSAL_RESULT_JSON:"
)

TEAM_RESULT_MARKER = (
    "TEAM_RESULT_JSON:"
)

TEAM_RESULT_CONTRACT_VERSION = 1

MERCHANT_PROPOSAL_READY_OUTCOME = (
    "PROPOSAL_READY"
)

MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES = {
    "REQUIRES_CLARIFICATION",
    "FAILED",
    "BLOCKED",
}

MERCHANT_RESOLUTION_OPERATIONS = frozenset(
    {
        "merchant_read",
        "merchant_propose",
        "merchant_apply",
    }
)


def record_teammate_result(
    state: dict[str, Any],
    teammate_name: str,
    task_id: str,
    source: str = "unknown",
) -> bool:
    """Record a teammate result delivery in the idempotent ledger.

    Deduplication key: run_id + task_id + teammate_name.
    Returns True for a first result delivery, False when already delivered.
    """
    run_id = state.get(
        "run_id",
        "",
    )
    ledger = state.get(
        "result_ledger",
        {},
    )

    dedup_key = (
        f"{run_id}:"
        f"{task_id}:"
        f"{teammate_name}"
    )

    is_new_result = (
        dedup_key not in ledger
    )

    if dedup_key not in ledger:
        ledger[dedup_key] = {
            "teammate_name": teammate_name,
            "task_id": task_id,
            "result_received": True,
            "delivery_sources": [],
            "recovery_sent": False,
        }
    else:
        ledger[
            dedup_key
        ][
            "result_received"
        ] = True

    if (
        source
        not in ledger[
            dedup_key
        ][
            "delivery_sources"
        ]
    ):
        ledger[
            dedup_key
        ][
            "delivery_sources"
        ].append(
            source
        )

    state[
        "result_ledger"
    ] = ledger

    return is_new_result


def mark_recovery_sent(
    state: dict[str, Any],
    teammate_name: str,
    task_id: str,
) -> bool:
    """Mark that delivery recovery was requested and suppress duplicates."""
    run_id = state.get(
        "run_id",
        "",
    )
    ledger = state.get(
        "result_ledger",
        {},
    )

    dedup_key = (
        f"{run_id}:"
        f"{task_id}:"
        f"{teammate_name}"
    )

    if dedup_key not in ledger:
        ledger[dedup_key] = {
            "teammate_name": teammate_name,
            "task_id": task_id,
            "result_received": False,
            "delivery_sources": [],
            "recovery_sent": False,
        }

    record = ledger[
        dedup_key
    ]

    if record.get(
        "result_received"
    ):
        return False

    if record.get(
        "recovery_sent"
    ):
        return False

    record[
        "recovery_sent"
    ] = True

    state[
        "result_ledger"
    ] = ledger

    return True


def _coalesced_text(
    mapping: dict[str, Any],
    *fields: str,
) -> str:
    """Return one unambiguous non-empty text value across true alias fields."""
    values: list[str] = []

    for field in fields:
        value = mapping.get(
            field
        )

        if value is None:
            continue

        text = str(
            value
        ).strip()

        if text:
            values.append(
                text
            )

    if (
        not values
        or any(
            value != values[0]
            for value in values[1:]
        )
    ):
        return ""

    return values[0]


def send_message_body(
    tool_input: dict[str, Any],
) -> str:
    """Return the canonical SendMessage report body.

    Current Claude Code Agent Team payloads may expose `message` as the
    complete report while `content` is only a short compatibility/display
    value. They are therefore not treated as equivalent aliases.
    """
    message = tool_input.get(
        "message"
    )

    if isinstance(
        message,
        str,
    ):
        message = (
            message.strip()
        )

        if message:
            return message

    content = tool_input.get(
        "content"
    )

    if isinstance(
        content,
        str,
    ):
        return content.strip()

    return ""


def task_result_candidate_from_message(
    message: str,
) -> dict[str, Any] | None:
    """Parse one strict structured teammate task outcome.

    This result describes what actually happened during the task.
    It is not authorization and it does not grant Merchant proposal
    or apply authority.
    """

    report = str(
        message
        or ""
    ).strip()

    if (
        report.count(
            TEAM_RESULT_MARKER
        )
        != 1
    ):
        return None

    _, encoded = (
        report.split(
            TEAM_RESULT_MARKER,
            1,
        )
    )

    encoded = (
        encoded.strip()
    )

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

    # No prose or extra payload may follow
    # the structured task-result object.
    trailing_content = (
        encoded[
            end:
        ].strip()
    )

    has_proposal_delivery_block = False

    if trailing_content:
        # Gate 12A compatibility:
        # TEAM_RESULT_JSON may be followed only by the existing
        # Gate 11 Merchant proposal-delivery block.
        #
        # This does not make SendMessage proposal authority.
        # Exact proposal authority still comes exclusively from
        # the Merchant CLI PostToolUse staging path.
        if (
            trailing_content.count(
                MERCHANT_PROPOSAL_RESULT_MARKER
            )
            != 1
        ):
            return None

        if not trailing_content.startswith(
            MERCHANT_PROPOSAL_RESULT_MARKER
        ):
            return None

        _, proposal_encoded = (
            trailing_content.split(
                MERCHANT_PROPOSAL_RESULT_MARKER,
                1,
            )
        )

        proposal_encoded = (
            proposal_encoded.strip()
        )

        if not proposal_encoded:
            return None

        try:
            proposal_candidate, proposal_end = (
                json.JSONDecoder().raw_decode(
                    proposal_encoded
                )
            )
        except json.JSONDecodeError:
            return None

        if (
            proposal_encoded[
                proposal_end:
            ].strip()
        ):
            return None

        if not isinstance(
            proposal_candidate,
            dict,
        ):
            return None

        has_proposal_delivery_block = True

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    if (
        candidate.get(
            "contract_version"
        )
        != TEAM_RESULT_CONTRACT_VERSION
    ):
        return None

    outcome = str(
        candidate.get(
            "outcome"
        )
        or ""
    ).strip()

    operation = str(
        candidate.get(
            "operation"
        )
        or ""
    ).strip()

    database_target = str(
        candidate.get(
            "database_target"
        )
        or ""
    ).strip()

    proposal_emitted = (
        candidate.get(
            "proposal_emitted"
        )
    )

    allowed_outcomes = {
        MERCHANT_PROPOSAL_READY_OUTCOME,
        *MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES,
    }

    if (
        outcome
        not in allowed_outcomes
    ):
        return None

    if not (
        operation
        and database_target
    ):
        return None

    if not isinstance(
        proposal_emitted,
        bool,
    ):
        return None

    if (
        outcome
        == MERCHANT_PROPOSAL_READY_OUTCOME
    ):
        if proposal_emitted is not True:
            return None

    else:
        if proposal_emitted is not False:
            return None

        # A result claiming that no proposal was emitted
        # must not carry a Merchant proposal delivery block.
        if has_proposal_delivery_block:
            return None

    if (
        outcome
        == "REQUIRES_CLARIFICATION"
    ):
        missing_fields = (
            candidate.get(
                "missing_fields"
            )
        )

        # Backward-compatible normalization for Gate 12A
        # results that predate missing_one_of. New Merchant
        # results should emit it explicitly.
        missing_one_of = (
            candidate.get(
                "missing_one_of",
                [],
            )
        )

        question = str(
            candidate.get(
                "question"
            )
            or ""
        ).strip()

        if not isinstance(
            missing_fields,
            list,
        ):
            return None

        if not isinstance(
            missing_one_of,
            list,
        ):
            return None

        if any(
            not isinstance(
                field,
                str,
            )
            or not field.strip()
            for field in missing_fields
        ):
            return None

        for group in missing_one_of:
            if (
                not isinstance(
                    group,
                    list,
                )
                or not group
            ):
                return None

            if any(
                not isinstance(
                    field,
                    str,
                )
                or not field.strip()
                for field in group
            ):
                return None

        if not (
            missing_fields
            or missing_one_of
        ):
            return None

        if not question:
            return None

        # Normalize legacy Gate 12A clarification results so
        # downstream Gate 12C enforcement always sees the same
        # semantic shape.
        candidate = dict(
            candidate
        )

        candidate[
            "missing_one_of"
        ] = missing_one_of

    return candidate


def trusted_post_tool_sender(
    payload: dict[str, Any],
) -> str:
    """Return sender only when both harness-authenticated fields are present."""
    agent_id = str(
        payload.get(
            "agent_id"
        )
        or ""
    ).strip()

    agent_type = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if not (
        agent_id
        and agent_type
    ):
        return ""

    return agent_type


def active_task_id(
    session_id: Any,
    teammate_name: str,
) -> str:
    """Resolve the current task because TeammateIdle may omit task_id."""
    team_state = (
        load_team_state(
            session_id
        )
    )

    if not isinstance(
        team_state,
        dict,
    ):
        return ""

    record = (
        team_state.get(
            "teammates"
        )
        or {}
    ).get(
        teammate_name
    )

    if not isinstance(
        record,
        dict,
    ):
        return ""

    if (
        record.get(
            "canonical_name"
        )
        != teammate_name
    ):
        return ""

    return str(
        record.get(
            "current_task_id"
        )
        or ""
    ).strip()


def _merchant_resolution_invocation_query(
    payload: dict[str, Any],
) -> str:
    """Return query only for one direct allowlisted resolver invocation.

    Resolution JSON is easy to fabricate with shell output, so exact stdout
    alone is insufficient authority. The PostToolUse command must also be one
    direct Merchant agent CLI resolver invocation with no pipeline, redirect,
    command chaining, or wrapper script.
    """

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    if tool_name not in {
        "Bash",
        "PowerShell",
    }:
        return ""

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return ""

    command = tool_input.get(
        "command"
    )

    if not isinstance(
        command,
        str,
    ):
        return ""

    command = command.strip()

    if not command:
        return ""

    try:
        tokens = shlex.split(
            command,
            posix=True,
        )
    except ValueError:
        return ""

    if len(
        tokens
    ) != 6:
        return ""

    (
        executable,
        script,
        resource,
        action,
        query_flag,
        query,
    ) = tokens

    normalized_executable = (
        executable
        .replace(
            "\\",
            "/",
        )
        .lower()
    )

    allowed_executables = {
        "python",
        "python.exe",
        "py",
        "py.exe",
        ".venv/scripts/python.exe",
        "./.venv/scripts/python.exe",
    }

    if (
        normalized_executable
        not in allowed_executables
    ):
        return ""

    normalized_script = (
        script
        .replace(
            "\\",
            "/",
        )
    )

    if normalized_script.startswith(
        "./"
    ):
        normalized_script = (
            normalized_script[
                2:
            ]
        )

    if (
        normalized_script
        != (
            ".claude/agents/tools/"
            "merchant/agent_cli.py"
        )
    ):
        return ""

    if (
        resource
        != "merchant"
        or action
        != "resolve"
        or query_flag
        != "--query"
    ):
        return ""

    normalized_query = (
        unicodedata.normalize(
            "NFKC",
            query,
        )
        .strip()
    )

    return normalized_query


def merchant_resolution_from_tool_response(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract one exact validated Merchant resolver CLI result."""

    invocation_query = (
        _merchant_resolution_invocation_query(
            payload
        )
    )

    if not invocation_query:
        return None

    response: Any = None

    for field in (
        "tool_response",
        "tool_result",
        "toolUseResult",
    ):
        candidate_response = (
            payload.get(
                field
            )
        )

        if (
            candidate_response
            is not None
        ):
            response = (
                candidate_response
            )
            break

    stdout: Any = None

    if isinstance(
        response,
        dict,
    ):
        stdout = response.get(
            "stdout"
        )

    elif isinstance(
        response,
        str,
    ):
        stdout = response

    if not isinstance(
        stdout,
        str,
    ):
        return None

    text = stdout.strip()

    if not text:
        return None

    try:
        candidate = json.loads(
            text
        )
    except json.JSONDecodeError:
        return None

    validated = (
        validate_merchant_resolution_result(
            candidate
        )
    )

    if validated is None:
        return None

    if (
        validated.get(
            "query"
        )
        != invocation_query
    ):
        return None

    return validated


def _stage_exact_tmux_merchant_resolution(
    payload: dict[str, Any],
    session_id: Any,
    resolution: dict[str, Any],
) -> bool:
    """Stage exact resolver evidence for one authorized Merchant task."""

    pane_session_id = str(
        session_id
        or ""
    ).strip()

    if not pane_session_id:
        return False

    role_hint = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if (
        role_hint
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    authenticated_sender = (
        trusted_post_tool_sender(
            payload
        )
    )

    if (
        authenticated_sender
        and authenticated_sender
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    (
        owner_session_id,
        owner_record,
        owner_resolution,
    ) = (
        find_unique_active_teammate_owner(
            MERCHANT_MANAGER_AGENT
        )
    )

    if (
        owner_resolution
        != "FOUND"
        or not owner_session_id
        or not isinstance(
            owner_record,
            dict,
        )
    ):
        return False

    owner_run_id = str(
        owner_record.get(
            "current_run_id"
        )
        or ""
    ).strip()

    owner_task_id = str(
        owner_record.get(
            "current_task_id"
        )
        or ""
    ).strip()

    if not (
        owner_run_id
        and owner_task_id
    ):
        return False

    authorized_operations = [
        str(
            operation
        )
        for operation in (
            owner_record.get(
                "authorized_operations"
            )
            or []
        )
    ]

    authorized_selected_agents = [
        str(
            agent
        )
        for agent in (
            owner_record.get(
                "authorized_selected_agents"
            )
            or []
        )
    ]

    if (
        len(
            authorized_operations
        )
        != 1
        or authorized_operations[0]
        not in MERCHANT_RESOLUTION_OPERATIONS
    ):
        return False

    if (
        authorized_selected_agents
        != [
            MERCHANT_MANAGER_AGENT
        ]
    ):
        return False

    # Do NOT require pane_session_id != owner_session_id.
    #
    # Live Agent Team PostToolUse may use the lead session id for an
    # authenticated teammate. Identity and authorization binding, not
    # session-id inequality, form the security boundary.
    return (
        stage_pending_merchant_resolution(
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            tool_use_id=str(
                payload.get(
                    "tool_use_id"
                )
                or ""
            ).strip(),
            resolution=resolution,
        )
    )


def _clear_merchant_resolution_after_release(
    session_id: Any,
    teammate_name: str,
) -> None:
    """Clear task-scoped Merchant entity evidence after successful release."""

    if (
        teammate_name
        != MERCHANT_MANAGER_AGENT
    ):
        return

    pane_session_id = str(
        session_id
        or ""
    ).strip()

    if not pane_session_id:
        return

    clear_pending_merchant_resolution(
        pane_session_id
    )


def merchant_proposal_from_tool_response(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract one fully validated exact Merchant CLI proposal.

    This path accepts exact JSON stdout only. It deliberately does not scan
    arbitrary prose and does not repair/reconstruct a confirmation token.
    """

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    if tool_name not in {
        "Bash",
        "PowerShell",
    }:
        return None

    response: Any = None

    for field in (
        "tool_response",
        "tool_result",
        "toolUseResult",
    ):
        candidate_response = (
            payload.get(
                field
            )
        )

        if (
            candidate_response
            is not None
        ):
            response = (
                candidate_response
            )
            break

    stdout: Any = None

    if isinstance(
        response,
        dict,
    ):
        stdout = response.get(
            "stdout"
        )
    elif isinstance(
        response,
        str,
    ):
        stdout = response

    if not isinstance(
        stdout,
        str,
    ):
        return None

    text = stdout.strip()

    if not text:
        return None

    try:
        candidate = (
            json.loads(
                text
            )
        )
    except json.JSONDecodeError:
        return None

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    if (
        validate_proposal_result(
            candidate
        )
        is None
    ):
        return None

    return candidate


def merchant_completeness_from_tool_response(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract one exact Merchant completeness CLI result."""

    tool_name = str(
        payload.get("tool_name") or ""
    ).strip()

    if tool_name not in {
        "Bash",
        "PowerShell",
    }:
        return None

    response: Any = None

    for field in (
        "tool_response",
        "tool_result",
        "toolUseResult",
    ):
        candidate_response = payload.get(
            field
        )

        if candidate_response is not None:
            response = candidate_response
            break

    stdout: Any = None

    if isinstance(
        response,
        dict,
    ):
        stdout = response.get(
            "stdout"
        )
    elif isinstance(
        response,
        str,
    ):
        stdout = response

    if not isinstance(
        stdout,
        str,
    ):
        return None

    text = stdout.strip()

    if not text:
        return None

    try:
        candidate = json.loads(
            text
        )
    except json.JSONDecodeError:
        return None

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    if (
        validate_completeness_result(
            candidate
        )
        is None
    ):
        return None

    return candidate


def _stage_exact_tmux_merchant_proposal(
    payload: dict[str, Any],
    session_id: Any,
    proposal: dict[str, Any],
) -> bool:
    """Stage an exact CLI proposal without granting runtime authority.

    The exact CLI output may come from a pane-backed teammate whose
    PostToolUse contains either:
    - only agent_type, or
    - both agent_id and agent_type.

    Staging itself is not authorization to apply the proposal.

    Final trust is established later by:
    - trusted TeammateIdle identity;
    - unique lead owner;
    - exact owner session;
    - exact run_id;
    - exact task_id.

    The lead run must also authorize exactly:
        operations == ["merchant_propose"]
        selected_agents == ["merchant-manager"]
    """

    pane_session_id = str(
        session_id or ""
    ).strip()

    if not pane_session_id:
        return False

    role_hint = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if (
        role_hint
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    # If the harness provides an authenticated sender,
    # it must agree with the Merchant role.
    #
    # IMPORTANT:
    # Do NOT reject merely because agent_id exists.
    authenticated_sender = (
        trusted_post_tool_sender(
            payload
        )
    )

    if (
        authenticated_sender
        and authenticated_sender
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    (
        owner_session_id,
        owner_record,
        owner_resolution,
    ) = (
        find_unique_active_teammate_owner(
            MERCHANT_MANAGER_AGENT
        )
    )

    if (
        owner_resolution
        != "FOUND"
        or not owner_session_id
        or not isinstance(
            owner_record,
            dict,
        )
    ):
        return False

    # Gate 11I staging is specifically for a teammate/pane
    # session owned by a different lead session.
    #
    # This prevents the lead session itself from accidentally
    # using this transient tmux path.
    if (
        str(
            owner_session_id
        ).strip()
        == pane_session_id
    ):
        return False

    owner_run_id = str(
        owner_record.get(
            "current_run_id"
        )
        or ""
    ).strip()

    owner_task_id = str(
        owner_record.get(
            "current_task_id"
        )
        or ""
    ).strip()

    if not (
        owner_run_id
        and owner_task_id
    ):
        return False

    authorized_operations = [
        str(operation)
        for operation in (
            owner_record.get(
                "authorized_operations"
            )
            or []
        )
    ]

    authorized_selected_agents = [
        str(agent)
        for agent in (
            owner_record.get(
                "authorized_selected_agents"
            )
            or []
        )
    ]

    if (
        authorized_operations
        != [
            MERCHANT_PROPOSE_OPERATION
        ]
    ):
        return False

    if (
        authorized_selected_agents
        != [
            MERCHANT_MANAGER_AGENT
        ]
    ):
        return False

    return (
        stage_pending_merchant_proposal(
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            tool_use_id=str(
                payload.get(
                    "tool_use_id"
                )
                or ""
            ).strip(),
            proposal=proposal,
        )
    )


def _stage_exact_tmux_merchant_completeness(
    payload: dict[str, Any],
    session_id: Any,
    result: dict[str, Any],
) -> bool:
    """Stage exact completeness evidence for one Merchant teammate task."""

    pane_session_id = str(
        session_id or ""
    ).strip()

    if not pane_session_id:
        return False

    role_hint = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if (
        role_hint
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    authenticated_sender = (
        trusted_post_tool_sender(
            payload
        )
    )

    if (
        authenticated_sender
        and authenticated_sender
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    (
        owner_session_id,
        owner_record,
        owner_resolution,
    ) = find_unique_active_teammate_owner(
        MERCHANT_MANAGER_AGENT
    )

    if (
        owner_resolution != "FOUND"
        or not owner_session_id
        or not isinstance(
            owner_record,
            dict,
        )
    ):
        return False

    # tmux receipt must come from the teammate pane,
    # not the lead session itself.
    if (
        str(
            owner_session_id
        ).strip()
        == pane_session_id
    ):
        return False

    owner_run_id = str(
        owner_record.get(
            "current_run_id"
        )
        or ""
    ).strip()

    owner_task_id = str(
        owner_record.get(
            "current_task_id"
        )
        or ""
    ).strip()

    if not (
        owner_run_id
        and owner_task_id
    ):
        return False

    authorized_operations = [
        str(operation)
        for operation
        in (
            owner_record.get(
                "authorized_operations"
            )
            or []
        )
    ]

    authorized_agents = [
        str(agent)
        for agent
        in (
            owner_record.get(
                "authorized_selected_agents"
            )
            or []
        )
    ]

    if (
        authorized_operations
        != [
            MERCHANT_PROPOSE_OPERATION
        ]
    ):
        return False

    if (
        authorized_agents
        != [
            MERCHANT_MANAGER_AGENT
        ]
    ):
        return False

    return stage_pending_merchant_completeness(
        pane_session_id=(
            pane_session_id
        ),
        owner_session_id=(
            owner_session_id
        ),
        teammate_name=(
            MERCHANT_MANAGER_AGENT
        ),
        run_id=(
            owner_run_id
        ),
        task_id=(
            owner_task_id
        ),
        tool_use_id=str(
            payload.get(
                "tool_use_id"
            )
            or ""
        ).strip(),
        result=result,
    )


def handle_post_tool_use(
    state: dict[str, Any] | None,
    payload: dict[str, Any],
    session_id: Any = None,
) -> None:
    """Handle exact Merchant CLI staging plus canonical SendMessage delivery."""

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    completeness = (
        merchant_completeness_from_tool_response(
            payload
        )
    )

    if completeness is not None:
        _stage_exact_tmux_merchant_completeness(
            payload,
            session_id,
            completeness,
        )

    resolution = (
        merchant_resolution_from_tool_response(
            payload
        )
    )

    if resolution is not None:
        _stage_exact_tmux_merchant_resolution(
            payload,
            session_id,
            resolution,
        )

    # ------------------------------------------------------------
    # Gate 11I exact CLI path.
    #
    # This MUST execute before the SendMessage-only return because
    # Merchant CLI proposal output arrives through Bash/PowerShell.
    # ------------------------------------------------------------
    proposal = (
        merchant_proposal_from_tool_response(
            payload
        )
    )

    if proposal is not None:
        _stage_exact_tmux_merchant_proposal(
            payload,
            session_id,
            proposal,
        )

    # ------------------------------------------------------------
    # SendMessage remains the machine-verifiable result-delivery path.
    # ------------------------------------------------------------
    if (
        tool_name
        != "SendMessage"
    ):
        return

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return

    # recipient/to are true aliases and must agree when both are present.
    to_field = (
        _coalesced_text(
            tool_input,
            "recipient",
            "to",
        )
    )

    if (
        to_field
        != "team-lead"
    ):
        return

    # Gate 11H: prefer full `message`; legacy `content` is fallback only.
    message = (
        send_message_body(
            tool_input
        )
    )

    if not message:
        return

    teammate_name = (
        trusted_post_tool_sender(
            payload
        )
    )

    # ------------------------------------------------------------
    # tmux / pane-backed teammate.
    #
    # No trusted agent_id is available here. `agent_type` is only a role
    # hint used to find exactly one active lifecycle owner. TeammateIdle
    # later supplies trusted teammate_name.
    # ------------------------------------------------------------
    if not teammate_name:
        tmux_role_hint = str(
            payload.get(
                "agent_type"
            )
            or ""
        ).strip()

        if not (
            session_id
            and tmux_role_hint
        ):
            return

        (
            owner_session_id,
            owner_record,
            owner_resolution,
        ) = (
            find_unique_active_teammate_owner(
                tmux_role_hint
            )
        )

        if (
            owner_resolution
            != "FOUND"
            or not owner_session_id
            or not isinstance(
                owner_record,
                dict,
            )
        ):
            return

        owner_run_id = str(
            owner_record.get(
                "current_run_id"
            )
            or ""
        ).strip()

        owner_task_id = str(
            owner_record.get(
                "current_task_id"
            )
            or ""
        ).strip()

        if not (
            owner_run_id
            and owner_task_id
        ):
            return

        owner_operations = [
            str(operation)
            for operation in (
                owner_record.get(
                    "authorized_operations"
                )
                or []
            )
        ]

        owner_selected_agents = [
            str(agent)
            for agent in (
                owner_record.get(
                    "authorized_selected_agents"
                )
                or []
            )
        ]

        stage_pending_result(
            session_id=(
                session_id
            ),
            message=(
                message
            ),
            tool_use_id=str(
                payload.get(
                    "tool_use_id"
                )
                or ""
            ).strip(),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                tmux_role_hint
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            operations=(
                owner_operations
            ),
            selected_agents=(
                owner_selected_agents
            ),
        )

        return

    # ------------------------------------------------------------
    # Gate 12C.9A:
    #
    # An authenticated teammate pane may provide both agent_id and
    # agent_type. Authentication proves sender identity, but it does
    # NOT mean a Merchant terminal result is already trustworthy.
    #
    # For an exact merchant-manager / merchant_propose owner binding,
    # defer REPORT_RECEIVED until TeammateIdle validates the staged
    # TEAM_RESULT_JSON against deterministic completeness/proposal
    # evidence.
    #
    # This intentionally mirrors the tmux role-hint staging path.
    # ------------------------------------------------------------
    if (
        teammate_name
        == MERCHANT_MANAGER_AGENT
        and session_id
    ):
        (
            owner_session_id,
            owner_record,
            owner_resolution,
        ) = (
            find_unique_active_teammate_owner(
                teammate_name
            )
        )

        if (
            owner_resolution == "FOUND"
            and owner_session_id
            and isinstance(
                owner_record,
                dict,
            )
        ):
            owner_run_id = str(
                owner_record.get(
                    "current_run_id"
                )
                or ""
            ).strip()

            owner_task_id = str(
                owner_record.get(
                    "current_task_id"
                )
                or ""
            ).strip()

            owner_operations = [
                str(operation)
                for operation in (
                    owner_record.get(
                        "authorized_operations"
                    )
                    or []
                )
            ]

            owner_selected_agents = [
                str(agent)
                for agent in (
                    owner_record.get(
                        "authorized_selected_agents"
                    )
                    or []
                )
            ]

            requires_deferred_merchant_result = (
                owner_run_id
                and owner_task_id
                and owner_operations
                == [
                    MERCHANT_PROPOSE_OPERATION
                ]
                and owner_selected_agents
                == [
                    MERCHANT_MANAGER_AGENT
                ]
            )

            if requires_deferred_merchant_result:
                stage_pending_result(
                    session_id=session_id,
                    message=message,
                    tool_use_id=str(
                        payload.get(
                            "tool_use_id"
                        )
                        or ""
                    ).strip(),
                    owner_session_id=(
                        owner_session_id
                    ),
                    teammate_name=(
                        teammate_name
                    ),
                    run_id=(
                        owner_run_id
                    ),
                    task_id=(
                        owner_task_id
                    ),
                    operations=(
                        owner_operations
                    ),
                    selected_agents=(
                        owner_selected_agents
                    ),
                )

                # Critical Gate 12C invariant:
                # do NOT call record_teammate_result()
                # or mark_report_received() yet.
                #
                # TeammateIdle is responsible for validating
                # completeness/proposal evidence first.
                return

    # ------------------------------------------------------------
    # Authenticated non-tmux teammate path.
    # ------------------------------------------------------------
    task_id = str(
        tool_input.get(
            "task_id"
        )
        or ""
    ).strip()

    if not task_id:
        task_id = str(
            payload.get(
                "task_id"
            )
            or ""
        ).strip()

    current_task_id = (
        active_task_id(
            session_id,
            teammate_name,
        )
    )

    if current_task_id:
        if (
            task_id
            and task_id
            != current_task_id
        ):
            return

        task_id = (
            current_task_id
        )

    if not (
        teammate_name
        and task_id
    ):
        return

    if state is not None:
        record_teammate_result(
            state,
            teammate_name,
            task_id,
            "sendmessage",
        )

    if session_id:
        mark_report_received(
            session_id,
            teammate_name,
            task_id,
            "sendmessage",
        )


def bounded_terminal_result_failure(
    *,
    owner_session_id: Any,
    pane_session_id: Any,
    teammate_name: str,
    run_id: str,
    task_id: str,
    reason: str,
) -> str:
    """Give an invalid terminal result exactly one correction turn.

    First failure:
        block TeammateIdle once and request contract-only correction.

    Repeated failure:
        mark the teammate FAILED and allow the turn to terminate.

    No proposal authority is created by this path.
    """

    recovery_claimed, recovery_status = (
        claim_terminal_recovery(
            owner_session_id,
            teammate_name,
            run_id,
            task_id,
        )
    )

    if recovery_claimed:
        return (
            INVALID_TERMINAL_RESULT_FEEDBACK
        )

    if recovery_status == "ALREADY_SENT":
        mark_teammate_failed(
            owner_session_id,
            teammate_name,
            reason=reason,
        )

        if pane_session_id:
            clear_pending_result(
                pane_session_id
            )

        return ""

    # Unexpected lifecycle/binding failures remain fail-closed.
    return PENDING_RESULT_FEEDBACK


def bound_merchant_completeness_receipt(
    *,
    pane_session_id: str,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Return completeness evidence only for the exact current task."""

    if not pane_session_id:
        return None

    receipt = (
        load_pending_merchant_completeness(
            pane_session_id
        )
    )

    if not isinstance(
        receipt,
        dict,
    ):
        return None

    if not pending_merchant_completeness_matches(
        receipt,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
    ):
        return None

    return receipt


def handle_teammate_idle(
    state: dict[str, Any] | None,
    payload: dict[str, Any],
    session_id: Any = None,
) -> str:
    """Handle TeammateIdle as the trusted delivery/lifecycle gate."""

    teammate_name = str(
        payload.get(
            "teammate_name"
        )
        or ""
    ).strip()

    task_id = str(
        payload.get(
            "task_id"
        )
        or ""
    ).strip()

    if not teammate_name:
        return ""

    if session_id:
        direct_team_state = (
            load_team_state(
                session_id
            )
        )

        if (
            direct_team_state
            is not None
        ):
            released, _ = (
                release_reported_teammate_to_idle(
                    session_id,
                    teammate_name,
                )
            )

            if released:
                _clear_merchant_resolution_after_release(
                    session_id,
                    teammate_name,
                )

                return ""

        # tmux fallback:
        # TeammateIdle provides trusted teammate_name. Its session_id belongs
        # to the pane, so find the unique lead session that currently owns it.
        (
            owner_session_id,
            owner_record,
            owner_resolution,
        ) = (
            find_unique_active_teammate_owner(
                teammate_name
            )
        )

        if (
            owner_resolution
            == "AMBIGUOUS"
        ):
            return (
                "Cannot safely reconcile this teammate because more than "
                "one active lead session owns the same canonical teammate. "
                "Do not start new work."
            )

        if (
            owner_resolution
            == "FOUND"
            and owner_session_id
            and isinstance(
                owner_record,
                dict,
            )
            and str(
                owner_session_id
            )
            != str(
                session_id
            )
        ):
            pending_result = (
                load_pending_result(
                    session_id
                )
                if session_id
                else None
            )

            if (
                pending_result
                is None
            ):
                return (
                    MISSING_RESULT_FEEDBACK
                )

            owner_run_id = str(
                owner_record.get(
                    "current_run_id"
                )
                or ""
            ).strip()

            owner_task_id = str(
                owner_record.get(
                    "current_task_id"
                )
                or ""
            ).strip()

            if not (
                owner_run_id
                and owner_task_id
            ):
                return (
                    PENDING_RESULT_FEEDBACK
                )

            receipt_matches_owner = (
                str(
                    pending_result.get(
                        "owner_session_id"
                    )
                    or ""
                ).strip()
                == str(
                    owner_session_id
                ).strip()
                and str(
                    pending_result.get(
                        "teammate_name"
                    )
                    or ""
                ).strip()
                == teammate_name
                and str(
                    pending_result.get(
                        "run_id"
                    )
                    or ""
                ).strip()
                == owner_run_id
                and str(
                    pending_result.get(
                        "task_id"
                    )
                    or ""
                ).strip()
                == owner_task_id
            )

            if not (
                receipt_matches_owner
            ):
                return (
                    MISSING_RESULT_FEEDBACK
                )

            marked = (
                mark_bound_report_received(
                    owner_session_id,
                    teammate_name,
                    owner_run_id,
                    owner_task_id,
                    "sendmessage",
                )
            )

            if not marked:
                return (
                    PENDING_RESULT_FEEDBACK
                )

            # --------------------------------------------------------
            # Gate 11I:
            # Merchant proposal authority comes from the exact staged CLI
            # output, not from the model-copied SendMessage JSON.
            #
            # Missing/mismatched proposal state does not invent authority.
            # It also does not undo a valid report delivery.
            # --------------------------------------------------------
            merchant_proposal_captured = False

            owner_authorized_operations = [
                str(operation)
                for operation in (
                    owner_record.get(
                        "authorized_operations"
                    )
                    or []
                )
            ]

            owner_authorized_agents = [
                str(agent)
                for agent in (
                    owner_record.get(
                        "authorized_selected_agents"
                    )
                    or []
                )
            ]

            requires_exact_merchant_proposal = (
                teammate_name
                == MERCHANT_MANAGER_AGENT
                and owner_authorized_operations
                == [
                    MERCHANT_PROPOSE_OPERATION
                ]
                and owner_authorized_agents
                == [
                    MERCHANT_MANAGER_AGENT
                ]
            )

            # --------------------------------------------------------
            # Gate 12A:
            #
            # Authorization tells us what the teammate was allowed
            # to attempt. The structured task outcome tells us what
            # actually happened.
            #
            # Only PROPOSAL_READY requires exact Merchant proposal
            # evidence. Clarification/failure/block are valid terminal
            # results without proposal authority.
            #
            # Missing or malformed TEAM_RESULT_JSON deliberately falls
            # back to Gate 11 behavior and therefore remains fail-closed.
            # --------------------------------------------------------
            if requires_exact_merchant_proposal:
                task_result = (
                    task_result_candidate_from_message(
                        str(
                            pending_result.get(
                                "message"
                            )
                            or ""
                        )
                    )
                )

                if (task_result is not None and str(task_result.get("operation") or "").strip() == MERCHANT_PROPOSE_OPERATION and str(task_result.get("database_target") or "").strip() == "runtime"):
                    bound_completeness = (
                        bound_merchant_completeness_receipt(
                            pane_session_id=str(
                                session_id
                                or ""
                            ).strip(),
                            owner_session_id=str(
                                owner_session_id
                            ).strip(),
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                        )
                    )

                    completeness_decision = (
                        validate_completeness_receipt_for_outcome(
                            task_result,
                            bound_completeness,
                        )
                    )

                    if not completeness_decision.accepted:
                        return bounded_terminal_result_failure(
                            owner_session_id=owner_session_id,
                            pane_session_id=session_id,
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                            reason=(
                                "Merchant completeness evidence did not "
                                "match the structured task outcome: "
                                f"{completeness_decision.reason}"
                            ),
                        )

                    task_outcome = str(
                        task_result.get(
                            "outcome"
                        )
                        or ""
                    ).strip()

                    if (
                        task_outcome
                        in MERCHANT_TERMINAL_WITHOUT_PROPOSAL_OUTCOMES
                    ):
                        # A non-proposal terminal outcome must not coexist
                        # with staged proposal authority. Preserve evidence
                        # and fail closed if the two disagree.
                        unexpected_proposal = (
                            load_pending_merchant_proposal(
                                session_id
                            )
                        )

                        if (
                            unexpected_proposal
                            is not None
                        ):
                            return (
                                PENDING_RESULT_FEEDBACK
                            )

                        requires_exact_merchant_proposal = (
                            False
                        )

            if requires_exact_merchant_proposal:
                pending_proposal = (
                    load_pending_merchant_proposal(
                        session_id
                    )
                )

                # A merchant_propose run MUST have an exact
                # CLI-staged proposal before the teammate can
                # become reusable.
                if pending_proposal is None:
                    return bounded_terminal_result_failure(
                        owner_session_id=owner_session_id,
                        pane_session_id=session_id,
                        teammate_name=teammate_name,
                        run_id=owner_run_id,
                        task_id=owner_task_id,
                        reason=(
                            "Merchant terminal report did not establish "
                            "a valid non-proposal outcome and no exact "
                            "CLI proposal was staged."
                        ),
                    )

                if not pending_merchant_proposal_matches(
                    pending_proposal,
                    owner_session_id=(
                        owner_session_id
                    ),
                    teammate_name=(
                        teammate_name
                    ),
                    run_id=(
                        owner_run_id
                    ),
                    task_id=(
                        owner_task_id
                    ),
                ):
                    return PENDING_RESULT_FEEDBACK

                proposal = (
                    pending_proposal.get(
                        "proposal"
                    )
                )

                if not isinstance(
                    proposal,
                    dict,
                ):
                    return PENDING_RESULT_FEEDBACK

                if (
                    task_result is not None
                    and str(
                        task_result.get(
                            "outcome"
                        )
                        or ""
                    ).strip()
                    == MERCHANT_PROPOSAL_READY_OUTCOME
                ):
                    if not isinstance(
                        bound_completeness,
                        dict,
                    ):
                        return bounded_terminal_result_failure(
                            owner_session_id=owner_session_id,
                            pane_session_id=session_id,
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                            reason=(
                                "PROPOSAL_READY has no exact "
                                "completeness receipt"
                            ),
                        )

                    completeness_result = (
                        bound_completeness.get(
                            "result"
                        )
                    )

                    if not isinstance(
                        completeness_result,
                        dict,
                    ):
                        return PENDING_RESULT_FEEDBACK

                    completeness_command = str(
                        completeness_result.get(
                            "command"
                        )
                        or ""
                    ).strip()

                    proposal_command = str(
                        proposal.get(
                            "command"
                        )
                        or ""
                    ).strip()

                    if (
                        not completeness_command
                        or completeness_command
                        != proposal_command
                    ):
                        return bounded_terminal_result_failure(
                            owner_session_id=owner_session_id,
                            pane_session_id=session_id,
                            teammate_name=teammate_name,
                            run_id=owner_run_id,
                            task_id=owner_task_id,
                            reason=(
                                "Merchant proposal command does not match "
                                "the exact completeness command"
                            ),
                        )

                capture_outcome = (
                    capture_proposal_receipt(
                        owner_session_id,
                        proposal,
                    )
                )

                # Critical Gate 11I fail-closed boundary:
                # do not release the teammate and do not delete
                # transient evidence when receipt capture fails.
                if not capture_outcome.accepted:
                    return PENDING_RESULT_FEEDBACK

                merchant_proposal_captured = True

            # Update the lead run ledger when it still exists.
            # Stop may already have removed it; team state remains the
            # authoritative lifecycle completion record in that case.
            if (
                str(
                    owner_session_id
                )
                == str(
                    session_id
                )
            ):
                if (
                    state
                    is not None
                ):
                    record_teammate_result(
                        state,
                        teammate_name,
                        owner_task_id,
                        "sendmessage",
                    )
            else:
                with locked_state(
                    owner_session_id
                ) as owner_state:
                    if (
                        owner_state
                        is not None
                    ):
                        record_teammate_result(
                            owner_state,
                            teammate_name,
                            owner_task_id,
                            "sendmessage",
                        )

            released, _ = (
                release_reported_teammate_to_idle(
                    owner_session_id,
                    teammate_name,
                )
            )

            if not released:
                return (
                    PENDING_RESULT_FEEDBACK
                )

            _clear_merchant_resolution_after_release(
                session_id,
                teammate_name,
            )

            # Clear transient raw-token proposal only after successful
            # lifecycle reconciliation. SendMessage receipt is cleared in
            # the same successful path.
            if session_id:
                if merchant_proposal_captured:
                    clear_pending_merchant_proposal(
                        session_id
                    )

                clear_pending_merchant_completeness(
                    session_id
                )

                clear_pending_result(
                    session_id
                )
            return ""

    current_task_id = (
        active_task_id(
            session_id,
            teammate_name,
        )
    )

    if current_task_id:
        if (
            task_id
            and task_id
            != current_task_id
        ):
            return ""

        task_id = (
            current_task_id
        )

    if not (
        teammate_name
        and task_id
    ):
        return ""

    if state is None:
        return (
            MISSING_RESULT_FEEDBACK
        )

    run_id = state.get(
        "run_id",
        "",
    )

    ledger = state.get(
        "result_ledger",
        {},
    )

    dedup_key = (
        f"{run_id}:"
        f"{task_id}:"
        f"{teammate_name}"
    )

    result_already_received = (
        dedup_key in ledger
        and ledger[
            dedup_key
        ].get(
            "result_received"
        )
    )

    if result_already_received:
        if session_id:
            mark_report_received(
                session_id,
                teammate_name,
                task_id,
                "sendmessage",
            )

            released, _ = (
                release_reported_teammate_to_idle(
                    session_id,
                    teammate_name,
                )
            )

            if released:
                _clear_merchant_resolution_after_release(
                    session_id,
                    teammate_name,
                )

            if not released:
                team_state = (
                    load_team_state(
                        session_id
                    )
                )

                teammate_record = None

                if isinstance(
                    team_state,
                    dict,
                ):
                    teammate_record = (
                        team_state.get(
                            "teammates",
                            {},
                        )
                    ).get(
                        teammate_name
                    )

                if isinstance(
                    teammate_record,
                    dict,
                ):
                    return (
                        PENDING_RESULT_FEEDBACK
                    )

        return ""

    recovery_is_new = (
        mark_recovery_sent(
            state,
            teammate_name,
            task_id,
        )
    )

    return (
        MISSING_RESULT_FEEDBACK
        if recovery_is_new
        else PENDING_RESULT_FEEDBACK
    )


def merchant_report_sender(
    payload: dict[str, Any],
) -> str:
    """Resolve sender only from harness-authenticated PostToolUse fields."""
    return (
        trusted_post_tool_sender(
            payload
        )
    )


def embedded_json_objects(
    text: str,
) -> list[Any]:
    """Return every JSON object embedded in a teammate report body."""
    decoder = (
        json.JSONDecoder()
    )

    objects: list[Any] = []

    index = text.find(
        "{"
    )

    while (
        index != -1
    ):
        try:
            value, end = (
                decoder.raw_decode(
                    text,
                    index,
                )
            )
        except ValueError:
            index = text.find(
                "{",
                index + 1,
            )
            continue

        if isinstance(
            value,
            dict,
        ):
            objects.append(
                value
            )

            index = text.find(
                "{",
                max(
                    end,
                    index + 1,
                ),
            )
        else:
            index = text.find(
                "{",
                index + 1,
            )

    return objects


def merchant_proposal_candidate_from_message(
    message: str,
) -> dict[str, Any] | None:
    """Parse the legacy/direct machine-readable proposal block.

    For tmux Gate 11I this is no longer proposal authority. It remains for
    authenticated direct teammates and compatibility tests.
    """
    report = str(
        message
        or ""
    ).strip()

    if (
        report.count(
            MERCHANT_PROPOSAL_RESULT_MARKER
        )
        != 1
    ):
        return None

    _, encoded = (
        report.split(
            MERCHANT_PROPOSAL_RESULT_MARKER,
            1,
        )
    )

    encoded = (
        encoded.strip()
    )

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

    if (
        encoded[
            end:
        ].strip()
    ):
        return None

    if not isinstance(
        candidate,
        dict,
    ):
        return None

    if not str(
        candidate.get(
            "confirmation_token"
        )
        or ""
    ).strip():
        return None

    return candidate


def capture_merchant_proposal_from_message(
    state: dict[str, Any],
    session_id: Any,
    teammate_name: str,
    message: str,
) -> bool:
    """Capture proposal from an authenticated direct teammate report."""
    if (
        teammate_name
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    operations = [
        str(
            operation
        )
        for operation in (
            state.get(
                "operations"
            )
            or []
        )
    ]

    selected_agents = [
        str(
            agent
        )
        for agent in (
            state.get(
                "selected_agents"
            )
            or []
        )
    ]

    if (
        operations
        != [
            MERCHANT_PROPOSE_OPERATION
        ]
    ):
        return False

    if (
        selected_agents
        != [
            MERCHANT_MANAGER_AGENT
        ]
    ):
        return False

    report = str(
        message or ""
    ).strip()

    if not report:
        return False

    candidate = (
        merchant_proposal_candidate_from_message(
            message
        )
    )

    if (
        candidate
        is None
    ):
        return False

    return (
        capture_proposal_receipt(
            session_id,
            candidate,
        ).accepted
    )


def handle_merchant_proposal_receipt(
    state: dict[str, Any],
    payload: dict[str, Any],
    session_id: Any = None,
) -> bool:
    """Compatibility path for authenticated direct merchant-manager reports.

    Pane-backed tmux Merchant proposal authority is handled by Gate 11I exact
    CLI staging + trusted TeammateIdle reconciliation instead.
    """
    if (
        str(
            payload.get(
                "tool_name"
            )
            or ""
        ).strip()
        != "SendMessage"
    ):
        return False

    tool_input = (
        payload.get(
            "tool_input"
        )
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return False

    if (
        _coalesced_text(
            tool_input,
            "recipient",
            "to",
        )
        != "team-lead"
    ):
        return False

    teammate_name = (
        merchant_report_sender(
            payload
        )
    )

    if (
        teammate_name
        != MERCHANT_MANAGER_AGENT
    ):
        return False

    # Gate 11H: content/message are not aliases.
    message = (
        send_message_body(
            tool_input
        )
    )

    if not message:
        return False

    return (
        capture_merchant_proposal_from_message(
            state,
            session_id,
            teammate_name,
            message,
        )
    )


def main() -> int:
    try:
        payload = (
            json.load(
                sys.stdin
            )
        )
    except (
        json.JSONDecodeError,
        ValueError,
    ):
        return 0

    if not isinstance(
        payload,
        dict,
    ):
        return 0

    hook_event = str(
        payload.get(
            "hook_event_name"
        )
        or ""
    ).strip()

    session_id = (
        payload.get(
            "session_id"
        )
    )

    if (
        hook_event
        not in HOOK_EVENT_NAMES
    ):
        return 0

    idle_feedback = ""

    with locked_state(
        session_id
    ) as state:
        if (
            hook_event
            == "PostToolUse"
        ):
            handle_post_tool_use(
                state,
                payload,
                session_id,
            )

            # Direct authenticated teammate compatibility path only.
            # tmux Gate 11I does not trust SendMessage as proposal-token
            # authority.
            if (
                state
                is not None
            ):
                handle_merchant_proposal_receipt(
                    state,
                    payload,
                    session_id,
                )

        elif (
            hook_event
            == "TeammateIdle"
        ):
            idle_feedback = (
                handle_teammate_idle(
                    state,
                    payload,
                    session_id,
                )
            )

    if idle_feedback:
        print(
            idle_feedback,
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
