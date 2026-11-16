# Agent Ecosystem — Unified Roadmap to Production

<!-- CURRENT_STATUS_START -->
## CURRENT STATUS & SESSION HANDOFF — 23 October 2026

**This section is the authoritative CURRENT state.** Historical baseline prose farther down was written on 22 October; where it conflicts, the dated status and verified Git/test evidence below prevail. No new checkpoint credit is awarded by editing this file.

- **Local repository:** `C:\Users\nguyen.nguyen30\Desktop\coding-agent-workspace`
- **Branch:** `feat/cp7-9-merchant-reliability`
- **Last verified commit:** `26d979c` — `fix(merchant): fail closed without direct scope`
- **Latest working-tree state:** One modified, **uncommitted** file: `.claude/agents/tools/merchant/cli.py` (CP12-B.1 runtime legacy-mode guard, 8 added lines); latest Git state was observed before this document update. Do **not** assume clean working tree or stage it implicitly.
- **User requirement:** No Claude Code. Work via ChatGPT-authored instructions and user-run local PowerShell/Python/pytest. Keep changes small, traceable, and easy to debug/handoff.

### Current production progress — separate verified work from provisional credit

| Stage | Roadmap weight | Stage acceptance | Credited contribution |
|---|---:|---|---:|
| CP7.9 Merchant Reliability | 12.00 pp | 70% accepted: A 40%, B 15%, E non-live regression 15%; C, D, F not finally accepted | **8.40 pp** |
| CP12 Direct Execution Authority | 17.00 pp | CP12-A (no trusted-scope fallback) **PASS + committed**; remaining CP12 gates incomplete | **0.34 pp provisional** (locally allocated 2% of CP12; not yet reconciled with official 12A–H subgate ledger) |
| CP13–CP18 | 71.00 pp | Not yet newly reconciled/accepted | 0.00 pp |
| **TOTAL** | **100.00 pp** | | **8.40 pp strict verified; 8.74 pp including provisional CP12-A credit** |

**Progress convention:** Until CP12-A's fractional credit is formally mapped to one of the official CP12 subgates, show both **strict 8.40%** and **working 8.74%**; do not silently describe 8.74% as audited official ledger. There has been no new acceptance from the CP12-B.1 failed regression.

### Evidence and completed checkpoints

| Item | Result / evidence | Acceptance |
|---|---|---|
| CP7.9A recovery | Verified crash/persistence, generation, bounded read-only committed-evidence recovery; included in `2709d29` | PASS (40% CP7.9) |
| CP7.9B diagnostics | Allowlisted best-effort lifecycle diagnostics; `2709d29`; focused `125 passed, 1 xfailed` | PASS (15% CP7.9) |
| CP7.9C error classification | Exception handler inventory and caller/recovery audit; existing fail-closed behavior, but classification acceptance review pending | PENDING (10%) |
| CP7.9D legacy state compatibility | 71 selected tests passed, state/receipt/generation/archive tests inspected; not yet exhaustive legacy-state acceptance | PENDING (15%) |
| CP7.9E non-live full suite | Most recent **clean** full suite at CP12-A: `3282 passed, 20 skipped, 1 xfailed, 97 subtests passed` (80.88 s); live DB tests intentionally skipped | PASS for non-live portion (15%) |
| CP7.9F final handoff | Recovery commit `2709d29`, roadmap commits `6daa5be` and `49195a3`; final CP7.9 gate handoff still pending | PENDING (5%) |
| CP12-A disable operational legacy fallback | `26d979c`; missing `merchant_scope` raises `SELECT_AUTHORIZATION`; direct-scope route still allowed; full suite `3282 passed` | PASS, committed |
| CP12-B baseline | 80 relevant tests passed on clean `26d979c` | PASS baseline only |
| **CP12-B.1 runtime legacy mode guard** | Added fail-closed check in `.claude/agents/tools/merchant/cli.py`, blocking runtime business-write `PROPOSE/APPLY` before constructing write handler | **PATCH PRESENT, TARGETED REGRESSION FAILED, NOT COMMITTED** |

### CURRENT BLOCKER — CP12-B.1 (resume here)

**Exact test failure** from the latest user-run targeted suite:

```text
tests/merchant/test_direct_execution_boundary.py::test_cli_main_runtime_proposal_is_not_blocked_by_write_guard
AssertionError: assert [] == ['runtime']
1 failed, 81 passed in 5.08s
```

The existing test expects runtime `--propose` to construct a `write_command_factory` (tracking `factory_calls == ['runtime']`). New CP12-B.1 architecture requires **deny before factory creation**, so `factory_calls == []` is the intended boundary. The CLI emits a bounded JSON error `MerchantCommandError` and does not invoke a handler. This is **an expected legacy-test mismatch to examine**, not proof of a new execution engine defect. Do not remove the runtime guard to satisfy the old test.

**Next implementation procedure (smallest safe batch):**

1. Inspect full body of `test_cli_main_runtime_proposal_is_not_blocked_by_write_guard` and nearby direct-execution boundary tests; confirm current expectations and error result assertions.
2. Update/rename **only** that test to require runtime `--propose` rejection *before factory construction* (`factory_calls == []`, nonzero exit/error, no handler mutation). Add/retain a matching runtime `--apply` rejection assertion if coverage is missing; avoid changing admin `bootstrap.py`/`migrate.py` `--apply` semantics.
3. Run targeted `test_direct_execution_boundary.py`, `test_direct_cli_execution.py`, `test_direct_agent_cli.py`, `test_merchant_cli.py`, `test_runtime_authorization.py`; inspect any remaining failures without weakening authorization.
4. Complete CP12-B.2: decide how to remove public Merchant business-write CLI `PROPOSE/APPLY` without altering database-admin CLIs or allowing generic runtime Merchant CREATE. Update affected tests together, not one-by-one; do not delete internal legacy helpers until caller/dependency audit confirms safety.
5. Run full non-live `pytest tests -q --tb=short -rs`, `git diff --check`, review exact staged files and commit. No live DB writes or automatic retries of uncertain commits.

**Critical nuance:** `merchant create` on `runtime` is intentionally blocked from generic CLI `EXECUTE` and instead requires durable reservation + `execute_reserved_merchant_create()` → protected PostgreSQL executor. Other approved runtime commands use exact one-use `RuntimeApplyAuthorization.consume_direct`. Removing proposal/apply must **not** create a bypass into either path.

### Known production architectural paths and boundaries

```text
PostToolUse → team_result_dispatcher.py → invoke_trusted_merchant_session_apply()
  → trusted merchant_scope present: invoke_authorized_scope_apply() → one-use authorization / EXECUTE
  → scope absent: SELECT_AUTHORIZATION fail-closed (CP12-A)

Direct Merchant CREATE: durable reservation/generation fence
  → execute_reserved_merchant_create() → execute_protected_merchant_create()
  → PostgreSQL claim/ledger/COMMIT → read-only evidence verification
  → completion receipt → report → idle archive

Merchant generic CLI: cli.py → dispatch_write_command() → write_commands.execute()
  → runtime authority check; runtime merchant create denied
  → CP12-B.1 now blocks runtime PROPOSE/APPLY at entrypoint (uncommitted)
```

**Safety invariants:** user/model/teammate text cannot mint trusted scope; keep exact entity binding, one-use authority, durable reservations, generation fencing, no replay if COMMIT uncertain, no unsafe background retries; reporting/diagnostics cannot claim authority. Historical proposal records may be read for audits but cannot authorize business writes. Do not globally remove `--apply` from database bootstrap/migration admin tools.

### Verified Git history and resume commands

```text
80322f0  CP7.8 baseline
2709d29  test(merchant): harden recovery and lifecycle diagnostics
6daa5be  docs: establish direct-execution production roadmap
49195a3  docs: sync CP7.9 verified progress
26d979c  fix(merchant): fail closed without direct scope
```

On new session, start in repository root:

```powershell
git branch --show-current
git log -1 --oneline
git status --short
git diff -- .claude/agents/tools/merchant/cli.py
.\.venv\Scripts\python.exe -m pytest .\tests\merchant\test_direct_execution_boundary.py -q --tb=short
```

**Session handoff instruction:** Read this dated CURRENT STATUS first, then the original roadmap sections for CP12–18 scope. Do not start with CP7.9A.3: already finished. Do not treat CP12-B.1 as committed. After next validated change, update this CURRENT STATUS and progress ledger with actual results and Git hash. No Claude Code.

<!-- CURRENT_STATUS_END -->


**Version:** 2.0 — Direct Execution First (22 October 2026)
**Scope:** `coding-agent-workspace` — CP7.9 + original CP12–CP18, from trusted Merchant lifecycle to secure internal multi-user production rollout, with **no proposal/confirmation/apply layer for authorized internal Merchant writes**.
**Current working branch reported:** `feat/cp7-9-merchant-reliability` (local); **last verified completed baseline:** CP7.8 at commit `80322f0`.
**Source-of-truth documents:** `AGENT_ECOSYSTEM_CHECKPOINT_12_TO_18_ROADMAP_2026-09-24.md` (original), `CP7_9_Merchant_Reliability_Roadmap.md` (new), CP7.8 test/commit logs.
**Document type:** planning and progress ledger; **not** authorization to mutate production databases, deploy services, or change security policy.

> **Progress philosophy:** 100% means **production rollout criteria satisfied**, not merely code written or tests passing. A completed earlier checkpoint can support later stages, but it must not be counted twice. Historic statements and currently validated evidence are tracked separately. **Proposal elimination is a fixed design requirement for future acceptance; progress is not awarded for merely updating this roadmap.**

## 1. Executive destination

A business user can interact in natural language; agents resolve exact entities, enforce trusted identity and authorization, perform authorized internal Merchant mutations through **one direct execution operation**, run deterministic multi-step Merchant workflows, access governed external data, leverage grounded knowledge and proactive alerts, and operate under auditable, recoverable, multi-user production controls.

**Release target:** CP18H reaches *selected business-unit production* and *broader controlled rollout*, with monitoring, rollback, accountable owners, security signoff, and operational readiness. A shadow/pilot deployment alone is **not 100%**.

```text
CP7.8 verified baseline (COMPLETE)
  → CP7.9 Merchant Reliability Hardening
  → CP12 Deterministic Direct-Execution Trust & Entity Authority [audit legacy paths]
  → CP13 Complete Merchant Operational Surface
  → CP14 End-to-End Workflow Orchestration
  → CP15 External Data & Integration Layer
  → CP16 Production Reliability & Observability
  → CP17 RAG / Memory / Proactive Intelligence
  → CP18 Platformization & Controlled Production Rollout
  → 100% PRODUCTION
```

The original CP12–18 dependency order is preserved. CP7.9 is an added reliability prerequisite that does **not** replace CP16's broader backup/metrics/chaos scope.

## 1A. Non-negotiable execution architecture (Decision ADR-DE-001)

```text
Natural language request
  → trusted orchestration / exact canonical entity resolution
  → completeness + command schema validation
  → actor/role + operation + environment/database policy gate
  → attempt reservation & generation fence (durable trusted state)
  → single direct execution through approved executor
  → atomic PostgreSQL transaction + claim + ledger + domain event
  → committed-evidence verification, recovery-safe receipt
  → audit, result delivery, teammate reuse
```

**Removed from normal internal Merchant writes:** proposal file/layout, `--propose`, `--apply`, proposal hash used as user confirmation, confirmation token, generic approval round-trip, old Gate7.3-based proposal dispatch and legacy apply adapters. A user request is *not* permission in itself: policy authority still applies. **Do not delete audit/evidence hashes or operation identity hashes**, which are distinct from proposal hashes and are required for idempotency/security.

**Write behavior:** Missing required data → ask for the exact missing input, do not execute; ambiguous entity → reject/clarify; unauthorized command/environment → deny; valid authorized command → execute once, no separate preview; unknown COMMIT outcome → evidence/recovery only, **never a new CREATE attempt**. Higher-risk actions may require RBAC-specific approval or operator controls, but never generic Merchant proposal/apply revival.

**Coverage caveat:** Existing tests verify the new Merchant CREATE path and selected lifecycle gates; Project/Step/Document/etc. full elimination is **PENDING AUDIT**, not already complete.

## 2. Original allocation and 22 October baseline (historical; see CURRENT STATUS for latest)

| Stage | Weight of unified roadmap | Credited now | Evidence / exit gate |
|---|---:|---:|---|
| CP7.9 — Merchant Lifecycle Reliability & Observability | **12%** | **1.8%** | Only A.1 and A.2 passed, representing 15% *within CP7.9* |
| CP12 — Direct Execution Trust & Entity Authority | **17%** | **0% (pending reconciliation)** | No reachable legacy proposal/apply entry points; direct-execute trust matrix, adversarial and authorized isolated E2E |
| CP13 — Complete Merchant Operational Surface | **13%** | 0% | Reads, writes, grammar, natural-language UX |
| CP14 — End-to-End Workflow Orchestration | **12%** | 0% | Dependency graph, branches, blockers, safe transitions |
| CP15 — External Data & Integration Layer | **10%** | 0% | Read-first connectors, governed BigQuery, external authority |
| CP16 — Production Reliability & Observability | **12%** | 0% | Metrics, audits, backups, restore drills, chaos testing |
| CP17 — RAG / Memory / Proactive Intelligence | **10%** | 0% | Grounded retrieval and memory that cannot grant authority |
| CP18 — Platformization & Production Rollout | **14%** | 0% | Identity/RBAC, environments, security, phased rollout |
| **TOTAL** | **100%** | **1.8% verified** | **98.2% not yet credited** |

**Why CP12 shows 0% credited:** Original plan dated 2026-09-24 described 12A–F as done and 12G partially complete; subsequent work reportedly changed 12H and Merchant runtime behavior. We must audit the actual code, receipts, tests, and changed direct-execution architecture before moving historical CP12 work into the new verified progress ledger. This is *not* an assertion that those features are absent or need rebuilding. Credit is awarded once evidence is reconciled, not twice or based on old labels alone.

**Relative progress:** CP7.9 itself is **15%** completed. In the entire production roadmap, **12% × 15% = 1.8 percentage points**. When CP7.9 reaches 100%, global progress becomes **12%**, before any validated CP12 carry-over is credited.

## 3. Detailed weighted work breakdown

### CP7.9 — 12 percentage points (locally 100%)

| Subgate | Work package | CP7.9 share | Global points | Current status / exit criteria |
|---|---|---:|---:|---|
| 7.9A.1 | Recovery architecture & test audit | 8% | 0.96 | **PASS**: code paths and 57-test inventory reviewed |
| 7.9A.2 | Repeat recovery identity safety | 7% | 0.84 | **PASS**: 1 targeted + 37 recovery regression tests |
| 7.9A.3 | Crash at locked filesystem persistence | 15% | 1.80 | **IN PROGRESS**: read-only audit complete; fault injection and durable retry proof missing |
| 7.9A.4 | Crash matrix and committed-write E2E | 10% | 1.20 | Not started: pre/post COMMIT, before/after VERIFIED/receipt/archive |
| 7.9B | Structured lifecycle diagnostics | 15% | 1.80 | Not started: bounded structured logs, redaction, correlation IDs |
| 7.9C | Recovery failure classification | 10% | 1.20 | Not started: actionable error taxonomy, no unsafe retries |
| 7.9D | Legacy state compatibility | 15% | 1.80 | Not started: safe migration/recognition of old states |
| 7.9E | Integration/full regression | 15% | 1.80 | Not started: PostgreSQL test DB, full regression, diff review |
| 7.9F | Final local checkpoint commit | 5% | 0.60 | Not started: clean staging, commit and handoff |
| **CP7.9 total** | | **100%** | **12.00** | **15% local complete** |

**Next concrete gate — 7.9A.3:** `locked_team_state()` yields mutable state and calls `save_team_state()` *after* the block while still holding the exclusive lock. Test fault injection must use a temporary persistent file and prove an exception during `save_team_state()` does not misleadingly claim durable success. After a simulated partial/failed save, inspect disk state, then retry only with original committed PostgreSQL evidence/attempt/generation. **Do not re-execute Merchant CREATE.** Unit fixture `env` currently mocks the lock with a mere `yield state`, so it cannot prove disk durability by itself. Include a real state-store test or equivalent boundary-level exercise.

### CP12 — 17 percentage points — Direct Execution Only

**Fixed architecture decision:** for internal Merchant write commands, the supported operational path is `request → resolve canonical entities → completeness validation → trusted actor/action/target/database policy → reserve execution identity → direct execute once → PostgreSQL COMMIT → committed evidence → audit/result`. **No proposal document/hash, no separate `--propose`, `--apply`, legacy confirmation receipt or confirmation-dependent dispatch is required for these authorized internal writes.** Errors, missing permissions, unknown entities, and absent required inputs **block** execution; the model cannot compensate by assuming values. This is an architecture requirement, **not a claim that all repository paths are already migrated**.

External side effects, privileged administrative changes and higher-risk financial or partner operations can require approval under an explicit *action policy*; approvals are not implemented by resurrecting the generic Merchant proposal/apply pipeline.

| Subgate | Work package | Global points | Acceptance criteria |
|---|---|---:|---|
| 12A–12F | Result-delivery lifecycle; deterministic completeness; Merchant/Project/Step canonical resolvers | 3 | Reverify old tests and actual runtime binding under direct execution; no stale authorization |
| 12G | Document revision and scoped entity resolution | 2 | Revision identity/scope, evidence, test DB E2E |
| **12H** | **Legacy Proposal Elimination & Trusted Direct Execution Authority** | **3** | Full reachable-path audit; disable/remove legacy proposal/apply runtime entrypoints; authoritative command policy and generation-bound execution; non-live tests; no model-owned DB bypass |
| 12I | Approval/Procurement/Identifier/Contact entity authorities | 3 | Exact parent/child scope; PII-safe imports; fail-closed writes |
| 12J | Complete **direct-write** trust matrix | 2 | Every command has actor, entity, completeness, database target, allowed action, immutable attempt/idempotency, evidence, audit; no proposal/confirm/apply columns |
| 12K | Adversarial regression | 2 | Unauthorized direct call, legacy route, replay, wrong user/run/task/entity, stale claims, forged results, cross-db and cross-session blocked |
| 12L | Isolated real-data E2E with authorized test DB | 2 | Merchant→Project→Steps→Document revision→report→IDLE_REUSABLE→reuse; no production DB mutation |
| **CP12 total** | | **17** | `CHECKPOINT_12_DIRECT_EXECUTION_AUTHORITY_PASSED` |

#### CP12H — detailed gates (within existing 3 points; no extra global percentage)

- **H.1 — Inventory all invocation paths:** CLI parser, write adapters, orchestration hooks, agent prompts, templates, docs, tests and old runtime handoff; classify as reachable legacy behavior, dormant legacy code, or active direct execution. Check *effective dispatch*, not just string matches.
- **H.2 — Make direct execution the sole supported internal write contract:** reject `--propose`/`--apply`/legacy confirmation operationally; no implicit fallbacks; unify default `EXECUTE` where authorized.
- **H.3 — Preserve indispensable protections:** exact entity and parent scope, required inputs, actor/role policy, runtime/test DB isolation, deterministic operation_key/payload hash, immutable execution_attempt_id/claim_generation, transaction/ledger, audit.
- **H.4 — Cover all commands (not CREATE only):** Project/Step/Document/Approval/Procurement/Signing/Contact/Identifier and any other installed write routes. Missing direct executor means command must fail closed, not revert to proposal/apply.
- **H.5 — Adversarial tests:** no untrusted tool invocation or SQL bypass; stale/duplicate/cross-task/cross-user/invalid command; legacy CLI cannot reintroduce prohibited proposal flow.
- **H.6 — Documentation and agent contract migration:** remove active instructions requiring proposal/confirmation/apply. Historical documents may remain in an explicitly labeled archive, not operational guidance.
- **H.7 — Evidence gate:** full relevant test suite, authorized isolated E2E, reviewed route inventory; *only then* mark eliminated repository-wide.

**Migration compatibility rule:** Preserve read/inspection of historical proposal/audit data when necessary, but historic records cannot authorize a new write. Legacy write executors are disabled or removed; no automatic conversion of a proposal into execution authority.

**Original CP12 12H.1–12H.9 (Gate7.3/7.4/7.5 and `LOCAL_AUTO` propose/confirm/apply)** are **superseded as workflow requirements** by these direct execution gates. Any remaining safety property (binding, at-most-once attempts, audit, fail-closed and E2E) is retained and re-proved in the new design. Neither old completion markers nor old proposal-oriented tests automatically satisfy new CP12H.

### CP13 — 13 percentage points

| Subgate | Global points | Deliverable |
|---|---:|---|
| 13A | 3 | Deterministic Merchant/Step/Document/Approval/Procurement/Identifier/Contact reads |
| 13B | 4 | Business-required **direct** writes (approval, document supersede, procurement, signing, contact, identifier), each with policy enforcement, transaction identity, read-back verification |
| 13C | 3 | Machine-readable unified CLI/tool command grammar and schema |
| 13D | 3 | Business natural-language UX with clarification for missing information, single authorized direct execution and verified read-back (no generic proposal step) |
| **Total** | **13** | `CHECKPOINT_13_COMPLETE_MERCHANT_OPERATIONAL_SURFACE_PASSED` |

### CP14 — 12 percentage points

| Subgate | Global points | Deliverable |
|---|---:|---|
| 14A | 2 | Workflow templates as source of truth |
| 14B | 3 | Deterministic dependency graph engine |
| 14C | 2 | Conditional branches including procurement skipping |
| 14D | 2 | Reliable blocker/deadline/explanation surface |
| 14E | 3 | Policy-gated direct-execute workflow transitions; no implicit proposal stage or LLM-invented mutations |
| **Total** | **12** | `CHECKPOINT_14_END_TO_END_WORKFLOW_ORCHESTRATION_PASSED` |

### CP15 — 10 percentage points

| Subgate | Global points | Deliverable |
|---|---:|---|
| 15A | 2 | Read-only connectors first; scoped credentials |
| 15B | 3 | BigQuery parameterized approved templates and bounded results |
| 15C | 3 | Connector authority policy, dataset/action allowlists, rate limits/classification |
| 15D | 2 | Action-specific authorization for external side effects (email, Slack, APIs, uploads); no generic proposal/apply handshake |
| **Total** | **10** | `CHECKPOINT_15_EXTERNAL_INTEGRATION_LAYER_PASSED` |

### CP16 — 12 percentage points

| Subgate | Global points | Deliverable |
|---|---:|---|
| 16A | 3 | Structured audit trail and protected metadata |
| 16B | 2 | Core system performance/cost/error metrics |
| 16C | 2 | AOP evaluation: time, data, workflow friction, comparative cost |
| 16D | 3 | Verified database backup/restore, migration/role/RAG recovery and documented RPO/RTO |
| 16E | 2 | Chaos/incident testing: DB, locks, process death, provider timeout, duplicate messages |
| **Total** | **12** | `CHECKPOINT_16_PRODUCTION_RELIABILITY_PASSED` |

**CP7.9 vs CP16:** CP7.9 hardens Merchant write recovery; CP16 covers all services, backups, operations and reliability. Reuse proofs but do not double-credit work.

### CP17 — 10 percentage points

| Subgate | Global points | Deliverable |
|---|---:|---|
| 17A | 2 | Governed workspace RAG document ingestion, secret/PII exclusion |
| 17B | 2 | Contextual retrieval with citations and fresh source checks |
| 17C | 2 | User/team memory separated from direct-execution authority |
| 17D | 2 | Proactive notification, recommendation or **non-executable plan**; mutations require the normal direct-execution policy gate |
| 17E | 2 | Retrieval precision/recall, groundedness, freshness, citation and latency evaluation |
| **Total** | **10** | `CHECKPOINT_17_CONTEXTUAL_INTELLIGENCE_PASSED` |

### CP18 — 14 percentage points

| Subgate | Global points | Deliverable |
|---|---:|---|
| 18A | 2 | Durable user/team/BU identity and identity provider integration |
| 18B | 2 | RBAC/least privilege (staff, heads, legal, finance, admin) with deny-by-default tests |
| 18C | 2 | DEV/UAT/STAGING/PROD separated DB, secrets, connector grants and policies |
| 18D | 1 | Service boundaries, deployment contract and health probes |
| 18E | 1 | Production secrets manager, rotations and no source-level secrets |
| 18F | 2 | Security review: injection, tenant leaks, forgery, replay, poisoning, SQL/tool abuse |
| 18G | 1 | Run/team/model/tool budgets and alerts |
| 18H | 3 | Shadow → read-only pilot → policy-authorized limited **direct-write** pilot (test/UAT before production) → selected-BU production → broader rollout; rollback and go/no-go evidence |
| **Total** | **14** | `CHECKPOINT_18_PLATFORM_PRODUCTION_ROLLOUT_PASSED` |

## 4. Explicit production go-live gates

The final 100% requires **all** of the following conditions, beyond a green unit-test suite:

1. **Security & authority:** verified multi-user identity, least-privilege RBAC, policy enforcement for every write, cross-user isolation, no agent-owned production DB bypass, security review signed off.
2. **Correctness:** deterministic entities, complete command trust matrix, E2E business flows, audit/replay protection, no duplicate Merchant execution under failures.
3. **Operations:** documented owners/on-call, deploy and rollback runbooks, monitoring/alerting, restore drills with measured RPO/RTO, secrets handling, incident response.
4. **Environment:** isolated DEV/UAT/STAGING/PROD infrastructure; designated test-data sources; explicit UAT and limited-prod rollout signoff (separate from any per-write proposal pipeline).
5. **Product:** user acceptance criteria, business stakeholders, cost limits, privacy/retention rules, documented connector scope.
6. **Rollout:** evidence from each rollout wave, entry/exit thresholds and rollback triggers; at least selected-BU production followed by controlled broader rollout.

**Non-goals / forbidden shortcuts:** Never infer runtime authority from model text, docs, RAG output, `SendMessage`, stale receipt or old task binding. Never perform live production mutation merely to increase roadmap percentage. Never treat `pytest` skips as covered live tests. Never auto-retry an uncertain write via another execution attempt. Never commit unrelated local changes or push unless expressly requested.

## 5. Dependency and sequencing policy

- CP7.9 first (Merchant reliability); CP12 follow-up must reconcile original roadmap with current direct-execute surface, then CP13 → CP14 → CP15 → CP16 → CP17 → CP18.
- Safe research/spec/test design may be parallel; **authority-dependent implementation and rollout cannot bypass earlier fail-closed gates**.
- CP18A/B/C can be designed early, but production capabilities cannot be accepted until prerequisite security evidence exists.
- For checkpoint status, use `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `PARTIAL`, `PASS`, `FAILED`, and `CARRIED_FORWARD_UNVERIFIED`. A PASS requires recorded tests/evidence.

## 6. Progress ledger and reporting protocol (historical baseline plus current status above)

### Formula

`global_completed_percentage = sum(global_points_for_verified_completed_subgates)`

`stage_completed_percentage = (earned_stage_points / stage_total_points) × 100`

Fractional global points are permitted; show to one decimal place. E.g. CP7.9A.1 + A.2 = 0.96 + 0.84 = **1.80 / 100**. The full CP7.9 weighting is 12 points and internally remains 15% complete until A.3 has passed its fault-injection acceptance criteria.

**No points** for: planned tests, code patches without green acceptance, successful audit of implementation but missing runtime verification, or an old status carried forward without reconciliation. Regressions invalidate the corresponding credit until repaired and retested; explicitly report rollbacks.

### Mandatory update after *every* fix, patch, test completion, or status change

```text
AGENT ECOSYSTEM — PRODUCTION ROADMAP PROGRESS
Current branch / commit: <verified values, or 'not rechecked'>
Checkpoint: <CPx.y>
Change / proof: <what changed and what was tested>
Outcome: PASS | FAIL | PARTIAL | BLOCKED
Stage progress: <e.g. CP7.9 = 15.0% of its stage>
Global production progress: <e.g. 1.8% / 100%>
Change this update: <+0.0 percentage points or other exact delta>
Remaining: <98.2%>
Next acceptance gate: <specific test/deliverable>
Risks / blockers: <relevant specifics>
```

Keep the **same denominator and weights** across turns. A reweighting requires a documented roadmap version bump and an old-vs-new reconciliation table. Never silently change 1.8% to 15% just because CP7.9 is 15% complete internally.

### Baseline ledger — 22 October 2026

| Event | Evidence | Local CP7.9 | Global points earned | Global total |
|---|---|---:|---:|---:|
| CP7.8 baseline committed | Commit `80322f0`, full suite 3,225 passed, 20 skipped, 1 xfailed, 97 subtests | Not included in denominator | 0.00 | 0.00 |
| CP7.9A.1 architecture/test audit | Read-only code-path audit, 57 tests collected | +8% | +0.96 | 0.96 |
| CP7.9A.2 repeat recovery contract | Repeat recovery test PASS, 37 recovery regression tests PASS | +7% | +0.84 | **1.80** |
| CP7.9A.3 persistence boundary audit | Found `locked_team_state()` calls `save_team_state()` on context exit; no fault-injection test yet | +0% | +0.00 | **1.80** |

**Current verified status: 1.8% / 100%; CP7.9 local: 15% / 100%; 98.2% remaining.** Historic CP12A–H may be credited after evidence reconciliation, but not before.

## 7. Historical next executable work (superseded by CURRENT BLOCKER above)

**CP7.9A.3 — Fault-injection test of state persistence (direct-execution recovery, no legacy proposal flow):** use temporary filesystem storage, exercise the real `locked_team_state`→`save_team_state` boundary, intercept a persistence failure, verify actual disk state and exception semantics, and retry exact bound committed evidence. Compare against `test_direct_recovery.py` fixture, which currently provides an in-memory `locked` context manager and cannot demonstrate durability. Keep production mutations out of scope.

After CP7.9A.3 pass: move to A.4 crash matrix. Publish the progress report for each subgate. **Do not begin CP12 rework until CP7.9 passes final regression and checkpoint commit**, except read-only reconnaissance.

## 8. Provenance and interpretation

Original CP12–CP18 scope, original marker names, named commands, trust matrix, and rollout progression: `AGENT_ECOSYSTEM_CHECKPOINT_12_TO_18_ROADMAP_2026-09-24.md` as originally drafted. CP7.9 phases and 15% stage progress: recent CP7.9 planning/testing conversation. CP7.8 baseline: user-submitted full regression and Git commit logs.

The CP7.9→CP18 global weights, finer stage scoring, explicit acceptance thresholds and the 1.8% conservative credit rule are **new planning choices introduced in this unified version**, not figures quoted from the original CP12–18 roadmap. This version treats the old proposal/confirmation/apply implementation as deprecated for internal Merchant writes, and does **not** claim a complete elimination audit has yet passed.
