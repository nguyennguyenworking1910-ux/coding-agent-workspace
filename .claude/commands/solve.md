---
description: Run a request through the validated intent envelope and visible Agent Team teammates
argument-hint: "[request]"
disable-model-invocation: true
allowed-tools: Agent, TaskCreate, TaskGet, TaskList, TaskUpdate, TaskStop, SendMessage, Read, Grep, Glob, Bash(git diff *), Bash(git status *), Bash(git log *)
disallowed-tools: EnterWorktree, ExitWorktree
---

# Controlled Agent Team execution

**Request:** $ARGUMENTS

This command is the lead session for one controlled Claude Code Agent Team run. It must use
real Agent Team teammates in visible tmux/psmux panes. It must never use ordinary subagents.

## 1. Validate the intent envelope first

An `INTENT_ENVELOPE_JSON` block is injected ahead of the request. It is the sole authority for
the run: task class, risk level, selected roster, clarification and confirmation requirements,
and resource limits.

Do not read project files, plan, create a team, create tasks, or dispatch teammates until the
envelope passes every check below.

### Required checks

1. **Present**

   If the block is missing, respond exactly:

   `Gate failed: INTENT_ENVELOPE_JSON is missing.`

   Then stop. Do not classify the request, reconstruct an envelope, or select agents yourself.

2. **Well-formed**

   The block must parse as JSON and contain:

   - `task_class`
   - `risk_level`
   - `limits`
   - `selected_agents`
   - `requires_clarification`
   - `requires_confirmation`
   - `raw_request`

   `task_class` must be one of:

   - `small_task`
   - `medium_task`
   - `complex_task`

   `risk_level` must be one of:

   - `read_only`
   - `write`
   - `external_write`
   - `destructive`

   `limits` must contain valid non-negative values for:

   - `max_members`
   - `max_tool_rounds`
   - `max_total_tool_calls`
   - `max_run_budget_usd`

   `selected_agents` must be a list containing only registered teammate types and its length
   must not exceed `limits.max_members`.

   For malformed data, report the exact failing field in one concise line and stop.

3. **Current, matching, and unspent**

   - Honour any issue and expiry timestamps carried by the envelope.
   - `raw_request` must match the current request in `$ARGUMENTS`.
   - An envelope for different work is stale, even if the work is related.
   - An envelope authorizes one dispatch only. Never reuse a spent envelope.

   If any check fails, report the reason, request a fresh envelope for the current request, and
   stop. Never repair or reconstruct an envelope.

Failing this gate is a valid fail-closed outcome.

## 2. Initialize only after the gate passes

After validation:

1. Read `.claude/documents/ARCHITECTURE.md`.
2. Apply its folder ownership, dependency, naming, documentation, and safety rules.
3. Confirm that `$ARGUMENTS` is not empty.
4. Report these authoritative envelope fields before dispatch:

   - `task_class`
   - `risk_level`
   - `selected_agents`
   - `limits`
   - `requires_clarification`
   - `requires_confirmation`

If the request is empty, ask what the user wants and stop.

## 3. Resolve clarification and confirmation before team creation

### Clarification

If `requires_clarification` is `true`, ask the specific required question and stop. Do not
create a team, create tasks, dispatch a partial roster, narrow the request, or assume missing
details.

### Confirmation

Explicit confirmation is required before team creation when any condition below is true:

- `risk_level` is `external_write`;
- `risk_level` is `destructive`; or
- `requires_confirmation` is `true`.

Confirmation is valid only when the envelope carries `confirmed: true`, or the user explicitly
confirmed the exact action in the current session. Before asking, state the exact external or
destructive action that would occur.

A generic or earlier approval does not authorize a different action. External and destructive
mutations receive one attempt only; an uncertain or failed result must be reported, not retried.

## 4. Required Agent Team and pane mode

This command requires all of the following runtime conditions:

- Claude Code is running interactively, not with `-p` or `--print`;
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is enabled;
- `teammateMode` is `tmux`, or Claude Code was started with `--teammate-mode tmux`;
- the current Claude Code session is already inside the compatible tmux/psmux environment.

These are prerequisites, not work for `/solve`. Do not install software, edit settings, start a
new multiplexer, or manually split panes during the run.

Do not use the absence of a separately exposed `TeamCreate` tool as proof that Agent Teams are
unavailable. Claude Code versions differ: in this project runtime, teammates are created through
the team-aware mode of the `Agent` tool. Test the authorized team-aware dispatch itself.

If that dispatch rejects the required teammate fields, creates an ordinary subagent, or fails to
open a separate pane, respond:

`Agent Team tmux backend unavailable — no teammates were dispatched.`

Then stop. Never fall back to an in-process agent.

## 5. Hard dispatch contract

Create exactly one session-scoped Agent Team for this run through the runtime's **team-aware
`Agent` path**. In this Claude Code runtime, `Agent` has two distinct uses:

- with a teammate `name` and shared `team_name`/team context, it creates an Agent Team teammate;
- without team context, it creates an ordinary subagent.

Only the first form is allowed by `/solve`. Do not preflight by requiring or searching for a
separate `TeamCreate` tool.

Choose one stable, unique `team_name` for the run. Every selected teammate must use that same
team context.

For every id in `selected_agents`:

1. Invoke `Agent` in Agent Team teammate mode.
2. Set `subagent_type` to the exact selected agent id.
3. Set a stable unique teammate `name`, normally the agent id; add a deterministic suffix only
   when required for uniqueness.
4. Supply the shared `team_name` or equivalent team-context field exposed by the runtime.
5. Supply a complete bounded assignment as the teammate prompt.
6. Ensure the result is an independent Agent Team teammate in its own visible tmux/psmux pane.
7. Give it one bounded task through the shared team task list when task tools are exposed.

The direct semantic instruction is:

> Create an Agent Team with one named teammate for each `selected_agents` entry. Use the
> team-aware `Agent` path with the corresponding project agent type, teammate name, and shared
> team context. Every teammate must run in a separate tmux pane. Do not use an ordinary
> subagent.

The following are forbidden:

- calling `Agent` without teammate `name` and team context;
- calling `Agent` in ordinary foreground, background, or fork mode;
- ordinary foreground or background subagents;
- forked subagents;
- `isolation: "worktree"`;
- in-process fallback;
- omitting or substituting a selected agent;
- creating an agent not listed in `selected_agents`;
- creating extra instances unless the envelope explicitly authorizes them;
- manually creating, renaming, splitting, or killing tmux panes;
- creating or editing project-level team configuration files;
- manually editing Claude Code team, task, mailbox, or pane state.

After the first teammate is created, verify that it has the requested teammate name, belongs to
the run's team context, and appears in a separate pane. If any condition fails, stop immediately,
report the backend failure, and do not dispatch the remaining roster.

If another Agent Team from an earlier run is still active in the session, do not reuse it or
destroy it automatically. Report the conflict and stop so the earlier team can be resolved
safely first.

## 6. Authorized teammate types

Definitions live in `.claude/agents/*.md`. A definition can be reused as an Agent Team teammate
type, but its presence does not authorize dispatch; only `selected_agents` does.

| Teammate type | Responsibility | Writes? |
|---|---|---:|
| `diagnostician` | Root-cause analysis from logs, metrics, traces, and system state | No |
| `red-team` | Authorized security analysis, abuse cases, and boundary conditions | No |
| `reviewer` | Correctness, security, test coverage, and maintainability review | No |
| `coder` | Feature implementation and refactoring from a specification | Yes |
| `bug-fixer` | Repairing a specific reproduced failure or defect | Yes |
| `group-sales-manager` | Sales-data queries, capacity analysis, and allocation planning | No |
| `scheduler` | Creating a confirmed calendar event | Calendar only |

Never invent an unregistered teammate type.

## 7. Limits are hard boundaries

Apply every envelope limit across the entire run, not per teammate or per round:

- `max_members`: maximum distinct teammates; the lead does not count;
- `max_tool_rounds`: maximum coordination/dispatch rounds;
- `max_total_tool_calls`: maximum tool calls allowed by the run state and hooks;
- `max_run_budget_usd`: maximum authorized run cost.

Use the runtime hooks and shared run state as the authoritative counters. Include relevant
remaining limits in every teammate assignment. If a hook or counter stops the run, stop; do not
move unfinished specialist work into the lead session to bypass the boundary.

`candidate_agents` is only a ranked longlist. It never authorizes a teammate.

If an authorized teammate is unavailable, fails to start, or fails during work, report the real
failure. Do not substitute a role or create a retry teammate without a fresh envelope.

## 8. Plan and assign work

The lead coordinates; it does not perform specialist implementation itself.

Before dispatch, describe in two or three concise lines:

- what each selected teammate will own;
- which tasks can run concurrently;
- which dependencies require sequencing.

Every teammate assignment must include:

- exact objective;
- relevant request context;
- owned files or domain;
- whether writing is permitted;
- expected output;
- task dependencies;
- remaining relevant limits;
- instruction to report failures accurately.

Teammates load project context, including `CLAUDE.md`, but do not inherit the lead's conversation
history. Put all necessary task-specific context in the assignment.

## 9. Coordinate safely

Create independent teammates in the same dispatch round so their panes run concurrently. Use
task dependencies when the work is genuinely sequential, such as:

- diagnose before fixing;
- implement before reviewing;
- retrieve data before analysis.

Never let writing teammates edit overlapping paths concurrently. Give `coder` and `bug-fixer`
explicit disjoint ownership, or sequence their tasks. Two writing teammates must not edit the
same file in the same round.

Monitor the shared task list and teammate messages. Wait for every required teammate result.
Do not implement the task yourself while waiting.

When a teammate fails:

- preserve and report the actual failure;
- do not hide it or claim success;
- do not substitute another role;
- do not create a replacement without a fresh envelope.

## 10. Synthesize, verify, and clean up

The final answer in the lead pane must be complete even though the user can see individual
teammate panes. Clearly separate:

- completed work;
- findings;
- changed files;
- verification or tests;
- unresolved, failed, or skipped work.

For a run that permits writes or reports working-tree changes, and only if limits remain, run:

- `git status --short`
- `git diff --stat`

Do not hide unrelated pre-existing changes or attribute them to the current run unless verified.
For a strictly `read_only` run, do not consume tool budget on Git inspection unless it is needed
to support the requested analysis.

After all required results are collected:

1. Request graceful shutdown of every teammate created by this run.
2. Wait until no teammate remains active.
3. Use the runtime's native team-cleanup action if it is exposed. Do not require a separately
   named `TeamDelete` tool when the installed version manages cleanup through team-aware agent
   controls.
4. Clean up only the Agent Team created by this run.
5. If shutdown or cleanup fails, report it; never kill panes or the tmux/psmux session manually.

Nothing is committed or pushed unless the request explicitly asks for it and the envelope
authorizes it. When files changed, remind the user to review the exact diff before deciding
whether to commit or discard anything. Never recommend a broad discard command without first
identifying the exact paths and confirming those changes may be removed.

## Architectural boundaries

- Components are `agents`, `tools`, `clients`, `commands`, and `documents`.
- Documentation belongs in `.claude/documents/`.
- Agent definitions belong in `.claude/agents/`.
- Slash commands belong in `.claude/commands/`.
- Dependencies flow one way: agents → tools → clients.
- Register new components in `.claude/agents.json` when the architecture requires it.
- Follow repository naming and folder-ownership conventions.
- Do not commit, push, create branches, or open pull requests unless explicitly requested and
  authorized by the current envelope.
