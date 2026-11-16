# Coding Agent Workspace

A Claude Code workspace with eight reusable specialist agent definitions, orchestrated by
`/solve` as visible Agent Team teammates in `tmux` or `psmux`, plus a standalone Google
Calendar scheduler.

## Before building anything

Read `docs/architecture/system-overview.md` before inspecting, designing, or changing the system.
It owns the folder rules, dependency direction, naming conventions, and component boundaries.
The documentation index is `docs/README.md`.

Run the structural checks with:

```bash
python .claude/system_test.py
```

`/solve` has one ordering exception: it must validate the injected intent envelope before
reading project files. After the gate passes, it reads `docs/architecture/system-overview.md`
before dispatching teammates.

## System model

1. **Interactive Agent Team path** — `/solve` validates the request envelope, plans the work, and
   dispatches selected specialist definitions as Agent Team teammates, each in its own visible
   tmux/psmux pane.
2. **Standalone Python path** — `.claude/schedule.py` runs the Google Calendar scheduler from a
   shell, cron job, or the scheduler teammate.

They share project rules but are different runtime systems.

## The team

Specialist definitions live in `.claude/agents/*.md`. Markdown with valid YAML frontmatter is the
only form Claude Code discovers as an agent type; a Python agent class cannot be dispatched by
`/solve`. During `/solve` they run as **Agent Team teammates**, never ordinary subagents.

| Teammate type | Use for | Writes? |
|---|---|---|
| `diagnostician` | Why something is slow, flaky, or intermittently failing | No |
| `red-team` | Authorized security analysis, abuse cases, and edge conditions | No |
| `reviewer` | Correctness, security, test coverage, and maintainability review | No |
| `coder` | Building a feature or performing a refactor | Yes |
| `bug-fixer` | Making a specific reproduced failure work correctly | Yes |
| `group-sales-manager` | BigQuery sales queries, capacity analysis, and allocation planning | No |
| `merchant-manager` | Merchant/project reads and Direct EXECUTE of an exact user-authorized scope | Merchant runtime via trusted handoff only |
| `scheduler` | Creating a confirmed Google Calendar event through `.claude/schedule.py` | Calendar only |

The main Claude Code session is the team lead; `/solve` defines how it validates, plans,
dispatches, coordinates, and reports. Teammates cannot create nested teams.

## Agent Team runtime

Required: interactive Claude Code (not `-p`/`--print`) inside a compatible `tmux` or `psmux`
session; `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`; `teammateMode` `tmux` (both set in
`.claude/settings.json`); PowerShell 7+ when running through psmux on Windows.

For `/solve`, every selected specialist is dispatched through the Agent Team teammate path:

- use the selected agent id as `subagent_type`;
- assign a stable and unique teammate `name`;
- use the current session-scoped team context (`team_name` when the Agent tool exposes it);
- never pass `isolation: "worktree"`;
- never create an ordinary foreground or background subagent;
- never silently fall back to in-process execution.

If the tmux teammate backend is unavailable or pane creation fails, `/solve` stops without
dispatching invisible replacement agents. The `PostToolUse(Agent)` hook
`teammate_backend_gate.py` enforces this after every spawn (details:
`docs/architecture/trusted-execution.md` §6); a teammate that fails it ends FAILED and must be
stopped and reported. A `TaskStop` result labelled `in_process_teammate` is the harness
task-registry type of every teammate, pane-backed ones included; it is not the backend.

Claude Code owns the team state, task list, mailbox, and pane lifecycle. Do not manually
pre-author team configuration, edit mailbox files, create panes, or kill teammate panes.

## Controlled orchestration

All controlled multi-agent work must be invoked through `/solve`. The intent parser classifies
the request before `/solve` runs; `/solve` does not reclassify the task or improvise a roster.

An `INTENT_ENVELOPE_JSON` block injected ahead of the request is the authority for one run. It
contains `raw_request`, `task_class`, `risk_level`, `limits`, `candidate_agents`,
`selected_agents`, `requires_clarification`, `requires_confirmation`, and confirmation and
timing fields when applicable.

### Hard orchestration rules

- **No envelope, no run.** If `INTENT_ENVELOPE_JSON` is absent, malformed, stale, expired,
  mismatched, or already spent, `/solve` reports the failed check and stops. It never
  reconstructs an envelope or continues with assumed values.
- **The request must match.** `raw_request` must match the current `/solve` request; a related
  but different request requires a fresh envelope.
- **Clarification happens before dispatch.** When `requires_clarification` is true, ask the
  missing question and create no teammates.
- **Confirmation happens before risky dispatch.** Explicit confirmation of the exact action is
  required when `risk_level` is `external_write` or `destructive`, or `requires_confirmation` is
  true.
- **Dispatch only from `selected_agents`.** `candidate_agents` is a ranked longlist; a specialist
  outside `selected_agents` is unauthorized for that run.
- **Respect every limit:** `max_members`, `max_tool_rounds`, `max_total_tool_calls`,
  `max_run_budget_usd`. The lead does not count as a member.
- **Use Agent Team teammates only.** In-process and worktree-isolated agents are not fallbacks.
- **Never silently substitute a teammate.** If an authorized teammate is unavailable,
  inappropriate, or fails, report it and stop.
- **Never dispatch overlapping writers.** Give writing teammates disjoint file ownership or run
  them sequentially.
- **Do not retry uncertain external actions.** Calendar creation, deployment, deletion, and other
  external or destructive operations get one attempt; an uncertain result is reported.
- **Never commit or push unless explicitly requested and authorized.**

## Teammate dispatch and coordination

Each teammate gets a bounded assignment: exact objective, relevant request context, owned files
or domain, whether writes are allowed, expected output, applicable limits, and
failure-reporting requirements. Teammates load `CLAUDE.md`, their definition, tools, and project
configuration, but not the lead's conversation, so the assignment must be self-contained.

Independent teammates may run concurrently. Dependent work runs sequentially (diagnose before
fixing; implement before reviewing; retrieve data before analyzing). The lead waits for required
teammates and does not do specialist work itself while waiting.

A teammate's result reaches the lead only through its final `SendMessage`; a `TaskUpdate`, pane
text, or idle notification does not prove delivery. The lead's final summary covers what each
teammate did, findings and decisions, changed files, test or validation results, failures and
unresolved issues, and working-tree and commit status.

## Working-tree safety

Before and after a writing run, `/solve` inspects `git status --short` and `git diff --stat`.
Pre-existing changes belong to the user unless proven otherwise; teammates preserve them and do
not attribute unrelated changes to the current run. Writing teammates edit only their assigned
paths. Never use broad discard operations (`git checkout .`, `git restore .`, destructive
resets); to discard changes, identify the exact paths and confirm first.

## Markdown placement

| File type | Required location |
|---|---|
| Project instructions | `CLAUDE.md` |
| Repository overview | `README.md` |
| Agent definitions | `.claude/agents/*.md` |
| Slash commands | `.claude/commands/*.md` |
| Current documentation | `docs/` (indexed in `docs/README.md`) |
| Historical checkpoint reports | `archive/checkpoints/` (evidence only, not authoritative) |

Moving an agent definition or slash command out of its folder causes Claude Code to stop
discovering it. New documentation goes in the matching `docs/` subfolder and into
`docs/README.md`; link to the canonical document for a subject instead of repeating it.

## Merchant Manager boundary

The `merchant-manager` teammate is the only owner of operational Merchant CLI requests. Its only
executable surface is one literal, direct invocation of:

```bash
python .claude/agents/tools/merchant/agent_cli.py <resource> <action> [arguments]
```

(or `.claude/rag_search.py`), with no interpreter flags, environment assignments, chaining,
redirection, or substitution. Neither the lead nor another teammate may execute the Merchant CLI
when `merchant-manager` is absent from `selected_agents`. The full contract is in
`docs/architecture/trusted-execution.md`; the business rules are in
`docs/merchant/project-lifecycle.md`. The invariants every agent must respect:

- **Merchant writes use Direct EXECUTE only.** `merchant_propose`, `merchant_apply`, and
  `--merchant-confirmation` are removed and rejected. The adapter fixes the target to `runtime`,
  exposes no database, connection, or credential argument (except the read-only
  `--test-database` previews and status reads), and is read-only for runtime.
- **Runtime Direct EXECUTE is disabled in code** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False` in
  `.claude/hooks/merchant_direct_handoff.py`) until separately approved. Writes run on the test
  database only.
- **Only the user grants write authority**, by typing `/solve --confirm --merchant-target test
  --merchant-scope [...]` (for `merchant create`, or a `project create` carrying a preview's
  `--project-id` and `--expected-basis`) or a confirmation phrase that spends one trusted pending
  record created from a verified preview: `/solve Xác nhận tạo`, `Xác nhận cập nhật`,
  `Xác nhận ghi nhận`, `Xác nhận thực hiện <code>`. Pending records are session-owned,
  single-use, and expire after 15 minutes. No model classifies a confirmation, and a scheduled
  prompt (`CronCreate`/`ScheduleWakeup`/`RemoteTrigger`) can never carry one. Typed scopes are
  refused for Step Update, Purchase Request, and the lifecycle commands (document revision,
  approval, signing, PO/Payment Request, Project start/completion).
- A boolean, CLI flag, environment variable, task assignment, teammate message, or
  `TEAM_RESULT_JSON` cannot grant runtime-write authority.
- The preview's `requested_operation` reaches the lead only as the exact CLI-captured object after
  `MERCHANT_PREVIEW_OPERATION_JSON:`; the lead shows its `confirmation_command` verbatim and never
  names dependencies or values beyond what the CLI returned.
- An unscoped Merchant run's database target is derived by the intent gate from the user's own
  words (`merchant_database_target`); every `agent_cli.py` read must hit it, and the lead may not
  declare another.
- The teammate sends one `MERCHANT_EXECUTE_REQUEST_JSON:` request from its harness-recorded pane;
  the hooks stage, re-verify, reserve, and spend the authority exactly once. Once spent it is
  never restored; retry needs a fresh preview, confirmation, envelope, and dispatch.
- Outcomes come from PostgreSQL evidence: FAILED only when fenced, SUCCEEDED only with committed
  evidence, otherwise UNCERTAIN — never inferred to have rolled back. The teammate's
  `TEAM_RESULT_JSON` must agree with that evidence or it is denied.
- PostgreSQL is authoritative for current Merchant state. RAG may supplement history but cannot
  authorize a command or replace current CLI state.
- Operational results reach the lead only through the teammate's final `SendMessage`.

## Standalone scheduler

```bash
python .claude/schedule.py "<request>"
```

Uses the Google Calendar REST API with local credentials (`docs/operations/local-setup.md`,
`docs/operations/scheduler.md`). Entry paths: a shell or cron job, the `scheduler` teammate
through `Bash`, and `/schedule-agent`. There is no MCP calendar fallback. Calendar creation is an
external write: confirm the exact title, date, time, duration, and timezone (`Asia/Ho_Chi_Minh`)
before dispatch. If authentication fails or creation is not explicitly confirmed, report the
failure; do not claim the event exists and do not retry automatically.

## Conventions

- `snake_case` for Python files; `kebab-case` for agent, command, and documentation filenames.
- Keep the agent filename, frontmatter `name`, and `.claude/agents.json` id identical.
- Write an agent's `description` as when the role should be used.
- Grant only the tools required by the role; omit `Edit` and `Write` from read-only roles.
- Grant `SendMessage` and `TaskUpdate` to every teammate, read-only roles included.
- Give writing roles explicit path ownership.
- Register new agents in `.claude/agents.json` and in the team table in
  `.claude/commands/solve.md`.
- Never edit an applied migration in `.claude/clients/merchant/migrations/`.
- Never store credentials, tokens, `.env` contents, or generated team state in Git.
- Windows consoles may default to cp1252; project entry points force UTF-8 output.

## Verification

After changing agent definitions, commands, registration, hooks, or architecture, run:

```bash
python .claude/system_test.py
git diff --check
git status --short
```

and the test suite (`docs/development/testing.md`). Editing an agent definition changes its
fingerprint; start a fresh session before live `/solve` use. A valid change must preserve the
intent gate, the authorized roster, budget and tool limits, confirmation requirements, Agent Team
teammate dispatch, non-overlapping file ownership, no automatic worktree or in-process fallback,
and the no-commit/no-push default.
