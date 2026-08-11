# Coding Agent Workspace

A Claude Code workspace: a team of specialist subagents for code work, plus a standalone
Google Calendar scheduler.

## Overview

Everything here runs inside a Claude Code session. There is no separate CLI to install or
launch — you open Claude Code in this directory and the configuration below is picked up
automatically.

Two things live in this repo:

1. **Subagent definitions** (`.claude/agents/*.md`) — seven specialists that Claude Code
   discovers and dispatches, orchestrated by the `/solve` command.
2. **The standalone scheduler** (`.claude/schedule.py`) — the one piece of Python that runs
   outside a session, for scripting or cron. It talks to the Google Calendar REST API and
   needs local credentials.

## The team

| Subagent | Use for | Writes? |
|---|---|---|
| `diagnostician` | Why something is slow, flaky, or intermittently failing | No |
| `red-team` | Security holes and edge cases | No |
| `reviewer` | Correctness and maintainability of a finished change | No |
| `coder` | Building a feature, doing a refactor | Yes |
| `bug-fixer` | Making a specific broken thing work | Yes |
| `group-sales-manager` | Sales data queries, capacity and allocation analysis | No |
| `scheduler` | Putting something on the calendar | Calendar only |

Writing agents edit the working tree and **never commit** — you review the diff and commit
yourself.

## Usage

### Let the team leader plan it

```
/solve find and fix the race condition in the upload handler
```

`/solve` reads the request, decides which specialists it needs, dispatches them (in parallel
where the work is independent), relays what each one found, and shows you `git diff --stat`.

### Or call one specialist directly

Just ask — Claude Code dispatches by matching your request against each subagent's
description:

```
have the reviewer look at my last commit
ask red-team to probe the auth middleware
```

### Schedule something

```
/schedule-agent trình ký GLX appendix 28 today 30 mins
```

This uses Claude's native Google Calendar integration and needs no local credentials. Works
in any language; the event title keeps your original wording.

## Installation

Nothing is required for the subagents or slash commands — they are configuration, not code.

Only the standalone scheduler needs a Python environment:

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -e .

python .claude/schedule.py "schedule planning session tomorrow 2 hours"
```

Requires **Python 3.9+**. Credential setup is in
[.claude/documents/SCHEDULER_SETUP.md](./.claude/documents/SCHEDULER_SETUP.md) — the short
version is:

```bash
gcloud auth application-default login \
  --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/calendar
```

## Project structure

```
.claude/
├── agents.json           # Master registry: the roster, in human-readable form
├── settings.json         # Harness configuration (theme, env, tmux preferences)
├── settings.local.json   # Local permission grants — not committed
│
├── agents/
│   ├── reviewer.md              # ← the seven subagent definitions
│   ├── red-team.md              #   (markdown + YAML frontmatter is the
│   ├── bug-fixer.md             #    only form Claude Code dispatches)
│   ├── diagnostician.md
│   ├── coder.md
│   ├── group-sales-manager.md
│   ├── scheduler.md
│   │
│   ├── base_agent.py            # Python: base class for the standalone scheduler
│   ├── system_init.py           # Python: the ARCHITECTURE.md reading requirement
│   ├── team/scheduler.py        # Python: SchedulerAgent implementation
│   └── tools/scheduler/         # Python: calendar helpers
│
├── commands/
│   ├── solve.md          # /solve — the team leader
│   └── schedule-agent.md # /schedule-agent — calendar via MCP
│
├── clients/              # Google Calendar API wrapper + credential resolution
├── system/schemas.py     # TaskResult, shared by the Python scheduler path
├── documents/            # ALL markdown documentation lives here
└── schedule.py           # Standalone scheduler entry point
```

## Documentation

Read in this order:

1. **[.claude/documents/ARCHITECTURE.md](./.claude/documents/ARCHITECTURE.md)** — system
   design, folder ownership, and the rules for adding anything
2. **[.claude/documents/AGENT_INITIALIZATION.md](./.claude/documents/AGENT_INITIALIZATION.md)** —
   the checklist every agent follows before executing
3. **[.claude/documents/SCHEDULE_CLI.md](./.claude/documents/SCHEDULE_CLI.md)** — scheduler
   usage and examples
4. **[.claude/documents/SETUP.md](./.claude/documents/SETUP.md)** — credential setup

Full index: [.claude/documents/README.md](./.claude/documents/README.md)

## Configuration

`.claude/settings.json` holds harness configuration:

```json
{
  "theme": "dark",
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_AGENT_COMMUNICATION_ENABLED": "1",
    "INTERACTIVE_MODE_ENABLED": "1"
  },
  "preferences": {
    "terminalManager": "tmux",
    "tmuxSessionPrefix": "agents-",
    "tmuxSplitPanes": true
  },
  "teammateMode": "tmux"
}
```

`.claude/settings.local.json` holds your local permission grants and is not committed.

## Adding a subagent

1. Create `.claude/agents/{name}.md` with `name`, `description`, `tools`, and `model`
   frontmatter, then the system prompt as the body.
2. Write the `description` for dispatch — it is what Claude Code matches a request against,
   so say when to use the agent, not just what it is.
3. Give it only the tools it needs. Omit `Edit`/`Write` for anything read-only.
4. Register it in `.claude/agents.json` and add it to the table in
   `.claude/commands/solve.md`.
5. Run the checks: `python .claude/system_test.py`

Full checklist and the folder rules are in
[ARCHITECTURE.md](./.claude/documents/ARCHITECTURE.md).

## Verifying the workspace

```bash
python .claude/system_test.py
```

Checks folder structure, that every `.md` is in a valid location, that `agents.json` parses,
that all seven subagents have frontmatter and the ARCHITECTURE.md requirement, and that the
documentation index is complete.

## Troubleshooting

**A subagent isn't being dispatched.** Check that `.claude/agents/{name}.md` starts with
`---` and has both `name:` and `description:`. Without frontmatter it is inert documentation.
`python .claude/system_test.py` catches this.

**`/solve` or `/schedule-agent` not found.** Slash commands are read from
`.claude/commands/`. Confirm you opened Claude Code in the repository root.

**Scheduler says credentials are missing.** Run the `gcloud auth application-default login`
command above, or see
[SCHEDULER_SETUP.md](./.claude/documents/SCHEDULER_SETUP.md) for the OAuth and service
account alternatives.

**Scheduler output is garbled on Windows.** The console defaults to cp1252. Set
`PYTHONIOENCODING=utf-8`, or use the entry points here — they already force UTF-8.

## License

MIT
