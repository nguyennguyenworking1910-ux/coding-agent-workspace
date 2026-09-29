#!/usr/bin/env python3
"""Transient exact Document Revision resolution receipts for tmux teammates.

A document-revision receipt preserves the exact JSON emitted by:

    document resolve --project-id <uuid> --query <value>

or:

    document resolve --merchant-id <uuid> --query <value>

between PostToolUse staging and later trusted lifecycle/policy reconciliation.

This module does not grant write authority and does not call the Merchant CLI.

Security boundary:
- PostToolUse may stage exact document-resolver output only.
- Merchant scope permits revisions from any source project owned by the exact
  trusted merchant.
- Project scope requires every candidate/result to belong to the exact trusted
  merchant and exact trusted project.
- Resolution output is validated before persistence.
- Receipt is bound to pane + owner + teammate + run + task + scope + parents.
- Receipts are short-lived and cleared after successful reconciliation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid

from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout


CLAUDE_DIR = Path(__file__).resolve().parents[1]

PENDING_DOCUMENT_REVISION_RESOLUTION_DIR = (
    CLAUDE_DIR
    / "runtime"
    / "pending_document_revision_resolutions"
)

DOCUMENT_REVISION_RESOLUTION_DIR_ENV = (
    "CLAUDE_PENDING_DOCUMENT_REVISION_RESOLUTION_DIR"
)

DOCUMENT_REVISION_RESOLUTION_TTL_SECONDS = 3600
LOCK_TIMEOUT_SECONDS = 10.0

SCOPE_PROJECT = "PROJECT"
SCOPE_MERCHANT = "MERCHANT"

SCOPES = frozenset(
    {
        SCOPE_PROJECT,
        SCOPE_MERCHANT,
    }
)

RECEIPT_FIELDS = frozenset(
    {
        "pane_session_id",
        "owner_session_id",
        "teammate_name",
        "run_id",
        "task_id",
        "merchant_id",
        "project_id",
        "scope",
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
        "scope",
        "merchant_id",
        "project_id",
        "status",
        "match_kind",
        "resolved",
        "revision_id",
        "source_project_id",
        "document_type",
        "revision_number",
        "signed",
        "superseded_by",
        "candidates",
    }
)

CANDIDATE_FIELDS = frozenset(
    {
        "revision_id",
        "project_id",
        "merchant_id",
        "document_type",
        "revision_number",
        "signed",
        "superseded_by",
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
        "REVISION_KEY",
        "DOCUMENT_TYPE",
        "CANDIDATE",
        "NONE",
    }
)

RESOLVED_MATCH_KINDS = frozenset(
    {
        "UUID",
        "REVISION_KEY",
        "DOCUMENT_TYPE",
        "CANDIDATE",
    }
)

AMBIGUOUS_MATCH_KINDS = frozenset(
    {
        "REVISION_KEY",
        "DOCUMENT_TYPE",
        "CANDIDATE",
    }
)

DOCUMENT_TYPE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_]{0,99}$"
)

_INVALID = object()


def pending_document_revision_resolution_dir() -> Path:
    override = os.environ.get(
        DOCUMENT_REVISION_RESOLUTION_DIR_ENV
    )

    return (
        Path(override)
        if override
        else PENDING_DOCUMENT_REVISION_RESOLUTION_DIR
    )


def _session_key(
    session_id: Any,
) -> str:
    value = _clean_text(
        session_id
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def pending_document_revision_resolution_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_document_revision_resolution_dir()
        / f"{_session_key(pane_session_id)}.json"
    )


def pending_document_revision_resolution_lock_path(
    pane_session_id: Any,
) -> Path:
    return (
        pending_document_revision_resolution_dir()
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


def _optional_uuid_text(
    value: Any,
) -> str | None | object:
    if value is None:
        return None

    canonical = _canonical_uuid_text(
        value
    )

    if canonical is None:
        return _INVALID

    return canonical


def _positive_integer(
    value: Any,
) -> int | object:
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
        return _INVALID

    return value


def _optional_positive_integer(
    value: Any,
) -> int | None | object:
    if value is None:
        return None

    return _positive_integer(
        value
    )


def _optional_bool(
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


def _document_type(
    value: Any,
) -> str | None:
    text = _nonempty_exact_text(
        value
    )

    if (
        text is None
        or DOCUMENT_TYPE_PATTERN.fullmatch(
            text
        )
        is None
    ):
        return None

    return text


def _optional_document_type(
    value: Any,
) -> str | None | object:
    if value is None:
        return None

    normalized = _document_type(
        value
    )

    if normalized is None:
        return _INVALID

    return normalized


def _scope_parent(
    *,
    scope: Any,
    merchant_id: Any,
    project_id: Any,
) -> tuple[
    str,
    str,
    str | None,
] | None:
    if (
        not isinstance(
            scope,
            str,
        )
        or scope
        not in SCOPES
    ):
        return None

    trusted_merchant_id = (
        _canonical_uuid_text(
            merchant_id
        )
    )

    if trusted_merchant_id is None:
        return None

    if scope == SCOPE_MERCHANT:
        if project_id is not None:
            return None

        return (
            scope,
            trusted_merchant_id,
            None,
        )

    trusted_project_id = (
        _canonical_uuid_text(
            project_id
        )
    )

    if trusted_project_id is None:
        return None

    return (
        scope,
        trusted_merchant_id,
        trusted_project_id,
    )


def _validate_candidate(
    value: Any,
    *,
    scope: str,
    trusted_merchant_id: str,
    trusted_project_id: str | None,
) -> dict[str, Any] | None:
    if not isinstance(
        value,
        dict,
    ):
        return None

    if set(
        value
    ) != CANDIDATE_FIELDS:
        return None

    revision_id = (
        _canonical_uuid_text(
            value.get(
                "revision_id"
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

    merchant_id = (
        _canonical_uuid_text(
            value.get(
                "merchant_id"
            )
        )
    )

    document_type = (
        _document_type(
            value.get(
                "document_type"
            )
        )
    )

    revision_number = (
        _positive_integer(
            value.get(
                "revision_number"
            )
        )
    )

    signed = value.get(
        "signed"
    )

    superseded_by = (
        _optional_uuid_text(
            value.get(
                "superseded_by"
            )
        )
    )

    if (
        revision_id is None
        or project_id is None
        or merchant_id is None
        or document_type is None
        or revision_number is _INVALID
        or not isinstance(
            signed,
            bool,
        )
        or superseded_by is _INVALID
    ):
        return None

    if (
        merchant_id
        != trusted_merchant_id
    ):
        return None

    if (
        scope == SCOPE_PROJECT
        and project_id
        != trusted_project_id
    ):
        return None

    return {
        "revision_id": revision_id,
        "project_id": project_id,
        "merchant_id": merchant_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "signed": signed,
        "superseded_by": superseded_by,
    }


def _candidate_sort_key(
    candidate: dict[str, Any],
) -> tuple[
    str,
    int,
    str,
    str,
]:
    return (
        candidate[
            "document_type"
        ],
        candidate[
            "revision_number"
        ],
        candidate[
            "project_id"
        ],
        candidate[
            "revision_id"
        ],
    )


def _validate_candidates(
    value: Any,
    *,
    scope: str,
    trusted_merchant_id: str,
    trusted_project_id: str | None,
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

    seen_revision_ids: set[
        str
    ] = set()

    for candidate in value:
        normalized = (
            _validate_candidate(
                candidate,
                scope=scope,
                trusted_merchant_id=(
                    trusted_merchant_id
                ),
                trusted_project_id=(
                    trusted_project_id
                ),
            )
        )

        if normalized is None:
            return None

        revision_id = (
            normalized[
                "revision_id"
            ]
        )

        if (
            revision_id
            in seen_revision_ids
        ):
            return None

        seen_revision_ids.add(
            revision_id
        )

        validated.append(
            normalized
        )

    if validated != sorted(
        validated,
        key=_candidate_sort_key,
    ):
        return None

    return validated


def validate_document_revision_resolution_result(
    value: Any,
) -> dict[str, Any] | None:
    """Validate one exact machine-readable `document resolve` result."""

    if not isinstance(
        value,
        dict,
    ):
        return None

    if set(
        value
    ) != RESOLUTION_FIELDS:
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
        != "DOCUMENT_REVISION_RESOLUTION"
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

    parent = _scope_parent(
        scope=value.get(
            "scope"
        ),
        merchant_id=value.get(
            "merchant_id"
        ),
        project_id=value.get(
            "project_id"
        ),
    )

    if parent is None:
        return None

    (
        scope,
        merchant_id,
        project_id,
    ) = parent

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

    candidates = (
        _validate_candidates(
            value.get(
                "candidates"
            ),
            scope=scope,
            trusted_merchant_id=(
                merchant_id
            ),
            trusted_project_id=(
                project_id
            ),
        )
    )

    if candidates is None:
        return None

    revision_id_value = value.get(
        "revision_id"
    )

    source_project_id_value = (
        value.get(
            "source_project_id"
        )
    )

    document_type = (
        _optional_document_type(
            value.get(
                "document_type"
            )
        )
    )

    revision_number = (
        _optional_positive_integer(
            value.get(
                "revision_number"
            )
        )
    )

    signed = _optional_bool(
        value.get(
            "signed"
        )
    )

    superseded_by = (
        _optional_uuid_text(
            value.get(
                "superseded_by"
            )
        )
    )

    if any(
        item is _INVALID
        for item in (
            document_type,
            revision_number,
            signed,
            superseded_by,
        )
    ):
        return None

    if status == "RESOLVED":
        if resolved is not True:
            return None

        if (
            match_kind
            not in RESOLVED_MATCH_KINDS
        ):
            return None

        revision_id = (
            _canonical_uuid_text(
                revision_id_value
            )
        )

        source_project_id = (
            _canonical_uuid_text(
                source_project_id_value
            )
        )

        if (
            revision_id is None
            or source_project_id
            is None
            or document_type
            is None
            or revision_number
            is None
            or signed
            is None
        ):
            return None

        if (
            scope
            == SCOPE_PROJECT
            and source_project_id
            != project_id
        ):
            return None

        if len(
            candidates
        ) != 1:
            return None

        expected_candidate = {
            "revision_id": revision_id,
            "project_id": (
                source_project_id
            ),
            "merchant_id": (
                merchant_id
            ),
            "document_type": (
                document_type
            ),
            "revision_number": (
                revision_number
            ),
            "signed": signed,
            "superseded_by": (
                superseded_by
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

        if any(
            item is not None
            for item in (
                revision_id_value,
                source_project_id_value,
                document_type,
                revision_number,
                signed,
                superseded_by,
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

        if any(
            item is not None
            for item in (
                revision_id_value,
                source_project_id_value,
                document_type,
                revision_number,
                signed,
                superseded_by,
            )
        ):
            return None

        if candidates:
            return None

    else:  # pragma: no cover
        return None

    return value


def stage_pending_document_revision_resolution(
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    merchant_id: Any,
    scope: Any,
    project_id: Any = None,
    resolution: dict[str, Any],
    tool_use_id: Any,
) -> bool:
    """Atomically stage one exact document-revision resolver result."""

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
        for field in BINDING_TEXT_FIELDS
    ):
        return False

    parent = _scope_parent(
        scope=scope,
        merchant_id=merchant_id,
        project_id=project_id,
    )

    if parent is None:
        return False

    (
        trusted_scope,
        trusted_merchant_id,
        trusted_project_id,
    ) = parent

    validated = (
        validate_document_revision_resolution_result(
            resolution
        )
    )

    if validated is None:
        return False

    if (
        validated.get(
            "scope"
        )
        != trusted_scope
        or validated.get(
            "merchant_id"
        )
        != trusted_merchant_id
        or validated.get(
            "project_id"
        )
        != trusted_project_id
    ):
        return False

    directory = (
        pending_document_revision_resolution_dir()
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        pending_document_revision_resolution_path(
            binding[
                "pane_session_id"
            ]
        )
    )

    lock = FileLock(
        str(
            pending_document_revision_resolution_lock_path(
                binding[
                    "pane_session_id"
                ]
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    payload = {
        **binding,
        "merchant_id": (
            trusted_merchant_id
        ),
        "project_id": (
            trusted_project_id
        ),
        "scope": trusted_scope,
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


def load_pending_document_revision_resolution(
    pane_session_id: Any,
) -> dict[str, Any] | None:
    """Load one unexpired exact document-revision resolution receipt."""

    pane_id = _clean_text(
        pane_session_id
    )

    if not pane_id:
        return None

    path = (
        pending_document_revision_resolution_path(
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

    if set(
        payload
    ) != RECEIPT_FIELDS:
        return None

    for field in BINDING_TEXT_FIELDS:
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

    parent = _scope_parent(
        scope=payload.get(
            "scope"
        ),
        merchant_id=payload.get(
            "merchant_id"
        ),
        project_id=payload.get(
            "project_id"
        ),
    )

    if parent is None:
        return None

    (
        scope,
        merchant_id,
        project_id,
    ) = parent

    created_at = payload.get(
        "created_at"
    )

    if (
        isinstance(
            created_at,
            bool,
        )
        or not isinstance(
            created_at,
            (
                int,
                float,
            ),
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
        > DOCUMENT_REVISION_RESOLUTION_TTL_SECONDS
    ):
        return None

    resolution = (
        validate_document_revision_resolution_result(
            payload.get(
                "resolution"
            )
        )
    )

    if resolution is None:
        return None

    if (
        resolution.get(
            "scope"
        )
        != scope
        or resolution.get(
            "merchant_id"
        )
        != merchant_id
        or resolution.get(
            "project_id"
        )
        != project_id
    ):
        return None

    return payload


def pending_document_revision_resolution_matches(
    payload: Any,
    *,
    pane_session_id: Any,
    owner_session_id: Any,
    teammate_name: Any,
    run_id: Any,
    task_id: Any,
    merchant_id: Any,
    scope: Any,
    project_id: Any = None,
) -> bool:
    """Exact-match receipt to pane/owner/run/task/scope/parent identity."""

    if not isinstance(
        payload,
        dict,
    ):
        return False

    parent = _scope_parent(
        scope=scope,
        merchant_id=merchant_id,
        project_id=project_id,
    )

    if parent is None:
        return False

    (
        trusted_scope,
        trusted_merchant_id,
        trusted_project_id,
    ) = parent

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
        "scope": trusted_scope,
    }

    if any(
        not value
        for value in expected.values()
    ):
        return False

    if not all(
        payload.get(
            field
        )
        == value
        for (
            field,
            value,
        ) in expected.items()
    ):
        return False

    if (
        payload.get(
            "project_id"
        )
        != trusted_project_id
    ):
        return False

    resolution = (
        validate_document_revision_resolution_result(
            payload.get(
                "resolution"
            )
        )
    )

    return (
        resolution is not None
        and resolution.get(
            "scope"
        )
        == trusted_scope
        and resolution.get(
            "merchant_id"
        )
        == trusted_merchant_id
        and resolution.get(
            "project_id"
        )
        == trusted_project_id
    )


document_revision_resolution_receipt_matches = (
    pending_document_revision_resolution_matches
)


def clear_pending_document_revision_resolution(
    pane_session_id: Any,
) -> bool:
    """Remove one transient document-revision resolution receipt."""

    pane_id = _clean_text(
        pane_session_id
    )

    if not pane_id:
        return False

    directory = (
        pending_document_revision_resolution_dir()
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock = FileLock(
        str(
            pending_document_revision_resolution_lock_path(
                pane_id
            )
        ),
        timeout=LOCK_TIMEOUT_SECONDS,
    )

    try:
        with lock:
            try:
                pending_document_revision_resolution_path(
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