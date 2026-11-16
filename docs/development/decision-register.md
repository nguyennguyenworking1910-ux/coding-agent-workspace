# Decision Register

The current status of every owner decision that shapes Merchant behaviour. Options, trade-offs
and the original wording are preserved in the archived
[NL4D decision register](../../archive/checkpoints/cp12h/cp12h_nl4d_decision_register.md) and
[simplified Local MVP policy](../../archive/checkpoints/cp12h/cp12h_nl4d_simplified_local_mvp_policy.md).
How the decisions apply in practice: [project lifecycle](../merchant/project-lifecycle.md).

A decision changes only by an explicit new owner decision recorded here. Do not revive a
superseded or withdrawn decision without one.

## Architecture

| ID | Decision | Status |
|---|---|---|
| ADR-DE-001 | Merchant writes use Direct EXECUTE only; proposal/apply and confirmation tokens removed | APPROVED, implemented (CP7.9/CP12-B) |
| RUNTIME | Runtime Direct EXECUTE disabled (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`); runtime migration of 007+ not authorized | IN FORCE until separately approved |

## Local MVP policy

| ID | Decision | Status |
|---|---|---|
| **DEC-SIMPLIFY** (P1–P8) | Confirmation-first single-operator Local MVP: confirmation is the authority; evidence optional; no role system | **OWNER_APPROVED — Local Test MVP, 2026-11-12** |
| DEC-SIMPLIFY-a | `METADATA_ONLY` revision class (migration 009) | OWNER_APPROVED 2026-11-12 |
| DEC-SIMPLIFY-b | Record REJECTED as well as APPROVED; final per revision and role | OWNER_APPROVED 2026-11-12 |
| DEC-A0 | Recording actor = trusted local operator id (`MERCHANT_OPERATOR_ID`); attribution only, no operators table | APPROVED 2026-11-11 |
| DEC-P1a | Unique `(merchant_id, procurement_type, reference)`, exact match, enforced by migration 007 | APPROVED 2026-11-11 |
| DEC-P1b | Reference format pattern per type | PROPOSED — no format rule until ERP formats are given |
| DEC-P1c | A recorded procurement reference is never replaced | APPROVED 2026-11-11 |
| DEC-P2 | Purchase Request allowed on a no-procurement Project, with `PROCUREMENT_NOT_REQUIRED` | APPROVED 2026-11-11 |
| DEC-D4, D4a–c | Managed local store outside the repository + PostgreSQL metadata; PDF/DOCX/PNG/JPEG ≤ 25 MiB; SHA-256 identity; filename as sanitized metadata only | APPROVED — Local Test MVP, 2026-11-11 (upload not yet implemented) |
| DEC-D4d | Reject a new MANAGED revision identical to the active one | APPROVED 2026-11-11 |
| DEC-D4e | A signed revision is never superseded | APPROVED 2026-11-11 |
| DEC-D4f | Legacy hash-only revisions stay `UNVERIFIED_LEGACY`; a labelling rule — they may satisfy ordinary gates but are never shown as verified files | APPROVED 2026-11-11, clarified by DEC-SIMPLIFY |
| DEC-D4g | Document-type allowlist = canonical domain types | APPROVED; canonical list still undefined (pattern + "hợp đồng" → CONTRACT alias) |
| MASTER-FIX reuse | An Existing-Document Media Project may bind one signed CONTRACT revision of another Project of the same Merchant (migration 011) | APPROVED — Local Test MVP, 2026-11-12 |

## Superseded or withdrawn (do not reintroduce)

| ID | Was | Replaced by |
|---|---|---|
| DEC-S1a/b | Per-role operator mapping; ≥ 2 distinct operators (two-person approval) | DEC-SIMPLIFY: one local operator records any role |
| DEC-S2a/b | Mandatory attestation fields / evidence for approvals | DEC-SIMPLIFY P2/P3: optional notes and date; `approved_by` never fabricated |
| DEC-D1a/b | Mandatory signed-document upload, `document_signatures` table | DEC-SIMPLIFY P4: operator-attested signing flag (D1c runtime grant deferred) |
| DEC-G1a/b/c | New evidence gates on Steps 2, 3, 9–11 | Withdrawn: those Steps stay ungated |
| DEC-G2a/b | UAT document and Partner evidence for Steps 21–22 | DEC-SIMPLIFY P7: operator-attested completion of evaluator-less gates |
| "Fail closed on UNVERIFIED_LEGACY" | Legacy revisions block gates | DEC-D4f clarification above |

## Open owner decisions

| ID | Question | Options |
|---|---|---|
| F7 | Two open INTEGRATION_NEW_MERCHANT Projects for one Merchant: the second can never complete after the first activates the Merchant | Refuse a second open integration Project per Merchant at create, **or** let activation accept an already-ACTIVE Merchant |
| DEC-P1b | Procurement reference formats | Await ERP formats |
| DEC-D4g list | Canonical document types | Define the list |
| Superseded signed revision reuse | A superseded signed revision is not reusable (conservative) | Keep, or relax |
