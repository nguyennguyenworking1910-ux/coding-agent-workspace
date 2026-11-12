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

For a Project, the scope is the `requested_operation.argv` of a `project preview` (it carries
`--project-id` and `--expected-basis`); the preview is recomputed before any spend and inside
the write transaction, and a changed basis is refused:

`/solve --confirm --merchant-target test --merchant-scope [<preview argv>] Create the previewed Project`

**Conversational confirmation (CP12H.NL3).** A verified READY preview also leaves a trusted
pending record for this session (15 minutes, single use). The user may then type
`/solve Xác nhận tạo` (or `/solve Xác nhận tạo <first 8 characters of project_id>` when more
than one is pending; `/solve Hủy tạo [<id>]` cancels). The intent gate, not you, turns that
prompt into the same persisted `merchant_scope` as a typed scope, with a deterministic envelope
whose `raw_request` is the confirmation text and which carries `conversational_confirmation`.
Treat that run exactly like a typed scoped run. You never confirm, re-request or rebuild a
pending operation yourself, and a bare "Xác nhận tạo" without `/solve` is not a confirmation.
A verified READY `step preview` works the same way in its own store: `/solve Xác nhận cập nhật
[<first 8 characters of step_id>]` (cancel: `/solve Hủy cập nhật [<id>]`), test database only;
its envelope's `conversational_confirmation.kind` is `step_update`. A Project confirmation never
confirms a Step, nor the reverse. A verified, confirmable Purchase Request `evidence preview`
(CP12H.NL4D4A) has a third store: `/solve Xác nhận ghi nhận [<first 8 characters of
project_id>]` (cancel: `/solve Hủy ghi nhận [<id>]`), test database only, `kind`
`purchase_request`. The intent gate refuses it unspent when the trusted local recording
operator is missing or differs from the preview's. A verified, confirmable lifecycle operation
(CP12H.MASTER: metadata-only revision, approval decision, operator-attested signing, Purchase
Order, Payment Request, Project start or completion) has a fourth store: `/solve Xác nhận thực
hiện [<first 8 characters of operation_id>]` (cancel: `/solve Hủy thực hiện [<id>]`), test
database only, `kind` `lifecycle`; same operator rule. No kind ever confirms another.
An unscoped Project create request ("Tạo project mở rạp ...") runs as the read-only preview
without `--confirm`.

Test mode runs only:
- `merchant create`;
- `project create`;
- (CP12H.NL4C2A) a `step update` that the user confirmed with `/solve Xác nhận cập nhật` from a
  verified preview; a typed Step scope is refused;
- (CP12H.NL4D4A) the creation of one new Purchase Request (`procurement update`) that the user
  confirmed with `/solve Xác nhận ghi nhận` from a verified preview. A typed procurement scope is
  refused, so no general procurement update can run;
- (CP12H.MASTER) `document revision-create`, `document approve`, `document sign`, `project
  update` and a Purchase Order or Payment Request `procurement update`, each only as the
  lifecycle operation the user confirmed with `/solve Xác nhận thực hiện` from a verified
  preview (the preflight requires that pending record with the identical argv). A typed scope
  for them is refused.
It connects only to `coding_agent_merchant_test` as
`merchant_test` after a read-only identity preflight, and binds the target into the scope hash,
confirmation hash, staged request, reservation, spent authority and receipt. No teammate message,
CLI argument, environment variable or payload can select or change it.
- `merchant_propose`, `merchant_apply`, and `--merchant-confirmation` are removed and rejected.
- A `merchant_execute` run without a scope can read and check completeness only; it ends with
  `REQUIRES_CLARIFICATION` or `BLOCKED`. Never infer runtime-write permission from natural
  language alone.
- A natural-language Project request ("Tạo project mở rạp Beta Nguyễn Văn Cừ", "Preview a
  cinema opening project for Beta") is never a Merchant creation. Without a scope,
  `merchant-manager` answers it with the read-only `project preview`; pass the user's words
  through semantically. The preview's operation is data, not authority.

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
   - A Merchant runtime write additionally requires an exact validated `--merchant-scope`, or
     the gate-issued `merchant_scope` of a conversational confirmation (its `raw_request` is the
     confirmation text, e.g. `Xác nhận tạo.`).
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

After each spawn, a trusted hook verifies that the teammate runs in its own psmux pane of this
session. If it blocks the dispatch (for example an in-process teammate), the teammate's task has
ended FAILED: stop that teammate with `TaskStop`, report the failure, and do not dispatch a
replacement or use its result.

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
   `ACKNOWLEDGED`, `FAILED`, `STALE_DEFINITION`, or unknown, stop and report the
   conflict. `STALE_DEFINITION` is an idle teammate started before its
   `.claude/agents/` definition changed; it would run stale instructions, so the
   user needs a fresh Claude Code session. A report
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
- preserve `operation: merchant_execute` (or `merchant_read`) and declare
  `database_target: <the envelope's merchant_database_target>`. It is trusted: the scope's
  target, or for an unscoped run the intent gate's reading of the user's own words ("trên
  database test" → `test`). Never choose or change it yourself; the policy gate denies an
  assignment that declares another target, or an unscoped `test` run that omits it, and the
  teammate's reads are held to the same target;
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

### Project status delivery (CP12H.NL4A)

A Project status or list question ("Project … đến bước nào?", "Liệt kê các Project của …") is a
read-only run (`merchant_read`, no `--confirm`). `merchant-manager` answers it with
`project status --request "<user words>"`, and its report carries the CLI result once after
`MERCHANT_PROJECT_STATUS_JSON:`; the policy gate has checked that object against the CLI output
it captured. Build your summary only from that object:

- the Project's `project_id`, `title`, `status`, Merchant `code`, `project_type`,
  `workflow_variant` and `last_updated_at`, and `database_target`;
- `step_counts`; `current_steps` (actionable: READY or IN_PROGRESS); `waiting_steps` with their
  `unmet_predecessors`; `dependency_ready_steps` (unlocked but still PENDING); `completed_steps`
  and `skipped_steps` separately (SKIPPED is never COMPLETED); `approval_gates`; `evidence`;
- for `NEEDS_CLARIFICATION`, the question and any `candidates` (never choose one);
- for `PROJECT_LIST`, the Projects with their status.

Never add, infer or change a step state from the conversation. State what a step waits on only
from its own `unmet_predecessors`; steps sharing predecessors are parallel, never a range. A `STATUS_DELIVERY_FAILED` report
is not a status: report the failure only.

### Evidence and approval discovery delivery (CP12H.NL4D2)

A question about a Project's documents, approvals, procurement records or what a gate still
lacks is a read-only run (`merchant_read`, no `--confirm`). `merchant-manager` answers it with
`project evidence --request "<user words>"`; its report carries the CLI result once after
`MERCHANT_EVIDENCE_STATUS_JSON:`, checked by the policy gate against the captured CLI output.
Build your summary only from that object: the Project and Merchant, `focus_step` (when a step
was named, with its `gate` and `unmet_direct_dependencies`), `approvals` per role (`status`:
PRESENT, MISSING, INVALID or UNKNOWN, and `requirement`: REQUIRED or NOT_REQUIRED, with
`required_by`), `outdated_approvals` (on superseded revisions: they never approve the latest
revision), `documents`, `procurement`, `gates` and `missing`. Name only what those fields
contain; never infer a requirement. A gate with `NO_DATABASE_EVALUATOR` cannot be satisfied by
any stored evidence. Nothing was recorded or changed, and this discovery read offers no write:
never offer one, a confirmation, a scope or a command from it (a Purchase Request is recorded
only through the evidence write preview below). An `EVIDENCE_DELIVERY_FAILED` report is not a
result: report the failure only.

### Evidence write preview delivery (CP12H.NL4D3)

A request to record a document revision, a LEGAL, ACCOUNTING or PARTNER approval, or a Purchase
Request, Purchase Order or Payment Request reference runs without `--confirm` as a read-only
run (`merchant_read`). `merchant-manager` answers it with `evidence preview --request "<user
words>"`; its report carries the CLI result once after `MERCHANT_EVIDENCE_PREVIEW_JSON:`,
checked by the policy gate against the captured CLI output. Build your summary only from that
object: `operation_kind`, `evidence_type`, the resolved Project and Merchant, `requested_fields`,
`missing_required_fields`, `existing_evidence`, `domain_validation` (its `plan`, or its
`error`), `policy_notes` and `outcome` (PREVIEW_VALID, BLOCKED or NEEDS_CLARIFICATION).
Nothing was recorded or changed. PREVIEW_VALID is not an authorization.

**Purchase Request confirmation (CP12H.NL4D4A).** `confirmation_available: true` appears only on a
`PREVIEW_VALID` new Purchase Request on the test database, and it carries a `requested_operation`
with status NOT_AUTHORIZED. It means the user *may* confirm; it never means a write is
authorized.
- **What to tell the user.** Say they can confirm in this session within 15 minutes by typing
  `/solve Xác nhận ghi nhận <first 8 characters of requested_operation.project_id>` (or cancel
  with `/solve Hủy ghi nhận <same id>`). Name, from that block:
  - the reference;
  - the Project and its Merchant;
  - the test database;
  - the `recording_operator` status;
  - the `PROCUREMENT_NOT_REQUIRED` note when present (the Project does not require procurement;
    recording is still allowed and changes no step).
- **What the confirmation binds.** It binds exactly that Merchant, Project, reference, recording
  operator and test database. The operator comes only from trusted local configuration, never
  from the request, the teammate or you.
- **Who confirms.** Only the user's own prompt confirms. Never submit, schedule or relay it. Never
  offer a `--merchant-scope` or argv: a handwritten procurement scope is refused and is never
  authorization.
- **No confirmation.** When `confirmation_available` is false, relay `confirmation_blockers` and
  offer nothing.
- **How it runs.** A confirmed Purchase Request runs as an ordinary scoped `merchant_execute` run.
  The trusted Direct EXECUTE hook re-checks it and performs the write; the teammate only sends
  the persisted scope once.
- **No retry.** It gets one attempt: a refused, failed or uncertain result is reported, never
  retried. A new attempt needs a new preview and the user's new confirmation.

**Lifecycle confirmation (CP12H.MASTER, owner-approved DEC-SIMPLIFY).** The same
`evidence preview` covers a metadata-only revision, one APPROVED or REJECTED decision, operator-
attested signing, a Purchase Order or Payment Request, and starting or completing the Project.
`confirmation_available: true` (test database, trusted operator) comes with a
`requested_operation` (NOT_AUTHORIZED) whose `operation` names it.
- **What to tell the user.** They may confirm within 15 minutes by typing `/solve Xác nhận thực
  hiện <first 8 characters of requested_operation.operation_id>` (cancel: `/solve Hủy thực hiện
  <same id>`). Name the `summary`, the Project and Merchant, the test database, the
  `recording_operator` status and every `policy_notes` label: a metadata-only revision has no
  file or integrity evidence; a decision is recorded by the operator, the approver is not
  identified, and it is final for that revision; signing is operator-attested and verifies
  nothing about the signature; completing the last Step never completes the Project.
- **Who confirms, how it runs, no retry.** As for the Purchase Request above: only the user's own
  prompt; a scoped `merchant_execute` run the trusted hook re-checks; one attempt.

**Never offered.** Nothing is offered for a runtime target (Runtime Direct EXECUTE is disabled),
for a `BLOCKED` or `NEEDS_CLARIFICATION` preview, or when `confirmation_available` is false. An
`EVIDENCE_WRITE_PREVIEW_FAILED` report is not a result: report the failure only.

### Step Update preview delivery (CP12H.NL4B)

An unscoped request to update one Project step is a read-only run (`merchant_read`, no
`--confirm`). `merchant-manager` answers it with `step preview --request "<user words>"`; its
report carries the CLI result once after `MERCHANT_STEP_PREVIEW_JSON:`, checked by the policy
gate against the captured CLI output. Build your summary only from that object: `outcome`,
`project` (id, title, `version`), `step` (sequence, name, status, `version`), `transition`,
`unmet_dependencies` (scope in `unmet_dependency_scope`, normally direct predecessors) and
`unmet_transitive_dependencies` (all unfinished earlier steps, counted by
`unmet_transitive_count`), `gate`, `blocking`, `project_state`, and for `NEEDS_CLARIFICATION`
every question, the `missing` fields and `candidates`. Name only steps those lists contain;
never infer one from a count. Nothing was updated. `READY_FOR_CONFIRMATION` means the domain rules
would accept the update now; nothing was updated. `confirmation_available: true` (only on
a READY test-database preview) means the user may confirm; it never means a write is
authorized. When the verified block's
`requested_operation.database_target` is `test`, tell the user they can confirm in this
session within 15 minutes by typing `/solve Xác nhận cập nhật <first 8 characters of
requested_operation.step_id>` (or cancel with `/solve Hủy cập nhật <same id>`), naming the step,
its current and target status and the Project from that block. When the operation carries
`gate_attestation: OPERATOR_ATTESTED` (CP12H.MASTER: completing a gate Step with no stored-
evidence evaluator, such as "Complete UAT acceptance"), say plainly that the user attests the
gate and the system verifies nothing; completing the last Step never completes the Project
(that is its own `Hoàn tất Project ...` preview). Only the user's own prompt
confirms: never submit, schedule or relay it, never offer a `--merchant-scope` or argv (a typed
Step scope is refused), and offer nothing for a runtime target (runtime Direct EXECUTE is
disabled). A confirmed Step Update runs as an ordinary scoped `merchant_execute` run. A `STEP_UPDATE_DELIVERY_FAILED` report is not a preview:
report the failure only. An idle notice's `RESULT_DELIVERED` means only that a report was
sent; the outcome is what that report says, so a delivery failure or refusal is still a
failure.

### Project preview operation delivery

A `project preview` that is `READY_FOR_CONFIRMATION` reaches you inside the teammate's report
as one `MERCHANT_PREVIEW_OPERATION_JSON:` object. The policy gate has already checked it
against the CLI output it captured, so it is complete and exact. In the final answer:

- show `confirmation_command` verbatim in a code block, copied character for character
  (Unicode title included); never rebuild it from the argv or the prose;
- list `merchant_id`, `merchant_code`, `merchant_name`, `project_id`, `project_type`,
  `workflow_variant`, `title`, `requires_procurement`, `expected_basis` and `database_target`;
- when `merchant_confirmation_required` is true, state that the Merchant matched only as a
  CANDIDATE on `merchant_matched_text` and that typing the command confirms `merchant_code`
  (`merchant_name`) as the intended Merchant;
- state that the operation is `NOT_AUTHORIZED` preview data and that this run created nothing;
- tell the user they can confirm in this session within 15 minutes by typing
  `/solve Xác nhận tạo <first 8 characters of project_id>` (or cancel with
  `/solve Hủy tạo <same id>`); the `confirmation_command` remains an equivalent alternative.

If the report starts with `PREVIEW_DELIVERY_FAILED:` (the operation could not be verified
from the CLI output), the result is not actionable. Report that delivery failure and the
read-only findings, give no confirmation command, and never rebuild one from the findings.

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
`EXECUTE_UNCERTAIN`, `REQUIRES_CLARIFICATION`, `BLOCKED`, and `FAILED`.

The outcome comes from trusted execution evidence. A report that contradicts it (a committed
write reported as anything but `EXECUTE_SUCCESS`, an uncertain one as failed, success without
committed evidence, or a `database_target` other than the scope's) is denied before it reaches
the lead and rejected again at `TeammateIdle`. A delivered `EXECUTE_UNCERTAIN` means the write
may have committed; report it to the user as such and never as a rollback.

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
