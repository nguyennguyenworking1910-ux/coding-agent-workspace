#!/usr/bin/env python3
"""Persist and render the exact session-scoped intent envelope.

UserPromptExpansion classifies the controlled request first and persists the
exact envelope here. /solve then reads the same envelope through Claude Code
dynamic context before its prompt reaches the model.

This avoids relying on UserPromptExpansion.additionalContext delivery while
preserving the same trusted classification boundary.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

if __package__ in (None, ""):
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parent),
    )

    from runtime_state import (  # type: ignore
        CLAUDE_DIR,
        replace_with_retry,
        sanitize_session_id,
    )
else:
    from .runtime_state import (
        CLAUDE_DIR,
        replace_with_retry,
        sanitize_session_id,
    )


DEFAULT_ENVELOPE_DIR = (
    CLAUDE_DIR
    / "runtime"
    / "intent_envelopes"
)

ENVELOPE_DIR_ENV_VAR = (
    "CLAUDE_INTENT_ENVELOPE_DIR"
)

SESSION_ID_ENV_VAR = (
    "CLAUDE_CODE_SESSION_ID"
)

REQUIRED_FIELDS = frozenset(
    {
        "task_class",
        "risk_level",
        "limits",
        "selected_agents",
        "requires_clarification",
        "requires_confirmation",
        "raw_request",
    }
)


def envelope_dir() -> Path:
    override = os.environ.get(
        ENVELOPE_DIR_ENV_VAR
    )

    return (
        Path(override)
        if override
        else DEFAULT_ENVELOPE_DIR
    )


def envelope_path(
    session_id: Any,
) -> Path:
    return (
        envelope_dir()
        / (
            f"{sanitize_session_id(session_id)}"
            ".json"
        )
    )


def save_intent_envelope(
    session_id: Any,
    envelope: Mapping[str, Any],
) -> None:
    if not isinstance(
        envelope,
        Mapping,
    ):
        raise ValueError(
            "Intent envelope must be a mapping"
        )

    document = dict(envelope)

    missing = (
        REQUIRED_FIELDS
        - set(document)
    )

    if missing:
        raise ValueError(
            "Intent envelope is missing required fields: "
            + ", ".join(
                sorted(missing)
            )
        )

    path = envelope_path(
        session_id
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    descriptor, temporary_name = (
        tempfile.mkstemp(
            prefix=f"{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
    )

    temporary = Path(
        temporary_name
    )

    replaced = False

    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                document,
                handle,
                ensure_ascii=False,
                indent=2,
            )

            handle.flush()
            os.fsync(
                handle.fileno()
            )

        replace_with_retry(
            temporary,
            path,
        )

        replaced = True
    finally:
        if not replaced:
            try:
                temporary.unlink()
            except OSError:
                pass


def load_intent_envelope(
    session_id: Any,
) -> dict[str, Any] | None:
    try:
        with envelope_path(
            session_id
        ).open(
            "r",
            encoding="utf-8",
        ) as handle:
            document = json.load(
                handle
            )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
    ):
        return None

    if not isinstance(
        document,
        dict,
    ):
        return None

    if not REQUIRED_FIELDS.issubset(
        document
    ):
        return None

    return document


def clear_intent_envelope(
    session_id: Any,
) -> bool:
    try:
        envelope_path(
            session_id
        ).unlink()

        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def render_intent_envelope(
    session_id: Any,
) -> str:
    envelope = (
        load_intent_envelope(
            session_id
        )
    )

    if envelope is None:
        raise RuntimeError(
            "No valid intent envelope exists "
            "for this Claude Code session"
        )

    encoded = json.dumps(
        envelope,
        ensure_ascii=False,
        indent=2,
    )

    return (
        "INTENT_ENVELOPE_JSON\n"
        "```json\n"
        f"{encoded}\n"
        "```\n"
        "This envelope was persisted by the "
        "trusted intent hook for this exact "
        "Claude Code session."
    )


def main() -> int:
    session_id = str(
        os.environ.get(
            SESSION_ID_ENV_VAR
        )
        or ""
    ).strip()

    if not session_id:
        print(
            "Intent envelope bridge failed: "
            "CLAUDE_CODE_SESSION_ID is missing.",
            file=sys.stderr,
        )

        return 2

    try:
        print(
            render_intent_envelope(
                session_id
            )
        )
    except RuntimeError as error:
        print(
            str(error),
            file=sys.stderr,
        )

        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )