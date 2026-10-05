"""Shared tmux handler validation utilities for resolution and proposal handlers.

Consolidates ~400 lines of duplicate text validation across tmux_*_resolution.py files:
- _clean_text()
- _nonempty_text()
- _canonical_uuid_text()
- File path/dir helpers
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any


LOCK_TIMEOUT_SECONDS = 10.0
MAX_RESOLUTION_AGE_SECONDS = 3600


def clean_text(value: Any) -> str:
    """Safely convert value to string."""
    return str(value or "").strip()


def nonempty_text(value: Any) -> str | None:
    """Validate non-empty string (no internal whitespace changes)."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned != value:
        return None
    return cleaned


def canonical_uuid_text(value: Any) -> str | None:
    """Validate and canonicalize UUID string."""
    if not isinstance(value, str) or not value:
        return None
    try:
        canonical = str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError):
        return None
    return canonical if canonical == value else None


def session_key(session_id: Any) -> str:
    """Hash session ID to filename-safe key."""
    value = clean_text(session_id)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_handler_dir(
    env_var: str,
    default_dir: Path,
) -> Path:
    """Get handler directory from env or default."""
    override = os.environ.get(env_var)
    return Path(override) if override else default_dir
