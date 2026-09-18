#!/usr/bin/env python3
"""Transient exact Merchant proposal receipts for tmux-backed teammates.

This store is intentionally short-lived. It may contain the raw Merchant
confirmation_token because the exact CLI proposal has to survive from the
Merchant CLI PostToolUse event until the trusted TeammateIdle event.

Security boundary:
- PostToolUse may stage only; it must not authorize or persist LOCAL_AUTO state.
- TeammateIdle supplies the trusted teammate identity.
- Callers must exact-match owner_session_id + teammate_name + run_id + task_id
  before consuming the staged proposal.
- The file must be cleared after successful reconciliation.
- Long-lived merchant_confirmation state must never persist confirmation_token.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout


CLAUDE_DIR = Path(__file__).resolve().parents[1]

DEFAULT_PENDING_MERCHANT_PROPOSAL_DIR = (
    CLAUDE_DIR
    / "runtime"
    / "pending_merchant_proposals"
)

PENDING_MERCHANT_PROPOSAL_DIR_ENV_VAR = (
    "CLAUDE_PENDING_MERCHANT_PROPOSAL_DIR"
)

LOCK_TIMEOUT_SECONDS = 10.0
MAX_PROPOSAL_AGE_SECONDS = 3600

REQUIRED_BINDING_FIELDS = (
    "pane_session_id",
    "owner_session_id",
    "teammate_name",
    "run_id",
    "task_id",
)


def pending_merchant_proposal_dir() -> Path:
    override = os.environ.get(
        PENDING_MERCHANT_PROPOSAL_DIR_ENV_VAR
    )

    return (
        Path(override)
        if override
        else DEFAULT_PENDING_MERCHANT_PROPOSAL_DIR
    )


def _session_key(session_id: Any) -> str:
    value = str(session_id or "").strip()

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def pending_merchant_proposal_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_merchant_proposal_dir()
        / f"{_session_key(pane_session_id)}.json"
    )


def pending_merchant_proposal_lock_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_merchant_proposal_dir()
        / f"{_session_key(pane_session_id)}.lock"
    )


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _proposal_shape_is_usable(
    proposal: Any,
) -> bool:
    """Minimal defense in depth; full validation belongs to the caller."""

    if not isinstance(proposal, dict):
        return False

    if proposal.get("success") is not True:
        return False

    if proposal.get("mode") != "PROPOSE":
        return False

    if proposal.get("database") != "runtime":
        return False

    token = proposal.get("confirmation_token")

    return (
        isinstance(token, str)
        and bool(token.strip())
    )


def stage_pending_merchant_proposal(
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    proposal: dict[str, Any],
    tool_use_id: Any = "",
) -> bool:
    """Atomically stage one exact CLI proposal for later trusted reconciliation."""

    binding = {
        "pane_session_id": _clean_text(
            pane_session_id
        ),
        "owner_session_id": _clean_text(
            owner_session_id
        ),
        "teammate_name": _clean_text(
            teammate_name
        ),
        "run_id": _clean_text(
            run_id
        ),
        "task_id": _clean_text(
            task_id
        ),
    }

    if any(
        not binding[field]
        for field in REQUIRED_BINDING_FIELDS
    ):
        return False

    if not _proposal_shape_is_usable(
        proposal
    ):
        return False

    directory = pending_merchant_proposal_dir()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        pending_merchant_proposal_path(
            binding["pane_session_id"]
        )
    )

    lock = FileLock(
        str(
            pending_merchant_proposal_lock_path(
                binding["pane_session_id"]
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    payload = {
        **binding,
        "tool_use_id": _clean_text(
            tool_use_id
        ),
        "proposal": proposal,
        "created_at": time.time(),
    }

    temporary: Path | None = None

    try:
        with lock:
            descriptor, temporary_name = (
                tempfile.mkstemp(
                    prefix=(
                        destination.name
                        + "."
                    ),
                    suffix=".tmp",
                    dir=str(directory),
                )
            )

            temporary = Path(
                temporary_name
            )

            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(
                    handle.fileno()
                )

            os.replace(
                temporary,
                destination,
            )

            temporary = None
            return True

    except (Timeout, OSError):
        return False

    finally:
        if (
            temporary is not None
            and temporary.exists()
        ):
            try:
                temporary.unlink()
            except OSError:
                pass


def load_pending_merchant_proposal(
    pane_session_id: Any,
) -> dict[str, Any] | None:
    """Load one unexpired staged proposal without trusting it as authority."""

    pane_id = _clean_text(
        pane_session_id
    )

    if not pane_id:
        return None

    path = pending_merchant_proposal_path(
        pane_id
    )

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(payload, dict):
        return None

    for field in REQUIRED_BINDING_FIELDS:
        if not _clean_text(
            payload.get(field)
        ):
            return None

    if (
        payload.get("pane_session_id")
        != pane_id
    ):
        return None

    created_at = payload.get(
        "created_at"
    )

    try:
        age = (
            time.time()
            - float(created_at)
        )
    except (TypeError, ValueError):
        return None

    if (
        age < 0
        or age > MAX_PROPOSAL_AGE_SECONDS
    ):
        return None

    proposal = payload.get(
        "proposal"
    )

    if not _proposal_shape_is_usable(
        proposal
    ):
        return None

    return payload


def pending_merchant_proposal_matches(
    payload: Any,
    *,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
) -> bool:
    """Exact-match a staged proposal to the trusted owner/run/task identity."""

    if not isinstance(payload, dict):
        return False

    expected = {
        "owner_session_id": _clean_text(
            owner_session_id
        ),
        "teammate_name": _clean_text(
            teammate_name
        ),
        "run_id": _clean_text(
            run_id
        ),
        "task_id": _clean_text(
            task_id
        ),
    }

    if any(
        not value
        for value in expected.values()
    ):
        return False

    return all(
        _clean_text(
            payload.get(field)
        )
        == value
        for field, value in expected.items()
    )


def clear_pending_merchant_proposal(
    pane_session_id: Any,
) -> bool:
    """Remove the transient exact proposal, including its raw token."""

    pane_id = _clean_text(
        pane_session_id
    )

    if not pane_id:
        return False

    directory = pending_merchant_proposal_dir()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock = FileLock(
        str(
            pending_merchant_proposal_lock_path(
                pane_id
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    try:
        with lock:
            try:
                pending_merchant_proposal_path(
                    pane_id
                ).unlink()
            except FileNotFoundError:
                return False

            return True
    except (Timeout, OSError):
        return False
