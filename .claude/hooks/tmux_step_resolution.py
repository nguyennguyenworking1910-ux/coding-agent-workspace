#!/usr/bin/env python3
"""Transient exact Step resolution receipts for tmux teammates.

A Step-resolution receipt preserves the exact JSON emitted by:

    step resolve --project-id <uuid> --query <value>

between PostToolUse staging and later trusted lifecycle/policy reconciliation.

This module does not grant write authority and does not call the Merchant CLI.

Security boundary:
- PostToolUse may stage exact Step-resolver output only.
- Step resolution is always bound to one trusted merchant_id and project_id.
- Resolution output is validated before persistence.
- Receipt is bound to pane + owner + teammate + run + task + merchant + project.
- Candidate Steps must belong to the same trusted Project.
- template_step_id is metadata only; it never substitutes for step_id.
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

PENDING_STEP_RESOLUTION_DIR = (
    CLAUDE_DIR
    / "runtime"
    / "pending_step_resolutions"
)

STEP_RESOLUTION_DIR_ENV = (
    "CLAUDE_PENDING_STEP_RESOLUTION_DIR"
)

STEP_RESOLUTION_TTL_SECONDS = 3600
LOCK_TIMEOUT_SECONDS = 10.0


RECEIPT_FIELDS = frozenset(
    {
        "pane_session_id",
        "owner_session_id",
        "teammate_name",
        "run_id",
        "task_id",
        "merchant_id",
        "project_id",
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
        "project_id",
        "status",
        "match_kind",
        "resolved",
        "step_id",
        "template_step_id",
        "branch_key",
        "step_name",
        "step_type",
        "step_status",
        "sequence_number",
        "version",
        "condition_key",
        "is_optional",
        "candidates",
    }
)


CANDIDATE_FIELDS = frozenset(
    {
        "step_id",
        "project_id",
        "template_step_id",
        "branch_key",
        "step_name",
        "step_type",
        "status",
        "sequence_number",
        "version",
        "condition_key",
        "is_optional",
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
        "STEP_NAME",
        "CANDIDATE",
        "NONE",
    }
)


RESOLVED_MATCH_KINDS = frozenset(
    {
        "UUID",
        "STEP_NAME",
        "CANDIDATE",
    }
)


AMBIGUOUS_MATCH_KINDS = frozenset(
    {
        "STEP_NAME",
        "CANDIDATE",
    }
)


_INVALID = object()


def pending_step_resolution_dir() -> Path:
    override = os.environ.get(
        STEP_RESOLUTION_DIR_ENV
    )

    return (
        Path(override)
        if override
        else PENDING_STEP_RESOLUTION_DIR
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


def pending_step_resolution_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_step_resolution_dir()
        / f"{_session_key(pane_session_id)}.json"
    )


def pending_step_resolution_lock_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_step_resolution_dir()
        / f"{_session_key(pane_session_id)}.lock"
    )


def _clean_text(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()


def _nonempty_exact_text(
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


def _optional_exact_text(
    value: Any,
) -> str | None | object:
    if value is None:
        return None

    cleaned = (
        _nonempty_exact_text(
            value
        )
    )

    if cleaned is None:
        return _INVALID

    return cleaned


def _canonical_uuid_text(
    value: Any,
) -> str | None:
    if (
        not isinstance(
            value,
            str,
        )
        or not value
    ):
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


def _positive_integer(
    value: Any,
) -> int | None:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
        or value < 1
    ):
        return None

    return value


def _optional_positive_integer(
    value: Any,
) -> int | None | object:
    if value is None:
        return None

    normalized = (
        _positive_integer(
            value
        )
    )

    if normalized is None:
        return _INVALID

    return normalized


def _optional_boolean(
    value: Any,
) -> bool | None | object:
    if value is None:
        return None

    if not isinstance(
        value,
        bool,
    ):
        return _INVALID

    return value


def _validate_candidate(
    value: Any,
    *,
    trusted_project_id: str,
) -> dict[str, Any] | None:
    if not isinstance(
        value,
        dict,
    ):
        return None

    if (
        set(value)
        != CANDIDATE_FIELDS
    ):
        return None

    step_id = (
        _canonical_uuid_text(
            value.get(
                "step_id"
            )
        )
    )

    project_id = (
        _canonical_uuid_text(
            value.get(
                "project_id"
            )
        )
    )

    template_step_id = (
        _canonical_uuid_text(
            value.get(
                "template_step_id"
            )
        )
    )

    if (
        step_id is None
        or project_id is None
        or template_step_id is None
        or project_id
        != trusted_project_id
    ):
        return None

    step_name = (
        _nonempty_exact_text(
            value.get(
                "step_name"
            )
        )
    )

    if step_name is None:
        return None

    branch_key = (
        _optional_exact_text(
            value.get(
                "branch_key"
            )
        )
    )

    step_type = (
        _optional_exact_text(
            value.get(
                "step_type"
            )
        )
    )

    status = (
        _optional_exact_text(
            value.get(
                "status"
            )
        )
    )

    condition_key = (
        _optional_exact_text(
            value.get(
                "condition_key"
            )
        )
    )

    sequence_number = (
        _positive_integer(
            value.get(
                "sequence_number"
            )
        )
    )

    version = (
        _positive_integer(
            value.get(
                "version"
            )
        )
    )

    is_optional = (
        _optional_boolean(
            value.get(
                "is_optional"
            )
        )
    )

    if (
        sequence_number is None
        or version is None
        or branch_key is _INVALID
        or step_type is _INVALID
        or status is _INVALID
        or condition_key is _INVALID
        or is_optional is _INVALID
    ):
        return None

    return {
        "step_id": step_id,
        "project_id": project_id,
        "template_step_id": (
            template_step_id
        ),
        "branch_key": branch_key,
        "step_name": step_name,
        "step_type": step_type,
        "status": status,
        "sequence_number": (
            sequence_number
        ),
        "version": version,
        "condition_key": condition_key,
        "is_optional": is_optional,
    }


def _validate_candidates(
    value: Any,
    *,
    trusted_project_id: str,
) -> list[
    dict[str, Any]
] | None:
    if not isinstance(
        value,
        list,
    ):
        return None

    validated: list[
        dict[str, Any]
    ] = []

    seen_step_ids: set[str] = set()

    for candidate in value:
        normalized = (
            _validate_candidate(
                candidate,
                trusted_project_id=(
                    trusted_project_id
                ),
            )
        )

        if normalized is None:
            return None

        step_id = normalized[
            "step_id"
        ]

        if (
            step_id
            in seen_step_ids
        ):
            return None

        seen_step_ids.add(
            step_id
        )

        validated.append(
            normalized
        )

    actual_order = [
        (
            candidate[
                "sequence_number"
            ],
            candidate[
                "step_id"
            ],
        )
        for candidate
        in validated
    ]

    expected_order = sorted(
        actual_order
    )

    if (
        actual_order
        != expected_order
    ):
        return None

    return validated


def validate_step_resolution_result(
    value: Any,
) -> dict[str, Any] | None:
    """Validate one exact machine-readable `step resolve` result."""

    if not isinstance(
        value,
        dict,
    ):
        return None

    if (
        set(value)
        != RESOLUTION_FIELDS
    ):
        return None

    if (
        value.get("success")
        is not True
    ):
        return None

    if (
        value.get("mode")
        != "STEP_RESOLUTION"
    ):
        return None

    query = (
        _nonempty_exact_text(
            value.get(
                "query"
            )
        )
    )

    if query is None:
        return None

    project_id = (
        _canonical_uuid_text(
            value.get(
                "project_id"
            )
        )
    )

    if project_id is None:
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

    template_step_id_value = (
        value.get(
            "template_step_id"
        )
    )

    branch_key = (
        _optional_exact_text(
            value.get(
                "branch_key"
            )
        )
    )

    step_name = (
        _optional_exact_text(
            value.get(
                "step_name"
            )
        )
    )

    step_type = (
        _optional_exact_text(
            value.get(
                "step_type"
            )
        )
    )

    step_status = (
        _optional_exact_text(
            value.get(
                "step_status"
            )
        )
    )

    sequence_number = (
        _optional_positive_integer(
            value.get(
                "sequence_number"
            )
        )
    )

    version = (
        _optional_positive_integer(
            value.get(
                "version"
            )
        )
    )

    condition_key = (
        _optional_exact_text(
            value.get(
                "condition_key"
            )
        )
    )

    is_optional = (
        _optional_boolean(
            value.get(
                "is_optional"
            )
        )
    )

    if any(
        item is _INVALID
        for item in (
            branch_key,
            step_name,
            step_type,
            step_status,
            sequence_number,
            version,
            condition_key,
            is_optional,
        )
    ):
        return None

    candidates = (
        _validate_candidates(
            value.get(
                "candidates"
            ),
            trusted_project_id=(
                project_id
            ),
        )
    )

    if candidates is None:
        return None

    step_id_value = value.get(
        "step_id"
    )

    if status == "RESOLVED":
        if resolved is not True:
            return None

        if (
            match_kind
            not in RESOLVED_MATCH_KINDS
        ):
            return None

        step_id = (
            _canonical_uuid_text(
                step_id_value
            )
        )

        template_step_id = (
            _canonical_uuid_text(
                template_step_id_value
            )
        )

        if (
            step_id is None
            or template_step_id
            is None
            or step_name is None
            or sequence_number is None
            or version is None
        ):
            return None

        if len(
            candidates
        ) != 1:
            return None

        expected_candidate = {
            "step_id": step_id,
            "project_id": project_id,
            "template_step_id": (
                template_step_id
            ),
            "branch_key": (
                branch_key
            ),
            "step_name": (
                step_name
            ),
            "step_type": (
                step_type
            ),
            "status": (
                step_status
            ),
            "sequence_number": (
                sequence_number
            ),
            "version": version,
            "condition_key": (
                condition_key
            ),
            "is_optional": (
                is_optional
            ),
        }

        if (
            candidates[0]
            != expected_candidate
        ):
            return None

    elif status == "AMBIGUOUS":
        if resolved is not False:
            return None

        if (
            match_kind
            not in AMBIGUOUS_MATCH_KINDS
        ):
            return None

        if (
            step_id_value
            is not None
            or template_step_id_value
            is not None
        ):
            return None

        if any(
            item is not None
            for item in (
                branch_key,
                step_name,
                step_type,
                step_status,
                sequence_number,
                version,
                condition_key,
                is_optional,
            )
        ):
            return None

        if len(
            candidates
        ) < 2:
            return None

    elif status == "NOT_FOUND":
        if resolved is not False:
            return None

        if (
            match_kind
            != "NONE"
        ):
            return None

        if (
            step_id_value
            is not None
            or template_step_id_value
            is not None
        ):
            return None

        if any(
            item is not None
            for item in (
                branch_key,
                step_name,
                step_type,
                step_status,
                sequence_number,
                version,
                condition_key,
                is_optional,
            )
        ):
            return None

        if candidates:
            return None

    else:  # pragma: no cover
        return None

    return value


def stage_pending_step_resolution(
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    merchant_id: Any,
    project_id: Any,
    resolution: dict[str, Any],
    tool_use_id: Any,
) -> bool:
    """Atomically stage one exact Step-resolver result."""

    binding = {
        "pane_session_id": (
            _clean_text(
                pane_session_id
            )
        ),
        "owner_session_id": (
            _clean_text(
                owner_session_id
            )
        ),
        "teammate_name": (
            _clean_text(
                teammate_name
            )
        ),
        "run_id": (
            _clean_text(
                run_id
            )
        ),
        "task_id": (
            _clean_text(
                task_id
            )
        ),
        "tool_use_id": (
            _clean_text(
                tool_use_id
            )
        ),
    }

    if any(
        not binding[field]
        for field
        in BINDING_TEXT_FIELDS
    ):
        return False

    trusted_merchant_id = (
        _canonical_uuid_text(
            merchant_id
        )
    )

    trusted_project_id = (
        _canonical_uuid_text(
            project_id
        )
    )

    if (
        trusted_merchant_id
        is None
        or trusted_project_id
        is None
    ):
        return False

    validated = (
        validate_step_resolution_result(
            resolution
        )
    )

    if validated is None:
        return False

    if (
        validated.get(
            "project_id"
        )
        != trusted_project_id
    ):
        return False

    directory = (
        pending_step_resolution_dir()
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        pending_step_resolution_path(
            binding[
                "pane_session_id"
            ]
        )
    )

    lock = FileLock(
        str(
            pending_step_resolution_lock_path(
                binding[
                    "pane_session_id"
                ]
            )
        ),
        timeout=(
            LOCK_TIMEOUT_SECONDS
        ),
    )

    payload = {
        **binding,
        "merchant_id": (
            trusted_merchant_id
        ),
        "project_id": (
            trusted_project_id
        ),
        "resolution": validated,
        "created_at": (
            time.time()
        ),
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


def load_pending_step_resolution(
    pane_session_id: Any,
) -> dict[str, Any] | None:
    """Load one unexpired exact Step-resolution receipt."""

    pane_id = (
        _clean_text(
            pane_session_id
        )
    )

    if not pane_id:
        return None

    path = (
        pending_step_resolution_path(
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

    if (
        set(payload)
        != RECEIPT_FIELDS
    ):
        return None

    for field in (
        BINDING_TEXT_FIELDS
    ):
        if (
            _nonempty_exact_text(
                payload.get(
                    field
                )
            )
            is None
        ):
            return None

    if (
        payload.get(
            "pane_session_id"
        )
        != pane_id
    ):
        return None

    merchant_id = (
        _canonical_uuid_text(
            payload.get(
                "merchant_id"
            )
        )
    )

    project_id = (
        _canonical_uuid_text(
            payload.get(
                "project_id"
            )
        )
    )

    if (
        merchant_id is None
        or project_id is None
    ):
        return None

    created_at = (
        payload.get(
            "created_at"
        )
    )

    if (
        isinstance(
            created_at,
            bool,
        )
        or not isinstance(
            created_at,
            (int, float),
        )
    ):
        return None

    age = (
        time.time()
        - float(
            created_at
        )
    )

    if (
        age < 0
        or age
        > STEP_RESOLUTION_TTL_SECONDS
    ):
        return None

    resolution = (
        validate_step_resolution_result(
            payload.get(
                "resolution"
            )
        )
    )

    if resolution is None:
        return None

    if (
        resolution.get(
            "project_id"
        )
        != project_id
    ):
        return None

    return payload


def pending_step_resolution_matches(
    payload: Any,
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    merchant_id: Any,
    project_id: Any,
) -> bool:
    """Exact-match receipt to pane/owner/run/task/Merchant/Project."""

    if not isinstance(
        payload,
        dict,
    ):
        return False

    trusted_merchant_id = (
        _canonical_uuid_text(
            merchant_id
        )
    )

    trusted_project_id = (
        _canonical_uuid_text(
            project_id
        )
    )

    if (
        trusted_merchant_id
        is None
        or trusted_project_id
        is None
    ):
        return False

    expected = {
        "pane_session_id": (
            _clean_text(
                pane_session_id
            )
        ),
        "owner_session_id": (
            _clean_text(
                owner_session_id
            )
        ),
        "teammate_name": (
            _clean_text(
                teammate_name
            )
        ),
        "run_id": (
            _clean_text(
                run_id
            )
        ),
        "task_id": (
            _clean_text(
                task_id
            )
        ),
        "merchant_id": (
            trusted_merchant_id
        ),
        "project_id": (
            trusted_project_id
        ),
    }

    if any(
        not value
        for value
        in expected.values()
    ):
        return False

    if not all(
        payload.get(
            field
        )
        == value
        for field, value
        in expected.items()
    ):
        return False

    resolution = (
        validate_step_resolution_result(
            payload.get(
                "resolution"
            )
        )
    )

    return (
        resolution is not None
        and resolution.get(
            "project_id"
        )
        == trusted_project_id
    )


step_resolution_receipt_matches = (
    pending_step_resolution_matches
)


def clear_pending_step_resolution(
    pane_session_id: Any,
) -> bool:
    """Remove one transient Step-resolution receipt."""

    pane_id = (
        _clean_text(
            pane_session_id
        )
    )

    if not pane_id:
        return False

    directory = (
        pending_step_resolution_dir()
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock = FileLock(
        str(
            pending_step_resolution_lock_path(
                pane_id
            )
        ),
        timeout=(
            LOCK_TIMEOUT_SECONDS
        ),
    )

    try:
        with lock:
            try:
                pending_step_resolution_path(
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