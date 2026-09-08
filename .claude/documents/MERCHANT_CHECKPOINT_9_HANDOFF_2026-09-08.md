# Merchant Project Manager — Checkpoint 9 Handoff

**Date:** September 8, 2026
**Branch:** `feat/workspace-rag`
**Base commit:** `efa05fa` (`Complete Checkpoint 8 Merchant deadline and alert calculation`)
**Completion commit:** Pending commit and push verification
**Checkpoint:** 9 — Private Runtime Initialization
**Status:** Implementation and runtime verification complete; final staging review pending

## 1. Outcome

Checkpoint 9 completes the currently planned core Phase 4 Merchant Project Manager. It adds a
strict private-catalog contract, deterministic import plans, read-only readiness and deployment
plans, separately authorized runtime migrations and template initialization, an atomic private
catalog initializer, and read-only post-initialization verification.

The runtime result is represented only through counts, status distribution, and hashes:

| Evidence | Result |
|---|---:|
| Merchant records | 22 |
| `ONBOARDING` | 22 |
| `ACTIVE` | 0 |
| Catalog initialization events | 22 |
| Contacts | 0 |
| Projects | 0 |
| Alert deliveries | 0 |

No Merchant id, code, name, contact, identifier, credential, private filesystem path, or catalog
row is reproduced in this handoff.

## 2. Private catalog contract

The runtime catalog is loaded only from an explicit local path. It must be UTF-8 without a byte
order mark and contain exactly 22 objects. Each object permits only:

- required `code`, `name`, and `account_status`;
- optional `region_code`;
- exact status `ONBOARDING` or `ACTIVE`.

The validator normalizes codes, regions, and Unicode names; generates stable UUIDv5 identities;
sorts by normalized code; rejects duplicate fields and codes; and returns errors containing only
a record position and reason code. Test fixtures use fictitious values only.

The reviewed catalog bindings are:

```text
source_sha256  c0c48cf58a0cd55a25a78abc35922114a36c42b92d29d6c1c58d97898733a501
catalog_sha256 d657f977a384b4747882017ef77163bf4e268a38f6092dfbdd8dfc4ebb609354
```

The source hash binds the exact private bytes. The catalog hash binds the normalized UTF-8
records and stable identities. Neither hash reveals a catalog value.

## 3. Backup and authority boundaries

Readiness was restricted to database `coding_agent_merchant` at `127.0.0.1:5434`. Planning and
verification used `merchant_app` with read-only transactions. Migration execution used
`merchant_owner`; catalog insertion used the least-privilege `merchant_app` grants established by
migration 3.

A PostgreSQL custom-format backup was created before runtime mutation. Its archive listing,
recovery procedure, and role recovery path were reviewed. The bound backup evidence was:

```text
backup_sha256 5567a6ac9508490085382b58a6b8395e37814a698c0eb024577e94abaab2e145
size_bytes    53606
```

Three independent authorization phrases were accepted only after their exact read-only plans:

1. `MIGRATIONS_2_3_AUTHORIZED`;
2. `STANDARD_TEMPLATES_AUTHORIZED`;
3. `PRIVATE_CATALOG_22_AUTHORIZED`.

These phrases are audit labels, not reusable runtime capabilities. Future real workflow changes
still require the Checkpoint 7 proposal, exact confirmation, policy acceptance, and one-use
in-process authorization for that operation.

## 4. Runtime migrations

The runtime began with migration 1 applied and migrations 2 and 3 pending. The authorized runner
applied them forward-only, in order, with one transaction per migration and the migration advisory
lock.

| Version | Description | SHA-256 |
|---:|---|---|
| 1 | `initial_schema` | `8ff45d352766953f18ec0378c74cc280571641d40bcf5f4e27c5bedc700e51f1` |
| 2 | `add_project_payment_period` | `e7729b83ae1bbf121e0d94fd095ee4b07e18092c72195653fd00c16b3c2fa666` |
| 3 | `add_cli_write_grants` | `209179ad284a62b9c3d47558bf4cd5093389d693559af3855257ae9c02439575` |

Post-apply verification proved the payment-period column and constraint, all three reviewed unique
indexes, insert grants, column-scoped update grants, read-only application checks, and unchanged
empty business tables.

## 5. Standard workflow templates

The separately authorized template transaction installed the four immutable standard templates:

- 4 templates;
- 64 workflow steps;
- 68 dependencies.

The full template manifest hash is:

```text
71e6570aef9eac09b0707d487388059bc8f26249c1aa4c08c36a99cd6203842f
```

The template initialization plan hash is:

```text
38706d3193c1065b5116ad7cabf2964f9fb9b700d86a3d9b6387df2c594b88dc
```

All templates, steps, and dependencies were inserted in one atomic transaction. An identical retry
inserted nothing and verified all four templates as unchanged.

## 6. Atomic catalog initialization

The catalog preflight proved an empty target, matching templates, migrations 1–3, the reviewed
backup, exact source and catalog hashes, and this bound runtime plan:

```text
catalog_plan_sha256 88baf29663420759bea16504f59cdbbf5e1ed46191375b48c1446f48b4f0d40b
runtime_plan_sha256 f4da32fac417d8d63fa4f843f55c9b3993f58e0c2c608171a984504993578f06
```

The authorized initializer used one connection, one transaction, and an advisory transaction
lock. It inserted exactly 22 merchants and 22 deterministic `MERCHANT_CATALOG_INITIALIZED` events.
The events contain only status, catalog hash, version, and a generic summary. No contacts or
projects were inserted.

The first authorized attempt found a verifier defect after inserting inside the transaction: SQL
omitted the absent `ACTIVE` group while the plan represented it as `ACTIVE: 0`. The verifier
rejected the evidence, and the transaction context rolled back all inserts. A read-only preflight
then proved the target was still empty. The correction normalizes every allowlisted status to zero
before applying returned counts and includes a direct regression for the all-`ONBOARDING` case.

The corrected transaction committed successfully. Its immediate identical retry returned
`NO_OP`, with 0 merchants and 0 events inserted and all 22 merchants verified unchanged.

## 7. Read-only runtime verification

`runtime_verification.py` collects two read-only snapshots around ordinary read and pure planning
probes. The accepted final report proved:

- exact runtime database, application role, read-only transaction, and UTF-8 encoding;
- stored catalog hash equal to the reviewed normalized catalog hash;
- exactly 22 records with `ACTIVE: 0` and `ONBOARDING: 22`;
- exact migrations 1, 2, and 3;
- exactly 4 templates, 64 steps, and 68 dependencies;
- exactly 22 deterministic, redacted catalog events;
- zero contacts, projects, project steps, documents, procurement records, identifiers, and alert
  deliveries;
- ordinary merchant reads returned 22 records, the `ONBOARDING` filter returned 22, and the
  `ACTIVE` filter returned 0;
- ordinary project and global alert reads returned zero records;
- the snapshots before and after verification were identical.

The verifier never renders private rows. Its safe report contains only booleans, counts, status
distribution, migration versions, template totals, event totals, and hashes.

## 8. Workflow compatibility

No real project was created during Checkpoint 9. The compatibility verifier used pure project
planning to prove:

- an actual initialized `ONBOARDING` identity satisfies the Integration New Merchant precondition;
- the same `ONBOARDING` state is rejected by all three ACTIVE-only workflow variants;
- all three ACTIVE-only workflow planner contracts remain available for a future ACTIVE state;
- ACTIVE state is rejected by the Integration New Merchant workflow;
- the Integration preview contains 26 steps;
- three ACTIVE-only variants build valid in-memory previews;
- `runtime_projects_created` remains 0.

Any request to create one of those projects is a new real workflow mutation and requires its own
Checkpoint 7 controlled authorization path.

## 9. Privacy and repository isolation

The private source, backup, credentials, environment configuration, generated ZIP files, and
database state remain outside Git. Gate 9.7 scanned every modified and untracked text file against
the private codes and names and found no match. It separately rejected private catalog filenames,
environment files, spreadsheets, archives, dumps, backups, caches, and compiled Python files from
the staging boundary.

Catalog validators, planners, initializer tests, and verification tests contain only fictitious
records. Runtime outputs used during the checkpoint were restricted to counts, hashes, redacted
events, migration metadata, template metadata, and boolean checks.

## 10. Files added

Production and documentation:

- `.claude/agents/tools/merchant/catalog_contract.py`
- `.claude/agents/tools/merchant/catalog_plan.py`
- `.claude/clients/merchant/catalog_initializer.py`
- `.claude/clients/merchant/runtime_catalog_plan.py`
- `.claude/clients/merchant/runtime_migration_plan.py`
- `.claude/clients/merchant/runtime_readiness.py`
- `.claude/clients/merchant/runtime_template_plan.py`
- `.claude/clients/merchant/runtime_verification.py`
- `.claude/documents/MERCHANT_CHECKPOINT_9_PLAN_2026-09-07.md`
- `.claude/documents/MERCHANT_CHECKPOINT_9_HANDOFF_2026-09-08.md`

Tests:

- `tests/merchant/test_catalog_contract.py`
- `tests/merchant/test_catalog_initializer.py`
- `tests/merchant/test_catalog_plan.py`
- `tests/merchant/test_checkpoint_9_documentation.py`
- `tests/merchant/test_checkpoint_9_plan.py`
- `tests/merchant/test_checkpoint_9_runtime_catalog_initialization_live.py`
- `tests/merchant/test_checkpoint_9_runtime_catalog_preflight_live.py`
- `tests/merchant/test_checkpoint_9_runtime_migration_preflight_live.py`
- `tests/merchant/test_checkpoint_9_runtime_migrations_live.py`
- `tests/merchant/test_checkpoint_9_runtime_readiness_live.py`
- `tests/merchant/test_checkpoint_9_runtime_template_initialization_live.py`
- `tests/merchant/test_checkpoint_9_runtime_template_preflight_live.py`
- `tests/merchant/test_checkpoint_9_runtime_verification_live.py`
- `tests/merchant/test_runtime_catalog_plan.py`
- `tests/merchant/test_runtime_migration_plan.py`
- `tests/merchant/test_runtime_readiness.py`
- `tests/merchant/test_runtime_template_plan.py`
- `tests/merchant/test_runtime_verification.py`

## 11. Files updated

- `.claude/documents/ARCHITECTURE.md`
- `.claude/documents/MERCHANT_CHECKPOINT_8_HANDOFF_2026-09-07.md`
- `.claude/documents/README.md`
- `README.md`
- `tests/merchant/test_checkpoint_8_documentation.py`

## 12. Verification evidence

| Gate | Accepted evidence |
|---|---|
| 9.0 | Checkpoint 8 remote baseline, exact 27-file commit, clean-checkout structural proof |
| 9.1 | Private catalog contract passed |
| 9.2 | Deterministic catalog import plan passed |
| 9.3 | Read-only runtime readiness passed |
| 9.4 | Migration preflight passed; migrations 2 and 3 authorized, applied, and verified |
| 9.5A | Standard-template preflight passed |
| 9.5B | Four standard templates authorized, initialized, and identical retry verified |
| 9.5C | Exact private catalog preflight passed |
| 9.5D | Rollback proof, correction, 22-record initialization, and identical retry passed |
| 9.6 | Runtime verification and workflow compatibility passed |
| 9.7A | Focused regression, complete non-live regression, structural validation, privacy scan, and final runtime verification passed |

The Gate 9.7A accepted markers were:

```text
CHECKPOINT_9_GATE_7_FOCUSED_REGRESSION_PASSED
CHECKPOINT_9_GATE_7_ALL_NON_LIVE_TESTS_PASSED
CHECKPOINT_9_GATE_7_STRUCTURAL_VALIDATION_PASSED
CHECKPOINT_9_GATE_7_PRIVATE_DATA_ISOLATION_PASSED
CHECKPOINT_9_GATE_7_FINAL_RUNTIME_VERIFICATION_PASSED
CHECKPOINT_9_GATE_7A_COMPLETE_REGRESSION_PASSED
```

All 80 structural checks passed. `git diff --check` passed, and the complete repository regression
excluded integration tests. Every runtime mutation had a separate read-only preflight and explicit
authorization; the final verification was read-only.

## 13. Final runtime state

The verified runtime boundary at handoff is:

| Component | State |
|---|---|
| Database | `coding_agent_merchant` on `127.0.0.1:5434` |
| Application role | `merchant_app` |
| Encoding | UTF-8 |
| Migrations | 1, 2, and 3 applied; none pending |
| Templates | 4 templates, 64 steps, 68 dependencies |
| Catalog | 22 records; `ONBOARDING: 22`, `ACTIVE: 0` |
| Catalog events | 22 redacted initialization events |
| Contacts and projects | 0 |
| Alert deliveries | 0 |

## 14. Remaining boundary

Checkpoint 9 completes the core Phase 4A Merchant Project Manager. It does not authorize a real
project, contact, document, approval, procurement, identifier, transition, or alert-delivery
mutation.

Checkpoint 10 remains the optional Phase 4B production alert worker: delivery scheduling,
claiming, retries, channel integrations, and operational monitoring. It is not required for the
completed core Merchant Project Manager.

## 15. Commit boundary

Before committing Checkpoint 9:

1. Run the final documentation and complete non-live regression.
2. Review the exact modified and untracked file manifest against sections 10 and 11.
3. Confirm no private source, environment file, credential, backup, dump, cache, generated archive,
   or real Merchant value is staged.
4. Stage only the reviewed Checkpoint 9 files and run `git diff --cached --check`.
5. Commit and push only to `feat/workspace-rag` after confirming the branch.

After the Checkpoint 9 commit is pushed, a small documentation-only finalization will replace the
pending completion fields with the real commit SHA and record remote and clean-checkout evidence.
