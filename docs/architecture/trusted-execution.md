# Trusted Merchant Execution

How a Merchant write is authorized, executed exactly once, and proven from PostgreSQL. This is
the detailed contract behind the short rules in [`CLAUDE.md`](../../CLAUDE.md). The business
operations themselves are in [project lifecycle](../merchant/project-lifecycle.md).

## 1. One writer, one surface

- `merchant-manager` is the only owner of operational Merchant requests. Its only executable
  surface is one literal, direct invocation of
  `python .claude/agents/tools/merchant/agent_cli.py <resource> <action> [arguments]` or
  `.claude/rag_search.py` (no interpreter flags, environment assignments, chaining,
  redirection or substitution). Every other shell, file-writing or code-execution tool is
  denied by `policy_gate.py`.
- This is defense in depth, not a sandbox: any same-user process that can run arbitrary Python
  can still reach the runtime credentials, so other teammates with `Bash` remain trusted.
- The adapter fixes the database target to `runtime` and exposes no database-selection,
  connection or credential argument. The exceptions are read-only test-database reads:
  `project preview|status|evidence --test-database`, `evidence preview --test-database` and
  `step preview --test-database`.
- For runtime the adapter is read-only: it accepts the allowlisted reads and
  `completeness check`, and rejects every write mode including `--propose`, `--apply` and
  `--execute`.
- PostgreSQL is authoritative for current state. RAG may supplement history but can never
  authorize a command or replace current CLI state.

## 2. Authority: Direct EXECUTE only

`merchant_propose`, `merchant_apply` and `--merchant-confirmation` are removed and rejected.
A boolean, CLI flag, environment variable, task assignment, teammate message or
`TEAM_RESULT_JSON` can never grant write authority. The only sources are:

| Source | Produces | Store |
|---|---|---|
| User types `/solve --confirm --merchant-scope [...]` (`--merchant-target test` for the test DB) | an exact scope (`merchant create`, a basis-bound `project create`, activation) | — |
| `/solve Xác nhận tạo [<id>]` | Project create scope from one verified `project preview` | `<owner>.pending_*` (Project) |
| `/solve Xác nhận cập nhật [<step id>]` | Step Update scope from one READY `step preview` | `.pending_step.json` |
| `/solve Xác nhận ghi nhận` | Purchase Request scope from one valid `evidence preview` | `.pending_purchase_request.json` |
| `/solve Xác nhận thực hiện <code>` | lifecycle scope (revision, decision, signing, PO, Payment Request, Project start/completion) | `.pending_lifecycle.json` |

Pending records are created only by the trusted PostToolUse capture of a verified CLI preview
(`merchant_preview_delivery.py`), are owned by the session, expire after 15 minutes and are
single use (`merchant_pending_confirmation.py`). No model classifies a confirmation, and a
scheduled prompt (`CronCreate`, `ScheduleWakeup`, `RemoteTrigger`) can never carry one.
Typed scopes are refused for Step Update, Purchase Request and the lifecycle commands
(`intent_gate.py`). A typed `project create` scope must carry the `--project-id` and
`--expected-basis` of a `project preview`; the preview is recomputed in the preflight and again
inside the write transaction, and any change refuses it. The preview itself grants nothing.

The preview's `requested_operation` reaches the lead only as the exact CLI-captured object
after `MERCHANT_PREVIEW_OPERATION_JSON:`; the lead shows its `confirmation_command` verbatim.
A previewed `project create` carries `--merchant-code` and an explicit procurement flag in one
canonical argv order.

## 3. Execution pipeline

1. The `merchant-manager` teammate sends one `MERCHANT_EXECUTE_REQUEST_JSON:` request from the
   tmux/psmux pane the harness recorded for it (`TMUX_PANE` equals `members[].tmuxPaneId`, that
   pane's process is an ancestor of the hook process, and its server is the nearest server
   ancestor of the lead). Self-declared `agent_type` / `session_id` never bind a pane.
2. The trusted hook stages the request with trusted completeness evidence (blank required
   values are rejected) and persists a team-state reservation bound to owner, teammate, run,
   task, command, payload and execution attempt. A request whose arguments differ from the
   scope is rejected at staging without spending anything.
3. A read-only **preflight** verifies the target database (`coding_agent_merchant_test` /
   `merchant_test` for test), the confirmed record for this run with identical argv, the
   trusted operator, the schema version, and re-judges the operation against current state
   (`verify_step_update`, `purchase_request.verify_purchase_request`,
   `lifecycle_operation.verify`, project preview recompute). A refused preflight spends nothing.
4. Authority is spent only at `reserve_direct_scope_authorization`, which refuses without the
   reservation.
5. The write:
   - `merchant create` runs through a durable reservation and the protected reserved
     executor, and completes only after committed PostgreSQL evidence is verified;
   - every other write runs through
     `claude.system.merchant_runtime_handoff.invoke_authorized_scope_apply`, which passes an
     opaque expiring `RuntimeApplyAuthorization` only through the Python call chain and
     re-checks the reservation immediately before the mutation;
   - claim, ledger row, mutation and event commit in **one transaction**, and the operation is
     re-judged under the repository locks (lock order Project → revision → approval →
     procurement).
6. Outcome is read from durable evidence: FAILED only when fenced (a committed REVOKED claim
   makes a late commit impossible), SUCCEEDED only with its own committed evidence, otherwise
   UNCERTAIN — never inferred to have rolled back.
7. A receipt is reconciled from PostgreSQL (ledger, claim, event and entity row sharing one
   `xmin`): `merchant_step_update_receipt`, `merchant_purchase_request_receipt`,
   `merchant_lifecycle_receipt`, or the verified Create receipt. Recovery functions
   (`recover_step_update_receipts`, `recover_lifecycle_receipt`) rebuild them from the database
   alone.

Once spent, the single attempt is never restored: success, a mismatch at the spend point,
failure, expiry or an uncertain interruption all consume it. Retry requires a fresh preview,
confirmation, envelope and dispatch.

## 4. Result delivery

- Results reach the lead only through the teammate's final `SendMessage`. A `TaskUpdate`, pane
  text or idle notification does not prove delivery.
- The teammate's `TEAM_RESULT_JSON` must agree with the durable evidence and the scope's
  `database_target`, or it is denied before it reaches the lead.
- A teammate is released only on trusted evidence: verified Create receipts, a SUCCEEDED
  scoped execution, or a no-write marker for a task with no write footprint and no spent
  authority. Every other spent task ends FAILED with its evidence kept and cannot be reused.

## 5. Database isolation and attribution

- Runtime Direct EXECUTE is disabled in code: `RUNTIME_DIRECT_EXECUTE_ENABLED = False` in
  `.claude/hooks/merchant_direct_handoff.py`. A runtime-target confirmation is refused unspent.
- An unscoped Merchant run's database target is derived by the intent gate from the user's own
  words (`merchant_database_target` in the envelope). Every `agent_cli.py` read must hit it and
  the lead's assignment may not declare another.
- The target is bound into the scope and confirmation hashes, staged request, reservation,
  spent authority and receipt.
- The recording operator comes from `MERCHANT_OPERATOR_ID` in local configuration
  (`operator_identity.py`). It is attribution, never approver authorization (DEC-A0).

## 6. Agent Team backend enforcement

The `PostToolUse(Agent)` hook `teammate_backend_gate.py` accepts a teammate only if the harness
team config records `backendType: tmux` and a `tmuxPaneId` for it, and the process table shows
that pane as the teammate's own pane under the lead's nearest psmux server, for a dispatch
already bound to the current run. Otherwise the task ends FAILED. Reuse through `SendMessage`
re-checks that the same pane process still holds that pane id. A `TaskStop` result labelled
`in_process_teammate` is the harness task-registry type of every teammate, not the backend.

Each teammate's definition file is fingerprinted (`definition_sha256`) at allocation; editing an
agent definition marks running teammates stale, so start a fresh session afterwards.
