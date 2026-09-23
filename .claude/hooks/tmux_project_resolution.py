#!/usr/bin/env python3
"""Transient exact Project resolution receipts for tmux teammates.

A project-resolution receipt preserves the exact JSON emitted by:

    project resolve --merchant-id <uuid> --query <value>

between PostToolUse staging and later trusted lifecycle/policy reconciliation.

This module does not grant write authority and does not call the Merchant CLI.

Security boundary:
- PostToolUse may stage exact project-resolver output only.
- Project resolution is always bound to one trusted merchant_id.
- Resolution output is validated before persistence.
- Receipt is bound to pane + owner + teammate + run + task + merchant.
- Candidate projects must belong to the same trusted merchant.
- Receipts are short-lived and cleared after successful reconciliation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout


CLAUDE_DIR = Path(__file__).resolve().parents[1]

PENDING_PROJECT_RESOLUTION_DIR = (
    CLAUDE_DIR
    / "runtime"
    / "pending_project_resolutions"
)

PROJECT_RESOLUTION_DIR_ENV = (
    "CLAUDE_PENDING_PROJECT_RESOLUTION_DIR"
)

PROJECT_RESOLUTION_TTL_SECONDS = 3600
LOCK_TIMEOUT_SECONDS = 10.0

RECEIPT_FIELDS = frozenset(
    {
        "pane_session_id",
        "owner_session_id",
        "teammate_name",
        "run_id",
        "task_id",
        "merchant_id",
        "tool_use_id",
        "resolution",
        "created_at",
    }
)

BINDING_TEXT_FIELDS = (
    "pane_session_id",
    "owner_session_id",
    "teammate_name",
    "run_id",
    "task_id",
    "tool_use_id",
)

RESOLUTION_FIELDS = frozenset(
    {
        "success",
        "mode",
        "query",
        "merchant_id",
        "status",
        "match_kind",
        "resolved",
        "project_id",
        "title",
        "project_type",
        "workflow_variant",
        "project_status",
        "version",
        "candidates",
    }
)

CANDIDATE_FIELDS = frozenset(
    {
        "project_id",
        "merchant_id",
        "title",
        "project_type",
        "workflow_variant",
        "status",
        "version",
    }
)

RESOLUTION_STATUSES = frozenset(
    {
        "RESOLVED",
        "AMBIGUOUS",
        "NOT_FOUND",
    }
)

MATCH_KINDS = frozenset(
    {
        "UUID",
        "TITLE",
        "CANDIDATE",
        "NONE",
    }
)

RESOLVED_MATCH_KINDS = frozenset(
    {
        "UUID",
        "TITLE",
        "CANDIDATE",
    }
)

AMBIGUOUS_MATCH_KINDS = frozenset(
    {
        "TITLE",
        "CANDIDATE",
    }
)


def pending_project_resolution_dir() -> Path:
    override = os.environ.get(
        PROJECT_RESOLUTION_DIR_ENV
    )

    return (
        Path(override)
        if override
        else PENDING_PROJECT_RESOLUTION_DIR
    )


def _session_key(session_id: Any) -> str:
    value = _clean_text(session_id)

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def pending_project_resolution_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_project_resolution_dir()
        / f"{_session_key(pane_session_id)}.json"
    )


def pending_project_resolution_lock_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_project_resolution_dir()
        / f"{_session_key(pane_session_id)}.lock"
    )


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _nonempty_exact_text(
    value: Any,
) -> str | None:
    if not isinstance(value, str):
        return None

    cleaned = value.strip()

    if not cleaned or cleaned != value:
        return None

    return cleaned


def _optional_exact_text(
    value: Any,
) -> str | None | object:
    if value is None:
        return None

    cleaned = _nonempty_exact_text(value)

    if cleaned is None:
        return _INVALID

    return cleaned


def _canonical_uuid_text(
    value: Any,
) -> str | None:
    if not isinstance(value, str) or not value:
        return None

    try:
        canonical = str(uuid.UUID(value))
    except (
        AttributeError,
        TypeError,
        ValueError,
    ):
        return None

    if canonical != value:
        return None

    return canonical


def _optional_positive_integer(
    value: Any,
) -> int | None | object:
    if value is None:
        return None

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
    ):
        return _INVALID

    return value


_INVALID = object()


def _validate_candidate(
    value: Any,
    *,
    trusted_merchant_id: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    if set(value) != CANDIDATE_FIELDS:
        return None

    project_id = _canonical_uuid_text(
        value.get("project_id")
    )
    merchant_id = _canonical_uuid_text(
        value.get("merchant_id")
    )

    if (
        project_id is None
        or merchant_id is None
        or merchant_id != trusted_merchant_id
    ):
        return None

    title = _optional_exact_text(
        value.get("title")
    )
    project_type = _optional_exact_text(
        value.get("project_type")
    )
    workflow_variant = _optional_exact_text(
        value.get("workflow_variant")
    )
    status = _optional_exact_text(
        value.get("status")
    )
    version = _optional_positive_integer(
        value.get("version")
    )

    if any(
        item is _INVALID
        for item in (
            title,
            project_type,
            workflow_variant,
            status,
            version,
        )
    ):
        return None

    return {
        "project_id": project_id,
        "merchant_id": merchant_id,
        "title": title,
        "project_type": project_type,
        "workflow_variant": workflow_variant,
        "status": status,
        "version": version,
    }


def _validate_candidates(
    value: Any,
    *,
    trusted_merchant_id: str,
) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None

    validated: list[dict[str, Any]] = []
    seen_project_ids: set[str] = set()

    for candidate in value:
        normalized = _validate_candidate(
            candidate,
            trusted_merchant_id=trusted_merchant_id,
        )

        if normalized is None:
            return None

        project_id = normalized["project_id"]

        if project_id in seen_project_ids:
            return None

        seen_project_ids.add(project_id)
        validated.append(normalized)

    if [
        candidate["project_id"]
        for candidate in validated
    ] != sorted(
        candidate["project_id"]
        for candidate in validated
    ):
        return None

    return validated


def validate_project_resolution_result(
    value: Any,
) -> dict[str, Any] | None:
    """Validate one exact machine-readable `project resolve` result."""

    if not isinstance(value, dict):
        return None

    if set(value) != RESOLUTION_FIELDS:
        return None

    if value.get("success") is not True:
        return None

    if value.get("mode") != "PROJECT_RESOLUTION":
        return None

    query = _nonempty_exact_text(
        value.get("query")
    )

    if query is None:
        return None

    merchant_id = _canonical_uuid_text(
        value.get("merchant_id")
    )

    if merchant_id is None:
        return None

    status = value.get("status")

    if (
        not isinstance(status, str)
        or status not in RESOLUTION_STATUSES
    ):
        return None

    match_kind = value.get("match_kind")

    if (
        not isinstance(match_kind, str)
        or match_kind not in MATCH_KINDS
    ):
        return None

    resolved = value.get("resolved")

    if not isinstance(resolved, bool):
        return None

    title = _optional_exact_text(
        value.get("title")
    )
    project_type = _optional_exact_text(
        value.get("project_type")
    )
    workflow_variant = _optional_exact_text(
        value.get("workflow_variant")
    )
    project_status = _optional_exact_text(
        value.get("project_status")
    )
    version = _optional_positive_integer(
        value.get("version")
    )

    if any(
        item is _INVALID
        for item in (
            title,
            project_type,
            workflow_variant,
            project_status,
            version,
        )
    ):
        return None

    candidates = _validate_candidates(
        value.get("candidates"),
        trusted_merchant_id=merchant_id,
    )

    if candidates is None:
        return None

    project_id_value = value.get("project_id")

    if status == "RESOLVED":
        if resolved is not True:
            return None

        if match_kind not in RESOLVED_MATCH_KINDS:
            return None

        project_id = _canonical_uuid_text(
            project_id_value
        )

        if project_id is None:
            return None

        if len(candidates) != 1:
            return None

        expected_candidate = {
            "project_id": project_id,
            "merchant_id": merchant_id,
            "title": title,
            "project_type": project_type,
            "workflow_variant": workflow_variant,
            "status": project_status,
            "version": version,
        }

        if candidates[0] != expected_candidate:
            return None

    elif status == "AMBIGUOUS":
        if resolved is not False:
            return None

        if match_kind not in AMBIGUOUS_MATCH_KINDS:
            return None

        if project_id_value is not None:
            return None

        if any(
            item is not None
            for item in (
                title,
                project_type,
                workflow_variant,
                project_status,
                version,
            )
        ):
            return None

        if len(candidates) < 2:
            return None

    elif status == "NOT_FOUND":
        if resolved is not False:
            return None

        if match_kind != "NONE":
            return None

        if project_id_value is not None:
            return None

        if any(
            item is not None
            for item in (
                title,
                project_type,
                workflow_variant,
                project_status,
                version,
            )
        ):
            return None

        if candidates:
            return None

    else:  # pragma: no cover
        return None

    return value


def stage_pending_project_resolution(
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    merchant_id: Any,
    resolution: dict[str, Any],
    tool_use_id: Any,
) -> bool:
    """Atomically stage one exact project-resolver result."""

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
        "run_id": _clean_text(run_id),
        "task_id": _clean_text(task_id),
        "tool_use_id": _clean_text(
            tool_use_id
        ),
    }

    if any(
        not binding[field]
        for field in BINDING_TEXT_FIELDS
    ):
        return False

    trusted_merchant_id = _canonical_uuid_text(
        merchant_id
    )

    if trusted_merchant_id is None:
        return False

    validated = validate_project_resolution_result(
        resolution
    )

    if validated is None:
        return False

    if (
        validated.get("merchant_id")
        != trusted_merchant_id
    ):
        return False

    directory = pending_project_resolution_dir()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = pending_project_resolution_path(
        binding["pane_session_id"]
    )

    lock = FileLock(
        str(
            pending_project_resolution_lock_path(
                binding["pane_session_id"]
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    payload = {
        **binding,
        "merchant_id": trusted_merchant_id,
        "resolution": validated,
        "created_at": time.time(),
    }

    temporary: Path | None = None

    try:
        with lock:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=destination.name + ".",
                suffix=".tmp",
                dir=str(directory),
            )

            temporary = Path(temporary_name)

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
                os.fsync(handle.fileno())

            os.replace(
                temporary,
                destination,
            )
            temporary = None
            return True

    except (
        Timeout,
        OSError,
    ):
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


def load_pending_project_resolution(
    pane_session_id: Any,
) -> dict[str, Any] | None:
    """Load one unexpired exact project-resolution receipt."""

    pane_id = _clean_text(pane_session_id)

    if not pane_id:
        return None

    path = pending_project_resolution_path(
        pane_id
    )

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(payload, dict):
        return None

    if set(payload) != RECEIPT_FIELDS:
        return None

    for field in BINDING_TEXT_FIELDS:
        if (
            _nonempty_exact_text(
                payload.get(field)
            )
            is None
        ):
            return None

    if payload.get("pane_session_id") != pane_id:
        return None

    merchant_id = _canonical_uuid_text(
        payload.get("merchant_id")
    )

    if merchant_id is None:
        return None

    created_at = payload.get("created_at")

    if (
        isinstance(created_at, bool)
        or not isinstance(
            created_at,
            (int, float),
        )
    ):
        return None

    age = time.time() - float(created_at)

    if (
        age < 0
        or age > PROJECT_RESOLUTION_TTL_SECONDS
    ):
        return None

    resolution = validate_project_resolution_result(
        payload.get("resolution")
    )

    if resolution is None:
        return None

    if resolution.get("merchant_id") != merchant_id:
        return None

    return payload


def pending_project_resolution_matches(
    payload: Any,
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    merchant_id: Any,
) -> bool:
    """Exact-match a receipt to pane/owner/run/task/merchant identity."""

    if not isinstance(payload, dict):
        return False

    trusted_merchant_id = _canonical_uuid_text(
        merchant_id
    )

    if trusted_merchant_id is None:
        return False

    expected = {
        "pane_session_id": _clean_text(
            pane_session_id
        ),
        "owner_session_id": _clean_text(
            owner_session_id
        ),
        "teammate_name": _clean_text(
            teammate_name
        ),
        "run_id": _clean_text(run_id),
        "task_id": _clean_text(task_id),
        "merchant_id": trusted_merchant_id,
    }

    if any(
        not value
        for value in expected.values()
    ):
        return False

    if not all(
        payload.get(field) == value
        for field, value in expected.items()
    ):
        return False

    resolution = validate_project_resolution_result(
        payload.get("resolution")
    )

    return (
        resolution is not None
        and resolution.get("merchant_id")
        == trusted_merchant_id
    )


# Descriptive alias used by later policy/lifecycle gates.
project_resolution_receipt_matches = (
    pending_project_resolution_matches
)


def clear_pending_project_resolution(
    pane_session_id: Any,
) -> bool:
    """Remove one transient project-resolution receipt."""

    pane_id = _clean_text(pane_session_id)

    if not pane_id:
        return False

    directory = pending_project_resolution_dir()
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock = FileLock(
        str(
            pending_project_resolution_lock_path(
                pane_id
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    try:
        with lock:
            try:
                pending_project_resolution_path(
                    pane_id
                ).unlink()
            except FileNotFoundError:
                return False

            return True

    except (
        Timeout,
        OSError,
    ):
        return False