"""Trusted pending Project-create confirmations (CP12H.NL3).

A pending record is created only by trusted code: the PostToolUse(Bash) hook
that captured a VERIFIED, READY ``project preview`` from the CLI output in the
teammate's verified pane (``merchant_preview_delivery.record_preview_evidence``).
It holds the exact validated ``requested_operation`` and is owned by the lead
session that ran the preview.

The record is not approval. Approval is the user's own prompt: the intent gate
(UserPromptSubmit) accepts ``/solve Xác nhận tạo [<id>]`` as the *whole*
prompt, for the submitting session only, and spends exactly one live record
under a lock. The confirmed run then carries an ordinary ``merchant_scope``, so
completeness, reservation, pane identity, preview-basis recheck and execution
evidence are enforced by the existing Direct EXECUTE pipeline unchanged.

CP12H.NL4C1: pending Step Updates use the same machinery in a separate store
(``<owner>.pending_step.json``) with their own phrases (``Xác nhận cập nhật
[<step id>]`` / ``Hủy cập nhật``). A Project create record can never confirm
a Step Update, nor the reverse. The only creator is the PostToolUse(Bash)
capture of a VERIFIED, READY ``step preview``.
"""

from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock

from claude.hooks.runtime_state import (
    LOCK_TIMEOUT_SECONDS,
    replace_with_retry,
    sanitize_session_id,
    state_dir,
)

PENDING_TTL_SECONDS = 900
MAX_RECORDS = 20

PENDING = "PENDING"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"

CONFIRM = "confirm"
CANCEL = "cancel"

# Folded (casefolded, accent-free) whole-request phrases. Anything else in
# the request, a negation, an edit or a target, makes it not a confirmation.
_PHRASES = (
    (CONFIRM, ("xac", "nhan", "tao")),
    (CONFIRM, ("confirm", "create")),
    (CANCEL, ("huy", "tao")),
    (CANCEL, ("cancel", "create")),
)
_OPTIONAL_NOUNS = (("project",), ("du", "an"))
_STEP_PHRASES = (
    (CONFIRM, ("xac", "nhan", "cap", "nhat")),
    (CONFIRM, ("confirm", "update")),
    (CANCEL, ("huy", "cap", "nhat")),
    (CANCEL, ("cancel", "update")),
)
_STEP_NOUNS = (("buoc",), ("step",))
_CODE = re.compile(r"[0-9a-f]{8,32}")

PROJECT_KIND = "project"
STEP_KIND = "step"
# kind: (record key, label, confirm phrase, cancel phrase, effect word)
_KINDS = {
    PROJECT_KIND: ("project_id", "Project create", "Xác nhận tạo", "Hủy tạo", "created"),
    STEP_KIND: ("step_id", "Step Update", "Xác nhận cập nhật", "Hủy cập nhật", "updated"),
}

# Tools whose input becomes a future prompt the model wrote.
SCHEDULING_TOOLS = frozenset({"CronCreate", "ScheduleWakeup", "RemoteTrigger"})


def _now() -> float:
    return time.time()


def store_path(owner: Any, kind: str = PROJECT_KIND) -> Path:
    if kind not in _KINDS:
        raise ValueError(f"unknown pending kind {kind!r}")
    return state_dir() / f"{sanitize_session_id(owner)}.pending_{kind}.json"


def load_records(owner: Any, kind: str = PROJECT_KIND) -> list[dict[str, Any]]:
    try:
        records = json.loads(store_path(owner, kind).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(records, list):
        raise ValueError("pending confirmation store is malformed")
    return records


@contextmanager
def _locked(owner: Any, kind: str = PROJECT_KIND) -> Iterator[list[dict[str, Any]]]:
    """Yield the owner's records under an exclusive lock and persist them."""

    path = store_path(owner, kind)
    path.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(str(path.with_suffix(".lock")), timeout=LOCK_TIMEOUT_SECONDS):
        records = load_records(owner, kind)
        yield records
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(records[-MAX_RECORDS:], ensure_ascii=False), encoding="utf-8")
        replace_with_retry(temporary, path)


def record_pending(owner: Any, operation: dict[str, Any], *, run_id: str, task_id: str) -> dict[str, Any]:
    """Store one verified preview operation as the owner's pending create."""

    from claude.agents.tools.merchant.project_preview import validate_requested_operation

    validate_requested_operation(operation)
    now = _now()
    record = {
        "status": PENDING,
        "owner_session_id": str(owner),
        "source_run_id": run_id,
        "source_task_id": task_id,
        "project_id": operation["project_id"],
        "database_target": operation["database_target"],
        "operation": operation,
        "created_at": now,
        "expires_at": now + PENDING_TTL_SECONDS,
    }

    with _locked(owner) as records:
        # A re-captured preview of the same Project replaces its live record.
        records[:] = [
            r for r in records
            if not (r.get("status") == PENDING and r.get("project_id") == record["project_id"])
        ]
        records.append(record)

    return record


def record_pending_step(owner: Any, operation: dict[str, Any], *, run_id: str, task_id: str) -> dict[str, Any]:
    """Store one verified READY Step preview operation as a pending Step Update."""

    from claude.agents.tools.merchant.step_preview import validate_step_operation

    validate_step_operation(operation)
    now = _now()
    record = {
        "kind": STEP_KIND,
        "status": PENDING,
        "owner_session_id": str(owner),
        "source_run_id": run_id,
        "source_task_id": task_id,
        "step_id": operation["step_id"],
        "project_id": operation["project_id"],
        "database_target": operation["database_target"],
        "operation": operation,
        "created_at": now,
        "expires_at": now + PENDING_TTL_SECONDS,
    }

    with _locked(owner, STEP_KIND) as records:
        # A re-captured preview of the same step replaces its live record.
        records[:] = [
            r for r in records
            if not (r.get("status") == PENDING and r.get("step_id") == record["step_id"])
        ]
        records.append(record)

    return record


def parse_confirmation(text: str) -> tuple[str, str | None] | None:
    """(action, id prefix) when ``text`` is exactly a Project confirmation phrase."""

    return _parse(text, _PHRASES, _OPTIONAL_NOUNS)


def parse_step_confirmation(text: str) -> tuple[str, str | None] | None:
    """(action, step id prefix) when ``text`` is exactly a Step confirmation phrase."""

    return _parse(text, _STEP_PHRASES, _STEP_NOUNS)


def _parse(text, phrases, nouns):
    from claude.agents.tools.merchant.project_nl import fold

    tokens = fold(text).split()

    for action, phrase in phrases:
        if tuple(tokens[: len(phrase)]) != phrase:
            continue
        rest = tokens[len(phrase):]
        for noun in nouns:
            if tuple(rest[: len(noun)]) == noun:
                rest = rest[len(noun):]
                break
        if not rest:
            return action, None
        code = "".join(rest)  # a pasted UUID folds into hyphen-free parts
        return (action, code) if _CODE.fullmatch(code) else None

    return None


def _code(record: dict[str, Any], kind: str = PROJECT_KIND) -> str:
    return str(record.get(_KINDS[kind][0], ""))[:8]


def _describe(record: dict[str, Any], kind: str = PROJECT_KIND) -> str:
    operation = record.get("operation") or {}
    if kind == STEP_KIND:
        return (
            f"{_code(record, kind)} (step {operation.get('step_sequence')} "
            f"{operation.get('step_name')!r} -> {operation.get('target_status')}, "
            f"Project {operation.get('project_title')!r})"
        )
    return f"{_code(record)} ({operation.get('title')!r}, {operation.get('merchant_code')})"


def live_records(owner: Any, kind: str = PROJECT_KIND) -> list[dict[str, Any]]:
    now = _now()
    return [
        r for r in load_records(owner, kind)
        if r.get("status") == PENDING and r.get("owner_session_id") == str(owner)
        and isinstance(r.get("expires_at"), (int, float)) and now <= r["expires_at"]
    ]


def resolve(
    owner: Any,
    action: str,
    code: str | None,
    run_id: str,
    kind: str = PROJECT_KIND,
    allowed: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Spend exactly one live record of ``owner``; (record, None) or (None, reason).

    The status change is the single-use point: a replay, a concurrent
    confirmation or a crash after it finds nothing left to confirm.
    ``allowed(record)`` may refuse a confirmation (a reason string) before
    anything is spent.
    """

    key, label, confirm_word, _, effect = _KINDS[kind]
    noun = "Project" if kind == PROJECT_KIND else "step"
    now = _now()
    with _locked(owner, kind) as records:
        live = [
            r for r in records
            if r.get("status") == PENDING and r.get("owner_session_id") == str(owner)
            and isinstance(r.get("expires_at"), (int, float)) and now <= r["expires_at"]
            and (code is None or str(r.get(key, "")).replace("-", "").startswith(code))
        ]

        if not live:
            return None, (
                f"There is no pending {label}"
                + (f" matching {code!r}" if code else "")
                + " for this session to "
                + ("confirm" if action == CONFIRM else "cancel")
                + " (none was previewed here, it expired, or it was already "
                f"confirmed or cancelled). Nothing was {effect}. Preview the "
                f"{noun} again to get a fresh confirmation."
            )

        if len(live) > 1:
            return None, (
                f"More than one {label} is pending: "
                + "; ".join(_describe(r, kind) for r in live)
                + f". Say which one with its id, for example `/solve {confirm_word} "
                + _code(live[-1], kind)
                + f"`. Nothing was {effect}."
            )

        (record,) = live
        refusal = allowed(record) if action == CONFIRM and allowed is not None else None
        if refusal:
            return None, refusal  # nothing spent
        if action == CONFIRM:
            record.update(status=CONFIRMED, confirmed_at=now, confirmed_run_id=run_id)
        else:
            record.update(status=CANCELLED, cancelled_at=now)
        return dict(record), None


def confirmed_step_record(owner: Any, run_id: Any) -> dict[str, Any] | None:
    """CP12H.NL4C2A: the one Step Update the owner confirmed for ``run_id``.

    The execution preflight requires it, so a Step Update scope that did not
    come from the user's own confirmation of a verified preview never runs.
    Read only: the confirmation was already spent by ``resolve``.
    """

    matches = [
        r for r in load_records(owner, STEP_KIND)
        if r.get("status") == CONFIRMED and r.get("owner_session_id") == str(owner)
        and isinstance(run_id, str) and run_id and r.get("confirmed_run_id") == run_id
    ]
    return dict(matches[0]) if len(matches) == 1 else None


def bare_phrase_guidance(owner: Any, prompt: str) -> str | None:
    """Reason to refuse a confirmation typed without ``/solve``, if one is pending."""

    for kind, parse in ((PROJECT_KIND, parse_confirmation), (STEP_KIND, parse_step_confirmation)):
        parsed = parse(prompt)
        if parsed is None or not live_records(owner, kind):
            continue
        _, label, confirm_word, cancel_word, _ = _KINDS[kind]
        word = confirm_word if parsed[0] == CONFIRM else cancel_word
        return (
            f"A {label} is pending. To {parsed[0]} it, type `/solve {word}` "
            "(add its id when more than one is pending). Nothing was created or changed."
        )
    return None


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def scheduled_prompt_denial(tool_name: str, tool_input: Any) -> str | None:
    """Deny scheduling a prompt that would start a controlled run or confirm.

    A scheduled prompt is model-written text submitted later as if typed, so
    it must never carry a controlled command or a confirmation phrase.
    """

    if tool_name not in SCHEDULING_TOOLS:
        return None

    from claude.hooks.intent_gate import parse_prompt

    for text in _strings(tool_input):
        try:
            controlled = parse_prompt(text) is not None
        except ValueError:
            controlled = True
        if (
            controlled
            or parse_confirmation(text) is not None
            or parse_step_confirmation(text) is not None
        ):
            return (
                f"Blocked: {tool_name} would submit a controlled /solve or "
                "/schedule-agent prompt, or a Project or Step confirmation, as if the "
                "user had typed it. Only the user can start or confirm a "
                "controlled run. Nothing was scheduled."
            )

    return None
