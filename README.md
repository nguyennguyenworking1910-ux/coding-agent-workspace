# Coding Agent Workspace

A Claude Code workspace: a team of specialist subagents for code work, plus a standalone
Google Calendar scheduler.

## Overview

Everything here runs inside a Claude Code session. There is no separate CLI to install or
launch — you open Claude Code in this directory and the configuration below is picked up
automatically.

Two things live in this repo:

1. **Subagent definitions** (`.claude/agents/*.md`) — eight specialists that Claude Code
   discovers and dispatches, orchestrated by the `/solve` command.
2. **The standalone scheduler** (`.claude/schedule.py`) — the one piece of Python that runs
   outside a session, for scripting or cron. It talks to the Google Calendar REST API and
   needs local credentials.

The working agreement for both is [CLAUDE.md](./CLAUDE.md) in the repository root, loaded
automatically at the start of every session. It holds the team table, the folder rules, and
the hard rules for controlled orchestration — no envelope means no run, dispatch only from
`selected_agents`, one writing agent per path, and never commit unless you ask. Edit that
file to change how the agents behave; it previously lived inside `.claude/settings.json` as a
`claudeMd` string, which made it invisible to review.

## The team

| Subagent | Use for | Writes? |
|---|---|---|
| `diagnostician` | Why something is slow, flaky, or intermittently failing | No |
| `red-team` | Security holes and edge cases | No |
| `reviewer` | Correctness and maintainability of a finished change | No |
| `coder` | Building a feature, doing a refactor | Yes |
| `bug-fixer` | Making a specific broken thing work | Yes |
| `group-sales-manager` | Sales data queries, capacity and allocation analysis | No |
| `merchant-manager` | Merchant/project reads, redacted proposals, and exact confirmed-apply handoff | Ordinary CLI read/propose only; trusted in-process apply |
| `scheduler` | Putting something on the calendar | Calendar only |

The ordinary CLI remains read/propose-only. A Merchant mutation can run only through the
policy-accepted, one-use, in-process session handoff documented in the Checkpoint 7 handoff.

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

This confirms the details with you, then dispatches the `scheduler` subagent, which books the
slot by running `.claude/schedule.py` — so it needs the credentials set up below. Works in any
language; the event title keeps your original wording.

## Installation

Nothing is required for the subagents or slash commands — they are configuration, not code.

The standalone scheduler and the intent parser need a Python environment:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -e .

python .claude/schedule.py "schedule planning session tomorrow 2 hours"
```

Requires **Python 3.10+**. Full setup — virtual environment, `OPENAI_API_KEY` for the intent
parser, and credentials — is in
[.claude/documents/SETUP.md](./.claude/documents/SETUP.md). The short version for the
calendar:

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
│   ├── reviewer.md              # ← the eight subagent definitions
│   ├── red-team.md              #   (markdown + YAML frontmatter is the
│   ├── bug-fixer.md             #    only form Claude Code dispatches)
│   ├── diagnostician.md
│   ├── coder.md
│   ├── group-sales-manager.md
│   ├── merchant-manager.md
│   ├── scheduler.md
│   │
│   ├── base_agent.py            # Python: base class for the standalone scheduler
│   ├── system_init.py           # Python: the ARCHITECTURE.md reading requirement
│   ├── team/scheduler.py        # Python: SchedulerAgent implementation
│   ├── tools/merchant/          # Merchant CLI and credential-safe agent adapter
│   └── tools/scheduler/         # Python: calendar helpers
│
├── commands/
│   ├── solve.md          # /solve — the team leader
│   └── schedule-agent.md # /schedule-agent — dispatches the scheduler
│
├── clients/              # Google Calendar API wrapper + credential resolution
├── hooks/                # Intent/policy gates and locked per-session run state
├── system/
│   ├── schemas.py                 # TaskResult, shared by the scheduler path
│   └── merchant_runtime_handoff.py # One-use confirmed Merchant apply bridge
├── documents/            # ALL markdown documentation lives here
└── schedule.py           # Standalone scheduler entry point
```

## Documentation

Read in this order:

1. **[.claude/documents/ARCHITECTURE.md](./.claude/documents/ARCHITECTURE.md)** — system
   design, folder ownership, and the rules for adding anything
2. **[.claude/documents/AGENT_INITIALIZATION.md](./.claude/documents/AGENT_INITIALIZATION.md)** —
   the checklist every agent follows before executing
3. **[.claude/documents/SETUP.md](./.claude/documents/SETUP.md)** — Python environment, API
   keys, credentials, and the test commands
4. **[.claude/documents/SCHEDULE_CLI.md](./.claude/documents/SCHEDULE_CLI.md)** — scheduling
   from a session or a shell, and credential troubleshooting
5. **[.claude/documents/BIGQUERY_INTEGRATION.md](./.claude/documents/BIGQUERY_INTEGRATION.md)** —
   adding and running `.sql` query templates
6. **[.claude/documents/MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md](./.claude/documents/MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md)** —
   Merchant intent, confirmation, dispatch, and trusted runtime-apply boundary
7. **[.claude/documents/MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md](./.claude/documents/MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md)** —
   Merchant deadline, blocker, missing-gate, and global alert-read boundary
8. **[.claude/documents/MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md](./.claude/documents/MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md)** —
   Private runtime initialization, hash-bound catalog, and final core Phase 4 boundary
9. **[.claude/documents/MERCHANT_CHECKPOINT_10_PLAN_2026-09-09.md](./.claude/documents/MERCHANT_CHECKPOINT_10_PLAN_2026-09-09.md)** —
   Production alert delivery, lease-safe claiming, bounded retries, and operational verification
10. **[.claude/documents/MERCHANT_CHECKPOINT_10_HANDOFF_2026-09-09.md](./.claude/documents/MERCHANT_CHECKPOINT_10_HANDOFF_2026-09-09.md)** —
    Final Merchant implementation, runtime rollout evidence, and debugging boundary
11. **[.claude/documents/MERCHANT_ALERT_OPERATIONS.md](./.claude/documents/MERCHANT_ALERT_OPERATIONS.md)** —
    One-shot alert-worker modes, safe limits, health checks, Task Scheduler, and recovery

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

1. Create `.claude/agents/{name}.md` with `name`, `description`, `tools`, `model`,
   `permissionMode`, and `maxTurns` frontmatter, then the system prompt as the body. The
   frontmatter is authoritative; `agents.json` must agree with it.
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
that all eight subagents have frontmatter and the ARCHITECTURE.md requirement, that each
registry entry has a matching definition whose `name`, `model`, and `maxTurns` agree with it,
that `AGENTS_BY_OPERATION` in the intent parser names only enabled agents, and that the
documentation index is complete. It exits non-zero on failure.

## Troubleshooting

**A subagent isn't being dispatched.** Check that `.claude/agents/{name}.md` starts with
`---` and has both `name:` and `description:`. Without frontmatter it is inert documentation.
`python .claude/system_test.py` catches this.

**`/solve` or `/schedule-agent` not found.** Slash commands are read from
`.claude/commands/`. Confirm you opened Claude Code in the repository root.

**Scheduler says credentials are missing.** Run the `gcloud auth application-default login`
command above, or see
[SCHEDULE_CLI.md](./.claude/documents/SCHEDULE_CLI.md) for the OAuth and service account
alternatives and a message-by-message walkthrough.

**Scheduler output is garbled on Windows.** The console defaults to cp1252. Set
`PYTHONIOENCODING=utf-8`, or use the entry points here — they already force UTF-8.

## License

MIT
