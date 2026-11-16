# Checkpoint History

A concise record of how the system reached its current state: what each checkpoint delivered,
the decisions and lessons that still matter, and where the detailed evidence is. The detailed
reports are archived unchanged under [`archive/checkpoints/`](../../archive/checkpoints/); they are
historical evidence, not current instructions. Current rules live in the documents linked from
[docs/README.md](../README.md).

## Timeline

| Checkpoint | Date | Outcome | Commit | Archived report |
|---|---|---|---|---|
| CP1–2 | 2026-08 | RAG phases 1–2; Merchant Project Manager design; PostgreSQL bootstrap and privilege verification | `e38bab3`, `dcde763` | — (design kept as [project manager design](../merchant/project-manager-design.md)) |
| CP3 | 2026-09-03 | Merchant domain foundations | — | [MERCHANT_CHECKPOINT_3_HANDOFF_2026-09-03.md](../../archive/checkpoints/MERCHANT_CHECKPOINT_3_HANDOFF_2026-09-03.md) |
| CP4 | 2026-09-05 | Workflow engine and mutations | `d1b2175` | — |
| CP5 | 2026-09-06 | Read/write CLI, redaction, repository adapters; migration 3 | `29733fd` | [MERCHANT_CHECKPOINT_5_HANDOFF_2026-09-05.md](../../archive/checkpoints/MERCHANT_CHECKPOINT_5_HANDOFF_2026-09-05.md) |
| CP6 | 2026-09-06 | `merchant-manager` teammate and `/solve` routing; fail-closed runtime | `ba16daa` | [MERCHANT_CHECKPOINT_6_HANDOFF_2026-09-06.md](../../archive/checkpoints/MERCHANT_CHECKPOINT_6_HANDOFF_2026-09-06.md) |
| CP7 | 2026-09-07 | Merchant intent/policy integration (proposal/apply era, since superseded) | `370b0d0` | [MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md](../../archive/checkpoints/MERCHANT_CHECKPOINT_7_HANDOFF_2026-09-07.md) |
| CP8 | 2026-09-07 | Deterministic deadline, blocker, missing-gate and alert reads | `efa05fa` | [plan](../../archive/checkpoints/MERCHANT_CHECKPOINT_8_PLAN_2026-09-07.md), [MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md](../../archive/checkpoints/MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md) |
| CP9 | 2026-09-08 | Private runtime initialization: migrations, four templates, 22-record catalog (hash-verified) | `2ac90c0`, `ef2ee1d` | [plan](../../archive/checkpoints/MERCHANT_CHECKPOINT_9_PLAN_2026-09-07.md), [MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md](../../archive/checkpoints/MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md) |
| CP10 | 2026-09-09 | Lease-safe alert-delivery worker (INTERNAL/EMAIL/Slack), migration 4 | `d4d29db`, `55f7312` | [MERCHANT_CHECKPOINT_10_PLAN_2026-09-09.md](../../archive/checkpoints/MERCHANT_CHECKPOINT_10_PLAN_2026-09-09.md), [MERCHANT_CHECKPOINT_10_HANDOFF_2026-09-09.md](../../archive/checkpoints/MERCHANT_CHECKPOINT_10_HANDOFF_2026-09-09.md); operations: [merchant-alert-operations.md](../operations/merchant-alert-operations.md) |
| CP11 | 2026-09-10 | Agent Team lifecycle: no duplicate suffixed teammates, result de-duplication | `1c8a2fb`…`b6dcc81` | [ORCHESTRATION_LIFECYCLE_FIX_2026-09-10.md](../../archive/checkpoints/ORCHESTRATION_LIFECYCLE_FIX_2026-09-10.md) |
| CP12A–G | 2026-09/10 | Result delivery, completeness, deterministic Merchant/Project/Step/Revision entity resolution | `bbc28a0`…`580ba5b` | [CP12–18 roadmap](../../archive/checkpoints/AGENT_ECOSYSTEM_CHECKPOINT_12_TO_18_ROADMAP_2026-09-24.md) |
| CP7.9 / CP12-B | 2026-10-14…10-30 | **Direct EXECUTE only**: proposal/apply removed, execution claims + ledger, fencing, crash recovery, pane-verified teammates | `afae84a`…`84d28d2` | [unified roadmap v2](../../archive/checkpoints/AGENT_ECOSYSTEM_UNIFIED_ROADMAP_DIRECT_EXECUTION_TO_PRODUCTION_v2.md) |
| CP12H | 2026-10-30…11-16 | Natural-language Merchant operations on the test database, ending in the confirmation-first Local MVP lifecycle | see below | [`archive/checkpoints/cp12h/`](../../archive/checkpoints/cp12h/) |

The 2026-10-05 over-engineering audit is archived as
[PONYTAIL_AUDIT.md](../../archive/checkpoints/PONYTAIL_AUDIT.md).

## CP12H — natural-language operations to Local MVP

| Step | Delivered | Commit | Suite | Report (in `archive/checkpoints/cp12h/`) |
|---|---|---|---|---|
| 5A–5B | Live psmux validation; runtime identity and routing fixes | `011d29e` | — | `cp12h5a_live_psmux_validation.md`, `cp12h5b_runtime_identity_and_routing.md` |
| 5C | Report/evidence consistency, claim + ledger in the write transaction, REVOKED fencing, UNCERTAIN outcome | `204bcde` | 3407 | `cp12h5c_correctness_and_recovery.md` |
| NL1–NL2H | NL Project preview; test-mode `project create` bound to a preview basis; UTF-8 hook boundary; fail-closed dispatch; respawned-pane verification; execute delivery; single envelope ownership | `96c3c0e` | 3500–3655 | `cp12h_nl1_*`, `cp12h_nl2*` |
| NL3 | Conversational confirmation `/solve Xác nhận tạo` from a trusted pending record | `1b56a0b` | — | `cp12h_nl3_*` |
| NL4A | Read-only `project status` and discovery | `dd103bb` | 3864 | `cp12h_nl4a_*` |
| NL4B | Read-only `step preview` | `578790c` | 4014 | `cp12h_nl4b_*` |
| NL4C | Test-only confirmed Step Update (`/solve Xác nhận cập nhật`), receipts, recovery; live accepted | `b0860a7` | 4196 | `cp12h_nl4c*` |
| NL4D2–D3 | Read-only evidence/approval discovery and evidence write previews | `d06e074`, `448003b` | 4276, 4420 | `cp12h_nl4d1_*`, `cp12h_nl4d2_*`, `cp12h_nl4d3_*` |
| NL4D4 | Trusted Purchase Request (`/solve Xác nhận ghi nhận`), migration 007; live accepted | `23f1f6d`, `91ad866` | 4526 | `cp12h_nl4d4*`, `cp12h_nl4d_decision_register.md` |
| NL4D5A | Immutable local document store; migration 008 (`document_files`) | `d7c15d1`, `4d7dbb9` | 4676 | `cp12h_nl4d5a*` |
| NL4D-S1 | DEC-SIMPLIFY (confirmation-first policy); migration 009 (`METADATA_ONLY`) | `f644988` | 4695 | `cp12h_nl4d_simplified_local_mvp_policy.md`, `cp12h_nl4d_s1_*` |
| MASTER | Complete lifecycle: revisions, decisions, attested signing, PO/Payment Request, Project start/completion, gate attestation; migration 010 | `cc64f25`, `c8c69e6` | 4797 | `cp12h_master_local_mvp_completion.md` |
| MASTER-FIX | Signed revision reuse across Projects; migration 011 | `e209d5d` | 4821 | (same report, §15) |
| MASTER-FIX-F1 | Signing requires the signing-gate Step COMPLETED | `b585de2` | 4825 | [live acceptance runbook](../operations/live-acceptance.md) |
| Live acceptance | Project A (revision, 3 approvals, signing) and Project D (reuse, PO, Payment Request, 4 Steps, COMPLETED) on the test DB | — | — | records kept in the test database |
| Cleanup | Automatic READY promotion completed and committed; documentation consolidated | `1f7fb4c`, `8c09bf4` | see [cleanup report](repository-cleanup-report.md) | — |

## Durable decisions

- **ADR-DE-001: Direct EXECUTE only.** No proposal/apply, no confirmation tokens. Authority is
  the user's own typed scope or confirmation phrase, spent exactly once
  ([trusted execution](../architecture/trusted-execution.md)).
- **Runtime stays disabled** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`) until separately
  approved. Migrations 007–011 are applied to the test database only.
- **Confirmation-first Local MVP (DEC-SIMPLIFY).** Withdrawn: mandatory approval evidence,
  per-role operators, two-person approval, mandatory signed uploads, extra evidence gates
  ([decision register](decision-register.md)).
- **PostgreSQL is authoritative**; receipts are reconciled from ledger, claim, event and entity
  rows sharing one transaction id. RAG never authorizes.

## Durable lessons

- **Validate identity changes live.** psmux has one server per session, pane ids restart at
  `%1` per server, servers nest (the lead's server is the *nearest* ancestor), bare `-t %N`
  silently falls back to the current pane, and a respawned pane reports an empty `pane_pid`.
  Several fixes that passed unit tests failed live.
- **`TaskStop` labels every teammate `in_process_teammate`;** check the team config
  `backendType`/`tmuxPaneId` instead.
- **Hook byte boundaries:** Windows hook stdin decodes cp1252 unless read as strict UTF-8 from
  `stdin.buffer`; in-process tests that pass decoded strings cannot catch this — use a real
  subprocess with `PYTHONIOENCODING=cp1252`.
- **A hook crash is non-blocking in Claude Code** (exit 1). Gates must deny on any exception.
- **Claude Code's Bash tool merges stderr into stdout;** CLI JSON capture must tolerate leading
  warning lines.
- **A broken import in a hook loaded by `policy_gate` blocks every tool,** including Read and
  Edit. `py_compile` and import-smoke hooks after each edit.
- **Never run PostgreSQL tests concurrently** (an advisory lock in `tests/merchant/conftest.py`
  now enforces it).
- **Migration bytes are evidence:** `.gitattributes` pins each migration's line endings to the
  bytes whose checksum was applied (`1ba8348`).
- **Agent definitions are fingerprinted:** editing one requires a fresh session before live use.
- **Global-count assertions break once real records exist;** PostgreSQL tests must scope to
  their own fixtures (`8c09bf4`).
