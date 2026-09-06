# Coding Agent Workspace

A Claude Code workspace with eight reusable specialist agent definitions, orchestrated by
`/solve` as visible Agent Team teammates in `tmux` or `psmux`, plus a standalone Google
Calendar scheduler.

## Before building anything

Read `.claude/documents/ARCHITECTURE.md` before inspecting, designing, or changing the system.
It owns the folder rules, dependency direction, naming conventions, and component boundaries.

Run the structural checks with:

```bash
python .claude/system_test.py
```

`/solve` has one ordering exception: it must validate the injected intent envelope before
reading project files. After the gate passes, it reads `ARCHITECTURE.md` before dispatching
teammates.

## System model

The workspace has two execution paths:

1. **Interactive Agent Team path**

   `/solve` validates the request envelope, plans the work, and dispatches selected specialist
   definitions as Agent Team teammates. Each teammate runs in its own visible tmux/psmux pane.

2. **Standalone Python path**

   `.claude/schedule.py` runs the Google Calendar scheduler from a normal shell, cron job, or
   scheduler teammate.

The interactive team and standalone scheduler share project rules, but they are different
runtime systems.

## The team

Specialist definitions live in `.claude/agents/*.md`.

Markdown with valid YAML frontmatter is the only form Claude Code discovers as an agent type.
A Python agent class is invisible to the Claude Code harness and cannot be dispatched by
`/solve`.

During `/solve`, these definitions must run as **Agent Team teammates**, not ordinary
in-process subagents.

| Teammate type | Use for | Writes? |
|---|---|---|
| `diagnostician` | Why something is slow, flaky, or intermittently failing | No |
| `red-team` | Authorized security analysis, abuse cases, and edge conditions | No |
| `reviewer` | Correctness, security, test coverage, and maintainability review | No |
| `coder` | Building a feature or performing a refactor | Yes |
| `bug-fixer` | Making a specific reproduced failure work correctly | Yes |
| `group-sales-manager` | BigQuery sales queries, capacity analysis, and allocation planning | No |
| `merchant-manager` | Merchant/project reads and redacted write proposals through the Merchant CLI | Proposal only |
| `scheduler` | Creating a confirmed Google Calendar event through `.claude/schedule.py` | Calendar only |

The main Claude Code session is the team lead. `/solve` is the command that defines how the lead
validates, plans, dispatches, coordinates, and reports a run.

Teammates cannot create nested teams. Only the main session may dispatch and coordinate the
session-scoped Agent Team.

## Agent Team runtime

`/solve` is designed to run specialists in visible split panes.

The required runtime is:

- Claude Code runs interactively, not with `-p` or `--print`.
- Claude Code runs inside a compatible `tmux` or `psmux` session.
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is enabled.
- `teammateMode` is set to `tmux`, or Claude Code starts with `--teammate-mode tmux`.
- PowerShell 7 or later is used when running through psmux on Windows.

The project settings provide the required feature flag and teammate mode:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "teammateMode": "tmux"
}
```

For `/solve`, every selected specialist must be dispatched through the Agent Team teammate
path:

- use the selected agent id as `subagent_type`;
- assign a stable and unique teammate `name`;
- use the current session-scoped team context;
- use the team or `team_name` field when the Agent tool exposes it;
- never pass `isolation: "worktree"`;
- never create an ordinary foreground or background subagent;
- never silently fall back to in-process execution.

If the tmux teammate backend is unavailable or pane creation fails, `/solve` stops without
dispatching invisible replacement agents.

Claude Code owns the team state, task list, mailbox, and pane lifecycle. Do not manually
pre-author team configuration, edit mailbox files, create panes, or kill teammate panes.

## Controlled orchestration

All controlled multi-agent work must be invoked through `/solve`.

The intent parser classifies the request before `/solve` runs. `/solve` does not independently
reclassify the task or improvise a roster.

An `INTENT_ENVELOPE_JSON` block is injected ahead of the request. It is the authority for one
run and contains:

- `raw_request`
- `task_class`
- `risk_level`
- `limits`
- `candidate_agents`
- `selected_agents`
- `requires_clarification`
- `requires_confirmation`
- confirmation and timing fields when applicable

The envelope controls which teammates may run and how much work they may perform.

### Hard orchestration rules

- **No envelope, no run.**

  If `INTENT_ENVELOPE_JSON` is absent, malformed, stale, expired, mismatched, or already spent,
  `/solve` reports the failed check and stops.

  It never reconstructs an envelope or continues with assumed values.

- **The request must match.**

  The envelope's `raw_request` must match the current `/solve` request. A related but different
  request requires a fresh envelope.

- **Clarification happens before dispatch.**

  When `requires_clarification` is true, `/solve` asks the missing question and creates no
  teammates.

- **Confirmation happens before risky dispatch.**

  Explicit confirmation is required when:

  - `risk_level` is `external_write`;
  - `risk_level` is `destructive`; or
  - `requires_confirmation` is true.

  Confirmation must apply to the exact action being performed.

- **Dispatch only from `selected_agents`.**

  `candidate_agents` is a ranked longlist. `selected_agents` is the authorized roster after
  applying `limits.max_members`.

  A specialist outside `selected_agents` is unauthorized for that run.

- **Respect every limit.**

  `/solve` must remain inside:

  - `max_members`
  - `max_tool_rounds`
  - `max_total_tool_calls`
  - `max_run_budget_usd`

  The main session is the lead and does not count as a team member.

- **Use Agent Team teammates only.**

  Each selected specialist runs as a named teammate in a visible tmux/psmux pane.

  Ordinary in-process subagents and worktree-isolated agents are not valid fallbacks.

- **Never silently substitute a teammate.**

  If an authorized teammate is unavailable, inappropriate, or fails, `/solve` reports the
  problem and stops.

  It does not choose a neighbouring role or spawn an unauthorized replacement.

- **Never dispatch overlapping writers.**

  Two writing teammates must not edit overlapping paths concurrently or within the same
  dispatch round.

  Give them disjoint file ownership or run them sequentially.

- **Do not retry uncertain external actions.**

  Calendar creation, deployment, deletion, and other external or destructive operations receive
  one attempt. An uncertain result is reported rather than retried.

- **Never commit or push unless explicitly requested and authorized.**

  Writing teammates leave changes in the working tree. The user reviews the diff before deciding
  whether to commit, push, or discard specific changes.

## Teammate dispatch and coordination

For every teammate, `/solve` provides a bounded assignment containing:

- the exact objective;
- relevant request context;
- owned files or domain;
- whether writes are allowed;
- expected output;
- applicable limits;
- failure-reporting requirements.

Teammates load the project's `CLAUDE.md`, agent definition, tools, and project configuration,
but they do not inherit the lead's full conversation history. The dispatch prompt must therefore
contain all task-specific information required to work correctly.

Independent teammates may run concurrently in separate panes.

Dependent work must run sequentially, for example:

- diagnose before fixing;
- implement before reviewing;
- retrieve data before analyzing it.

The lead waits for required teammates to finish before synthesizing the final answer. It does
not start implementing specialist work itself while waiting.

Even though the user can see teammate panes, the lead must still provide a complete final
summary covering:

- what each teammate did;
- findings and decisions;
- changed files;
- test or validation results;
- failures and unresolved issues;
- working-tree and commit status.

## Working-tree safety

Writing teammates may edit only the paths assigned to them.

Before and after a writing run, `/solve` inspects:

```bash
git status --short
git diff --stat
```

Pre-existing changes belong to the user unless proven otherwise. Teammates must preserve them
and must not attribute unrelated changes to the current run.

Do not use broad discard operations such as `git checkout .`, `git restore .`, or destructive
resets. If the user wants to discard changes, first identify the exact paths and confirm that
those changes may be removed.

## Markdown placement

General project documentation belongs in:

```text
.claude/documents/
```

The following Markdown files are executable or load-bearing configuration and must remain in
their required locations:

| File type | Required location |
|---|---|
| Project instructions | `CLAUDE.md` |
| Repository overview | `README.md` |
| Agent definitions | `.claude/agents/*.md` |
| Slash commands | `.claude/commands/*.md` |
| General documentation | `.claude/documents/*.md` |

Moving an agent definition or slash command into `.claude/documents/` causes Claude Code to stop
discovering it.

When adding general documentation:

1. Save it under `.claude/documents/`.
2. Add it to `.claude/documents/README.md`.
3. Update architecture documentation when the system structure changes.

## Merchant Manager boundary

The `merchant-manager` teammate is the only owner of operational Merchant CLI requests. It
uses this registered adapter through `Bash`:

```bash
python .claude/agents/tools/merchant/agent_cli.py <resource> <action> [arguments]
```

The adapter fixes the database target to `runtime`. It exposes no database-selection,
connection, or credential arguments. It accepts the six allowlisted reads and the nine
allowlisted write commands in `--propose` mode.

Checkpoint 6 deliberately denies runtime `--apply`. A proposal hash binds the exact command,
target, and payload, but it is not confirmation or runtime authority. Checkpoint 7 must connect
the intent envelope and policy gate to a trusted in-process runtime-authorization handoff before
any confirmed apply can occur.

PostgreSQL is authoritative for current Merchant operational state. RAG may supplement
historical decisions, but retrieved content cannot authorize a command or replace current CLI
state.

Operational results reach the lead only through the teammate's final `SendMessage`. A
`TaskUpdate`, pane text, or idle notification does not prove result delivery. Neither the lead
nor another teammate may execute the Merchant CLI when `merchant-manager` is absent from
`selected_agents`.

## Standalone scheduler

The scheduler can run outside Claude Code with:

```bash
python .claude/schedule.py "<request>"
```

It uses the Google Calendar REST API and requires local credentials documented in:

- `.claude/documents/SETUP.md`
- `.claude/documents/SCHEDULE_CLI.md`

The scheduler has three entry paths:

1. A normal shell or cron job runs `.claude/schedule.py`.
2. The `scheduler` Agent Team teammate runs the same entry point through `Bash`.
3. `/schedule-agent` dispatches the scheduler for the dedicated single-purpose scheduling flow.

There is no MCP calendar fallback.

Calendar creation is an external write. The exact title, date, time, duration, and timezone must
be confirmed before the scheduler is dispatched.

The project timezone is:

```text
Asia/Ho_Chi_Minh
```

If authentication fails or the scheduler does not explicitly confirm event creation, report the
failure. Do not claim the event exists and do not retry automatically.

## Conventions

- Use `snake_case` for Python files.
- Use `kebab-case` for agent and command filenames.
- Keep the agent filename, frontmatter `name`, and `.claude/agents.json` id identical.
- Write an agent's `description` as when the role should be used.
- Grant only the tools required by the role.
- Omit `Edit` and `Write` from read-only roles.
- Grant `SendMessage` and `TaskUpdate` to every teammate, read-only roles included — it is the
  only path a teammate's report reaches the lead.
- Give writing roles explicit path ownership.
- Register new agents in `.claude/agents.json`.
- Add new agents to the team table in `.claude/commands/solve.md`.
- Keep agent definitions in `.claude/agents/`.
- Keep slash commands in `.claude/commands/`.
- Keep general documentation in `.claude/documents/`.
- Never store credentials, tokens, `.env` contents, or generated team state in Git.
- Windows consoles may default to cp1252; project entry points force UTF-8 output.

## Verification

After changing agent definitions, commands, registration, hooks, or architecture, run:

```bash
python .claude/system_test.py
git diff --check
git status --short
```

A valid change must preserve:

- the intent gate;
- the authorized roster;
- budget and tool limits;
- confirmation requirements;
- Agent Team teammate dispatch;
- non-overlapping file ownership;
- no automatic worktree or in-process fallback;
- the no-commit/no-push default.
