"""Merchant resolution-chain cleanup.

Clears task-scoped child evidence before parent evidence while preserving
the original fail-closed release ordering.
"""

from __future__ import annotations

from typing import Any

try:
    from merchant_resolution_tool_contract import (
        ResidualMerchantDependencies,
    )
except ImportError:
    from .merchant_resolution_tool_contract import (
        ResidualMerchantDependencies,
    )


def _clear_merchant_resolution_after_release(
    session_id: Any,
    teammate_name: str,
    dependencies: ResidualMerchantDependencies | None = None,
) -> None:
    """Clear the task-scoped entity-resolution chain after release."""

    if dependencies is None:
        raise RuntimeError(
            "Merchant resolution dependencies are required"
        )

    MERCHANT_MANAGER_AGENT = (
        dependencies.MERCHANT_MANAGER_AGENT
    )

    clear_pending_document_revision_resolution = (
        dependencies.clear_pending_document_revision_resolution
    )

    clear_pending_merchant_resolution = (
        dependencies.clear_pending_merchant_resolution
    )

    clear_pending_project_resolution = (
        dependencies.clear_pending_project_resolution
    )

    clear_pending_step_resolution = (
        dependencies.clear_pending_step_resolution
    )

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

    # Clear child evidence before parent evidence.
    #
    # No Step receipt may survive without its Project parent,
    # and no Project receipt may survive without its Merchant parent.
    clear_pending_document_revision_resolution(
        pane_session_id
    )

    clear_pending_step_resolution(
        pane_session_id
    )

    clear_pending_project_resolution(
        pane_session_id
    )

    clear_pending_merchant_resolution(
        pane_session_id
    )
