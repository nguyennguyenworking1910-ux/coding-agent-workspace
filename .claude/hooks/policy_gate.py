#!/usr/bin/env python3
"""PreToolUse hook: enforce the envelope's limits on every tool call.

The envelope decides what a run is allowed to do; this is what makes that
binding. It fires for every tool, in the main session and inside subagents, and
denies the call when it would exceed the budget, dispatch an agent that was never
selected, mutate anything during a read-only run, or run a destructive command
without the risk level and confirmation to back it.

When the session has no run state, the hook stays silent — an ordinary session is
not a controlled run, and this must never become a global tool firewall.

Output uses `hookSpecificOutput.permissionDecision`, not the deprecated
top-level `decision` field, which PreToolUse no longer reads.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_state import locked_state  # noqa: E402  (path shim must run first)

HOOK_EVENT_NAME = "PreToolUse"

# `Task` is the old name for the dispatch tool; a session mid-migration can still
# emit it, and it must not become an unmetered way to spawn agents.
AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})

FILE_WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})

COORDINATION_TOOLS = frozenset({"SendMessage", "TaskUpdate"})

SHELL_TOOLS = frozenset({"Bash", "PowerShell", "BashOutput"})

RISK_READ_ONLY = "read_only"
RISK_WRITE = "write"
RISK_EXTERNAL_WRITE = "external_write"
RISK_DESTRUCTIVE = "destructive"

# Verbs that mark a tool as mutating something outside this machine.
EXTERNAL_MUTATION_VERBS = ("create", "update", "delete", "send", "publish", "upload")

# Harness-local tools whose names collide with those verbs but which mutate only
# session-local bookkeeping. Without this, a read-only run could not track its own
# task list.
#
# `SendMessage` belongs here for the same reason and matters more: "send" reads as
# an external verb, but it only writes to a teammate mailbox inside this session.
# It is also the single path by which a teammate's report reaches the lead, so
# denying it does not make a run safer — it silently discards the run's output
# while every pane still looks like it succeeded.
LOCAL_MUTATION_EXEMPT = frozenset(
    {
        "TaskCreate",
        "TaskUpdate",
        "TaskGet",
        "TaskList",
        "TaskOutput",
        "TaskStop",
        "TodoWrite",
        "SendMessage",
    }
)

# tool_input fields that carry something executable. Deliberately excludes
# `content`: a document that mentions "drop table" is not a destructive command,
# and scanning file bodies would make writing this very file impossible.
COMMAND_FIELDS = ("command", "query", "sql", "statement", "script", "code")

_DESTRUCTIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bdrop\s+(table|database|schema)\b"), "drops a table or database"),
    (re.compile(r"(?i)\btruncate\s+table\b"), "truncates a table"),
    (
        re.compile(r"(?i)\bdelete\s+(from\s+)?\S*(production|prod)\b"),
        "deletes production data",
    ),
    (re.compile(r"(?i)\bgit\s+push\b[^\n]*\s(--force|-f)\b"), "force-pushes git history"),
    (
        re.compile(r"(?i)\bgit\s+push\b[^\n]*--force-with-lease\b"),
        "force-pushes git history",
    ),
    (re.compile(r"(?i)\breset\s+--hard\b"), "discards work with reset --hard"),
    (re.compile(r"(?i)\bgit\s+clean\b[^\n]*-[a-z]*[dx]"), "deletes untracked files"),
    (re.compile(r"(?i)\brmdir\s+/s\b"), "recursively deletes a directory tree"),
)

# `rm -rf`, in either flag order, and PowerShell's equivalent.
_RECURSIVE_DELETE_PATTERNS = (
    re.compile(r"(?i)\brm\s+(?:-[a-z]*\s+)*-?[a-z]*r[a-z]*f[a-z]*\b(?P<targets>[^\n;&|]*)"),
    re.compile(r"(?i)\brm\s+(?:-[a-z]*\s+)*-?[a-z]*f[a-z]*r[a-z]*\b(?P<targets>[^\n;&|]*)"),
    re.compile(
        r"(?i)\bremove-item\b(?=[^\n]*-recurse)(?=[^\n]*-force)(?P<targets>[^\n;&|]*)"
    ),
)

# Targets broad enough that a recursive delete is not a scoped cleanup.
_BROAD_TARGETS = re.compile(
    r"""(?ix)
    (^|\s)
    (
        [/\\]                        # filesystem root
      | ~ [/\\]?                     # home
      | \$HOME | \$\{HOME\}          # home, via env
      | %USERPROFILE%
      | [A-Za-z]:[/\\]?(\s|$)        # a drive root
      | \.{1,2}[/\\]?(\s|$)          # . or ..
      | \*                           # any glob
      | /(usr|etc|var|bin|home|opt|Users)\b
    )
    """
)

# Shell commands that write. Read-only git verbs are deliberately absent.
_MUTATING_SHELL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)^\s*(sudo\s+)?(rm|mv|cp|mkdir|rmdir|touch|ln|chmod|chown)\b"), "writes to the filesystem"),
    (re.compile(r"(?i)\b(rm|mv|mkdir|rmdir|touch|chmod|chown)\s+-"), "writes to the filesystem"),
    (re.compile(r"(?i)\bsed\s+-i\b"), "edits a file in place"),
    (re.compile(r"(?i)\b(tee|dd)\b"), "writes to a file"),
    (
        re.compile(
            r"(?i)\bgit\s+(add|commit|push|pull|merge|rebase|reset|revert|checkout"
            r"|switch|restore|stash|tag|clean|apply|cherry-pick)\b"
        ),
        "changes git state",
    ),
    (
        re.compile(r"(?i)\b(pip|pip3|npm|pnpm|yarn|poetry|uv|gem|cargo|apt|apt-get|brew|choco)\s+(install|add|remove|uninstall|update|upgrade|publish)\b"),
        "installs or publishes packages",
    ),
    (re.compile(r"(?i)\bcurl\b[^\n]*\s-(X|-request)\s*(POST|PUT|PATCH|DELETE)\b"), "sends a mutating HTTP request"),
    (re.compile(r"(?i)\b(docker|kubectl|terraform|gcloud|aws|az)\s+(run|apply|create|delete|deploy|push|set|destroy)\b"), "mutates an external system"),
    (re.compile(r"(?i)\bbq\s+(insert|load|rm|mk|cp|update)\b"), "mutates BigQuery"),
    (re.compile(r"(?i)\b(insert\s+into|update\s+\S+\s+set|delete\s+from|create\s+table|alter\s+table)\b"), "writes to a database"),
    (
        re.compile(r"(?i)\b(Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Copy-Item|Move-Item|Rename-Item|Clear-Content|Set-ItemProperty)\b"),
        "writes to the filesystem",
    ),
    (re.compile(r"(?i)\bgit\s+push\b"), "pushes to a remote"),
)

# Redirections that are not writes: discarding output, or merging streams.
_HARMLESS_REDIRECTS = re.compile(r"(?i)(\d?>>?\s*(/dev/null|\$null|NUL)\b|\d>&\d)")

_REDIRECT_WRITE = re.compile(r">>?")


def _decision(decision: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT_NAME,
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def deny(reason: str) -> dict[str, Any]:
    return _decision("deny", reason)


def ask(reason: str) -> dict[str, Any]:
    return _decision("ask", reason)


def command_text(tool_input: dict[str, Any]) -> str:
    """Collect the executable parts of a tool input, ignoring file bodies."""
    if not isinstance(tool_input, dict):
        return ""

    parts = [
        str(tool_input[field])
        for field in COMMAND_FIELDS
        if isinstance(tool_input.get(field), str)
    ]

    return "\n".join(parts)


def find_destructive(text: str) -> str | None:
    """Return a description of the destructive action in `text`, or None."""
    if not text:
        return None

    for pattern, description in _DESTRUCTIVE_PATTERNS:
        if pattern.search(text):
            return description

    for pattern in _RECURSIVE_DELETE_PATTERNS:
        match = pattern.search(text)

        if match and _BROAD_TARGETS.search(match.group("targets") or ""):
            return "recursively deletes a broad path"

    return None


def find_mutation(text: str) -> str | None:
    """Return a description of the filesystem/external write in `text`, or None."""
    if not text:
        return None

    for pattern, description in _MUTATING_SHELL_PATTERNS:
        if pattern.search(text):
            return description

    stripped = _HARMLESS_REDIRECTS.sub("", text)

    if _REDIRECT_WRITE.search(stripped):
        return "redirects output into a file"

    return None


def is_external_mutation_tool(tool_name: str) -> bool:
    if tool_name in LOCAL_MUTATION_EXEMPT:
        return False

    lowered = tool_name.lower()

    return any(verb in lowered for verb in EXTERNAL_MUTATION_VERBS)


def _limit(state: dict[str, Any], name: str) -> int | None:
    limits = state.get("limits")

    if not isinstance(limits, dict):
        return None

    value = limits.get(name)

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coordination_reserve(state: dict[str, Any]) -> int:
    """Calculate the coordination reserve for SendMessage/TaskUpdate.

    These tools are essential for handoff between team leader and teammates.
    They must not be blocked just because regular tool calls exhausted the budget.

    Reserve is min(max_total_tool_calls, 2 * max_members), sized so that in the
    worst case with max_members teammates, each can deliver their result once.
    """
    max_total = _limit(state, "max_total_tool_calls")
    max_members = _limit(state, "max_members")

    if max_total is None or max_members is None:
        return 0

    return min(max_total, 2 * max_members)


def apply_call(
    state: dict[str, Any],
    tool_name: str,
    tool_input: dict[str, Any],
) -> dict[str, Any] | None:
    """Count the call, mutate `state`, and return a decision when one is needed.

    `state` is modified in place; the caller persists it. Counting happens before
    any early return so a denied call still consumes budget — otherwise a loop of
    denied calls would be free.

    SendMessage and TaskUpdate are not subject to the regular budget cap; they
    draw from a coordination reserve instead so that handoff communication is never
    blocked by tool exhaustion.
    """
    state["total_tool_calls"] = int(state.get("total_tool_calls", 0)) + 1

    max_total = _limit(state, "max_total_tool_calls")
    is_coordination_tool = tool_name in COORDINATION_TOOLS

    if max_total is not None:
        if is_coordination_tool:
            # Coordination tools are not subject to the regular budget;
            # they use a reserve. But they still count toward the hard cap.
            if state["total_tool_calls"] > max_total:
                return deny(
                    f"Coordination budget exhausted: this run has used "
                    f"{state['total_tool_calls']} of {max_total} total calls. "
                    "The hard cap includes coordination calls. "
                    "Report what is done so far and stop."
                )
        else:
            # Regular tools are subject to regular budget minus the reserve.
            coordination_reserve = _coordination_reserve(state)
            regular_budget = max(0, max_total - coordination_reserve)
            regular_calls = int(state.get("total_tool_calls_regular", 0))

            if regular_calls >= regular_budget:
                return deny(
                    f"Tool-call budget exhausted: this run has used "
                    f"{regular_calls} of {regular_budget} regular calls "
                    f"(coordination reserve: {coordination_reserve}). "
                    f"Report what is done so far and stop; a new request gets a new envelope."
                )

            state["total_tool_calls_regular"] = regular_calls + 1

    risk_level = str(state.get("risk_level") or "")
    confirmed = bool(state.get("confirmed"))

    text = command_text(tool_input)

    destructive = find_destructive(text)

    if destructive is not None:
        if risk_level != RISK_DESTRUCTIVE:
            return deny(
                f"Blocked: this command {destructive}, but the run was classified "
                f"risk_level={risk_level or 'unknown'}. A destructive action needs "
                "an envelope that says so. Stop and ask the user to resubmit."
            )

        if not confirmed:
            return deny(
                f"Blocked: this command {destructive} and the run is not confirmed. "
                "Resubmit the request with `--confirm` to authorize it."
            )

        return ask(
            f"This command {destructive}. The envelope authorizes it "
            "(risk_level=destructive, confirmed), so it still needs your explicit "
            "approval here."
        )

    if tool_name in AGENT_TOOL_NAMES:
        return _check_agent_dispatch(state, tool_input)

    if risk_level == RISK_READ_ONLY:
        if tool_name in FILE_WRITE_TOOLS:
            return deny(
                f"Blocked: {tool_name} writes files, but this run is read-only. "
                "Report the change you would make instead of making it."
            )

        if tool_name in SHELL_TOOLS:
            mutation = find_mutation(text)

            if mutation is not None:
                return deny(
                    f"Blocked: this command {mutation}, but this run is read-only. "
                    "Use a read-only command, or ask the user for a run that can write."
                )

    if is_external_mutation_tool(tool_name):
        if risk_level not in (RISK_EXTERNAL_WRITE, RISK_DESTRUCTIVE):
            return deny(
                f"Blocked: {tool_name} mutates an external system, but the run was "
                f"classified risk_level={risk_level or 'unknown'}. Stop and ask the "
                "user to resubmit if this is really wanted."
            )

        if not confirmed:
            return deny(
                f"Blocked: {tool_name} mutates an external system and the run is not "
                "confirmed. Resubmit the request with `--confirm` to authorize it."
            )

    return None


def _check_agent_dispatch(
    state: dict[str, Any],
    tool_input: dict[str, Any],
) -> dict[str, Any] | None:
    """Enforce the roster, the member cap, and the dispatch-round cap.

    Members are tracked by their unique `name` field, not by subagent_type.
    Multiple instances with the same subagent_type but different names are
    distinct members and each consumes a slot.
    """
    subagent_type = ""
    teammate_name = ""

    if isinstance(tool_input, dict):
        subagent_type = str(tool_input.get("subagent_type") or "").strip()
        teammate_name = str(tool_input.get("name") or "").strip()

    selected_agents = [str(agent) for agent in state.get("selected_agents") or []]

    if not subagent_type:
        return deny(
            "Blocked: the dispatch names no subagent_type. Dispatch only agents from "
            f"selected_agents: {', '.join(selected_agents) or '(none)'}."
        )

    if subagent_type not in selected_agents:
        return deny(
            f"Blocked: '{subagent_type}' is not in selected_agents "
            f"({', '.join(selected_agents) or 'none'}). Substituting another agent is "
            "not allowed — report that the roster does not cover this work and stop."
        )

    if not teammate_name:
        return deny(
            "Blocked: the dispatch provides no name. Each teammate must have a stable, "
            "unique name. Provide it via the `name` parameter."
        )

    max_rounds = _limit(state, "max_tool_rounds")
    agent_rounds = int(state.get("agent_rounds", 0))

    if max_rounds is not None and agent_rounds >= max_rounds:
        return deny(
            f"Blocked: this run has already used its {max_rounds} dispatch round(s) "
            f"for task_class {state.get('task_class')}. Synthesize what the agents "
            "reported and stop."
        )

    members_used = [str(member) for member in state.get("members_used") or []]

    if teammate_name not in members_used:
        max_members = _limit(state, "max_members")

        if max_members is not None and len(members_used) + 1 > max_members:
            return deny(
                f"Blocked: dispatching teammate '{teammate_name}' would make "
                f"{len(members_used) + 1} members, over the {max_members} allowed for "
                f"task_class {state.get('task_class')}. Already dispatched: "
                f"{', '.join(members_used) or 'none'}."
            )

        members_used.append(teammate_name)
        state["members_used"] = members_used

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if not isinstance(payload, dict):
        return 0

    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")

    if not isinstance(tool_input, dict):
        tool_input = {}

    output: dict[str, Any] | None = None

    with locked_state(payload.get("session_id")) as state:
        if state is not None:
            output = apply_call(state, tool_name, tool_input)

    if output:
        print(json.dumps(output, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
