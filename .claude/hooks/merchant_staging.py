"""Trusted Merchant teammate staging.

This module owns the transient Merchant resolution, proposal, and
completeness staging paths plus trusted Merchant teammate context lookup.

The hook retains thin compatibility adapters so existing dependency
injection and monkeypatch seams remain stable.
"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
)

try:
    from merchant_confirmation_preferences import (
        MERCHANT_MANAGER_AGENT,
        MERCHANT_PROPOSE_OPERATION,
    )
except ModuleNotFoundError:
    from .merchant_confirmation_preferences import (
        MERCHANT_MANAGER_AGENT,
        MERCHANT_PROPOSE_OPERATION,
    )


MERCHANT_RESOLUTION_OPERATIONS = frozenset(
    {
        "merchant_read",
        "merchant_propose",
        "merchant_apply",
    }
)


class MerchantStagingDependencies:
    """Explicit dynamic dependencies for Merchant staging."""

    def __init__(
        self,
        *,
        trusted_post_tool_sender: Callable[..., Any],
        find_unique_active_teammate_owner: Callable[..., Any],
        stage_pending_merchant_resolution: Callable[..., Any],
        stage_pending_merchant_proposal: Callable[..., Any],
        stage_pending_merchant_completeness: Callable[..., Any],
    ) -> None:
        self.trusted_post_tool_sender = (
            trusted_post_tool_sender
        )
        self.find_unique_active_teammate_owner = (
            find_unique_active_teammate_owner
        )
        self.stage_pending_merchant_resolution = (
            stage_pending_merchant_resolution
        )
        self.stage_pending_merchant_proposal = (
            stage_pending_merchant_proposal
        )
        self.stage_pending_merchant_completeness = (
            stage_pending_merchant_completeness
        )


def _stage_exact_tmux_merchant_resolution(
    payload: dict[str, Any],
    session_id: Any,
    resolution: dict[str, Any],
    dependencies: MerchantStagingDependencies,
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
        dependencies.trusted_post_tool_sender(
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
        dependencies.find_unique_active_teammate_owner(
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
        dependencies.stage_pending_merchant_resolution(
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


def _trusted_tmux_merchant_stage_context(
    *,
    payload: dict[str, Any],
    session_id: Any,
    dependencies: MerchantStagingDependencies,
) -> tuple[
    str,
    str,
    str,
    str,
    str,
    list[str],
] | None:
    """Return trusted tmux Merchant task context for entity staging."""

    pane_session_id = str(
        session_id
        or ""
    ).strip()

    if not pane_session_id:
        return None

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
        return None

    authenticated_sender = (
        dependencies.trusted_post_tool_sender(
            payload
        )
    )

    if (
        authenticated_sender
        and authenticated_sender
        != MERCHANT_MANAGER_AGENT
    ):
        return None

    (
        owner_session_id,
        owner_record,
        owner_resolution,
    ) = (
        dependencies.find_unique_active_teammate_owner(
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
        return None

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
        return None

    authorized_operations = [
        str(
            operation
        ).strip()
        for operation
        in (
            owner_record.get(
                "authorized_operations"
            )
            or []
        )
        if str(
            operation
        ).strip()
    ]

    authorized_selected_agents = [
        str(
            agent
        ).strip()
        for agent
        in (
            owner_record.get(
                "authorized_selected_agents"
            )
            or []
        )
        if str(
            agent
        ).strip()
    ]

    if (
        len(
            authorized_operations
        )
        != 1
    ):
        return None

    if (
        authorized_operations[0]
        not in {
            "merchant_read",
            "merchant_propose",
            "merchant_apply",
        }
    ):
        return None

    if (
        authorized_selected_agents
        != [
            MERCHANT_MANAGER_AGENT
        ]
    ):
        return None

    return (
        pane_session_id,
        str(
            owner_session_id
        ).strip(),
        MERCHANT_MANAGER_AGENT,
        owner_run_id,
        owner_task_id,
        authorized_operations,
    )


def _stage_exact_tmux_merchant_proposal(
    payload: dict[str, Any],
    session_id: Any,
    proposal: dict[str, Any],
    dependencies: MerchantStagingDependencies,
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
        dependencies.trusted_post_tool_sender(
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
        dependencies.find_unique_active_teammate_owner(
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
        dependencies.stage_pending_merchant_proposal(
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
    dependencies: MerchantStagingDependencies,
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
        dependencies.trusted_post_tool_sender(
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
    ) = dependencies.find_unique_active_teammate_owner(
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

    return dependencies.stage_pending_merchant_completeness(
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
