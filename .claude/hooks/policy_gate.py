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

import hashlib
import hmac
import json
import re
import sys
import shlex
import uuid
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(
        0,
        str(
            Path(__file__).resolve().parent
        ),
    )

    from runtime_state import (  # noqa: E402
        MERCHANT_CONFIRMATION_MODE_FIELD,
        MERCHANT_CONFIRMATION_MODE_LOCAL_AUTO,
        MERCHANT_CONFIRMATION_MODE_MANUAL,
        locked_state,
    )

    from merchant_confirmation_preferences import (  # noqa: E402
        reserve_receipt,
    )

    from team_lifecycle import (  # noqa: E402
        TeammateAllocationDecision,
        TeammateLifecycleStatus,
        allocate_teammate,
        check_role_in_selected_agents,
        find_unique_active_teammate_owner,
        mark_teammate_running,
        reserve_reusable_teammate,
        load_team_state,
    )

    from tmux_merchant_resolution import (  # noqa: E402
        load_pending_merchant_resolution,
    )

    from merchant_resolution_gate import (  # noqa: E402
        BOUND as PROJECT_BOUND,
        bind_merchant_resolution_receipt,
    )
    from tmux_project_resolution import (
        load_pending_project_resolution,
    )

    from project_resolution_gate import (
        BOUND,
        bind_project_resolution_receipt,
    )
    from tmux_step_resolution import (
        load_pending_step_resolution,
    )
    from step_resolution_gate import (
        BOUND as STEP_BOUND,
        bind_step_resolution_receipt,
    )
    from tmux_document_revision_resolution import (
        load_pending_document_revision_resolution,
    )

    from document_revision_resolution_gate import (
        BOUND as DOCUMENT_REVISION_BOUND,
        bind_document_revision_resolution_receipt,
    )

else:
    from .runtime_state import (
        MERCHANT_CONFIRMATION_MODE_FIELD,
        MERCHANT_CONFIRMATION_MODE_LOCAL_AUTO,
        MERCHANT_CONFIRMATION_MODE_MANUAL,
        locked_state,
    )

    from .merchant_confirmation_preferences import (
        reserve_receipt,
    )

    from .team_lifecycle import (
        TeammateAllocationDecision,
        TeammateLifecycleStatus,
        allocate_teammate,
        check_role_in_selected_agents,
        find_unique_active_teammate_owner,
        mark_teammate_running,
        reserve_reusable_teammate,
        load_team_state,
    )

    from .tmux_merchant_resolution import (
        load_pending_merchant_resolution,
    )

    from .merchant_resolution_gate import (
        BOUND as PROJECT_BOUND,
        bind_merchant_resolution_receipt,
    )
    from .tmux_project_resolution import (
        load_pending_project_resolution,
    )

    from .project_resolution_gate import (
        BOUND,
        bind_project_resolution_receipt,
    )
    from .tmux_step_resolution import (
        load_pending_step_resolution,
    )
    from .step_resolution_gate import (
        BOUND as STEP_BOUND,
        bind_step_resolution_receipt,
    )
    from .tmux_document_revision_resolution import (
        load_pending_document_revision_resolution,
    )

    from .document_revision_resolution_gate import (
        BOUND as DOCUMENT_REVISION_BOUND,
        bind_document_revision_resolution_receipt,
    )

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

MERCHANT_MANAGER_AGENT = "merchant-manager"
MERCHANT_OPERATIONS = frozenset(
    {"merchant_read", "merchant_propose", "merchant_apply"}
)
MERCHANT_WRITE_COMMANDS = frozenset(
    {
        "contact import",
        "document approve",
        "document revision-create",
        "integration identifier-set",
        "merchant activate",
        "merchant activate-all",
        "merchant create",
        "procurement update",
        "project create",
        "project update",
        "step update",
    }
)
MERCHANT_APPLY_OPERATION = "merchant_apply"
MERCHANT_PROPOSE_OPERATION = "merchant_propose"
MERCHANT_DISPATCH_MARKER = (
    "MERCHANT_DISPATCH_AUTHORIZATION_JSON"
)
MERCHANT_DISPATCH_MODE = (
    "CONFIRMED_APPLY_PENDING_RUNTIME_AUTHORITY"
)
MERCHANT_CONFIRMATION_FIELDS = frozenset(
    {
        "contract_version",
        "confirmation_version",
        "operation",
        "command",
        "database_target",
        "expected_version",
        "payload_hash",
        "proposal_hash",
        "confirmation_hash",
    }
)
MERCHANT_DISPATCH_FIELDS = (
    MERCHANT_CONFIRMATION_FIELDS | {"authorized_mode"}
)
MERCHANT_HASH_FIELDS = (
    "payload_hash",
    "proposal_hash",
    "confirmation_hash",
)

_MERCHANT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MERCHANT_DISPATCH_BLOCK_PATTERN = re.compile(
    r"(?ms)^MERCHANT_DISPATCH_AUTHORIZATION_JSON[ \t]*\r?\n"
    r"```json[ \t]*\r?\n"
    r"(?P<payload>\{.*?\})\r?\n"
    r"```[ \t]*$"
)


# A merchant_propose assignment carries semantic intent only. Concrete CLI
# spelling belongs to merchant-manager's registered contract, not to the lead
# prompt. This catches command-shaped text without blocking ordinary prose
# such as "run completeness before --propose".
_MERCHANT_PROPOSE_ASSIGNMENT_CLI_PATTERN = re.compile(
    r"""(?ix)
    \b(
        merchant\s+(?:list|resolve|activate(?:-all)?|create)
      | project\s+(?:list|resolve|show|history|blockers|alerts|create|update)
      | step\s+(?:resolve|update)
      | document\s+(?:resolve|revision-create|approve)
      | procurement\s+update
      | integration\s+identifier-set
      | contact\s+import
      | completeness\s+check
    )\b
    [^\r\n]{0,400}
    --[a-z0-9][a-z0-9-]*
    """
)

_MERCHANT_AGENT_CLI_REFERENCE_PATTERN = re.compile(
    r"(?i)(?:^|[/\\])agent_cli\.py\b"
)

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


def _direct_merchant_agent_cli_tokens(
    command: Any,
) -> tuple[str, ...] | None:
    """Parse only one direct Merchant agent CLI invocation."""

    if not isinstance(
        command,
        str,
    ):
        return None

    text = command.strip()

    if not text:
        return None

    try:
        tokens = tuple(
            shlex.split(
                text,
                posix=True,
            )
        )
    except ValueError:
        return None

    if len(tokens) < 4:
        return None

    shell_operators = {
        "|",
        "||",
        "&&",
        ";",
        ">",
        ">>",
        "<",
        "2>",
        "2>>",
        "2>&1",
    }

    if any(
        token in shell_operators
        for token in tokens
    ):
        return None

    executable = (
        tokens[0]
        .replace("\\", "/")
        .lower()
    )

    if executable not in {
        "python",
        "python.exe",
        "py",
        "py.exe",
        ".venv/scripts/python.exe",
        "./.venv/scripts/python.exe",
    }:
        return None

    script = (
        tokens[1]
        .replace("\\", "/")
    )

    if script.startswith("./"):
        script = script[2:]

    if script != (
        ".claude/agents/tools/"
        "merchant/agent_cli.py"
    ):
        return None

    return tokens


def _canonical_merchant_uuid(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    try:
        return str(
            uuid.UUID(
                value.strip()
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
    ):
        return None


def _canonical_project_uuid(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    try:
        return str(
            uuid.UUID(
                value.strip()
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
    ):
        return None

def _canonical_step_uuid(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    try:
        return str(
            uuid.UUID(
                value.strip()
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
    ):
        return None

def _canonical_document_revision_uuid(
    value: Any,
) -> str | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    try:
        return str(
            uuid.UUID(
                value.strip()
            )
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
    ):
        return None

def _merchant_id_from_cli_tokens(
    tokens: tuple[str, ...],
) -> tuple[str, str | None]:
    """Return normalized command and consumed Merchant id.

    Supported Merchant-id forms:

    --merchant-id <uuid>
    --merchant-id=<uuid>

    plus the registered positional Merchant id for:

    integration identifier-set <merchant_id>
    """

    if len(tokens) < 4:
        return "", None

    command = (
        f"{tokens[2]} {tokens[3]}"
        .strip()
        .lower()
    )

    arguments = tokens[4:]

    # ------------------------------------------------------------
    # Flag form.
    # ------------------------------------------------------------
    for index, token in enumerate(
        arguments
    ):
        if token == "--merchant-id":
            if (
                index + 1
                >= len(arguments)
            ):
                return command, ""

            return (
                command,
                arguments[
                    index + 1
                ],
            )

        if token.startswith(
            "--merchant-id="
        ):
            return (
                command,
                token.split(
                    "=",
                    1,
                )[1],
            )

    # ------------------------------------------------------------
    # Registered positional form.
    #
    # CLI contract:
    #
    # integration identifier-set <merchant_id> [project_id] ...
    # ------------------------------------------------------------
    if (
        command
        == "integration identifier-set"
    ):
        if not arguments:
            return command, ""

        first_argument = (
            arguments[0]
        )

        if first_argument.startswith(
            "-"
        ):
            return command, ""

        return (
            command,
            first_argument,
        )

    return command, None


def _project_id_from_cli_tokens(
    tokens: tuple[str, ...],
) -> tuple[str, str | None]:
    """Return normalized command and consumed Project id.

    Supported Project-id forms:

    Positional required:
        project show <project_id>
        project history <project_id>
        project blockers <project_id>
        project update <project_id>
        document revision-create <project_id>
        procurement update <project_id>

    Project alerts compatibility forms:
        project alerts <project_id>
        project alerts --project-id <project_id>
        project alerts --project-id=<project_id>

    Optional positional Project scope:
        integration identifier-set <merchant_id> [project_id]

    Return semantics:

    None
        command does not consume a Project id.

    ""
        command attempted to consume a Project id but the invocation is
        malformed or conflicting. Caller must fail closed.

    UUID/text
        supplied Project id to canonicalize and bind.
    """

    if len(tokens) < 4:
        return "", None

    command = (
        f"{tokens[2]} {tokens[3]}"
        .strip()
        .lower()
    )

    arguments = tokens[4:]

    # ------------------------------------------------------------
    # Required positional Project-id commands.
    # ------------------------------------------------------------

    positional_project_commands = frozenset(
        {
            "project show",
            "project history",
            "project blockers",
            "project update",
            "document revision-create",
            "procurement update",
        }
    )

    if (
        command
        in positional_project_commands
    ):
        if not arguments:
            return command, ""

        project_id = arguments[0]

        if project_id.startswith("-"):
            return command, ""

        return (
            command,
            project_id,
        )

    # ------------------------------------------------------------
    # step resolve
    #
    # CLI contract:
    #
    # step resolve
    #     --project-id <trusted-project-id>
    #     --query <step-reference>
    #
    # Project binding must already exist before Step resolution.
    # ------------------------------------------------------------

    if command == "step resolve":
        supplied_project_id: str | None = None

        index = 0

        while index < len(
            arguments
        ):
            token = arguments[index]

            if token == "--project-id":
                if (
                    supplied_project_id
                    is not None
                ):
                    return command, ""

                if (
                    index + 1
                    >= len(arguments)
                ):
                    return command, ""

                value = str(
                    arguments[
                        index + 1
                    ]
                ).strip()

                if (
                    not value
                    or value.startswith("-")
                ):
                    return command, ""

                supplied_project_id = (
                    value
                )

                index += 2
                continue

            if token.startswith(
                "--project-id="
            ):
                if (
                    supplied_project_id
                    is not None
                ):
                    return command, ""

                value = (
                    token.split(
                        "=",
                        1,
                    )[1]
                    .strip()
                )

                if not value:
                    return command, ""

                supplied_project_id = (
                    value
                )

                index += 1
                continue

            index += 1

        if supplied_project_id is None:
            return command, ""

        return (
            command,
            supplied_project_id,
        )

    # ------------------------------------------------------------
    # project alerts
    #
    # CLI contract:
    #
    # project alerts [legacy_project_id]
    #                [--merchant-id UUID]
    #                [--project-id UUID]
    #                [...]
    #
    # Both positional and --project-id are accepted for backwards
    # compatibility. If both exist they must identify the same
    # Project; otherwise fail closed before argparse/command logic.
    # ------------------------------------------------------------

    if command == "project alerts":
        legacy_project_id: str | None = None
        filtered_project_id: str | None = None

        if (
            arguments
            and not arguments[0].startswith("-")
        ):
            legacy_project_id = (
                arguments[0]
            )

        index = 0

        while index < len(
            arguments
        ):
            token = arguments[index]

            if token == "--project-id":
                if filtered_project_id is not None:
                    return command, ""

                if (
                    index + 1
                    >= len(arguments)
                ):
                    return command, ""

                value = str(
                    arguments[
                        index + 1
                    ]
                ).strip()

                if (
                    not value
                    or value.startswith("-")
                ):
                    return command, ""

                filtered_project_id = (
                    value
                )

                index += 2
                continue

            if token.startswith(
                "--project-id="
            ):
                if filtered_project_id is not None:
                    return command, ""

                value = (
                    token.split(
                        "=",
                        1,
                    )[1]
                    .strip()
                )

                if not value:
                    return command, ""

                filtered_project_id = (
                    value
                )

                index += 1
                continue

            index += 1

        if (
            legacy_project_id is not None
            and filtered_project_id is not None
            and legacy_project_id
            != filtered_project_id
        ):
            return command, ""

        if filtered_project_id is not None:
            return (
                command,
                filtered_project_id,
            )

        if legacy_project_id is not None:
            return (
                command,
                legacy_project_id,
            )

        # Global / merchant-filtered alert read.
        # No Project binding required.
        return command, None

    # ------------------------------------------------------------
    # integration identifier-set
    #
    # CLI contract:
    #
    # integration identifier-set
    #     <merchant_id>
    #     [project_id]
    #     --type ...
    #     --value ...
    #     --scope ...
    #
    # merchant_id is enforced independently by Gate 12D.
    # Project binding is required only when optional project_id exists.
    # ------------------------------------------------------------

    if (
        command
        == "integration identifier-set"
    ):
        if not arguments:
            # Merchant gate will reject the missing merchant id.
            return command, None

        merchant_id = arguments[0]

        if merchant_id.startswith("-"):
            # Again, Merchant gate owns this invalidity.
            return command, None

        if len(arguments) < 2:
            return command, None

        possible_project_id = (
            arguments[1]
        )

        if possible_project_id.startswith(
            "-"
        ):
            # Merchant-scoped identifier only.
            return command, None

        return (
            command,
            possible_project_id,
        )

    return command, None

def _document_revision_id_from_cli_tokens(
    tokens: tuple[str, ...],
) -> tuple[
    str,
    str | None,
    str | None,
]:
    """Return command, consumed revision id, and required resolver scope.

    Protected consumers:

    document approve <revision_id>
        -> PROJECT scope

    project create --reused-document-revision-id <revision_id>
        -> MERCHANT scope

    Return semantics for revision id:

    None
        command does not consume an existing Document Revision.

    ""
        command attempts to consume a revision but the invocation is
        malformed or conflicting.

    value
        supplied revision id to canonicalize and bind.
    """

    if len(tokens) < 4:
        return "", None, None

    command = (
        f"{tokens[2]} {tokens[3]}"
        .strip()
        .lower()
    )

    arguments = tokens[4:]

    # Resolver establishes evidence; it does not consume it.
    if command == "document resolve":
        return (
            command,
            None,
            None,
        )

    # ------------------------------------------------------------
    # document approve <revision_id>
    # ------------------------------------------------------------

    if command == "document approve":
        if not arguments:
            return (
                command,
                "",
                "PROJECT",
            )

        revision_id = (
            arguments[0]
        )

        if (
            not revision_id
            or revision_id.startswith(
                "-"
            )
        ):
            return (
                command,
                "",
                "PROJECT",
            )

        return (
            command,
            revision_id,
            "PROJECT",
        )

    # ------------------------------------------------------------
    # project create
    #
    # --reused-document-revision-id UUID
    # --reused-document-revision-id=UUID
    # ------------------------------------------------------------

    if command == "project create":
        revision_id: str | None = None
        seen = False

        index = 0

        while index < len(
            arguments
        ):
            token = arguments[
                index
            ]

            if (
                token
                == "--reused-document-revision-id"
            ):
                if seen:
                    return (
                        command,
                        "",
                        "MERCHANT",
                    )

                if (
                    index + 1
                    >= len(arguments)
                ):
                    return (
                        command,
                        "",
                        "MERCHANT",
                    )

                value = str(
                    arguments[
                        index + 1
                    ]
                ).strip()

                if (
                    not value
                    or value.startswith(
                        "-"
                    )
                ):
                    return (
                        command,
                        "",
                        "MERCHANT",
                    )

                revision_id = value
                seen = True
                index += 2
                continue

            if token.startswith(
                "--reused-document-revision-id="
            ):
                if seen:
                    return (
                        command,
                        "",
                        "MERCHANT",
                    )

                value = (
                    token.split(
                        "=",
                        1,
                    )[1]
                    .strip()
                )

                if not value:
                    return (
                        command,
                        "",
                        "MERCHANT",
                    )

                revision_id = value
                seen = True

            index += 1

        if not seen:
            return (
                command,
                None,
                None,
            )

        return (
            command,
            revision_id,
            "MERCHANT",
        )

    return (
        command,
        None,
        None,
    )

def _step_id_from_cli_tokens(
    tokens: tuple[str, ...],
) -> tuple[str, str | None]:
    """Return normalized command and consumed Step id.

    Current Step-id consumer:

        step update <step_id>

    Return semantics:

    None
        command does not consume a Step id.

    ""
        command attempted to consume a Step id but invocation
        is malformed. Caller must fail closed.

    UUID/text
        supplied Step id to canonicalize and bind.
    """

    if len(tokens) < 4:
        return "", None

    command = (
        f"{tokens[2]} {tokens[3]}"
        .strip()
        .lower()
    )

    arguments = tokens[4:]

    if command == "step update":
        if not arguments:
            return command, ""

        step_id = arguments[0]

        if step_id.startswith(
            "-"
        ):
            return command, ""

        return (
            command,
            step_id,
        )

    return command, None

def merchant_resolution_use_decision(
    payload: dict[str, Any],
    session_id: Any,
) -> dict[str, Any] | None:
    """Require trusted resolver evidence before consuming merchant_id."""

    sender_agent_type = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if (
        sender_agent_type
        != MERCHANT_MANAGER_AGENT
    ):
        return None

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    if tool_name not in {
        "Bash",
        "PowerShell",
    }:
        return None

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return None

    command_text_value = (
        tool_input.get(
            "command"
        )
    )

    tokens = (
        _direct_merchant_agent_cli_tokens(
            command_text_value
        )
    )

    # ------------------------------------------------------------
    # A Merchant CLI reference that is not one direct invocation is
    # not allowed to bypass entity binding via wrappers/pipelines.
    # ------------------------------------------------------------
    if tokens is None:
        raw_command = str(
            command_text_value
            or ""
        )

        normalized_raw = (
            raw_command
            .replace(
                "\\",
                "/",
            )
            .lower()
        )

        if (
            "agents/tools/merchant/agent_cli.py"
            in normalized_raw
        ):
            return deny(
                "Blocked: Merchant CLI must be invoked directly. "
                "Wrapper scripts, pipelines, redirects, shell chaining, "
                "and reconstructed Merchant commands cannot consume "
                "trusted entity bindings."
            )

        return None

    (
        merchant_command,
        supplied_merchant_id,
    ) = _merchant_id_from_cli_tokens(
        tokens
    )

    # Resolver itself establishes evidence.
    if (
        merchant_command
        == "merchant resolve"
    ):
        return None

    # Creating a brand-new Merchant is the one existing-entity exception.
    if (
        merchant_command
        == "merchant create"
    ):
        return None

    # This command does not consume --merchant-id.
    if supplied_merchant_id is None:
        return None

    canonical_supplied_id = (
        _canonical_merchant_uuid(
            supplied_merchant_id
        )
    )

    if canonical_supplied_id is None:
        return deny(
            "Blocked: --merchant-id must be a canonical Merchant UUID."
        )

    (
        owner_session_id,
        owner_record,
        owner_resolution,
    ) = (
        find_unique_active_teammate_owner(
            MERCHANT_MANAGER_AGENT
        )
    )

    if (
        owner_resolution
        != "FOUND"
        or not owner_session_id
        or not isinstance(
            owner_record,
            dict,
        )
    ):
        return deny(
            "Blocked: Merchant entity binding has no unique active "
            "Merchant task owner."
        )

    owner_run_id = str(
        owner_record.get(
            "current_run_id"
        )
        or ""
    ).strip()

    owner_task_id = str(
        owner_record.get(
            "current_task_id"
        )
        or ""
    ).strip()

    if not (
        owner_run_id
        and owner_task_id
    ):
        return deny(
            "Blocked: Merchant entity binding has no exact run/task identity."
        )

    pane_session_id = str(
        session_id
        or ""
    ).strip()

    if not pane_session_id:
        return deny(
            "Blocked: Merchant entity binding requires a session identity."
        )

    receipt = (
        load_pending_merchant_resolution(
            pane_session_id
        )
    )

    if receipt is None:
        return deny(
            "Blocked: this Merchant command consumes --merchant-id "
            "without an exact resolver receipt. Run "
            "`merchant resolve --query <merchant-reference>` first."
        )

    resolution = receipt.get(
        "resolution"
    )

    if not isinstance(
        resolution,
        dict,
    ):
        return deny(
            "Blocked: Merchant resolver evidence is malformed."
        )

    expected_query = resolution.get(
        "query"
    )

    binding = (
        bind_merchant_resolution_receipt(
            receipt,
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            expected_query=(
                expected_query
            ),
        )
    )

    if (
        not binding.accepted
        or binding.outcome
        != BOUND
    ):
        reason = (
            binding.question
            or (
                "Merchant resolver evidence does not authorize "
                "an exact entity binding."
            )
        )

        return deny(
            "Blocked: "
            + reason
        )

    if (
        binding.merchant_id
        != canonical_supplied_id
    ):
        return deny(
            "Blocked: --merchant-id does not match the exact Merchant "
            "resolved for this run/task. Do not copy or substitute a UUID "
            "from merchant list, prose, memory, or assignment text."
        )

    return None


def project_resolution_use_decision(
    payload: dict[str, Any],
    session_id: Any,
) -> dict[str, Any] | None:
    """Require trusted Project resolver evidence before consuming project_id."""

    sender_agent_type = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if (
        sender_agent_type
        != MERCHANT_MANAGER_AGENT
    ):
        return None

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    if tool_name not in {
        "Bash",
        "PowerShell",
    }:
        return None

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return None

    command_text_value = (
        tool_input.get(
            "command"
        )
    )

    tokens = (
        _direct_merchant_agent_cli_tokens(
            command_text_value
        )
    )

    # ------------------------------------------------------------
    # A Merchant CLI reference that is not one direct invocation
    # must not bypass Project binding.
    #
    # This mirrors Merchant entity enforcement.
    # ------------------------------------------------------------

    if tokens is None:
        raw_command = str(
            command_text_value
            or ""
        )

        normalized_raw = (
            raw_command
            .replace(
                "\\",
                "/",
            )
            .lower()
        )

        if (
            "agents/tools/merchant/agent_cli.py"
            in normalized_raw
        ):
            return deny(
                "Blocked: Merchant CLI must be invoked directly. "
                "Wrapper scripts, pipelines, redirects, shell chaining, "
                "and reconstructed Merchant commands cannot consume "
                "trusted Project entity bindings."
            )

        return None

    (
        merchant_command,
        supplied_project_id,
    ) = _project_id_from_cli_tokens(
        tokens
    )

    # ------------------------------------------------------------
    # Resolver itself establishes the Project evidence.
    # ------------------------------------------------------------

    if (
        merchant_command
        == "project resolve"
    ):
        return None

    # ------------------------------------------------------------
    # This command does not consume project_id within the 12E.6
    # command surface.
    #
    # project alerts and integration identifier-set are completed
    # separately in Gate 12E.7.
    # ------------------------------------------------------------

    if supplied_project_id is None:
        return None

    canonical_supplied_project_id = (
        _canonical_project_uuid(
            supplied_project_id
        )
    )

    if (
        canonical_supplied_project_id
        is None
    ):
        return deny(
            "Blocked: project_id must be a canonical Project UUID."
        )

    # ------------------------------------------------------------
    # Find exact active Merchant task owner.
    # ------------------------------------------------------------

    (
        owner_session_id,
        owner_record,
        owner_resolution,
    ) = (
        find_unique_active_teammate_owner(
            MERCHANT_MANAGER_AGENT
        )
    )

    if (
        owner_resolution
        != "FOUND"
        or not owner_session_id
        or not isinstance(
            owner_record,
            dict,
        )
    ):
        return deny(
            "Blocked: Project entity binding has no unique active "
            "Merchant task owner."
        )

    owner_run_id = str(
        owner_record.get(
            "current_run_id"
        )
        or ""
    ).strip()

    owner_task_id = str(
        owner_record.get(
            "current_task_id"
        )
        or ""
    ).strip()

    if not (
        owner_run_id
        and owner_task_id
    ):
        return deny(
            "Blocked: Project entity binding has no exact run/task identity."
        )

    pane_session_id = str(
        session_id
        or ""
    ).strip()

    if not pane_session_id:
        return deny(
            "Blocked: Project entity binding requires a session identity."
        )

    # ------------------------------------------------------------
    # Step 1:
    # Re-bind the trusted parent Merchant.
    #
    # The Project receipt must NEVER become a new source of Merchant
    # authority by itself.
    # ------------------------------------------------------------

    merchant_receipt = (
        load_pending_merchant_resolution(
            pane_session_id
        )
    )

    if merchant_receipt is None:
        return deny(
            "Blocked: Project binding requires an exact parent "
            "Merchant resolver receipt. Run "
            "`merchant resolve --query <merchant-reference>` first."
        )

    merchant_resolution = (
        merchant_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        merchant_resolution,
        dict,
    ):
        return deny(
            "Blocked: parent Merchant resolver evidence is malformed."
        )

    merchant_expected_query = (
        merchant_resolution.get(
            "query"
        )
    )

    merchant_binding = (
        bind_merchant_resolution_receipt(
            merchant_receipt,
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            expected_query=(
                merchant_expected_query
            ),
        )
    )

    if (
        not merchant_binding.accepted
        or merchant_binding.outcome
        != BOUND
        or not merchant_binding.merchant_id
    ):
        reason = (
            merchant_binding.question
            or (
                "parent Merchant resolver evidence does not establish "
                "an exact trusted Merchant binding."
            )
        )

        return deny(
            "Blocked: "
            + reason
        )

    trusted_merchant_id = (
        merchant_binding.merchant_id
    )

    # ------------------------------------------------------------
    # Step 2:
    # Load exact Project receipt.
    # ------------------------------------------------------------

    project_receipt = (
        load_pending_project_resolution(
            pane_session_id
        )
    )

    if project_receipt is None:
        return deny(
            "Blocked: this Merchant command consumes project_id "
            "without an exact Project resolver receipt. Run "
            "`project resolve --merchant-id <trusted-merchant-id> "
            "--query <project-reference>` first."
        )

    project_resolution = (
        project_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        project_resolution,
        dict,
    ):
        return deny(
            "Blocked: Project resolver evidence is malformed."
        )

    project_expected_query = (
        project_resolution.get(
            "query"
        )
    )

    # ------------------------------------------------------------
    # Step 3:
    # Bind Project under the exact already-bound Merchant.
    # ------------------------------------------------------------

    project_binding = (
        bind_project_resolution_receipt(
            project_receipt,
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            trusted_merchant_id=(
                trusted_merchant_id
            ),
            expected_query=(
                project_expected_query
            ),
        )
    )

    if (
        not project_binding.accepted
        or project_binding.outcome
        != PROJECT_BOUND
    ):
        reason = (
            project_binding.question
            or (
                "Project resolver evidence does not authorize "
                "an exact Project entity binding."
            )
        )

        return deny(
            "Blocked: "
            + reason
        )

    # ------------------------------------------------------------
    # Step 4:
    # Exact command ↔ Project binding equality.
    # ------------------------------------------------------------

    if (
        project_binding.project_id
        != canonical_supplied_project_id
    ):
        return deny(
            "Blocked: project_id does not match the exact Project "
            "resolved for this run/task and Merchant. Do not copy or "
            "substitute a Project UUID from project list, prose, memory, "
            "assignment text, or another Merchant."
        )

    return None

def step_resolution_use_decision(
    payload: dict[str, Any],
    session_id: Any,
) -> dict[str, Any] | None:
    """Require trusted Step resolver evidence before consuming step_id."""

    sender_agent_type = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if (
        sender_agent_type
        != MERCHANT_MANAGER_AGENT
    ):
        return None

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    if tool_name not in {
        "Bash",
        "PowerShell",
    }:
        return None

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return None

    command_text_value = (
        tool_input.get(
            "command"
        )
    )

    tokens = (
        _direct_merchant_agent_cli_tokens(
            command_text_value
        )
    )

    # ------------------------------------------------------------
    # No wrapped Merchant CLI may consume trusted Step bindings.
    # ------------------------------------------------------------

    if tokens is None:
        raw_command = str(
            command_text_value
            or ""
        )

        normalized_raw = (
            raw_command
            .replace(
                "\\",
                "/",
            )
            .lower()
        )

        if (
            "agents/tools/merchant/agent_cli.py"
            in normalized_raw
        ):
            return deny(
                "Blocked: Merchant CLI must be invoked directly. "
                "Wrapper scripts, pipelines, redirects, shell chaining, "
                "and reconstructed Merchant commands cannot consume "
                "trusted Step entity bindings."
            )

        return None

    (
        merchant_command,
        supplied_step_id,
    ) = _step_id_from_cli_tokens(
        tokens
    )

    # ------------------------------------------------------------
    # Resolver establishes Step evidence.
    #
    # Its --project-id is independently protected by Project gate.
    # ------------------------------------------------------------

    if (
        merchant_command
        == "step resolve"
    ):
        return None

    if supplied_step_id is None:
        return None

    canonical_supplied_step_id = (
        _canonical_step_uuid(
            supplied_step_id
        )
    )

    if (
        canonical_supplied_step_id
        is None
    ):
        return deny(
            "Blocked: step_id must be a canonical Step UUID."
        )

    # ------------------------------------------------------------
    # Exact active Merchant task owner.
    # ------------------------------------------------------------

    (
        owner_session_id,
        owner_record,
        owner_resolution,
    ) = (
        find_unique_active_teammate_owner(
            MERCHANT_MANAGER_AGENT
        )
    )

    if (
        owner_resolution
        != "FOUND"
        or not owner_session_id
        or not isinstance(
            owner_record,
            dict,
        )
    ):
        return deny(
            "Blocked: Step entity binding has no unique active "
            "Merchant task owner."
        )

    owner_run_id = str(
        owner_record.get(
            "current_run_id"
        )
        or ""
    ).strip()

    owner_task_id = str(
        owner_record.get(
            "current_task_id"
        )
        or ""
    ).strip()

    if not (
        owner_run_id
        and owner_task_id
    ):
        return deny(
            "Blocked: Step entity binding has no exact run/task identity."
        )

    pane_session_id = str(
        session_id
        or ""
    ).strip()

    if not pane_session_id:
        return deny(
            "Blocked: Step entity binding requires a session identity."
        )

    # ============================================================
    # PARENT 1 — MERCHANT
    #
    # Step receipt never establishes Merchant authority.
    # ============================================================

    merchant_receipt = (
        load_pending_merchant_resolution(
            pane_session_id
        )
    )

    if merchant_receipt is None:
        return deny(
            "Blocked: Step binding requires an exact parent "
            "Merchant resolver receipt. Run "
            "`merchant resolve --query <merchant-reference>` first."
        )

    merchant_resolution = (
        merchant_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        merchant_resolution,
        dict,
    ):
        return deny(
            "Blocked: parent Merchant resolver evidence is malformed."
        )

    merchant_expected_query = (
        merchant_resolution.get(
            "query"
        )
    )

    merchant_binding = (
        bind_merchant_resolution_receipt(
            merchant_receipt,
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            expected_query=(
                merchant_expected_query
            ),
        )
    )

    if (
        not merchant_binding.accepted
        or not merchant_binding.merchant_id
    ):
        reason = (
            merchant_binding.question
            or (
                "parent Merchant resolver evidence does not establish "
                "an exact trusted Merchant binding."
            )
        )

        return deny(
            "Blocked: "
            + reason
        )

    trusted_merchant_id = (
        merchant_binding.merchant_id
    )

    # ============================================================
    # PARENT 2 — PROJECT
    #
    # Step receipt never establishes Project authority.
    # ============================================================

    project_receipt = (
        load_pending_project_resolution(
            pane_session_id
        )
    )

    if project_receipt is None:
        return deny(
            "Blocked: Step binding requires an exact parent "
            "Project resolver receipt. Run "
            "`project resolve --merchant-id <trusted-merchant-id> "
            "--query <project-reference>` first."
        )

    project_resolution = (
        project_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        project_resolution,
        dict,
    ):
        return deny(
            "Blocked: parent Project resolver evidence is malformed."
        )

    project_expected_query = (
        project_resolution.get(
            "query"
        )
    )

    project_binding = (
        bind_project_resolution_receipt(
            project_receipt,
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            trusted_merchant_id=(
                trusted_merchant_id
            ),
            expected_query=(
                project_expected_query
            ),
        )
    )

    if (
        not project_binding.accepted
        or not project_binding.project_id
    ):
        reason = (
            project_binding.question
            or (
                "parent Project resolver evidence does not establish "
                "an exact trusted Project binding."
            )
        )

        return deny(
            "Blocked: "
            + reason
        )

    trusted_project_id = (
        project_binding.project_id
    )

    # ============================================================
    # STEP
    # ============================================================

    step_receipt = (
        load_pending_step_resolution(
            pane_session_id
        )
    )

    if step_receipt is None:
        return deny(
            "Blocked: this Merchant command consumes step_id "
            "without an exact Step resolver receipt. Run "
            "`step resolve --project-id <trusted-project-id> "
            "--query <step-reference>` first."
        )

    step_resolution = (
        step_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        step_resolution,
        dict,
    ):
        return deny(
            "Blocked: Step resolver evidence is malformed."
        )

    step_expected_query = (
        step_resolution.get(
            "query"
        )
    )

    step_binding = (
        bind_step_resolution_receipt(
            step_receipt,
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            trusted_merchant_id=(
                trusted_merchant_id
            ),
            trusted_project_id=(
                trusted_project_id
            ),
            expected_query=(
                step_expected_query
            ),
        )
    )

    if (
        not step_binding.accepted
        or step_binding.outcome
        != STEP_BOUND
        or not step_binding.step_id
    ):
        reason = (
            step_binding.question
            or (
                "Step resolver evidence does not authorize "
                "an exact Step entity binding."
            )
        )

        return deny(
            "Blocked: "
            + reason
        )

    # ============================================================
    # Exact CLI Step UUID equality.
    # ============================================================

    if (
        step_binding.step_id
        != canonical_supplied_step_id
    ):
        return deny(
            "Blocked: step_id does not match the exact Step "
            "resolved for this run/task, Merchant, and Project. "
            "Do not copy or substitute a Step UUID from project "
            "output, alerts, prose, memory, assignment text, "
            "template_step_id, or another Project."
        )

    return None

def document_revision_resolution_use_decision(
    payload: dict[str, Any],
    session_id: Any,
) -> dict[str, Any] | None:
    """Require trusted revision evidence before consuming revision_id."""

    sender_agent_type = str(
        payload.get(
            "agent_type"
        )
        or ""
    ).strip()

    if (
        sender_agent_type
        != MERCHANT_MANAGER_AGENT
    ):
        return None

    tool_name = str(
        payload.get(
            "tool_name"
        )
        or ""
    ).strip()

    if tool_name not in {
        "Bash",
        "PowerShell",
    }:
        return None

    tool_input = payload.get(
        "tool_input"
    )

    if not isinstance(
        tool_input,
        dict,
    ):
        return None

    command_text_value = (
        tool_input.get(
            "command"
        )
    )

    tokens = (
        _direct_merchant_agent_cli_tokens(
            command_text_value
        )
    )

    # ------------------------------------------------------------
    # Fail closed on wrappers / chaining / pipes / redirects for
    # commands that consume revision identity.
    # ------------------------------------------------------------

    if tokens is None:
        raw_command = str(
            command_text_value
            or ""
        )

        normalized_raw = (
            raw_command
            .replace(
                "\\",
                "/",
            )
            .lower()
        )

        if (
            "agents/tools/merchant/agent_cli.py"
            in normalized_raw
            and (
                "document approve"
                in normalized_raw
                or (
                    "--reused-document-revision-id"
                    in normalized_raw
                )
            )
        ):
            return deny(
                "Blocked: Merchant CLI must be invoked directly. "
                "Wrapper scripts, pipelines, redirects, shell chaining, "
                "and reconstructed Merchant commands cannot consume "
                "trusted Document Revision entity bindings."
            )

        return None

    (
        merchant_command,
        supplied_revision_id,
        required_scope,
    ) = (
        _document_revision_id_from_cli_tokens(
            tokens
        )
    )

    # document resolve establishes revision evidence.
    if (
        merchant_command
        == "document resolve"
    ):
        return None

    # Command does not consume an existing revision.
    if supplied_revision_id is None:
        return None

    if (
        not supplied_revision_id
        or required_scope
        not in {
            "PROJECT",
            "MERCHANT",
        }
    ):
        return deny(
            "Blocked: Document Revision identity in the Merchant "
            "CLI invocation is malformed or conflicting."
        )

    canonical_revision_id = (
        _canonical_document_revision_uuid(
            supplied_revision_id
        )
    )

    if canonical_revision_id is None:
        return deny(
            "Blocked: revision_id must be a canonical "
            "Document Revision UUID."
        )

    # ------------------------------------------------------------
    # Resolve current trusted teammate owner.
    # ------------------------------------------------------------

    (
        owner_session_id,
        owner_record,
        owner_resolution,
    ) = (
        find_unique_active_teammate_owner(
            MERCHANT_MANAGER_AGENT
        )
    )

    if (
        owner_resolution
        != "FOUND"
        or not owner_session_id
        or not isinstance(
            owner_record,
            dict,
        )
    ):
        return deny(
            "Blocked: Document Revision binding has no unique "
            "active Merchant task owner."
        )

    owner_run_id = str(
        owner_record.get(
            "current_run_id"
        )
        or ""
    ).strip()

    owner_task_id = str(
        owner_record.get(
            "current_task_id"
        )
        or ""
    ).strip()

    if not (
        owner_run_id
        and owner_task_id
    ):
        return deny(
            "Blocked: Document Revision binding has no exact "
            "run/task identity."
        )

    pane_session_id = str(
        session_id
        or ""
    ).strip()

    if not pane_session_id:
        return deny(
            "Blocked: Document Revision binding requires "
            "a session identity."
        )

    # ============================================================
    # Parent 1: Merchant
    #
    # Revision evidence must never become Merchant authority.
    # ============================================================

    merchant_receipt = (
        load_pending_merchant_resolution(
            pane_session_id
        )
    )

    if merchant_receipt is None:
        return deny(
            "Blocked: Document Revision binding requires an exact "
            "parent Merchant resolver receipt. Run "
            "`merchant resolve --query <merchant-reference>` first."
        )

    merchant_resolution = (
        merchant_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        merchant_resolution,
        dict,
    ):
        return deny(
            "Blocked: parent Merchant resolver evidence is malformed."
        )

    merchant_expected_query = (
        merchant_resolution.get(
            "query"
        )
    )

    merchant_binding = (
        bind_merchant_resolution_receipt(
            merchant_receipt,
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            expected_query=(
                merchant_expected_query
            ),
        )
    )

    if not merchant_binding.accepted:
        reason = (
            merchant_binding.question
            or (
                "parent Merchant resolver evidence does not authorize "
                "an exact Merchant entity binding."
            )
        )

        return deny(
            "Blocked: "
            + reason
        )

    trusted_merchant_id = (
        merchant_binding.merchant_id
    )

    if not trusted_merchant_id:
        return deny(
            "Blocked: parent Merchant binding has no Merchant UUID."
        )

    # ============================================================
    # Parent 2: Project, only for `document approve`.
    #
    # project create reuse deliberately has MERCHANT scope because
    # the new target Project does not exist yet.
    # ============================================================

    trusted_project_id = None

    if required_scope == "PROJECT":
        project_receipt = (
            load_pending_project_resolution(
                pane_session_id
            )
        )

        if project_receipt is None:
            return deny(
                "Blocked: Document Revision PROJECT scope requires "
                "an exact parent Project resolver receipt. Run "
                "`project resolve --merchant-id <trusted-merchant-id> "
                "--query <project-reference>` first."
            )

        project_resolution = (
            project_receipt.get(
                "resolution"
            )
        )

        if not isinstance(
            project_resolution,
            dict,
        ):
            return deny(
                "Blocked: parent Project resolver evidence is malformed."
            )

        project_expected_query = (
            project_resolution.get(
                "query"
            )
        )

        project_binding = (
            bind_project_resolution_receipt(
                project_receipt,
                pane_session_id=(
                    pane_session_id
                ),
                owner_session_id=(
                    owner_session_id
                ),
                teammate_name=(
                    MERCHANT_MANAGER_AGENT
                ),
                run_id=(
                    owner_run_id
                ),
                task_id=(
                    owner_task_id
                ),
                trusted_merchant_id=(
                    trusted_merchant_id
                ),
                expected_query=(
                    project_expected_query
                ),
            )
        )

        if not project_binding.accepted:
            reason = (
                project_binding.question
                or (
                    "parent Project resolver evidence does not authorize "
                    "an exact Project entity binding."
                )
            )

            return deny(
                "Blocked: "
                + reason
            )

        trusted_project_id = (
            project_binding.project_id
        )

        if not trusted_project_id:
            return deny(
                "Blocked: parent Project binding has no Project UUID."
            )

    # ============================================================
    # Revision receipt
    # ============================================================

    revision_receipt = (
        load_pending_document_revision_resolution(
            pane_session_id
        )
    )

    if revision_receipt is None:
        if (
            required_scope
            == "PROJECT"
        ):
            resolver_instruction = (
                "`document resolve --project-id "
                "<trusted-project-id> "
                "--query <revision-reference>`"
            )
        else:
            resolver_instruction = (
                "`document resolve --merchant-id "
                "<trusted-merchant-id> "
                "--query <revision-reference>`"
            )

        return deny(
            "Blocked: this Merchant command consumes a Document Revision "
            "UUID without an exact Document Revision resolver receipt. Run "
            + resolver_instruction
            + " first."
        )

    revision_resolution = (
        revision_receipt.get(
            "resolution"
        )
    )

    if not isinstance(
        revision_resolution,
        dict,
    ):
        return deny(
            "Blocked: Document Revision resolver evidence is malformed."
        )

    revision_expected_query = (
        revision_resolution.get(
            "query"
        )
    )

    revision_binding = (
        bind_document_revision_resolution_receipt(
            revision_receipt,
            pane_session_id=(
                pane_session_id
            ),
            owner_session_id=(
                owner_session_id
            ),
            teammate_name=(
                MERCHANT_MANAGER_AGENT
            ),
            run_id=(
                owner_run_id
            ),
            task_id=(
                owner_task_id
            ),
            trusted_merchant_id=(
                trusted_merchant_id
            ),
            trusted_project_id=(
                trusted_project_id
            ),
            expected_scope=(
                required_scope
            ),
            expected_query=(
                revision_expected_query
            ),
        )
    )

    if (
        not revision_binding.accepted
        or revision_binding.outcome
        != DOCUMENT_REVISION_BOUND
    ):
        reason = (
            revision_binding.question
            or (
                "Document Revision resolver evidence does not authorize "
                "an exact revision entity binding."
            )
        )

        return deny(
            "Blocked: "
            + reason
        )

    # ============================================================
    # Exact command ↔ trusted Revision equality.
    # ============================================================

    if (
        revision_binding.revision_id
        != canonical_revision_id
    ):
        return deny(
            "Blocked: revision_id does not match the exact "
            "Document Revision resolved for this run/task. "
            "Do not copy or substitute a revision UUID from project "
            "details, prose, memory, or assignment text."
        )

    return None

def apply_call(
    state: dict[str, Any],
    tool_name: str,
    tool_input: dict[str, Any],
    session_id: str | None = None,
    sender_agent_type: str = "",
) -> dict[str, Any] | None:
    """Count the call, mutate `state`, and return a decision when one is needed.

    `state` is modified in place; the caller persists it. Counting happens before
    any early return so a denied call still consumes budget — otherwise a loop of
    denied calls would be free.

    SendMessage and TaskUpdate are not subject to the regular budget cap; they
    draw from a coordination reserve instead so that handoff communication is never
    blocked by tool exhaustion.

    session_id is passed to _check_agent_dispatch for team lifecycle reservation.
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
        return _check_agent_dispatch(state, tool_input, session_id)

    if tool_name == "SendMessage":
        message_decision = _check_teammate_message(
            state,
            tool_input,
            session_id,
            sender_agent_type,
        )

        if message_decision is not None:
            return message_decision

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


def _coalesced_text(
    mapping: dict[str, Any],
    *fields: str,
) -> str:
    """Return one non-empty value only when aliases are unambiguous."""
    values = []

    for field in fields:
        value = mapping.get(field)

        if value is None:
            continue

        text = str(value).strip()

        if text:
            values.append(text)

    if not values or any(value != values[0] for value in values[1:]):
        return ""

    return values[0]



def _merchant_assignment_text(
    tool_input: dict[str, Any],
) -> str:
    """Return the lead-authored assignment body for Agent or SendMessage."""

    if not isinstance(tool_input, dict):
        return ""

    prompt = tool_input.get("prompt")
    message = tool_input.get("message")

    prompt_text = (
        str(prompt)
        if isinstance(prompt, str)
        else ""
    ).strip()

    message_text = (
        str(message)
        if isinstance(message, str)
        else ""
    ).strip()

    if prompt_text and message_text:
        if prompt_text != message_text:
            return ""
        return prompt_text

    return prompt_text or message_text


def _merchant_propose_assignment_error(
    assignment: str,
) -> str | None:
    """Reject lead-authored concrete Merchant CLI syntax for PROPOSE."""

    if not isinstance(assignment, str):
        return "assignment text is unavailable"

    text = assignment.strip()

    if not text:
        return "assignment text is empty"

    normalized = (
        text
        .replace("\\", "/")
    )

    if (
        _MERCHANT_AGENT_CLI_REFERENCE_PATTERN.search(
            normalized
        )
        is not None
    ):
        return (
            "assignment contains a direct agent_cli.py reference"
        )

    if (
        _MERCHANT_PROPOSE_ASSIGNMENT_CLI_PATTERN.search(
            text
        )
        is not None
    ):
        return (
            "assignment contains concrete Merchant CLI command/flag syntax"
        )

    return None


def _record_merchant_apply_dispatch(
    state: dict[str, Any],
    session_id: str | None,
    subagent_type: str,
    teammate_name: str,
) -> dict[str, Any] | None:
    """Reserve LOCAL_AUTO receipt and persist one accepted apply dispatch."""

    operations = {
        str(operation)
        for operation in state.get("operations") or []
    }

    if MERCHANT_APPLY_OPERATION not in operations:
        return None

    confirmation = state.get(
        "merchant_confirmation"
    )

    if not isinstance(
        confirmation,
        dict,
    ):
        return deny(
            "Blocked: Merchant apply dispatch has no validated confirmation. "
            "Nothing was dispatched."
        )

    if (
        str(
            state.get(
                MERCHANT_CONFIRMATION_MODE_FIELD
            )
            or MERCHANT_CONFIRMATION_MODE_MANUAL
        )
        == MERCHANT_CONFIRMATION_MODE_LOCAL_AUTO
    ):
        if not session_id:
            return deny(
                "Blocked: LOCAL_AUTO Merchant apply dispatch requires "
                "a valid session id. Nothing was dispatched."
            )

        reservation = reserve_receipt(
            session_id,
            confirmation.get(
                "confirmation_hash"
            ),
        )

        if not reservation.accepted:
            return deny(
                "Blocked: the local auto-confirm proposal receipt could "
                f"not be reserved ({reservation.reason}). Nothing was "
                "dispatched; generate a fresh proposal, or switch back "
                "to manual confirmation with "
                "`/merchant-confirmation on`."
            )

    state["merchant_dispatch_spent"] = True
    state["merchant_dispatch"] = {
        "operation": MERCHANT_APPLY_OPERATION,
        "subagent_type": subagent_type,
        "teammate_name": teammate_name,
        "confirmation_hash": confirmation[
            "confirmation_hash"
        ],
    }

    return None


def _run_task_id(state: dict[str, Any], teammate_name: str) -> str:
    """Build the internal task binding for one teammate in this run."""
    run_id = str(state.get("run_id") or "").strip()

    if not run_id:
        return ""

    return f"{run_id}:{teammate_name}"


def _check_teammate_message(
    state: dict[str, Any],
    tool_input: dict[str, Any],
    session_id: str | None,
    sender_agent_type: str,
) -> dict[str, Any] | None:
    """Authorize a lead assignment to one existing canonical teammate."""
    recipient = _coalesced_text(tool_input, "recipient", "to")

    if recipient == "team-lead":
        return None

    if not recipient:
        return deny(
            "Blocked: SendMessage has no unambiguous recipient. Use exactly "
            "one matching recipient/to value."
        )

    if sender_agent_type:
        return deny(
            "Blocked: only the team lead may assign work to a teammate. "
            "Teammates may report only to team-lead."
        )

    selected_agents = [
        str(agent) for agent in state.get("selected_agents") or []
    ]

    if recipient not in selected_agents:
        return deny(
            f"Blocked: teammate '{recipient}' is not in selected_agents "
            f"({', '.join(selected_agents) or 'none'})."
        )

    merchant_decision = _check_merchant_dispatch(
        state,
        recipient,
        recipient,
        tool_input,
    )

    if merchant_decision is not None:
        return merchant_decision

    if not session_id:
        return deny(
            "Blocked: teammate reuse requires a valid session id."
        )

    task_id = _run_task_id(state, recipient)

    if not task_id:
        return deny(
            "Blocked: teammate reuse requires the current run_id."
        )

    # -------------------------------------------------
    # Same-run completion circuit breaker.
    #
    # Once this exact run/task has already completed and
    # the teammate returned to IDLE_REUSABLE, the lead
    # must not wake it again inside the same run.
    #
    # A genuinely new /solve run has a different run_id,
    # therefore a different task_id, and remains reusable.
    # -------------------------------------------------

    team_state = load_team_state(
        session_id
    )

    if isinstance(
        team_state,
        dict,
    ):
        completed_record = (
            team_state.get(
                "teammates",
                {},
            ).get(
                recipient
            )
        )

        if isinstance(
            completed_record,
            dict,
        ):
            completed_status = str(
                completed_record.get(
                    "status"
                )
                or ""
            )

            last_completed_task_id = str(
                completed_record.get(
                    "last_completed_task_id"
                )
                or ""
            ).strip()

            if (
                completed_status
                == TeammateLifecycleStatus.IDLE_REUSABLE.value
                and last_completed_task_id
                == task_id
                and completed_record.get(
                    "result_received"
                )
                is True
                and completed_record.get(
                    "report_source"
                )
                == "sendmessage"
            ):
                return deny(
                    f"Blocked: teammate '{recipient}' has already completed "
                    "and delivered the result for this exact run/task. "
                    "Do not acknowledge, redispatch, remind, shut down, or "
                    "send follow-up work to the teammate in the same run. "
                    "Synthesize the delivered result and end the run."
                )

    members_used = [str(member) for member in state.get("members_used") or []]

    if recipient not in members_used:
        max_members = _limit(state, "max_members")

        if max_members is not None and len(members_used) + 1 > max_members:
            return deny(
                f"Blocked: reusing teammate '{recipient}' would exceed the "
                f"max_members limit of {max_members}."
            )

    reserved, prior_status = reserve_reusable_teammate(
        session_id,
        recipient,
        str(
            state.get(
                "run_id"
            )
            or ""
        ),
        task_id,
        operations=[
            str(operation)
            for operation in (
                state.get(
                    "operations"
                )
                or []
            )
        ],
        selected_agents=selected_agents,
    )

    if not reserved:
        return deny(
            f"Blocked: teammate '{recipient}' is not reusable "
            f"(status={prior_status}). Do not create a suffixed replacement."
        )

    merchant_apply_decision = (
        _record_merchant_apply_dispatch(
            state,
            session_id,
            recipient,
            recipient,
        )
    )

    if merchant_apply_decision is not None:
        return merchant_apply_decision

    if recipient not in members_used:
        members_used.append(recipient)
        state["members_used"] = members_used

    return None


def _check_agent_dispatch(
    state: dict[str, Any],
    tool_input: dict[str, Any],
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Enforce the roster, member cap, dispatch-round cap, and team lifecycle.

    Uses session-scoped team lifecycle to enable teammate reuse:
    - Allocates canonical teammate and checks lifecycle decision
    - CREATE: new teammate; proceeds with dispatch (consumes member slot)
    - REUSE: teammate exists and idle; instructs lead to use SendMessage instead
    - BUSY: teammate exists but active; blocks dispatch
    - DENIED: lock timeout; fails closed

    Authorization is checked against selected_agents and canonical names enforced.
    """
    subagent_type = ""
    requested_teammate_name = ""

    if isinstance(tool_input, dict):
        subagent_type = str(tool_input.get("subagent_type") or "").strip()
        requested_teammate_name = str(tool_input.get("name") or "").strip()

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

    if not requested_teammate_name:
        return deny(
            "Blocked: the dispatch provides no name. Each teammate must have a stable, "
            "unique name. Provide it via the `name` parameter."
        )

    canonical_name = subagent_type

    if requested_teammate_name != canonical_name:
        return deny(
            f"Blocked: requested teammate name '{requested_teammate_name}' does not "
            f"match the canonical name '{canonical_name}' for role '{subagent_type}'. "
            f"Use the canonical name to enable teammate reuse across runs."
        )

    merchant_decision = _check_merchant_dispatch(
        state,
        subagent_type,
        requested_teammate_name,
        tool_input,
    )

    if merchant_decision is not None:
        return merchant_decision

    max_rounds = _limit(state, "max_tool_rounds")
    agent_rounds = int(state.get("agent_rounds", 0))

    if max_rounds is not None and agent_rounds >= max_rounds:
        return deny(
            f"Blocked: this run has already used its {max_rounds} dispatch round(s) "
            f"for task_class {state.get('task_class')}. Synthesize what the agents "
            "reported and stop."
        )

    task_id = _run_task_id(state, requested_teammate_name)

    if session_id and not task_id:
        return deny(
            "Blocked: Agent Team dispatch requires the current run_id so the "
            "teammate can be bound before work starts."
        )

    members_used = [str(member) for member in state.get("members_used") or []]

    if requested_teammate_name not in members_used:
        max_members = _limit(state, "max_members")

        if max_members is not None and len(members_used) + 1 > max_members:
            return deny(
                f"Blocked: dispatching teammate '{requested_teammate_name}' would make "
                f"{len(members_used) + 1} members, over the {max_members} allowed for "
                f"task_class {state.get('task_class')}. Already dispatched: "
                f"{', '.join(members_used) or 'none'}."
            )

    if session_id:
        decision, teammate_name = allocate_teammate(session_id, subagent_type, canonical_name)

        if decision == TeammateAllocationDecision.DENIED:
            return deny(
                f"Blocked: unable to acquire team state lock for role '{subagent_type}'. "
                "Team state is temporarily unavailable; retry after a moment."
            )

        if decision == TeammateAllocationDecision.BUSY:
            return deny(
                f"Blocked: teammate '{teammate_name}' (role '{subagent_type}') is "
                "currently handling work. Do not dispatch a new instance. Instead, "
                "assign remaining work to the existing teammate by sending it a "
                "message via SendMessage. After the teammate reports completion, "
                "it will be available for reuse."
            )

        if decision == TeammateAllocationDecision.REUSE:
            return deny(
                f"Blocked: teammate '{teammate_name}' (role '{subagent_type}') "
                "exists and is idle. Do not create a new instance. Assign work to "
                "the existing teammate by sending it a message via SendMessage. "
                "Reusing existing teammates saves resources and maintains context."
            )

        if decision != TeammateAllocationDecision.CREATE:
            return deny(
                f"Blocked: unexpected allocation decision '{decision}' for role "
                f"'{subagent_type}'. Request a fresh dispatch."
            )

        if not mark_teammate_running(
            session_id,
            requested_teammate_name,
            str(
                state.get(
                    "run_id"
                )
                or ""
            ),
            task_id,
            operations=[
                str(operation)
                for operation in (
                    state.get(
                        "operations"
                    )
                    or []
                )
            ],
            selected_agents=selected_agents,
        ):
            return deny(
                "Blocked: the new teammate could not be bound to the current "
                "run safely. Nothing may rely on this dispatch result."
            )

    if requested_teammate_name not in members_used:
        members_used.append(requested_teammate_name)
        state["members_used"] = members_used

    merchant_apply_decision = (
        _record_merchant_apply_dispatch(
            state,
            session_id,
            subagent_type,
            requested_teammate_name,
        )
    )

    if merchant_apply_decision is not None:
        return merchant_apply_decision

    return None


def _check_merchant_dispatch(
    state: dict[str, Any],
    subagent_type: str,
    teammate_name: str,
    tool_input: dict[str, Any],
) -> dict[str, Any] | None:
    """Bind Merchant operational dispatch to the classified operation.

    A confirmed apply carries hashes rather than raw payload. Gate 7.4 will
    compare those hashes with the actual in-process CLI payload before it can
    authorize a runtime mutation; this gate only authorizes the one teammate
    dispatch that may receive that future handoff.
    """

    operations = {
        str(operation)
        for operation in state.get("operations") or []
    }
    merchant_operations = operations & MERCHANT_OPERATIONS
    confirmation = state.get("merchant_confirmation")
    assignment = _merchant_assignment_text(
        tool_input
    )
    has_dispatch_marker = (
        MERCHANT_DISPATCH_MARKER
        in assignment
    )

    if not merchant_operations:
        if confirmation is not None or has_dispatch_marker:
            return deny(
                "Blocked: Merchant confirmation or dispatch authority appeared "
                "outside a classified Merchant operation. Request a fresh "
                "matching envelope and stop."
            )

        return None

    if len(merchant_operations) != 1:
        return deny(
            "Blocked: a Merchant dispatch must carry exactly one classified "
            "Merchant operation. Request a narrower envelope and stop."
        )

    if operations != merchant_operations:
        return deny(
            "Blocked: a Merchant operational dispatch cannot combine Merchant "
            "and non-Merchant operations. Request a single-operation envelope "
            "and stop."
        )

    if selected_agents := [
        str(agent)
        for agent in state.get("selected_agents") or []
    ]:
        if selected_agents != [MERCHANT_MANAGER_AGENT]:
            return deny(
                "Blocked: Merchant operations require exclusive "
                "merchant-manager authority in selected_agents. Do not "
                "substitute or add a teammate."
            )
    else:
        return deny(
            "Blocked: the Merchant operation has no selected merchant-manager "
            "authority. Nothing was dispatched."
        )

    if subagent_type != MERCHANT_MANAGER_AGENT:
        return deny(
            "Blocked: only merchant-manager may receive a Merchant operational "
            "assignment. Nothing was dispatched."
        )

    if merchant_operations == {MERCHANT_PROPOSE_OPERATION}:
        if confirmation is not None or has_dispatch_marker:
            return deny(
                "Blocked: proposal dispatches cannot carry Merchant "
                "apply confirmation authority. Nothing was dispatched."
            )

        assignment_error = (
            _merchant_propose_assignment_error(
                assignment
            )
        )

        if assignment_error is not None:
            return deny(
                "Blocked: merchant_propose assignments must be semantic-only; "
                f"{assignment_error}. The lead must not author or copy "
                "Merchant CLI resource/action/flag syntax into the teammate "
                "assignment. Let merchant-manager resolve the registered "
                "command contract itself."
            )

        return None

    if merchant_operations != {MERCHANT_APPLY_OPERATION}:
        if confirmation is not None or has_dispatch_marker:
            return deny(
                "Blocked: read dispatches cannot carry Merchant "
                "apply confirmation authority. Nothing was dispatched."
            )

        return None

    if state.get("risk_level") not in {
        RISK_EXTERNAL_WRITE,
        RISK_DESTRUCTIVE,
    }:
        return deny(
            "Blocked: Merchant apply dispatch requires an external_write or "
            "destructive envelope. Nothing was dispatched."
        )

    if state.get("confirmed") is not True:
        return deny(
            "Blocked: Merchant apply dispatch requires exact confirmed state. "
            "Generate and confirm a fresh proposal."
        )

    if state.get("merchant_dispatch_spent") is True:
        return deny(
            "Blocked: this Merchant confirmation has already authorized one "
            "dispatch attempt. Generate and confirm a fresh proposal."
        )

    confirmation_error = _merchant_confirmation_error(
        confirmation
    )

    if confirmation_error is not None:
        return deny(
            "Blocked: Merchant confirmation state is missing or malformed "
            f"({confirmation_error}). Generate and confirm a fresh proposal."
        )

    dispatch, dispatch_error = _merchant_dispatch_payload(assignment)

    if dispatch_error is not None:
        return deny(
            "Blocked: Merchant apply assignment has no exact dispatch binding "
            f"({dispatch_error}). Nothing was dispatched."
        )

    expected_dispatch = dict(confirmation)
    expected_dispatch["authorized_mode"] = (
        MERCHANT_DISPATCH_MODE
    )

    if dispatch != expected_dispatch:
        return deny(
            "Blocked: Merchant apply assignment does not match the confirmed "
            "command, target, payload hash, expected version, or proposal. "
            "Nothing was dispatched; generate a fresh proposal if the action "
            "changed."
        )

    return None


def _merchant_confirmation_error(
    confirmation: Any,
) -> str | None:
    if not isinstance(confirmation, dict):
        return "confirmation object is absent"

    if set(confirmation) != MERCHANT_CONFIRMATION_FIELDS:
        return "confirmation fields are incomplete or unexpected"

    if (
        isinstance(confirmation.get("contract_version"), bool)
        or confirmation.get("contract_version") != 1
    ):
        return "contract version is unsupported"

    if (
        isinstance(confirmation.get("confirmation_version"), bool)
        or confirmation.get("confirmation_version") != 1
    ):
        return "confirmation version is unsupported"

    if confirmation.get("operation") != MERCHANT_APPLY_OPERATION:
        return "operation is not merchant_apply"

    if confirmation.get("database_target") != "runtime":
        return "database target is not runtime"

    command = confirmation.get("command")

    if (
        not isinstance(command, str)
        or command not in MERCHANT_WRITE_COMMANDS
    ):
        return "command is not an allowlisted normalized write"

    expected_version = confirmation.get("expected_version")

    if expected_version is not None and (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version <= 0
    ):
        return "expected version is invalid"

    for field in MERCHANT_HASH_FIELDS:
        value = confirmation.get(field)

        if (
            not isinstance(value, str)
            or _MERCHANT_HASH_PATTERN.fullmatch(value) is None
        ):
            return f"{field} is invalid"

    canonical = json.dumps(
        {
            key: confirmation[key]
            for key in MERCHANT_CONFIRMATION_FIELDS
            if key != "confirmation_hash"
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    expected_confirmation_hash = hashlib.sha256(
        canonical
    ).hexdigest()

    if not hmac.compare_digest(
        confirmation["confirmation_hash"],
        expected_confirmation_hash,
    ):
        return "confirmation hash does not match its binding"

    return None


def _merchant_dispatch_payload(
    prompt: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if prompt.count(MERCHANT_DISPATCH_MARKER) != 1:
        return None, "authorization marker must appear exactly once"

    matches = list(
        _MERCHANT_DISPATCH_BLOCK_PATTERN.finditer(prompt)
    )

    if len(matches) != 1:
        return None, "authorization block is missing or duplicated"

    try:
        payload = json.loads(matches[0].group("payload"))
    except (json.JSONDecodeError, ValueError):
        return None, "authorization block is not valid JSON"

    if not isinstance(payload, dict):
        return None, "authorization block must be a JSON object"

    if set(payload) != MERCHANT_DISPATCH_FIELDS:
        return None, "authorization fields are incomplete or unexpected"

    return payload, None


def completed_teammate_tool_decision(
    sender_agent_type: str,
) -> dict[str, Any] | None:
    """Freeze a teammate after its result has been delivered.

    Once the exact canonical teammate has a SendMessage-backed result,
    no further tool calls are allowed for that completed task.

    The teammate must finish its turn with plain final text only:
    RESULT_DELIVERED
    """

    teammate_name = str(
        sender_agent_type or ""
    ).strip()

    if not teammate_name:
        # Main/team-lead call.
        return None

    (
        _owner_session_id,
        record,
        resolution,
    ) = find_unique_active_teammate_owner(
        teammate_name
    )

    if resolution == "AMBIGUOUS":
        return deny(
            "Blocked: teammate ownership is ambiguous. "
            "Do not perform additional work or send another result. "
            "Finish with only: RESULT_DELIVERED."
        )

    if (
        resolution != "FOUND"
        or not isinstance(record, dict)
    ):
        return None

    status = str(
        record.get(
            "status"
        )
        or ""
    )

    if status not in {
        TeammateLifecycleStatus.REPORT_RECEIVED.value,
        TeammateLifecycleStatus.ACKNOWLEDGED.value,
    }:
        return None

    if (
        record.get(
            "result_received"
        )
        is not True
    ):
        return None

    if (
        record.get(
            "report_source"
        )
        != "sendmessage"
    ):
        return None

    return deny(
        "Blocked: your result for this task has already been delivered "
        "successfully through SendMessage. Do not call SendMessage, Bash, "
        "Read, TaskUpdate, or any other tool again for this completed task. "
        "Do not investigate further and do not repeat the work. "
        "Finish the teammate turn now with only: RESULT_DELIVERED."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if not isinstance(payload, dict):
        return 0

    tool_name = str(
        payload.get("tool_name")
        or ""
    )

    tool_input = payload.get(
        "tool_input"
    )

    session_id = payload.get(
        "session_id"
    )

    # Identify whether this PreToolUse event comes from
    # a teammate pane or from the team lead.
    sender_agent_type = str(
        payload.get("agent_type")
        or ""
    ).strip()

    if not isinstance(
        tool_input,
        dict,
    ):
        tool_input = {}

    # -------------------------------------------------
    # Gate 12B.6.1:
    # once a teammate has already delivered its result,
    # block every further tool call from that teammate.
    #
    # This check happens BEFORE looking up run state
    # because tmux teammate panes may carry their own
    # pane session_id rather than the lead session_id.
    # -------------------------------------------------

    freeze_decision = (
        completed_teammate_tool_decision(
            sender_agent_type
        )
    )

    if freeze_decision is not None:
        print(
            json.dumps(
                freeze_decision,
                ensure_ascii=False,
            )
        )

        return 0

    output: dict[str, Any] | None = None

    resolution_decision = (
        merchant_resolution_use_decision(
            payload,
            session_id,
        )
    )

    if resolution_decision is not None:
        print(
            json.dumps(
                resolution_decision,
                ensure_ascii=False,
            )
        )

        return 0

    project_resolution_decision = (
        project_resolution_use_decision(
            payload,
            session_id,
        )
    )

    if (
        project_resolution_decision
        is not None
    ):
        print(
            json.dumps(
                project_resolution_decision,
                ensure_ascii=False,
            )
        )

        return 0

    step_resolution_decision = (
        step_resolution_use_decision(
            payload,
            session_id,
        )
    )

    if (
        step_resolution_decision
        is not None
    ):
        print(
            json.dumps(
                step_resolution_decision,
                ensure_ascii=False,
            )
        )

        return 0

    document_revision_resolution_decision = (
        document_revision_resolution_use_decision(
            payload,
            session_id,
        )
    )

    if (
        document_revision_resolution_decision
        is not None
    ):
        print(
            json.dumps(
                document_revision_resolution_decision,
                ensure_ascii=False,
            )
        )

        return 0

    with locked_state(
        session_id
    ) as state:
        if state is not None:
            output = apply_call(
                state,
                tool_name,
                tool_input,
                session_id,
                sender_agent_type,
            )

    if output:
        print(
            json.dumps(
                output,
                ensure_ascii=False,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
