#!/usr/bin/env python3
"""Transient exact Merchant resolution receipts for tmux teammates.

A resolution receipt preserves the exact JSON emitted by:

    merchant resolve --query <value>

between PostToolUse and later trusted lifecycle reconciliation.

This module does not grant write authority and does not call the Merchant CLI.

Security boundary:
- PostToolUse may stage exact resolver output only.
- Resolution output is validated before persistence.
- Receipt is bound to pane + owner + teammate + run + task.
- Consumers must exact-match the trusted owner/run/task identity.
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


CLAUDE_DIR = Path(
    __file__
).resolve().parents[1]

DEFAULT_PENDING_MERCHANT_RESOLUTION_DIR = (
    CLAUDE_DIR
    / "runtime"
    / "pending_merchant_resolutions"
)

PENDING_MERCHANT_RESOLUTION_DIR_ENV_VAR = (
    "CLAUDE_PENDING_MERCHANT_RESOLUTION_DIR"
)

LOCK_TIMEOUT_SECONDS = 10.0
MAX_RESOLUTION_AGE_SECONDS = 3600

REQUIRED_BINDING_FIELDS = (
    "pane_session_id",
    "owner_session_id",
    "teammate_name",
    "run_id",
    "task_id",
)

RESOLUTION_FIELDS = frozenset(
    {
        "success",
        "mode",
        "query",
        "status",
        "match_kind",
        "resolved",
        "merchant_id",
        "code",
        "name",
        "candidates",
    }
)

CANDIDATE_FIELDS = frozenset(
    {
        "merchant_id",
        "code",
        "name",
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
        "CODE",
        "NAME",
        "ALIAS",
        "CANDIDATE",
        "NONE",
    }
)


def pending_merchant_resolution_dir() -> Path:
    override = os.environ.get(
        PENDING_MERCHANT_RESOLUTION_DIR_ENV_VAR
    )

    return (
        Path(
            override
        )
        if override
        else DEFAULT_PENDING_MERCHANT_RESOLUTION_DIR
    )


def _session_key(
    session_id: Any,
) -> str:
    value = _clean_text(
        session_id
    )

    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


def pending_merchant_resolution_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_merchant_resolution_dir()
        / (
            f"{_session_key(pane_session_id)}"
            ".json"
        )
    )


def pending_merchant_resolution_lock_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_merchant_resolution_dir()
        / (
            f"{_session_key(pane_session_id)}"
            ".lock"
        )
    )


def _clean_text(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()


def _nonempty_text(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    cleaned = value.strip()

    if (
        not cleaned
        or cleaned != value
    ):
        return None

    return cleaned


def _canonical_uuid_text(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    if not value:
        return None

    try:
        canonical = str(
            uuid.UUID(
                value
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
    ):
        return None

    if canonical != value:
        return None

    return canonical


def _validate_candidates(
    value: Any,
) -> list[dict[str, str]] | None:
    if not isinstance(
        value,
        list,
    ):
        return None

    validated: list[
        dict[str, str]
    ] = []

    seen_ids: set[str] = set()

    for candidate in value:
        if not isinstance(
            candidate,
            dict,
        ):
            return None

        if (
            set(
                candidate
            )
            != CANDIDATE_FIELDS
        ):
            return None

        merchant_id = (
            _canonical_uuid_text(
                candidate.get(
                    "merchant_id"
                )
            )
        )

        code = _nonempty_text(
            candidate.get(
                "code"
            )
        )

        name = _nonempty_text(
            candidate.get(
                "name"
            )
        )

        if (
            merchant_id is None
            or code is None
            or name is None
        ):
            return None

        if merchant_id in seen_ids:
            return None

        seen_ids.add(
            merchant_id
        )

        validated.append(
            {
                "merchant_id": merchant_id,
                "code": code,
                "name": name,
            }
        )

    return validated


def validate_merchant_resolution_result(
    value: Any,
) -> dict[str, Any] | None:
    """Validate one exact machine-readable Merchant resolution result."""

    if not isinstance(
        value,
        dict,
    ):
        return None

    if (
        set(
            value
        )
        != RESOLUTION_FIELDS
    ):
        return None

    if (
        value.get(
            "success"
        )
        is not True
    ):
        return None

    if (
        value.get(
            "mode"
        )
        != "RESOLUTION"
    ):
        return None

    query = _nonempty_text(
        value.get(
            "query"
        )
    )

    if query is None:
        return None

    status = value.get(
        "status"
    )

    if (
        not isinstance(
            status,
            str,
        )
        or status
        not in RESOLUTION_STATUSES
    ):
        return None

    match_kind = value.get(
        "match_kind"
    )

    if (
        not isinstance(
            match_kind,
            str,
        )
        or match_kind
        not in MATCH_KINDS
    ):
        return None

    resolved = value.get(
        "resolved"
    )

    if not isinstance(
        resolved,
        bool,
    ):
        return None

    candidates = _validate_candidates(
        value.get(
            "candidates"
        )
    )

    if candidates is None:
        return None

    merchant_id_value = value.get(
        "merchant_id"
    )

    code_value = value.get(
        "code"
    )

    name_value = value.get(
        "name"
    )

    if status == "RESOLVED":
        if resolved is not True:
            return None

        if match_kind == "NONE":
            return None

        merchant_id = (
            _canonical_uuid_text(
                merchant_id_value
            )
        )

        code = _nonempty_text(
            code_value
        )

        name = _nonempty_text(
            name_value
        )

        if (
            merchant_id is None
            or code is None
            or name is None
        ):
            return None

        if len(
            candidates
        ) != 1:
            return None

        if candidates[0] != {
            "merchant_id": merchant_id,
            "code": code,
            "name": name,
        }:
            return None

    elif status == "AMBIGUOUS":
        if resolved is not False:
            return None

        if match_kind in {
            "NONE",
            "UUID",
        }:
            return None

        if (
            merchant_id_value is not None
            or code_value is not None
            or name_value is not None
        ):
            return None

        if len(
            candidates
        ) < 2:
            return None

    elif status == "NOT_FOUND":
        if resolved is not False:
            return None

        if match_kind not in {
            "NONE",
            "UUID",
        }:
            return None

        if (
            merchant_id_value is not None
            or code_value is not None
            or name_value is not None
        ):
            return None

        if candidates:
            return None

    else:  # pragma: no cover
        return None

    return value


def stage_pending_merchant_resolution(
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    resolution: dict[str, Any],
    tool_use_id: Any = "",
) -> bool:
    """Atomically stage one exact resolver result."""

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
        not binding[
            field
        ]
        for field in REQUIRED_BINDING_FIELDS
    ):
        return False

    validated = (
        validate_merchant_resolution_result(
            resolution
        )
    )

    if validated is None:
        return False

    directory = (
        pending_merchant_resolution_dir()
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        pending_merchant_resolution_path(
            binding[
                "pane_session_id"
            ]
        )
    )

    lock = FileLock(
        str(
            pending_merchant_resolution_lock_path(
                binding[
                    "pane_session_id"
                ]
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    payload = {
        **binding,
        "tool_use_id": _clean_text(
            tool_use_id
        ),
        "resolution": validated,
        "created_at": time.time(),
    }

    temporary: Path | None = None

    try:
        with lock:
            (
                descriptor,
                temporary_name,
            ) = tempfile.mkstemp(
                prefix=(
                    destination.name
                    + "."
                ),
                suffix=".tmp",
                dir=str(
                    directory
                ),
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


def load_pending_merchant_resolution(
    pane_session_id: Any,
) -> dict[str, Any] | None:
    """Load one unexpired resolution receipt."""

    pane_id = _clean_text(
        pane_session_id
    )

    if not pane_id:
        return None

    path = (
        pending_merchant_resolution_path(
            pane_id
        )
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

    if not isinstance(
        payload,
        dict,
    ):
        return None

    for field in REQUIRED_BINDING_FIELDS:
        if not _clean_text(
            payload.get(
                field
            )
        ):
            return None

    if (
        payload.get(
            "pane_session_id"
        )
        != pane_id
    ):
        return None

    created_at = payload.get(
        "created_at"
    )

    try:
        age = (
            time.time()
            - float(
                created_at
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if (
        age < 0
        or age
        > MAX_RESOLUTION_AGE_SECONDS
    ):
        return None

    resolution = (
        validate_merchant_resolution_result(
            payload.get(
                "resolution"
            )
        )
    )

    if resolution is None:
        return None

    return payload


def pending_merchant_resolution_matches(
    payload: Any,
    *,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
) -> bool:
    """Exact-match receipt to the trusted owner/run/task identity."""

    if not isinstance(
        payload,
        dict,
    ):
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
            payload.get(
                field
            )
        )
        == value
        for (
            field,
            value,
        ) in expected.items()
    )


def clear_pending_merchant_resolution(
    pane_session_id: Any,
) -> bool:
    """Remove one transient resolution receipt."""

    pane_id = _clean_text(
        pane_session_id
    )

    if not pane_id:
        return False

    directory = (
        pending_merchant_resolution_dir()
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock = FileLock(
        str(
            pending_merchant_resolution_lock_path(
                pane_id
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    try:
        with lock:
            try:
                pending_merchant_resolution_path(
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