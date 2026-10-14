"""Bind Merchant Direct Execute to an active teammate task."""

from __future__ import annotations

import hashlib
import json

from claude.hooks.team_lifecycle import (
    trusted_teammate_pane_session_matches,
)


class DirectExecutionBindingError(PermissionError):
    """A Direct Execute request lacks active task authority."""


def bind_merchant_execute(
    *,
    owner_session_id: str,
    teammate_name: str,
    pane_session_id: str,
    run_id: str,
    task_id: str,
    write_id: str,
    command: str,
) -> str:
    """
    Return a stable operation key for one authorized write.

    Identifiers must originate from trusted orchestration,
    not from agent-supplied SendMessage or shell output.
    """

    values = (
        owner_session_id,
        teammate_name,
        pane_session_id,
        run_id,
        task_id,
        write_id,
        command,
    )

    if any(
        not isinstance(value, str) or not value.strip()
        for value in values
    ):
        raise DirectExecutionBindingError(
            "Incomplete execution binding"
        )

    if teammate_name != "merchant-manager":
        raise DirectExecutionBindingError(
            "Unauthorized teammate"
        )

    if command != "merchant create":
        raise DirectExecutionBindingError(
            "Command is not enabled for protected execution"
        )

    accepted, reason = trusted_teammate_pane_session_matches(
        owner_session_id,
        teammate_name,
        pane_session_id,
        run_id,
        task_id,
        required_operation="merchant_execute",
    )

    if not accepted:
        raise DirectExecutionBindingError(
            f"Lifecycle authority denied: {reason}"
        )

    identity = json.dumps(
        {
            "owner_session_id": owner_session_id,
            "teammate_name": teammate_name,
            "run_id": run_id,
            "task_id": task_id,
            "write_id": write_id,
            "command": command,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    digest = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()

    return f"merchant-direct:v1:{digest}"
