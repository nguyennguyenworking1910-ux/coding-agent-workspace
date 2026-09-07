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

For `merchant_apply`, the general `--confirm` flag is never sufficient. The intent hook must
validate the exact `--merchant-confirmation` token emitted by the prior proposal and inject a
`merchant_confirmation` object containing the command, runtime target, expected version,
payload hash, proposal hash, and confirmation hash. The token itself and raw proposal payload
must not appear in the envelope or persisted run state. A missing, malformed, changed,
non-runtime, or non-canonical token stops the run before team creation.

The structured confirmation records exactly what the user approved, but it does not by itself
grant the Merchant CLI runtime-write authority. Gate 7.3 permits one policy-validated
`merchant-manager` dispatch only when its redacted authorization block matches that confirmation
exactly. Runtime `--apply` remains unavailable in Checkpoint 6, and Gate 7.3 does not weaken
that inherited boundary: runtime `--apply` remains fail-closed until the trusted in-process
handoff in Gate 7.4.

Runtime `--apply` remains fail-closed throughout Gate 7.3.

The Checkpoint 7 intent/policy authorization handoff is therefore split across two boundaries:
Gate 7.3 authorizes the exact teammate dispatch, while Gate 7.4 must authorize the exact
in-process runtime mutation.

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
`Agent` path**. In Claude Code v2.1.178 and later, the first named teammate forms the
session-scoped team automatically. The runtime derives the team identity from the session;
`team_name` is accepted but ignored, and separate `TeamCreate` and `TeamDelete` tools no longer
exist.

Do not invent or depend on a custom `team_name`. Use the current session's automatically managed
team and distinguish teammates by their stable `name` values.

For every id in `selected_agents`:

1. Invoke `Agent` in Agent Team teammate mode.
2. Set `subagent_type` to the exact selected agent id.
3. Set a stable unique teammate `name`, normally the agent id; add a deterministic suffix only
   when required for uniqueness.
4. Supply a complete bounded assignment as the teammate prompt, including the mandatory
   result-delivery contract in section 8.
5. Ensure the result is an independent Agent Team teammate in its own visible tmux/psmux pane.
6. Give it one bounded task through the shared team task list when task tools are exposed.

The direct semantic instruction is:

> Spawn one named Agent Team teammate for each `selected_agents` entry, using the corresponding
> project agent type and a stable teammate name. Use the current session-scoped Agent Team.
> Every teammate must run in a separate tmux/psmux pane. Do not use an ordinary subagent.

The following are forbidden:

- calling `Agent` without a teammate `name` or without Agent Team teammate mode;
- treating a caller-supplied `team_name` as proof of team membership;
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

After the first teammate is created, verify that it has the requested teammate name, is
registered as a teammate of the current session-scoped team, and appears in a separate pane.
If any condition fails, stop immediately, report the backend failure, and do not dispatch the
remaining roster.

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
| `merchant-manager` | Merchant/project reads, redacted proposals, and confirmed-apply handoff through the Merchant CLI | Proposal only; runtime apply blocked through the ordinary CLI; Gate 7.4 in-process handoff only |
| `scheduler` | Creating a confirmed calendar event | Calendar only |

Never invent an unregistered teammate type.

### Merchant routing contract

Merchant operational work has one owner: `merchant-manager`. Apply all of these rules in
addition to the envelope gate and normal dispatch contract:

- A Merchant-state read may be assigned only to `merchant-manager`, and only when
  `merchant-manager` appears in `selected_agents`.
- A Merchant write-intent proposal may be assigned only to `merchant-manager`, and only when
  the envelope authorizes that teammate. The assignment must say that the requested outcome is
  a redacted `--propose` result and that no change may be applied.
- Do not route Merchant operations to `coder`, `bug-fixer`, `diagnostician`, another business
  teammate, or the lead session. Those roles may work on Merchant source code when separately
  selected for a development task, but they may not execute operational Merchant CLI commands.
- The lead must never run the Merchant CLI on a teammate's behalf or move an unauthorized
  Merchant operation into its own pane.
- If a Merchant operation is requested but `merchant-manager` is absent from
  `selected_agents`, report the authorization mismatch and stop. Do not add the teammate,
  substitute another role, reconstruct the envelope, or execute the command in the lead.
- A confirmed Merchant apply may be dispatched once only when the saved operation is exactly
  `merchant_apply`, the roster is exactly `merchant-manager`, the risk is `external_write` or
  `destructive`, and the assignment contains the exact redacted block defined below.
- Gate 7.3 dispatch authorization is not Merchant CLI runtime authority. The assignment must
  state that runtime `--apply` remains unavailable until Gate 7.4 and must not ask the teammate
  to bypass the adapter.
- Preserve the earlier safety boundary in every assignment: runtime `--apply` is outside Checkpoint 6 authority.
  Gate 7.3 authorizes only the redacted teammate dispatch, not the database mutation.
- The proposal hash binds a command, runtime target, and payload. It is not permission, a
  credential, or a substitute for confirmation.

For a confirmed apply assignment, include exactly one block in this form, copying every value
from the injected `merchant_confirmation` object without reconstructing or changing it:

````text
MERCHANT_DISPATCH_AUTHORIZATION_JSON
```json
{
  "contract_version": 1,
  "confirmation_version": 1,
  "operation": "merchant_apply",
  "command": "<confirmed allowlisted command>",
  "database_target": "runtime",
  "expected_version": null,
  "payload_hash": "<confirmed hash>",
  "proposal_hash": "<confirmed hash>",
  "confirmation_hash": "<confirmed hash>",
  "authorized_mode": "CONFIRMED_APPLY_PENDING_RUNTIME_AUTHORITY"
}
```
````

The outer `text` fence above is documentation only; the actual assignment contains the marker,
the single `json` fence, and the JSON object. Never include the confirmation token or raw
proposal payload in this block. The policy hook compares every field immediately before Agent
dispatch, rejects missing, extra, malformed, stale, or changed data, and consumes the binding
after one accepted dispatch attempt. Copy the exact confirmed positive integer into
`expected_version` when present; retain JSON `null` only when the confirmation carries `null`.

### Gate 7.4 runtime handoff

After Gate 7.3 accepts the dispatch, controlled orchestration may call
`claude.system.merchant_runtime_handoff.invoke_confirmed_merchant_apply` in the same Python
process with the persisted run-state object and the exact allowlisted apply arguments. This is
the only runtime-write path. It verifies the accepted dispatch receipt, issues an opaque
capability with a 60-second default and 300-second hard maximum lifetime, and consumes both the
run-state issuance slot and capability before the repository handler runs.

The capability is bound to the exact command, `runtime` target, payload, expected version,
proposal hash, and confirmation hash. A mismatched, expired, failed, concurrent, or successful
attempt spends it. Never retry an uncertain result; generate a fresh proposal, confirmation,
envelope, and dispatch instead.

The ordinary `agent_cli.py` command remains read/propose-only. A boolean such as the legacy
`runtime_authorized=True`, a CLI flag, environment variable, confirmation token, JSON object,
copied capability, or reconstructed run state is not runtime authority. If the installed
orchestration runtime cannot perform the in-process handoff, report that limitation and do not
fall back to shell apply, direct repository access, or another database target.

Gate 7.5 connects that handoff to the actual persisted hook state through
`invoke_confirmed_merchant_session_apply`. Controlled orchestration supplies the current session
ID and exact apply arguments; it does not copy state into a prompt or CLI option. The function
locks the session document, verifies the Gate 7.3 receipt, permanently reserves its single
runtime-authorization slot, and saves that reservation before capability issuance or repository
dispatch. This is deliberately at-most-once: after an uncertain interruption, failure, or
successful call, a fresh proposal and confirmation are required instead of a retry.

For an authorized Merchant assignment, require the teammate to use only the registered
credential-free Merchant CLI interface and to include the redacted CLI JSON, exit outcome,
confirmation state, failures, and unresolved work in its final `SendMessage` report.

Every Merchant assignment must explicitly declare all of these fields in its prompt:

- `database_target: runtime`;
- `authorized_mode: READ`, `authorized_mode: PROPOSE`, or, only for an exact confirmed apply,
  `authorized_mode: CONFIRMED_APPLY_PENDING_RUNTIME_AUTHORITY`;
- the exact allowlisted Merchant operation and the identifiers or filters supplied by the
  request;
- that database and credential arguments are forbidden;
- that runtime `--apply` is outside Checkpoint 6 authority and remains blocked until the Gate 7.4
  trusted in-process handoff;
- that `TaskUpdate` is a status signal only and final result delivery requires `SendMessage`.

If any required field is missing or conflicts with the envelope, do not improvise it. Stop the
Merchant dispatch and report the incomplete assignment contract.

For the Merchant report ledger, accept delivery only when `SendMessage` from the named
`merchant-manager` teammate carries the operation, runtime target, authorized mode, redacted
CLI JSON, exit outcome, confirmation state, failures, and unresolved work. `TaskUpdate`, pane
text, and idle notifications do not establish Merchant result delivery.

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
- whether writing is permitted;
- expected output;
- task dependencies;
- remaining relevant limits;
- instruction to report failures accurately;
- the mandatory result-delivery instruction below.

Teammates load project context, including `CLAUDE.md`, but do not inherit the lead's conversation
history. Put all necessary task-specific context in the assignment.

### Mandatory teammate result-delivery contract

Every teammate assignment must end with this semantic instruction:

> Before going idle, mark your shared task completed with `TaskUpdate` when a task exists. Your
> **FINAL ACTION** must be `SendMessage` to `team-lead` with your complete report. Include all
> findings, changed files, verification or test results, failures, and unresolved work in the
> message body. Do not rely on ordinary final text in your pane: it is not delivered to the
> lead. If `SendMessage` explicitly reports that nothing was sent, retry it once. If the retry
> fails, remain available and preserve the complete report in your pane.

The complete report must be carried in the `SendMessage` body, not only in its summary. A task
status change, pane output, or idle notification never substitutes for the report.

## 9. Coordinate safely and collect reports

Create independent teammates in the same dispatch round so their panes run concurrently. Use
task dependencies when the work is genuinely sequential, such as:

- diagnose before fixing;
- implement before reviewing;
- retrieve data before analysis.

Never let writing teammates edit overlapping paths concurrently. Give `coder` and `bug-fixer`
explicit disjoint ownership, or sequence their tasks. Two writing teammates must not edit the
same file in the same round.

Maintain a report ledger keyed by teammate name. Count a teammate's result as received only when
the lead receives that teammate's complete report through `SendMessage`. `TaskUpdate` status and
`idle_notification` are coordination signals only; neither contains or proves delivery of the
result.

If a teammate becomes idle before its report arrives, send exactly one bounded recovery message
to that teammate:

> Your result was not delivered to the lead. Send your complete existing report now through
> `SendMessage` to `team-lead`; do not redo the task.

After that one recovery message, wait for either the complete report or an explicit delivery
failure. Do not create a replacement, do not repeat the work in the lead, and do not synthesize
or shut down the teammate based only on an idle notification. All recovery coordination remains
subject to the envelope's remaining tool-call budget.

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

After every required `SendMessage` report is collected, or a delivery failure is established:

1. Request graceful shutdown of every teammate created by this run.
2. Wait until no teammate remains active.
3. Do not search for or require `TeamDelete` or a separately named cleanup action. Current
   Claude Code versions clean up the session-scoped team automatically when the session ends.
4. Never edit team directories, mailbox files, pane state, or task state manually.
5. If graceful shutdown fails, report it; never kill panes or the tmux/psmux session manually.

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
