"""Trusted Project, Document Revision, and Step resolution staging.

This module owns exact entity-resolution staging after the generic trusted
context and direct CLI invocation boundaries have passed.

Authority remains derived exclusively from bound Merchant / Project receipts.
No behavior is intentionally changed by this extraction.
"""

from __future__ import annotations

import json

from typing import (
    Any,
    Callable,
)


try:
    from resolution_cli_invocation import (
        parse_resolution_cli_invocation,
    )
    from resolution_staging_context import (
        resolution_stage_context,
    )
    from tmux_merchant_resolution import (
        load_pending_merchant_resolution,
        pending_merchant_resolution_matches,
    )
    from tmux_project_resolution import (
        load_pending_project_resolution,
        pending_project_resolution_matches,
        project_resolution_receipt_matches,
        stage_pending_project_resolution,
    )
    from tmux_document_revision_resolution import (
        stage_pending_document_revision_resolution,
    )
    from tmux_step_resolution import (
        stage_pending_step_resolution,
    )
except ModuleNotFoundError:
    from .resolution_cli_invocation import (
        parse_resolution_cli_invocation,
    )
    from .resolution_staging_context import (
        resolution_stage_context,
    )
    from .tmux_merchant_resolution import (
        load_pending_merchant_resolution,
        pending_merchant_resolution_matches,
    )
    from .tmux_project_resolution import (
        load_pending_project_resolution,
        pending_project_resolution_matches,
        project_resolution_receipt_matches,
        stage_pending_project_resolution,
    )
    from .tmux_document_revision_resolution import (
        stage_pending_document_revision_resolution,
    )
    from .tmux_step_resolution import (
        stage_pending_step_resolution,
    )



class ResolutionStagingDependencies:
    """Explicit authority/staging dependencies for resolution handlers."""

    def __init__(
        self,
        *,
        load_pending_merchant_resolution: Callable[..., Any],
        pending_merchant_resolution_matches: Callable[..., Any],
        load_pending_project_resolution: Callable[..., Any],
        pending_project_resolution_matches: Callable[..., Any],
        project_resolution_receipt_matches: Callable[..., Any],
        stage_pending_project_resolution: Callable[..., Any],
        stage_pending_document_revision_resolution: Callable[..., Any],
        stage_pending_step_resolution: Callable[..., Any],
    ) -> None:
        self.load_pending_merchant_resolution = (
            load_pending_merchant_resolution
        )
        self.pending_merchant_resolution_matches = (
            pending_merchant_resolution_matches
        )
        self.load_pending_project_resolution = (
            load_pending_project_resolution
        )
        self.pending_project_resolution_matches = (
            pending_project_resolution_matches
        )
        self.project_resolution_receipt_matches = (
            project_resolution_receipt_matches
        )
        self.stage_pending_project_resolution = (
            stage_pending_project_resolution
        )
        self.stage_pending_document_revision_resolution = (
            stage_pending_document_revision_resolution
        )
        self.stage_pending_step_resolution = (
            stage_pending_step_resolution
        )


DEFAULT_DEPENDENCIES = ResolutionStagingDependencies(
    load_pending_merchant_resolution=(
        load_pending_merchant_resolution
    ),
    pending_merchant_resolution_matches=(
        pending_merchant_resolution_matches
    ),
    load_pending_project_resolution=(
        load_pending_project_resolution
    ),
    pending_project_resolution_matches=(
        pending_project_resolution_matches
    ),
    project_resolution_receipt_matches=(
        project_resolution_receipt_matches
    ),
    stage_pending_project_resolution=(
        stage_pending_project_resolution
    ),
    stage_pending_document_revision_resolution=(
        stage_pending_document_revision_resolution
    ),
    stage_pending_step_resolution=(
        stage_pending_step_resolution
    ),
)



def _stage_exact_tmux_project_resolution(
    *,
    payload: dict[str, Any],
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    authorized_operations: Any,
    dependencies: ResolutionStagingDependencies = DEFAULT_DEPENDENCIES,
) -> bool:
    """Stage one exact Project resolution under a trusted Merchant binding."""

    context = resolution_stage_context(
        payload=payload,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        authorized_operations=authorized_operations,
    )

    if context is None:
        return False

    pane_id = context.pane_session_id
    owner_id = context.owner_session_id
    teammate = context.teammate_name
    owner_run_id = context.run_id
    owner_task_id = context.task_id

    invocation = parse_resolution_cli_invocation(
        payload,
        entity="project",
    )

    if invocation is None:
        return False

    query = invocation.query
    merchant_id = invocation.merchant_id

    if merchant_id is None:
        return False

    merchant_receipt = (
        dependencies.load_pending_merchant_resolution(
            pane_id
        )
    )

    if merchant_receipt is None:
        return False

    if not dependencies.pending_merchant_resolution_matches(
        merchant_receipt,
        owner_session_id=owner_id,
        teammate_name=teammate,
        run_id=owner_run_id,
        task_id=owner_task_id,
    ):
        return False

    merchant_resolution = (
        merchant_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        merchant_resolution,
        dict,
    ):
        return False

    if (
        merchant_resolution.get("status")
        != "RESOLVED"
    ):
        return False

    if (
        merchant_resolution.get("resolved")
        is not True
    ):
        return False

    trusted_merchant_id = str(
        merchant_resolution.get(
            "merchant_id"
        )
        or ""
    ).strip()

    if not trusted_merchant_id:
        return False

    if merchant_id != trusted_merchant_id:
        return False

    # -------------------------------------------------
    # Exact JSON stdout only.
    # -------------------------------------------------

    tool_response = payload.get(
        "tool_response"
    )

    if not isinstance(
        tool_response,
        dict,
    ):
        return False

    stdout = tool_response.get(
        "stdout"
    )

    if not isinstance(stdout, str):
        return False

    stdout = stdout.strip()

    if not stdout:
        return False

    try:
        project_resolution = json.loads(
            stdout
        )
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return False

    if not isinstance(
        project_resolution,
        dict,
    ):
        return False

    # -------------------------------------------------
    # Exact CLI command ↔ CLI result binding.
    # -------------------------------------------------

    if (
        project_resolution.get(
            "merchant_id"
        )
        != trusted_merchant_id
    ):
        return False

    if (
        project_resolution.get(
            "query"
        )
        != query
    ):
        return False

    tool_use_id = str(
        payload.get(
            "tool_use_id"
        )
        or ""
    ).strip()

    if not tool_use_id:
        return False

    # tmux_project_resolution performs the complete
    # RESOLVED / AMBIGUOUS / NOT_FOUND schema validation.
    return dependencies.stage_pending_project_resolution(
        pane_session_id=pane_id,
        owner_session_id=owner_id,
        teammate_name=teammate,
        run_id=owner_run_id,
        task_id=owner_task_id,
        merchant_id=trusted_merchant_id,
        resolution=project_resolution,
        tool_use_id=tool_use_id,
    )


def _stage_exact_tmux_document_revision_resolution(
    *,
    payload: dict[str, Any],
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    authorized_operations: Any,
    dependencies: ResolutionStagingDependencies = DEFAULT_DEPENDENCIES,
) -> bool:
    """Stage one exact Document Revision resolution under trusted parents."""

    context = resolution_stage_context(
        payload=payload,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        authorized_operations=authorized_operations,
    )

    if context is None:
        return False

    pane_id = context.pane_session_id
    owner_id = context.owner_session_id
    teammate = context.teammate_name
    owner_run_id = context.run_id
    owner_task_id = context.task_id

    invocation = parse_resolution_cli_invocation(
        payload,
        entity="document",
    )

    if invocation is None:
        return False

    query = invocation.query
    merchant_id = invocation.merchant_id
    project_id = invocation.project_id

    merchant_receipt = (
        dependencies.load_pending_merchant_resolution(
            pane_id
        )
    )

    if merchant_receipt is None:
        return False

    if not dependencies.pending_merchant_resolution_matches(
        merchant_receipt,
        owner_session_id=owner_id,
        teammate_name=teammate,
        run_id=owner_run_id,
        task_id=owner_task_id,
    ):
        return False

    merchant_resolution = (
        merchant_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        merchant_resolution,
        dict,
    ):
        return False

    if (
        merchant_resolution.get(
            "status"
        )
        != "RESOLVED"
        or merchant_resolution.get(
            "resolved"
        )
        is not True
    ):
        return False

    trusted_merchant_id = str(
        merchant_resolution.get(
            "merchant_id"
        )
        or ""
    ).strip()

    if not trusted_merchant_id:
        return False

    # -------------------------------------------------
    # Resolve parent scope.
    # -------------------------------------------------

    if merchant_id is not None:
        scope = "MERCHANT"
        trusted_project_id = None

        if (
            merchant_id
            != trusted_merchant_id
        ):
            return False

    else:
        scope = "PROJECT"

        project_receipt = (
            dependencies.load_pending_project_resolution(
                pane_id
            )
        )

        if project_receipt is None:
            return False

        if not dependencies.project_resolution_receipt_matches(
            project_receipt,
            pane_session_id=pane_id,
            owner_session_id=owner_id,
            teammate_name=teammate,
            run_id=owner_run_id,
            task_id=owner_task_id,
            merchant_id=trusted_merchant_id,
        ):
            return False

        project_resolution = (
            project_receipt.get(
                "resolution"
            )
        )

        if not isinstance(
            project_resolution,
            dict,
        ):
            return False

        if (
            project_resolution.get(
                "status"
            )
            != "RESOLVED"
            or project_resolution.get(
                "resolved"
            )
            is not True
        ):
            return False

        trusted_project_id = str(
            project_resolution.get(
                "project_id"
            )
            or ""
        ).strip()

        if not trusted_project_id:
            return False

        if (
            project_id
            != trusted_project_id
        ):
            return False

    # -------------------------------------------------
    # Exact JSON stdout.
    # -------------------------------------------------

    tool_response = payload.get(
        "tool_response"
    )

    if not isinstance(
        tool_response,
        dict,
    ):
        return False

    stdout = tool_response.get(
        "stdout"
    )

    if not isinstance(
        stdout,
        str,
    ):
        return False

    stdout = stdout.strip()

    if not stdout:
        return False

    try:
        resolution = json.loads(
            stdout
        )
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return False

    if not isinstance(
        resolution,
        dict,
    ):
        return False

    # -------------------------------------------------
    # CLI invocation ↔ exact output binding.
    # -------------------------------------------------

    if (
        resolution.get(
            "mode"
        )
        != "DOCUMENT_REVISION_RESOLUTION"
    ):
        return False

    if (
        resolution.get(
            "query"
        )
        != query
    ):
        return False

    if (
        resolution.get(
            "scope"
        )
        != scope
    ):
        return False

    if (
        resolution.get(
            "merchant_id"
        )
        != trusted_merchant_id
    ):
        return False

    if (
        resolution.get(
            "project_id"
        )
        != trusted_project_id
    ):
        return False

    tool_use_id = str(
        payload.get(
            "tool_use_id"
        )
        or ""
    ).strip()

    if not tool_use_id:
        return False

    return (
        dependencies.stage_pending_document_revision_resolution(
            pane_session_id=pane_id,
            owner_session_id=owner_id,
            teammate_name=teammate,
            run_id=owner_run_id,
            task_id=owner_task_id,
            merchant_id=trusted_merchant_id,
            project_id=trusted_project_id,
            scope=scope,
            resolution=resolution,
            tool_use_id=tool_use_id,
        )
    )


def _stage_exact_tmux_step_resolution(
    *,
    payload: dict[str, Any],
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    authorized_operations: Any,
    dependencies: ResolutionStagingDependencies = DEFAULT_DEPENDENCIES,
) -> bool:
    """Stage one exact Step resolution under trusted Merchant + Project bindings."""

    context = resolution_stage_context(
        payload=payload,
        pane_session_id=pane_session_id,
        owner_session_id=owner_session_id,
        teammate_name=teammate_name,
        run_id=run_id,
        task_id=task_id,
        authorized_operations=authorized_operations,
    )

    if context is None:
        return False

    pane_id = context.pane_session_id
    owner_id = context.owner_session_id
    teammate = context.teammate_name
    owner_run_id = context.run_id
    owner_task_id = context.task_id

    invocation = parse_resolution_cli_invocation(
        payload,
        entity="step",
    )

    if invocation is None:
        return False

    query = invocation.query
    project_id = invocation.project_id

    if project_id is None:
        return False

    merchant_receipt = (
        dependencies.load_pending_merchant_resolution(
            pane_id
        )
    )

    if merchant_receipt is None:
        return False

    if not (
        dependencies.pending_merchant_resolution_matches(
            merchant_receipt,
            owner_session_id=(
                owner_id
            ),
            teammate_name=(
                teammate
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
        )
    ):
        return False

    merchant_resolution = (
        merchant_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        merchant_resolution,
        dict,
    ):
        return False

    if (
        merchant_resolution.get(
            "status"
        )
        != "RESOLVED"
        or merchant_resolution.get(
            "resolved"
        )
        is not True
    ):
        return False

    trusted_merchant_id = str(
        merchant_resolution.get(
            "merchant_id"
        )
        or ""
    ).strip()

    if not trusted_merchant_id:
        return False

    # -------------------------------------------------
    # Parent 2: exact current-task Project receipt.
    #
    # Step receipt MUST NOT establish Project authority.
    # -------------------------------------------------

    project_receipt = (
        dependencies.load_pending_project_resolution(
            pane_id
        )
    )

    if project_receipt is None:
        return False

    if not (
        dependencies.pending_project_resolution_matches(
            project_receipt,
            pane_session_id=(
                pane_id
            ),
            owner_session_id=(
                owner_id
            ),
            teammate_name=(
                teammate
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            merchant_id=(
                trusted_merchant_id
            ),
        )
    ):
        return False

    project_resolution = (
        project_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        project_resolution,
        dict,
    ):
        return False

    if (
        project_resolution.get(
            "status"
        )
        != "RESOLVED"
        or project_resolution.get(
            "resolved"
        )
        is not True
    ):
        return False

    trusted_project_id = str(
        project_resolution.get(
            "project_id"
        )
        or ""
    ).strip()

    if not trusted_project_id:
        return False

    if (
        project_id
        != trusted_project_id
    ):
        return False

    # -------------------------------------------------
    # Exact JSON stdout only.
    # -------------------------------------------------

    tool_response = payload.get(
        "tool_response"
    )

    if not isinstance(
        tool_response,
        dict,
    ):
        return False

    stdout = tool_response.get(
        "stdout"
    )

    if not isinstance(
        stdout,
        str,
    ):
        return False

    stdout = stdout.strip()

    if not stdout:
        return False

    try:
        step_resolution = (
            json.loads(
                stdout
            )
        )
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return False

    if not isinstance(
        step_resolution,
        dict,
    ):
        return False

    # -------------------------------------------------
    # Exact command ↔ result binding.
    # -------------------------------------------------

    if (
        step_resolution.get(
            "project_id"
        )
        != trusted_project_id
    ):
        return False

    if (
        step_resolution.get(
            "query"
        )
        != query
    ):
        return False

    tool_use_id = str(
        payload.get(
            "tool_use_id"
        )
        or ""
    ).strip()

    if not tool_use_id:
        return False

    # tmux_step_resolution performs complete
    # RESOLVED / AMBIGUOUS / NOT_FOUND schema validation.
    return (
        dependencies.stage_pending_step_resolution(
            pane_session_id=(
                pane_id
            ),
            owner_session_id=(
                owner_id
            ),
            teammate_name=(
                teammate
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            merchant_id=(
                trusted_merchant_id
            ),
            project_id=(
                trusted_project_id
            ),
            resolution=(
                step_resolution
            ),
            tool_use_id=(
                tool_use_id
            ),
        )
    )
