"""Merchant runtime orchestration extracted from team_result_hook.

The functions in this module preserve the existing fail-closed runtime
handoff, proposal capture, completeness binding, and parsing behavior.

External hook dependencies are supplied explicitly so historical monkeypatch
and dependency-injection seams remain available through thin adapters.
"""

from __future__ import annotations

import shlex

from typing import Any


def _project_resolve_invocation(
    command: Any,
    dependencies: Any = None,
) -> tuple[str, str] | None:
    """Parse one exact direct project-resolve Merchant CLI invocation."""

    if dependencies is None:
        raise RuntimeError(
            "Merchant runtime dependencies are required"
        )

    shlex = (
        dependencies.shlex
    )

    if not isinstance(
        command,
        str,
    ):
        return None

    command = command.strip()

    if not command:
        return None

    # -------------------------------------------------
    # Tokenize while exposing shell control operators.
    #
    # Quoted text remains quoted data, while real:
    #
    # |  ||  &&  ;  >  >>  <
    #
    # becomes punctuation tokens and can be rejected.
    # -------------------------------------------------

    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars="|&;<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""

        tokens = list(lexer)

    except ValueError:
        return None

    if not tokens:
        return None

    forbidden_shell_tokens = {
        "|",
        "||",
        "&",
        "&&",
        ";",
        ">",
        ">>",
        "<",
        "<<",
    }

    if any(
        token in forbidden_shell_tokens
        for token in tokens
    ):
        return None

    # -------------------------------------------------
    # Find exactly one Merchant agent_cli.py.
    #
    # Supports:
    # python .claude/agents/tools/merchant/agent_cli.py
    # python.exe ...
    # .\.venv\Scripts\python.exe ...
    # -------------------------------------------------

    script_indexes = [
        index
        for index, token
        in enumerate(tokens)
        if (
            token.replace(
                "\\",
                "/",
            ).endswith(
                ".claude/agents/tools/"
                "merchant/agent_cli.py"
            )
        )
    ]

    if len(script_indexes) != 1:
        return None

    script_index = script_indexes[0]

    # agent_cli.py must not be the executable itself.
    if script_index == 0:
        return None

    executable = (
        tokens[
            script_index - 1
        ]
        .replace(
            "\\",
            "/",
        )
        .lower()
    )

    if not (
        executable == "python"
        or executable == "python.exe"
        or executable.endswith(
            "/python.exe"
        )
        or executable.endswith(
            "/python"
        )
    ):
        return None

    cli_tokens = tokens[
        script_index + 1:
    ]

    if (
        len(cli_tokens) < 4
        or cli_tokens[0:2]
        != [
            "project",
            "resolve",
        ]
    ):
        return None

    merchant_id: str | None = None
    query: str | None = None

    seen_merchant_id = False
    seen_query = False

    index = 2

    while index < len(
        cli_tokens
    ):
        token = cli_tokens[index]

        # ---------------------------------------------
        # --merchant-id VALUE
        # ---------------------------------------------

        if token == "--merchant-id":
            if (
                seen_merchant_id
                or index + 1
                >= len(cli_tokens)
            ):
                return None

            merchant_id = str(
                cli_tokens[
                    index + 1
                ]
            ).strip()

            if not merchant_id:
                return None

            seen_merchant_id = True
            index += 2
            continue

        # ---------------------------------------------
        # --merchant-id=VALUE
        # ---------------------------------------------

        if token.startswith(
            "--merchant-id="
        ):
            if seen_merchant_id:
                return None

            merchant_id = (
                token.split(
                    "=",
                    1,
                )[1]
                .strip()
            )

            if not merchant_id:
                return None

            seen_merchant_id = True
            index += 1
            continue

        # ---------------------------------------------
        # --query VALUE
        # ---------------------------------------------

        if token == "--query":
            if (
                seen_query
                or index + 1
                >= len(cli_tokens)
            ):
                return None

            query = str(
                cli_tokens[
                    index + 1
                ]
            ).strip()

            if not query:
                return None

            seen_query = True
            index += 2
            continue

        # ---------------------------------------------
        # --query=VALUE
        # ---------------------------------------------

        if token.startswith(
            "--query="
        ):
            if seen_query:
                return None

            query = (
                token.split(
                    "=",
                    1,
                )[1]
                .strip()
            )

            if not query:
                return None

            seen_query = True
            index += 1
            continue

        # Unknown / additional argument.
        return None

    if (
        merchant_id is None
        or query is None
    ):
        return None

    return (
        merchant_id,
        query,
    )


def prepare_merchant_runtime_handoff(
    payload: dict[str, Any],
    dependencies: Any = None,
) -> tuple[
    bool,
    PreparedRuntimeHandoff | None,
    str,
]:
    """Recognize, bind, and stage one non-terminal Gate 12H request.

    Returns:
        recognized:
            True when the message contains the handoff marker. This prevents
            the same SendMessage from falling through into terminal-result
            delivery.

        attempt:
            Prepared exact handoff when validation succeeds.

        reason:
            Bounded failure reason when the request is recognized but cannot
            be staged.
    """

    if dependencies is None:
        raise RuntimeError(
            "Merchant runtime dependencies are required"
        )

    MERCHANT_MANAGER_AGENT = (
        dependencies.MERCHANT_MANAGER_AGENT
    )

    _coalesced_text = (
        dependencies._coalesced_text
    )

    contains_handoff_marker = (
        dependencies.contains_handoff_marker
    )

    find_unique_active_teammate_owner = (
        dependencies.find_unique_active_teammate_owner
    )

    handoff_candidate_from_message = (
        dependencies.handoff_candidate_from_message
    )

    locked_state = (
        dependencies.locked_state
    )

    send_message_body = (
        dependencies.send_message_body
    )

    stage_runtime_handoff_attempt = (
        dependencies.stage_runtime_handoff_attempt
    )

    trusted_post_tool_sender = (
        dependencies.trusted_post_tool_sender
    )

    trusted_teammate_pane_session_matches = (
        dependencies.trusted_teammate_pane_session_matches
    )

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    if tool_name != "SendMessage":
        return (
            False,
            None,
            "",
        )

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return (
            False,
            None,
            "",
        )

    recipient = _coalesced_text(
        tool_input,
        "recipient",
        "to",
    )

    if recipient != "team-lead":
        return (
            False,
            None,
            "",
        )

    message = send_message_body(
        tool_input
    )

    if not contains_handoff_marker(
        message
    ):
        return (
            False,
            None,
            "",
        )

    # From this point onward the message is definitively a handoff attempt.
    # Never let malformed attempts fall through into terminal result delivery.
    candidate = (
        handoff_candidate_from_message(
            message
        )
    )

    if candidate is None:
        return (
            True,
            None,
            "MERCHANT_APPLY_HANDOFF_REQUEST_JSON is malformed",
        )

    authenticated_sender = (
        trusted_post_tool_sender(
            payload
        )
    )

    role_hint = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if authenticated_sender:
        if (
            authenticated_sender
            != MERCHANT_MANAGER_AGENT
        ):
            return (
                True,
                None,
                "handoff authenticated sender is not merchant-manager",
            )

        teammate_name = (
            authenticated_sender
        )

    else:
        # agent_type alone is NOT authority.
        #
        # It is used only to locate the exact canonical owner.
        # Runtime authority is established later by a previously
        # trusted pane binding + exact active run/task authorization.
        if (
            role_hint
            != MERCHANT_MANAGER_AGENT
        ):
            return (
                True,
                None,
                "handoff requires merchant-manager sender identity",
            )

        teammate_name = (
            MERCHANT_MANAGER_AGENT
        )

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
        != "FOUND"
        or not owner_session_id
        or not isinstance(
            owner_record,
            dict,
        )
    ):
        return (
            True,
            None,
            "no unique active lead session owns merchant-manager",
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

    owner_operations = [
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

    owner_selected_agents = [
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

    if not (
        owner_run_id
        and owner_task_id
    ):
        return (
            True,
            None,
            "merchant-manager has no active run/task binding",
        )

    if (
        owner_operations
        != [
            "merchant_apply"
        ]
        or owner_selected_agents
        != [
            MERCHANT_MANAGER_AGENT
        ]
    ):
        return (
            True,
            None,
            "merchant-manager lifecycle authority is not exact merchant_apply",
        )

    if not authenticated_sender:
        pane_session_id = str(
            payload.get(
                "session_id"
            )
            or ""
        ).strip()

        (
            trusted_pane,
            pane_reason,
        ) = (
            trusted_teammate_pane_session_matches(
                owner_session_id,
                teammate_name,
                pane_session_id,
                owner_run_id,
                owner_task_id,
                required_operation=(
                    "merchant_apply"
                ),
            )
        )

        if not trusted_pane:
            return (
                True,
                None,
                (
                    "handoff sender pane is not trusted for "
                    f"this merchant_apply task: {pane_reason}"
                ),
            )

    supplied_task_id = str(
        tool_input.get(
            "task_id"
        )
        or payload.get(
            "task_id"
        )
        or ""
    ).strip()

    if (
        supplied_task_id
        and supplied_task_id
        != owner_task_id
    ):
        return (
            True,
            None,
            "handoff task_id does not match the active teammate task",
        )

    attempt = None
    reason = ""

    with locked_state(
        owner_session_id
    ) as owner_state:
        if owner_state is None:
            return (
                True,
                None,
                "trusted owner run state is unavailable",
            )

        (
            attempt,
            reason,
        ) = (
            stage_runtime_handoff_attempt(
                owner_state,
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
                candidate=(
                    candidate
                ),
            )
        )

    return (
        True,
        attempt,
        reason,
    )


def bound_merchant_completeness_receipt(
    *,
    pane_session_id: str,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    dependencies: Any = None,
) -> dict[str, Any] | None:
    """Return completeness evidence only for the exact current task."""

    if dependencies is None:
        raise RuntimeError(
            "Merchant runtime dependencies are required"
        )

    load_pending_merchant_completeness = (
        dependencies.load_pending_merchant_completeness
    )

    pending_merchant_completeness_matches = (
        dependencies.pending_merchant_completeness_matches
    )

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


def capture_merchant_proposal_from_message(
    state: dict[str, Any],
    session_id: Any,
    teammate_name: str,
    message: str,
    dependencies: Any = None,
) -> bool:
    """Capture proposal from an authenticated direct teammate report."""

    if dependencies is None:
        raise RuntimeError(
            "Merchant runtime dependencies are required"
        )

    MERCHANT_MANAGER_AGENT = (
        dependencies.MERCHANT_MANAGER_AGENT
    )

    MERCHANT_PROPOSE_OPERATION = (
        dependencies.MERCHANT_PROPOSE_OPERATION
    )

    capture_proposal_receipt = (
        dependencies.capture_proposal_receipt
    )

    merchant_proposal_candidate_from_message = (
        dependencies.merchant_proposal_candidate_from_message
    )
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
    dependencies: Any = None,
) -> bool:
    """Compatibility path for authenticated direct merchant-manager reports.

    Pane-backed tmux Merchant proposal authority is handled by Gate 11I exact
    CLI staging + trusted TeammateIdle reconciliation instead.
    """

    if dependencies is None:
        raise RuntimeError(
            "Merchant runtime dependencies are required"
        )

    MERCHANT_MANAGER_AGENT = (
        dependencies.MERCHANT_MANAGER_AGENT
    )

    _coalesced_text = (
        dependencies._coalesced_text
    )

    capture_merchant_proposal_from_message = (
        dependencies.capture_merchant_proposal_from_message
    )

    merchant_report_sender = (
        dependencies.merchant_report_sender
    )

    send_message_body = (
        dependencies.send_message_body
    )
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
