# Coding Agent Workspace

A Claude Code workspace: seven specialist subagents plus a standalone Google Calendar scheduler.

## Before building anything

Read `.claude/documents/ARCHITECTURE.md`. It owns the folder rules, and `python .claude/system_test.py` enforces them.

## The team

Subagents are defined in `.claude/agents/*.md`. Markdown with YAML frontmatter is the only form Claude Code discovers and dispatches - a Python agent class is invisible to the harness and will never be dispatched.

| Subagent | Use for | Writes? |
|---|---|---|
| `diagnostician` | Why something is slow, flaky, or intermittently failing | No |
| `red-team` | Security holes and edge cases | No |
| `reviewer` | Correctness and maintainability of a finished change | No |
| `coder` | Building a feature, doing a refactor | Yes |
| `bug-fixer` | Making a specific broken thing work | Yes |
| `group-sales-manager` | Sales data queries (bq CLI), capacity and allocation analysis | No |
| `scheduler` | Putting something on the calendar (runs `.claude/schedule.py`) | Calendar only |

Orchestrate with `/solve`, which plans a request and dispatches these. The team leader is that command, not an agent - only the main session can dispatch others.

## Controlled orchestration

Controlled orchestration must be invoked through `/solve`. That command is the only place a run is bounded - it classifies the request, sizes the team, and caps the budget. Dispatching specialists by hand skips all of it.

`/solve` is handed an `INTENT_ENVELOPE_JSON` block ahead of the request. That envelope is the run's authority: `task_class`, `risk_level`, `limits`, the agent roster, and the two separate flags `requires_clarification` (the request is missing information) and `requires_confirmation` (policy wants the user to approve before acting).

The rules below are hard rules, not defaults:

- **No envelope, no run.** If no `INTENT_ENVELOPE_JSON` is injected, `/solve` stops and says so. It never guesses a task class or improvises a roster - the intent parser fails closed, and the command fails closed with it.
- **Dispatch only agents in `selected_agents`.** `candidate_agents` is the ranked longlist; `selected_agents` is that list already truncated to `limits.max_members`. An agent outside it is over budget, not merely unlikely.
- **Never dispatch two writing agents on overlapping paths.** Not concurrently, and not within the same round - the second silently clobbers the first. Split the paths or run them in separate rounds.
- **Never commit or push unless the user explicitly requests it.** Writing agents leave changes in the working tree; the user reviews the diff and commits.

## Markdown placement (critical)

All documentation goes in `.claude/documents/`. There are exactly two exceptions, and both are load-bearing rather than stylistic: subagent definitions must live at `.claude/agents/*.md` and slash commands at `.claude/commands/*.md`. Move one into `documents/` and that agent or command silently stops existing.

## Standalone scheduler

`python .claude/schedule.py "<request>"` runs the scheduler outside a session, against the Google Calendar REST API with local credentials (see `.claude/documents/SETUP.md`). It is the only Python agent in the repo and the only reason `.claude/system/schemas.py` exists. The `scheduler` subagent runs that same entry point through `Bash`, and `/schedule-agent` just dispatches that subagent - so every path needs those credentials, and there is no MCP calendar path left. Usage and troubleshooting: `.claude/documents/SCHEDULE_CLI.md`.

## Conventions

- `snake_case` for Python files, `kebab-case` for subagent and command filenames
- A subagent's `description` is what dispatch matches on - write it as when to use the agent
- Grant only the tools a role needs; omit `Edit`/`Write` for read-only agents
- Register new agents in `.claude/agents.json` and in the team table in `.claude/commands/solve.md`
- Windows consoles are cp1252; entry points force UTF-8 output
