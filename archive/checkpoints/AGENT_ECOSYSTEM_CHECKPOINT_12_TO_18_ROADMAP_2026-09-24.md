# Agent Ecosystem — Checkpoint 12–18 Roadmap

**Date:** 2026-09-24  
**Branch context:** `fix/orchestration-and-merchant-activation`  
**Status:** Planning baseline — no implementation changes should begin until this roadmap is accepted and stored in the repo.  
**Recommended repo path:** `.claude/documents/AGENT_ECOSYSTEM_CHECKPOINT_12_TO_18_ROADMAP_2026-09-24.md`

---

## 1. Purpose

This document defines the roadmap from the current Checkpoint 12 work through Checkpoint 18.

The original Merchant Project Manager plan in the repository was formally defined only through Checkpoint 10. Checkpoints 12–18 below are the extended roadmap derived from the system's current architecture, completed gates, active defects, and intended platform direction.

The implementation order is intentional. Later checkpoints must not bypass unresolved safety, identity, lifecycle, or authority gaps from earlier checkpoints.

---

## 2. High-Level Roadmap

```text
CP1–10  Merchant Project Manager core
   ↓
CP11    Agent-team orchestration reliability
   ↓
CP12    Deterministic Trust & Entity Authority
   ↓
CP13    Complete Merchant Operational Surface
   ↓
CP14    End-to-End Workflow Orchestration
   ↓
CP15    External Data & Integration Layer
   ↓
CP16    Production Reliability & Observability
   ↓
CP17    RAG / Memory / Proactive Intelligence
   ↓
CP18    Platformization & Production Rollout
```

---

## 3. Current Position

```text
CP12A  ✅
CP12B  ✅
CP12C  ✅
CP12D  ✅ Merchant Resolver
CP12E  ✅ Project Resolver
CP12F  ✅ Workflow Step Resolver
CP12G  🟡 Document Revision Resolver
CP12H  🔴 Runtime Apply Orchestration
CP12I  ⬜ Remaining Entity Authorities
CP12J  ⬜ Complete Write Trust Matrix
CP12K  ⬜ Adversarial Regression
CP12L  ⬜ Live Hierarchical E2E

CP13    ⬜
CP14    ⬜
CP15    ⬜
CP16    ⬜
CP17    ⬜
CP18    ⬜
```

Current blocker:

```text
Confirmed Merchant proposal
        ↓
Gate 7.3 dispatch authorization
        ↓
MISSING CONTROLLED ORCHESTRATION SURFACE
        ↓
invoke_confirmed_merchant_session_apply(...)
```

The Gate 7.4/7.5 runtime handoff engine exists, but the orchestration layer currently has no trusted trigger that invokes it safely after Gate 7.3.

This must be addressed as part of Checkpoint 12H, not as an isolated shortcut.

---

# 4. Checkpoint 12 — Deterministic Trust & Entity Authority

## Goal

Establish a complete trust chain so every important operation is tied to an exact canonical entity and exact runtime authority.

```text
natural-language reference
        ↓
deterministic resolver
        ↓
canonical UUID
        ↓
trusted receipt
        ↓
consumer gate
        ↓
proposal
        ↓
confirmation
        ↓
dispatch authority
        ↓
runtime authority
        ↓
apply
        ↓
verification
```

### 12A — Agent-Team Result Delivery Foundation ✅

Required lifecycle:

```text
RUNNING
→ RESULT_DELIVERED
→ REPORT_RECEIVED
→ IDLE_REUSABLE
```

Core requirements:
- `SendMessage` is the machine-verifiable result-delivery path.
- Pane output, `TaskUpdate`, and idle notifications do not substitute for a result.
- A terminal teammate cannot continue mutating the same run.
- A later run may reuse the teammate only after `IDLE_REUSABLE`.

### 12B — Delivery / Idle Reuse Circuit Breaker ✅

Prevent teammates from remaining stuck in `RUNNING` after work is complete.

### 12C — Deterministic Merchant Completeness ✅

```text
semantic request
→ normalize write family
→ completeness check
→ complete: --propose
→ missing: exact clarification
```

No guessed fields or rewritten clarification requirements.

### 12D — Merchant Entity Resolution ✅

Example:

```text
"AEON Beta"
→ merchant resolve
→ canonical merchant_id
→ trusted Merchant resolution receipt
```

Existing Merchant writes must not consume a guessed Merchant UUID.

### 12E — Project Entity Resolution ✅

Resolution priority:

```text
exact project UUID
→ normalized exact title
→ conservative whole-token candidate
→ NOT_FOUND / AMBIGUOUS
```

Always scoped to a trusted Merchant.

### 12F — Workflow Step Entity Resolution ✅

Resolution priority:

```text
exact step UUID
→ normalized step_name
→ conservative candidate
→ NOT_FOUND / AMBIGUOUS
```

Critical invariant:

```text
template_step_id ≠ step_id
```

### 12G — Document Revision Entity Resolution 🟡

Supported scopes:
- Project scope for `document approve`;
- Merchant scope for `project create --reused-document-revision-id`.

Resolution priority:

```text
exact revision UUID
→ DOCUMENT_TYPE#REVISION_NUMBER
→ normalized document_type
→ conservative candidate
→ NOT_FOUND / AMBIGUOUS
```

Non-live work is substantially complete; live closure is blocked by the missing controlled runtime apply path.

### 12H — Controlled Runtime Mutation Handoff 🔴

Goal: connect accepted Gate 7.3 dispatch to existing session-aware runtime apply authority without giving the model or `merchant-manager` the capability directly.

Correct architecture:

```text
merchant-manager
    │ prepares exact apply request
    ▼
trusted orchestrator
    │ Gate 7.4 / 7.5
    ▼
RuntimeApplyAuthorization
    ▼
Merchant CLI internal apply
    ▼
repository / PostgreSQL
```

Forbidden architecture:

```text
merchant-manager
→ Bash / Python
→ merchant_runtime_handoff
→ database
```

Sub-gates:

#### 12H.1 — Trusted Handoff Request Contract
Machine-verifiable, bounded, non-secret apply handoff request.

#### 12H.2 — Exact Session / Run / Task / Teammate Binding
Bind owner session, run ID, task ID, teammate, operation, and confirmation hash.

#### 12H.3 — At-Most-Once Reservation
Persist an attempt before runtime mutation. Success, mismatch, timeout, failure, or uncertainty must not make the same attempt replayable.

#### 12H.4 — Lock-Safe Invocation
Required sequence:

```text
LOCK state
validate + stage PENDING
UNLOCK
→ invoke_confirmed_merchant_session_apply(...)
→ LOCK state
persist SUCCESS / FAILED
UNLOCK
```

Never call the session handoff while already holding the same `locked_state`.

#### 12H.5 — LOCAL_AUTO Receipt Consumption
For:
- `project create`;
- `project update`;
- `step update`;

receipt lifecycle must be:

```text
AVAILABLE
→ RESERVED
→ CONSUMED
```

#### 12H.6 — Runtime Apply Result Receipt
Persist only bounded success/failure evidence. Never persist confirmation tokens, opaque runtime capabilities, credentials, or secrets.

#### 12H.7 — Fake APPLY_SUCCESS Rejection
Terminal `APPLY_SUCCESS` requires matching trusted Gate 7.4 evidence for the same session/run/task/teammate/confirmation.

#### 12H.8 — Full Non-Live Regression
Test duplicates, wrong bindings, stale state, mismatches, failures, fake results, direct handoff attempts, cleanup, and replay resistance.

#### 12H.9 — Live Runtime Apply
After all non-live gates pass, create a fresh proposal and validate a real project create for:

```text
Merchant: AEON Beta
Project: Mở rạp mới AEON Beta Hải Dương
Project type: OPENING_NEW_CINEMA
Workflow variant: OPENING_NEW_CINEMA_STANDARD
Requires procurement: false
```

Do not reuse a previously spent or uncertain apply attempt.

### 12I — Remaining Entity Authorities ⬜

#### 12I.1 — Approval Entity Resolution
```text
Merchant → Project → Document Revision → Approval
```

#### 12I.2 — Procurement Entity Resolution
```text
Merchant → Project → Procurement
```

#### 12I.3 — Integration Identifier Authority
Prevent cross-Merchant or accidental identifier overwrite.

#### 12I.4 — Contact Import Authority
Merchant-bound, file-bound, schema-bound, and PII-safe.

### 12J — Complete Write Trust Matrix ⬜

| Command | Parent Authority | Entity Authority | Completeness | Proposal | Confirmation | Runtime Apply |
|---|---|---|---|---|---|---|
| project create | Merchant | generated Project | required | required | required | required |
| project update | Merchant → Project | Project | required | required | required | required |
| step update | Merchant → Project → Step | Step | required | required | required | required |
| document revision-create | Merchant → Project | generated Revision | required | required | required | required |
| document approve | Project → Revision → Approval | Approval | required | required | required | required |
| procurement update | Project → Procurement | Procurement | required | required | required | required |
| integration identifier-set | Merchant | Identifier | required | required | required | required |
| contact import | Merchant | file/schema | required | required | required | required |

Checkpoint 12 cannot close while any authority column is undefined.

### 12K — Full Adversarial Regression ⬜

Required cases include:

```text
wrong merchant
wrong project
wrong step
wrong revision
wrong approval
wrong procurement
wrong run
wrong task
wrong teammate
cross-session authority
stale receipt
replayed receipt
changed proposal
changed payload
changed expected_version
forged SendMessage
duplicate terminal result
ambiguous name
UUID outside trusted scope
```

Expected:

```text
FAIL CLOSED
```

### 12L — Live Hierarchical E2E ⬜

```text
AEON Beta
→ Mở rạp mới AEON Beta Hải Dương
→ generated workflow steps
→ real document revision
→ deterministic revision resolution
→ downstream gate validation
→ result delivery
→ IDLE_REUSABLE
```

Then a new run must reuse the same teammate without inheriting stale authority.

### Checkpoint 12 Definition of Done

- required entity types resolve deterministically;
- write consumers require trusted authority;
- Gate 7.4/7.5 runtime path is operational;
- model and teammates cannot bypass runtime authority;
- replay/stale/cross-session attacks fail closed;
- full non-live regression passes;
- live hierarchical validation passes.

Final marker:

```text
CHECKPOINT_12_DETERMINISTIC_OPERATIONAL_AUTHORITY_PASSED
```

---

# 5. Checkpoint 13 — Complete Merchant Operational Surface

## Goal

Checkpoint 12 answers: **Can the system act on the exact right thing safely?**

Checkpoint 13 answers: **Can the system perform every supported Merchant operation needed for normal business use?**

### 13A — Read Surface Completion

Recommended deterministic reads:

```text
merchant show
step list / show / resolve
document list / show / resolve
approval list / show / resolve
procurement show / resolve
integration identifier list
contact summary
```

### 13B — Write Surface Completion

Candidate business operations, added only where real workflows require them:

```text
approval create / update
document supersede
procurement create
signing status update
merchant contact lifecycle
integration identifier replace / disable
```

Every write must receive:
```text
completeness
→ proposal
→ confirmation
→ runtime authority
→ verification
```

### 13C — Unified Command Grammar

Create a machine-readable command catalog describing:
- command;
- arguments;
- required/optional fields;
- entity dependencies;
- completeness rules;
- read/write classification;
- sensitive fields.

The agent should not need to inspect source code to discover CLI syntax.

### 13D — Natural-Language Operational UX

Target:

```text
User:
"Tạo project mở rạp AEON Beta Hải Dương"

System:
resolve Merchant
→ completeness
→ proposal
→ human-readable confirmation
→ trusted apply
→ read-back verification
```

The user should not need to know internal hashes or capability mechanics.

### Definition of Done

A business user can manage the complete supported Merchant lifecycle through natural language without knowing CLI syntax.

Marker:

```text
CHECKPOINT_13_COMPLETE_MERCHANT_OPERATIONAL_SURFACE_PASSED
```

---

# 6. Checkpoint 14 — End-to-End Workflow Orchestration

## Goal

Convert individual safe operations into deterministic business workflows.

### 14A — Workflow Template as Source of Truth

Templates determine:
- steps;
- ordering;
- dependencies;
- branch rules;
- required gates;
- approvals;
- documents.

The LLM must not invent workflow structure.

### 14B — Dependency Graph Execution

Example:

```text
Legal Review ─────┐
                  ├─→ Signing
Finance Approval ─┘
Signing → Integration → Go Live
```

### 14C — Conditional Branch Logic

Example:

```text
requires_procurement = false
→ Procurement branch = SKIPPED
```

### 14D — Automatic Blocker Explanation

Answer “Why can't this project proceed?” from actual graph state:
- blocking steps;
- missing approvals;
- missing documents;
- unmet prerequisites;
- overdue blockers.

### 14E — Safe Automatic Transitions

Deterministic low-risk transitions may occur automatically when prerequisites are satisfied; sensitive business mutations still require policy/confirmation.

### Definition of Done

A Project can progress from creation to completion through deterministic workflow state, blockers, branches, and transitions.

Marker:

```text
CHECKPOINT_14_END_TO_END_WORKFLOW_ORCHESTRATION_PASSED
```

---

# 7. Checkpoint 15 — External Data & Integration Layer

## Goal

Safely connect to systems outside Merchant PostgreSQL.

Candidate sources:
```text
BigQuery
Google Drive
email
Slack
internal APIs
partner APIs
web sources
```

### 15A — Read-Only Integrations First

Principle:

```text
external READ
before
external WRITE
```

### 15B — BigQuery Tooling

Target:

```text
user question
→ intent
→ approved query template
→ parameter binding
→ BigQuery
→ bounded result
```

Begin with approved query templates, not unrestricted model-generated production SQL.

### 15C — Connector Authority Model

Each connector defines:
```text
read permissions
write permissions
allowed datasets
allowed actions
data classification
rate limits
confirmation requirements
```

### 15D — External Write Confirmation

Actions such as email sending, Slack posting, file upload, or partner API updates require an explicit external-action authority boundary.

### Definition of Done

The system can safely retrieve external data and use it in workflow reasoning without allowing arbitrary side effects.

Marker:

```text
CHECKPOINT_15_EXTERNAL_INTEGRATION_LAYER_PASSED
```

---

# 8. Checkpoint 16 — Production Reliability & Observability

## Goal

Make failures visible, diagnosable, recoverable, and measurable.

### 16A — Structured Audit Trail

Record bounded metadata:
```text
request_id
session_id
run_id
task_id
agent
operation
entity
proposal state
confirmation state
apply state
result
timestamp
```

Never log credentials, confirmation tokens, opaque capabilities, or unredacted PII.

### 16B — System Metrics

Measure:
```text
task success rate
mean completion time
tool calls per run
teammate reuse rate
clarification rate
proposal→apply conversion
resolver ambiguity rate
failed apply rate
cost per run
```

### 16C — AOP Evaluation Metrics

Operationalize:
1. task completion speed;
2. amount of data accessible;
3. workflow/approval reduction;
4. cost versus traditional process.

### 16D — Backup and Recovery

Cover:
```text
database backup
restore validation
migration recovery
role/bootstrap recovery
RAG backup separation
```

Add PITR/WAL later if operationally justified.

### 16E — Failure / Chaos Testing

Simulate:
```text
DB disconnect
lock contention
teammate crash
Claude process termination
hook timeout
duplicate SendMessage
external provider timeout
partial network failure
stale runtime state
```

### Definition of Done

The system is observable and has tested recovery behavior for critical failure modes.

Marker:

```text
CHECKPOINT_16_PRODUCTION_RELIABILITY_PASSED
```

---

# 9. Checkpoint 17 — RAG, Memory & Proactive Intelligence

## Goal

Add contextual intelligence only after operational authority and production reliability are trustworthy.

### 17A — Workspace RAG

Index:
```text
architecture documents
SOP
contracts
workflow templates
historical Project knowledge
non-sensitive operational documentation
```

Never index:
```text
credentials
confirmation tokens
raw PII
private authorization artifacts
runtime capability data
```

### 17B — Contextual Retrieval

Example:
```text
"Tạo project giống lần mở AEON Mall trước"
```

RAG may retrieve workflow structure, document requirements, decisions, timing, and blockers, but never reuse stale authority.

### 17C — User / Organization Memory

Keep separate:
```text
knowledge
preference
authority
```

Memory may preserve preferences and terminology but must never bypass confirmation, approval, authorization, or entity resolution.

### 17D — Proactive Intelligence

Detect:
```text
approaching deadline
missing document
stalled approval
low balance
integration issue
```

Allowed proactive behavior:
```text
notify
recommend
prepare analysis
prepare proposal
```

Mutation remains gated.

### 17E — RAG Quality Evaluation

Track:
```text
retrieval precision
retrieval recall
groundedness
source freshness
citation correctness
retrieval latency
```

### Definition of Done

The system becomes context-aware and proactive without weakening deterministic trust boundaries.

Marker:

```text
CHECKPOINT_17_CONTEXTUAL_INTELLIGENCE_PASSED
```

---

# 10. Checkpoint 18 — Platformization & Production Rollout

## Goal

Transform the workspace-oriented system into a secure multi-user internal platform.

### 18A — Multi-User Identity

Introduce durable:
```text
user_id
team
business unit
role
permissions
```

Session identity alone is insufficient for production authorization.

### 18B — RBAC

Example:
```text
BU Staff → READ + PROPOSE
BU Head → CONFIRM selected business actions
Legal → legal approvals
Finance → finance approvals
Platform Admin → template / policy administration
```

### 18C — Environment Separation

```text
DEV
UAT
STAGING
PRODUCTION
```

Separate databases, credentials, connectors, and deployment policies.

### 18D — Service Boundaries

Candidate services:
```text
Agent Orchestrator
Merchant API / runtime
RAG Service
Alert Worker
Integration Workers
PostgreSQL
Observability stack
```

### 18E — Secrets Management

Move operational secrets out of repository-root `.env` files into an appropriate secrets-management system.

### 18F — Security Review

Cover:
```text
prompt injection
tool injection
cross-session leakage
privilege escalation
receipt forgery
RAG poisoning
SQL injection
replay attacks
secret leakage
connector abuse
```

### 18G — Cost Control

Budgets:
```text
per run
per user
per team
per model
per tool
```

### 18H — Controlled Production Rollout

Recommended:
```text
shadow mode
→ read-only pilot
→ proposal-only pilot
→ limited confirmed writes
→ selected BU production
→ broader rollout
```

### Definition of Done

The system operates as a secure, multi-user, observable internal platform with controlled production writes and explicit ownership boundaries.

Marker:

```text
CHECKPOINT_18_PLATFORM_PRODUCTION_ROLLOUT_PASSED
```

---

# 11. Dependency Rules

Mandatory order:

```text
CP12
↓
CP13
↓
CP14
↓
CP15
↓
CP16
↓
CP17
↓
CP18
```

Research/design may happen in parallel, but production implementation must not bypass unresolved authority dependencies.

---

# 12. Milestone Interpretation

- **Checkpoint 12:** Can the system act on the exact right thing safely?
- **Checkpoint 13:** Can the system perform every supported Merchant operation we need?
- **Checkpoint 14:** Can safe operations form complete deterministic workflows?
- **Checkpoint 15:** Can the system safely use external data and systems?
- **Checkpoint 16:** Can we reliably operate, observe, and recover the system?
- **Checkpoint 17:** Can the system use contextual knowledge and act proactively without weakening authority?
- **Checkpoint 18:** Can this become a secure multi-user production platform?

---

# 13. Immediate Next Work After Roadmap Acceptance

Do not begin implementation until this roadmap is accepted as the planning baseline.

Resume at:

```text
CHECKPOINT 12H
Controlled Runtime Mutation Handoff
```

Sequence:

```text
12H non-live implementation
→ 12H adversarial tests
→ 12H full regression
→ fresh AEON Beta project proposal
→ live project create
→ complete 12G live Document Revision validation
→ continue 12I
```

The previous uncertain live apply attempt must not be treated as reusable runtime authorization.

Any future live mutation must come from a fresh valid proposal/confirmation flow after 12H passes.

---

# 14. Planning Marker

This file is a roadmap artifact only. It does not authorize or perform any source-code or runtime mutation.

Recommended planning marker after review:

```text
CHECKPOINT_12_TO_18_ROADMAP_BASELINE_ACCEPTED
```
