---
description: Run a request through the validated intent envelope and visible Agent Team teammates
argument-hint: "[request]"
disable-model-invocation: true
allowed-tools: Agent, TaskCreate, TaskGet, TaskList, TaskUpdate, TaskStop, SendMessage, Read, Grep, Glob, Bash(git diff *), Bash(git status *), Bash(git log *), Bash(${CLAUDE_PROJECT_DIR}/.venv/Scripts/python.exe ${CLAUDE_PROJECT_DIR}/.claude/hooks/intent_envelope_bridge.py)
disallowed-tools: EnterWorktree, ExitWorktree
---

## Merchant Direct EXECUTE

Merchant writes use Direct EXECUTE only. There is no proposal, confirmation token, or apply
step. The only runtime-write authority is an explicitly confirmed exact scope typed by the user:

`/solve --confirm --merchant-scope ["project","update","<project-uuid>","--status","IN_PROGRESS","--expected-version","3"] Update project <project-uuid> to IN_PROGRESS`

- Intent Gate validates the scope and persists it under the owner run.
- `merchant_execute` is dispatched exclusively to `merchant-manager`.
- Merchant Manager sends one `MERCHANT_EXECUTE_REQUEST_JSON:` request to `team-lead`.
- Trusted orchestration records execution evidence, then executes the persisted scope once.
- The agent must never invoke the runtime handoff directly.

Runtime (production) Direct EXECUTE is disabled in code (`RUNTIME_DIRECT_EXECUTE_ENABLED =
False` in `merchant_direct_handoff.py`) until separately approved: a runtime-scoped request is
refused before any reservation or spend. To validate the real path, the user may type
`--merchant-target test` immediately before `--merchant-scope`:

`/solve --confirm --merchant-target test --merchant-scope ["merchant","create","--code","<CODE>","--name","<NAME>"] Create test merchant <CODE>`

Test mode runs only `merchant create`, connects only to `coding_agent_merchant_test` as
`merchant_test` after a read-only identity preflight, and binds the target into the scope hash,
confirmation hash, staged request, reservation, spent authority and receipt. No teammate message,
CLI argument, environment variable or payload can select or change it.
- `merchant_propose`, `merchant_apply`, and `--merchant-confirmation` are removed and rejected.
- A `merchant_execute` run without a scope can read and check completeness only; it ends with
  `REQUIRES_CLARIFICATION` or `BLOCKED`. Never infer runtime-write permission from natural
  language alone.

## Trusted intent envelope

!`${CLAUDE_PROJECT_DIR}/.venv/Scripts/python.exe ${CLAUDE_PROJECT_DIR}/.claude/hooks/intent_envelope_bridge.py`

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
   - Treat a leading `--confirm` followed by whitespace as a command option, not request content.
   - Compare `raw_request` with the request text after removing only that leading option and trimming surrounding whitespace.
   - Otherwise, compare against `$ARGUMENTS` after trimming surrounding whitespace.
   - Require `confirmed: true` in the persisted envelope when `--confirm` is supplied.
   - Keep exact request matching, expiry, session, and unspent-envelope checks.
   - A Merchant runtime write additionally requires an exact validated `--merchant-scope`.
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

For a Merchant write, `--confirm` authorizes the run, and only an exact validated
`--merchant-scope` authorizes the runtime write. The scope is persisted under the owner run and
bound to the policy-accepted dispatch. `--merchant-confirmation` is not supported; a prompt that
carries it stops before team creation.

## 4. Required Agent Team mode

This command requires all of the following runtime conditions:

- Claude Code is running interactively, not with `-p` or `--print`;
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is enabled;
- `teammateMode` is `tmux` (configured in settings.json).

These are prerequisites, not work for `/solve`. Do not install software or edit settings during
the run.

Do not use the absence of a separately exposed `TeamCreate` tool as proof that Agent Teams are
unavailable. Claude Code versions differ: in this project runtime, teammates are created through
the team-aware mode of the `Agent` tool. Test the authorized team-aware dispatch itself.

If that dispatch rejects the required teammate fields or creates an ordinary subagent, respond:

`Agent Team backend unavailable — no teammates were dispatched.`

Then stop. Never fall back to an ordinary subagent.

## 5. Hard dispatch contract

Create exactly one session-scoped Agent Team for this run through the runtime's **team-aware
`Agent` path**. In Claude Code v2.1.178 and later, the first named teammate forms the
session-scoped team automatically. The runtime derives the team identity from the session;
`team_name` is accepted but ignored, and separate `TeamCreate` and `TeamDelete` tools no longer
exist.

Do not invent or depend on a custom `team_name`. Use the current session's automatically managed
team and distinguish teammates by their stable `name` values.

Route every id in `selected_agents` from `TEAM_STATE_SNAPSHOT_JSON` before
calling a dispatch tool:

1. If `exists` is false, invoke `Agent` in Agent Team teammate mode, set
   `subagent_type` to the exact selected agent id, and set `name` to that same
   canonical id.
2. If its status is exactly `IDLE_REUSABLE`, do not call `Agent`. Send the
   complete new assignment directly to that exact canonical teammate with
   `SendMessage`.
3. If its status is `CREATED`, `DISPATCHED`, `RUNNING`, `REPORT_RECEIVED`,
   `ACKNOWLEDGED`, `FAILED`, or unknown, stop and report the conflict. A report
   can arrive just before the prior task becomes idle, so only
   `IDLE_REUSABLE` is safe. Do not create a replacement or suffixed name.
4. In either create or reuse path, supply the same complete bounded assignment,
   including the result-delivery contract in section 8.
5. Give it one bounded task through the shared team task list when task tools
   are exposed.

For a teammate that does not yet exist, the direct semantic instruction is:

> Spawn one named Agent Team teammate for each `selected_agents` entry, using the corresponding
> project agent type and a stable canonical teammate name. Use the current session-scoped Agent
> Team. Do not use an ordinary subagent.

For an existing reusable teammate, the direct semantic instruction is:

> Send the new bounded assignment to the existing canonical teammate with
> `SendMessage`. Do not invoke `Agent`, create another pane, or add a suffix.
>
> Treat the assignment as a fresh work unit. Re-read every primary input file
> owned by the new task before making findings or changes. Prior-run file
> contents, observations, cached context, and conclusions are not authoritative
> for the new task unless the assignment explicitly says to reuse them.

Whether the assignment goes to a newly created teammate or an existing
`IDLE_REUSABLE` teammate, the same result-delivery contract applies. After
successful completion, keep the existing teammate reusable, receiving its next task through `SendMessage`
rather than creating a replacement teammate.

The following are forbidden:

- calling `Agent` without a teammate `name` or without Agent Team teammate mode;
- treating a caller-supplied `team_name` as proof of team membership;
- calling `Agent` in ordinary foreground, background, or fork mode;
- ordinary foreground or background subagents;
- forked subagents;
- `isolation: "worktree"`;
- ordinary subagent fallback;
- omitting or substituting a selected agent;
- creating an agent not listed in `selected_agents`;
- creating extra instances unless the envelope explicitly authorizes them;
- creating suffixed teammate names (reviewer-2, reviewer-3, etc.);
- creating or editing project-level team configuration files;
- manually editing Claude Code team, task, mailbox, or state files.

After the first teammate is created, verify that it has the requested canonical teammate name
and is registered as a teammate of the current session-scoped team. If any condition fails,
stop immediately, report the backend failure, and do not dispatch the remaining roster.

Claude Code supports one Agent Team per session. If an earlier teammate from the same session is
still active and conflicts with this run, do not reuse or destroy it automatically. Report the
conflict and stop so the earlier work can be resolved safely first.

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
| `merchant-manager` | Merchant/project reads and Direct EXECUTE of the exact user-authorized scope | Runtime writes only through the trusted in-process handoff; ordinary CLI is read-only for runtime |
| `scheduler` | Creating a confirmed calendar event | Calendar only |

Never invent an unregistered teammate type.

### Merchant routing contract

Merchant operational work has one owner: `merchant-manager`. Apply all of these rules in
addition to the envelope gate and normal dispatch contract:

- A Merchant-state read may be assigned only to `merchant-manager`, and only when
  `merchant-manager` appears in `selected_agents`.
- A Merchant write (`merchant_execute`) may be assigned only to `merchant-manager`, and only
  when the envelope authorizes that teammate. Without a `--merchant-scope` the assignment must
  say that no runtime write is possible.
- Do not route Merchant operations to `coder`, `bug-fixer`, `diagnostician`, another business
  teammate, or the lead session. Those roles may work on Merchant source code when separately
  selected for a development task, but they may not execute operational Merchant CLI commands.
- The lead must never run the Merchant CLI on a teammate's behalf or move an unauthorized
  Merchant operation into its own pane.
- If a Merchant operation is requested but `merchant-manager` is absent from
  `selected_agents`, report the authorization mismatch and stop. Do not add the teammate,
  substitute another role, reconstruct the envelope, or execute the command in the lead.
- A scoped `merchant_execute` may be dispatched once only when the saved operation is exactly
  `merchant_execute`, the roster is exactly `merchant-manager`, the risk is `external_write`
  or `destructive`, and the run is confirmed. The policy gate records the dispatch receipt.
- Dispatch authorization is not runtime authority. Only the trusted in-process handoff spends
  the one-use scope authorization.
- A `MERCHANT_DISPATCH_AUTHORIZATION_JSON` block or proposal confirmation carries no authority;
  the policy gate rejects any assignment that contains one.

### Merchant dispatch command authority

The team lead authorizes the Merchant operation but does not author Merchant CLI syntax.

When dispatching `merchant-manager`:

- preserve the user's semantic objective and raw request;
- preserve `operation: merchant_execute` (or `merchant_read`) and the persisted scope's
  `database_target` (`runtime`, or `test` only when the user typed `--merchant-target test`);
- for a scoped run, quote the exact persisted `merchant_scope.argv` unchanged; it is the only
  write the teammate may request;
- for an unscoped run, do not invent, reconstruct, translate, or guess a concrete Merchant CLI
  command, flag, alias, or argument. The policy gate rejects an unscoped assignment that
  contains a direct `agent_cli.py` reference or command-shaped Merchant text with CLI flags;
- do not instruct the teammate to execute a write before deterministic completeness.

The `merchant-manager` owns normalization against its registered Merchant write families and
runs the deterministic completeness gate before any execute request or write-field
clarification. If the semantic action itself is unclear, preserve that ambiguity; the teammate
uses its `action_semantics` clarification path.

### Direct EXECUTE runtime handoff

The registered PostToolUse hook executes the runtime handoff. The teammate sends exactly one
non-terminal `SendMessage` to `team-lead`:

```text
MERCHANT_EXECUTE_REQUEST_JSON:
{"contract_version":1,"operation":"merchant_execute","database_target":"runtime","arguments":["<exact scope token 1>","<exact scope token 2>"]}
```

Its `database_target` must equal the persisted scope's target; a mismatch is rejected before
anything is spent.

The request carries no authority. The hook re-derives the command and binding from the persisted
scope, binds the executing pane on first use, persists execution evidence in team state, spends
the one-use authorization, and executes at most once:

- `merchant create` runs through a durable reservation and the protected reserved executor;
- every other write runs through one in-process `RuntimeApplyAuthorization`.

Changed arguments spend the authorization without writing. A failed or uncertain attempt is never
retried. The lead never executes the handoff, the Merchant CLI, or a fallback mutation.

### Merchant terminal result contract

For every `merchant_execute` assignment the teammate's final `SendMessage` contains exactly one
`TEAM_RESULT_JSON` block with `operation: merchant_execute`, the scope's `database_target`
(`runtime` unless the user selected `test`), and `proposal_emitted: false`. Allowed outcomes are `EXECUTE_SUCCESS`, `EXECUTE_FAILED`,
`REQUIRES_CLARIFICATION`, `BLOCKED`, and `FAILED`.

The report describes the outcome; it is never execution authority. `TeammateIdle` releases the
teammate only on trusted evidence:

- committed PostgreSQL evidence for every reserved Create write, recorded as a completion
  receipt;
- a SUCCEEDED scoped execution record for other writes;
- or, for a task with no write footprint, a run/task-bound no-write marker. A completeness-driven
  `REQUIRES_CLARIFICATION` must match the exact CLI completeness evidence.

A spent execution that did not succeed ends the task as FAILED and keeps its evidence. An invalid
terminal result gets one correction turn, then the task fails. A stale task carrying a removed
operation is terminated as FAILED without a write.

If any required field is missing, do not improvise it. Stop the
Merchant dispatch and obtain the missing information through the deterministic Merchant completeness path.

Every Merchant assignment must explicitly declare all of these fields in its prompt:

- `database_target: runtime` (or `database_target: test` only when the user typed
  `--merchant-target test`; always the persisted scope's target);
- `operation: merchant_read` or `operation: merchant_execute`;
- the semantic Merchant objective and the identifiers or filters actually supplied by the
  request;
- for `merchant_execute`, that the teammate owns normalized command resolution and
  deterministic completeness, and whether a user-authorized scope exists;
- that database and credential arguments are forbidden;
- that runtime writes happen only through the trusted Direct EXECUTE handoff;
- that `TaskUpdate` is a status signal only and final result delivery requires `SendMessage`.

For an unscoped `merchant_execute`, do not require the lead assignment to contain an "exact
allowlisted write command". The exact command is resolved by `merchant-manager` from the
registered contract.

If any required dispatch field conflicts with the envelope, do not improvise it. Stop the
Merchant dispatch and report the incomplete assignment contract.

For the Merchant report ledger, accept delivery only when `SendMessage` from the named
`merchant-manager` teammate carries the operation, runtime target, CLI-backed
outcome, failures, and unresolved work. `TaskUpdate`, pane text, and idle notifications do not
establish Merchant result delivery.

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

## 8. Plan, assign, and require result delivery

The lead coordinates; it does not perform specialist implementation itself.

Before dispatch, describe in two or three concise lines:

- what each selected teammate will own;
- which tasks can run concurrently;
- which dependencies require sequencing.

Every teammate assignment must include:

- exact objective;
- relevant request context;
- owned files or domain;
- for every primary input file owned by the task, an instruction to read the
  current file during this assignment rather than relying on prior-run context;
- whether writing is permitted;
- expected output;
- task dependencies;
- remaining relevant limits;
- instruction to report failures accurately;
- the mandatory result-delivery instruction below;
- for `merchant_execute`, the Merchant terminal result contract from section 6.

Teammates load project context, including `CLAUDE.md`, but do not inherit the lead's conversation
history. Put all necessary task-specific context in the assignment.

### Mandatory teammate result-delivery contract

Every teammate assignment must end with this semantic instruction:

> When your task finishes, return a complete final answer.
>
> **Result delivery:** Send your complete report exactly once through
> `SendMessage` to `team-lead`. This is the only machine-verifiable delivery
> path and the only path that satisfies the result ledger.
>
> After `SendMessage` succeeds, your natural final answer must contain only
> `RESULT_DELIVERED` (optionally followed by the task ID). Do not repeat the
> full report in the final answer because the Agent Team UI displays it again.
>
> Before a timeout, mark your task completed with `TaskUpdate` if a task exists.
> Ensure your complete report reaches the lead through `SendMessage` before
> becoming idle.
>
> Include in your result: all findings, changed files, verification or test results, failures,
> and unresolved work. Do not rely on pane text or status updates alone: the complete report
> must be delivered through `SendMessage`.
>
> A task status update (`TaskUpdate`), pane output, final-answer notification,
> or idle notification is not a ledger result. If delivery is missing, the
> `TeammateIdle` hook keeps you active and asks you to send the existing report.

Once `SendMessage` has been recorded and validated as terminal for the task, the lead must not
request the report again. Do not resend or redo work after terminal delivery has been accepted.

The lead must not acknowledge the completed result back through `SendMessage`.

For the Merchant report ledger, accept delivery only when `SendMessage` carries the complete Merchant result. `TaskUpdate`, pane
text, and idle notifications do not establish Merchant result delivery.

For `merchant_execute`, transport delivery and terminal-result validity are separate:

- a `SendMessage` may be staged before terminal validation;
- it must not be treated as accepted Merchant completion merely because transport succeeded;
- trusted execution and completeness evidence is validated at lifecycle reconciliation;
- a premature Merchant message must not cause the teammate's remaining tools to freeze;
- only a valid terminal Merchant result may transition the lifecycle to reusable completion.

## 9. Coordinate safely and collect reports

Create independent teammates in the same dispatch round so their panes run concurrently. Use
task dependencies when the work is genuinely sequential, such as:

- diagnose before fixing;
- implement before reviewing;
- retrieve data before analysis.

Never let writing teammates edit overlapping paths concurrently. Give `coder` and `bug-fixer`
explicit disjoint ownership, or sequence their tasks. Two writing teammates must not edit the
same file in the same round.

**Idempotent result ledger:** Maintain a report ledger keyed by `run_id + task_id + agent_name`.
Accept a teammate's result as delivered only after a successful explicit
`SendMessage` to `team-lead` with a non-empty complete report in the body.

`TaskUpdate`, pane output, automatic final-answer notifications, and
`TeammateIdle` are coordination or UI signals only. They do not contain a
hook-verifiable complete report and must not set `result_received`.

Repeated `SendMessage` events for the same task are idempotent. Process the
result once and keep one `sendmessage` delivery source in the ledger.

For Merchant work, "transport received" and "terminal result accepted" are not
interchangeable. The exact Merchant terminal contract is validated against trusted execution and
completeness evidence before reusable completion.

**Recovery behavior:** If a teammate becomes idle before a complete
`SendMessage` report is recorded, the `TeammateIdle` hook exits with code 2,
keeps that same teammate active, and sends this bounded feedback to it:

> Your result was not delivered to the lead. Send your complete existing report now through
> `SendMessage` to `team-lead`; do not redo the task.

If a Merchant terminal report was transported but is invalid or incomplete, use only the
bounded terminal-result correction path. Do not redo the Merchant operation. The same teammate
may correct its machine-readable result once when the lifecycle hook permits it.

The ledger records that recovery was initiated. The lead must not issue a
second manual request, create a replacement, repeat the work, or synthesize a
result. A repeated idle attempt remains blocked until the same teammate sends
the existing report or reports an explicit delivery failure. All recovery
coordination remains subject to the envelope's remaining tool-call budget.

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

After every required `SendMessage` report is collected and terminally accepted, or a delivery
failure is established:

1. `IDLE_REUSABLE` means the teammate pane must remain alive after successful completion and
   remain available for reuse by a later controlled run.
2. Do not request shutdown, call `TaskStop`, kill the teammate pane, or create a replacement
   after the teammate has reached `IDLE_REUSABLE`.
3. Wait until every successfully completed teammate has reached `IDLE_REUSABLE`, or an explicit
   lifecycle failure has been established.
4. Do not search for or require `TeamDelete` or a separately named cleanup action. Current
   Claude Code versions clean up the session-scoped team automatically when the session ends.
5. Never edit team directories, mailbox files, pane state, or task state manually.

Session-scoped teammate cleanup belongs to `SessionEnd`, not `/solve`.

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
