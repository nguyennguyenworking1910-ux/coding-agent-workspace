from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


COMPLETENESS_MODE = "COMPLETENESS"

RUNTIME_DIR_ENV_VAR = (
    "CLAUDE_RUNTIME_DIR"
)


def _runtime_root() -> Path:
    configured = os.environ.get(
        RUNTIME_DIR_ENV_VAR
    )

    if configured:
        return Path(configured)

    return (
        Path(".claude")
        / "runtime"
    )


def completeness_receipt_path(
    pane_session_id: str,
) -> Path:
    return (
        _runtime_root()
        / "merchant_completeness"
        / f"{pane_session_id}.json"
    )


def validate_completeness_result(
    value: Any,
) -> dict[str, Any] | None:
    """Accept only exact Merchant completeness CLI output."""

    if not isinstance(
        value,
        dict,
    ):
        return None

    if value.get("success") is not True:
        return None

    if (
        value.get("mode")
        != COMPLETENESS_MODE
    ):
        return None

    command = str(
        value.get("command")
        or ""
    ).strip()

    if not command:
        return None

    complete = value.get(
        "complete"
    )

    if not isinstance(
        complete,
        bool,
    ):
        return None

    missing_fields = value.get(
        "missing_fields"
    )

    missing_one_of = value.get(
        "missing_one_of"
    )

    if not isinstance(
        missing_fields,
        list,
    ):
        return None

    if not isinstance(
        missing_one_of,
        list,
    ):
        return None

    if any(
        not isinstance(field, str)
        or not field.strip()
        for field in missing_fields
    ):
        return None

    normalized_groups = []

    for group in missing_one_of:
        if (
            not isinstance(group, list)
            or not group
        ):
            return None

        if any(
            not isinstance(field, str)
            or not field.strip()
            for field in group
        ):
            return None

        normalized_groups.append(
            list(group)
        )

    clarification = value.get(
        "clarification"
    )

    if complete:
        if missing_fields:
            return None

        if missing_one_of:
            return None

        if clarification is not None:
            return None

    else:
        if not (
            missing_fields
            or missing_one_of
        ):
            return None

        if not isinstance(
            clarification,
            dict,
        ):
            return None

        if (
            clarification.get(
                "outcome"
            )
            != "REQUIRES_CLARIFICATION"
        ):
            return None

        if (
            clarification.get(
                "missing_fields"
            )
            != missing_fields
        ):
            return None

        if (
            clarification.get(
                "missing_one_of"
            )
            != missing_one_of
        ):
            return None

        question = str(
            clarification.get(
                "question"
            )
            or ""
        ).strip()

        if not question:
            return None

    return value


def stage_pending_merchant_completeness(
    *,
    pane_session_id: str,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
    tool_use_id: str,
    result: dict[str, Any],
) -> bool:
    validated = (
        validate_completeness_result(
            result
        )
    )

    if validated is None:
        return False

    required = (
        pane_session_id,
        owner_session_id,
        teammate_name,
        run_id,
        task_id,
    )

    if any(
        not str(value).strip()
        for value in required
    ):
        return False

    path = completeness_receipt_path(
        pane_session_id
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    record = {
        "pane_session_id": (
            pane_session_id
        ),
        "owner_session_id": (
            owner_session_id
        ),
        "teammate_name": (
            teammate_name
        ),
        "run_id": run_id,
        "task_id": task_id,
        "tool_use_id": (
            str(tool_use_id or "")
        ),
        "result": validated,
    }

    temporary = path.with_suffix(
        ".tmp"
    )

    temporary.write_text(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    temporary.replace(path)

    return True


def load_pending_merchant_completeness(
    pane_session_id: str,
) -> dict[str, Any] | None:
    path = completeness_receipt_path(
        pane_session_id
    )

    if not path.is_file():
        return None

    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(
        value,
        dict,
    ):
        return None

    return value


def pending_merchant_completeness_matches(
    receipt: dict[str, Any],
    *,
    owner_session_id: str,
    teammate_name: str,
    run_id: str,
    task_id: str,
) -> bool:
    return (
        str(
            receipt.get(
                "owner_session_id"
            )
            or ""
        ).strip()
        == str(owner_session_id).strip()
        and str(
            receipt.get(
                "teammate_name"
            )
            or ""
        ).strip()
        == str(teammate_name).strip()
        and str(
            receipt.get(
                "run_id"
            )
            or ""
        ).strip()
        == str(run_id).strip()
        and str(
            receipt.get(
                "task_id"
            )
            or ""
        ).strip()
        == str(task_id).strip()
    )


def clear_pending_merchant_completeness(
    pane_session_id: str,
) -> None:
    path = completeness_receipt_path(
        pane_session_id
    )

    try:
        path.unlink()
    except FileNotFoundError:
        pass