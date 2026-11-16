# Merchant Project Manager — Checkpoint 5 Handoff

**Date:** September 5, 2026  
**Branch:** `feat/workspace-rag`  
**Checkpoint:** 5 — Read and Write CLI  
**Status:** Implementation and verification complete; commit and push pending

## 1. Outcome

Checkpoint 5 adds a non-interactive JSON CLI for reading Merchant project
state and applying an allowlisted set of transactional mutations. It connects
the Checkpoint 4 workflow services to PostgreSQL repositories while preserving
the existing test/runtime role boundary.

The completed CLI supports:

### Read commands

- `merchant list`
- `project list`
- `project show`
- `project history`
- `project blockers`
- `project alerts`

### Write commands

- `merchant create`
- `contact import`
- `project create`
- `project update`
- `step update`
- `document revision-create`
- `document approve`
- `procurement update`
- `integration identifier-set`

Every write uses an explicit `--propose` or `--apply` mode. Apply requests
must include the proposal hash for the exact command, database target, and
payload. Updates to existing versioned entities also require the expected
version.

## 2. Safety boundary

The following guarantees were implemented and tested:

- The CLI accepts only `test` and `runtime` database targets.
- Test commands use the `merchant_test` repository role.
- Runtime reads use `merchant_app`.
- Runtime writes fail closed unless trusted in-process orchestration supplies
  `runtime_authorized=True`.
- There is no command-line flag that can self-authorize a runtime write.
- The CLI never prompts for terminal input.
- The CLI has no password or credential arguments.
- Proposal hashes use deterministic canonical JSON and constant-time
  comparison.
- A changed command, target, or payload invalidates the proposal hash before
  repository mutation.
- A proposal hash is a payload-binding mechanism, not a secret authorization
  token and not a globally persisted one-time token. Confirmation and runtime
  authority remain responsibilities of the intent/policy layer in Checkpoint
  7.
- Contact names, emails, and phone numbers are redacted from proposal, apply,
  project-detail, and audit output.
- Integration identifier values are redacted from proposal, apply,
  project-detail, and audit output.
- Content hashes and approval notes use the shared recursive redaction rules.
- Expected-version predicates and row-count checks protect optimistic updates.
- Successful writes and their audit events commit in the same transaction.
- Failed validation, stale versions, uniqueness conflicts, and forged proposal
  hashes do not create audit events.
- SQL values are parameterized and Merchant tables are schema-qualified.

## 3. Implementation files

### CLI and command boundary

- `.claude/agents/tools/merchant/cli.py`
  - Fixed argparse command tree.
  - Explicit database selection.
  - JSON-only stdout/stderr responses.
  - Read/write dispatch and safe error rendering.
  - UTF-8 CSV contact ingestion with 1 MiB and 1,000-row limits.
- `.claude/agents/tools/merchant/cli_contract.py`
  - Read/write allowlists.
  - Database and command normalization.
  - Deterministic JSON serialization.
  - Proposal hashing and verification.
  - Runtime-write authorization boundary.
  - Recursive sensitive-field redaction.
- `.claude/agents/tools/merchant/read_commands.py`
  - Read orchestration and public-output redaction.
- `.claude/agents/tools/merchant/write_commands.py`
  - Deterministic proposal/apply binding.
  - Stable generated identifiers for proposal-visible entities.
- `.claude/agents/tools/merchant/write_adapters.py`
  - Binds all nine write commands to their specialized repositories.

### New mutation engines and repositories

- `.claude/agents/tools/merchant/merchant_engine.py`
  - Merchant creation and contact-import validation/planning.
- `.claude/clients/merchant/merchant_repository.py`
  - Atomic Merchant creation, contact import, version increment, and audit.
- `.claude/agents/tools/merchant/identifier_engine.py`
  - Identifier insert/update planning and concurrency validation.
- `.claude/clients/merchant/identifier_repository.py`
  - Atomic identifier persistence, binding checks, and redacted audit events.
- `.claude/clients/merchant/read_repository.py`
  - Read-only Merchant/project projections and history access.

### Migration

- `.claude/clients/merchant/migrations/0003_add_cli_write_grants.sql`

Migration 3 SHA-256:

```text
209179ad284a62b9c3d47558bf4cd5093389d693559af3855257ae9c02439575
```

Migration 3 adds:

- Null-safe uniqueness for one identifier binding per Merchant/project/type/scope.
- Environment-value uniqueness for UAT and Production identifiers.
- One procurement record per project/procurement type.
- Narrow `merchant_app` insert grants required by the CLI repositories.
- Column-level updates for Merchant version timestamps, document supersession,
  and integration identifier updates.
- No delete, truncate, drop, or broad contact/identifier update privilege.

Migration 3 has been applied only to `coding_agent_merchant_test`. Do not apply
it to `coding_agent_merchant` without a fresh read-only plan, checksum review,
backup/readiness review, and explicit runtime authorization.

## 4. Test files

- `tests/merchant/test_cli_contract.py`
- `tests/merchant/test_read_repository.py`
- `tests/merchant/test_read_commands.py`
- `tests/merchant/test_merchant_cli.py`
- `tests/merchant/test_merchant_engine.py`
- `tests/merchant/test_merchant_repository.py`
- `tests/merchant/test_identifier_engine.py`
- `tests/merchant/test_identifier_repository.py`
- `tests/merchant/test_write_commands.py`
- `tests/merchant/test_write_adapters.py`
- `tests/merchant/test_cli_write_grants.py`
- `tests/merchant/test_merchant_cli_live.py`
- `tests/merchant/test_checkpoint_5_readiness_live.py`
- `tests/merchant/test_project_payment_period_migration.py` was updated so the
  frozen migration order is `1, 2, 3`.

The migration-3 structural test also freezes the applied SQL checksum.

## 5. Verification evidence

Focused gates passed during Checkpoint 5:

| Gate | Result |
|---|---:|
| CLI contract | 40 passed |
| Read repository | 21 passed |
| Read CLI | 26 passed |
| Merchant/contact persistence | 51 passed |
| Identifier/assignment persistence | 93 passed |
| Proposal/apply binding | 72 passed |
| Write CLI dispatch | 89 passed |
| Repository write adapters | 176 passed, 19 subtests |
| Migration-order correction | 12 passed |
| Live CLI lifecycle | 1 passed |
| Read-only readiness | 1 passed |

Final regression results:

- Merchant non-integration suite: **945 passed**, **97 subtests passed**,
  **7 integration tests deselected**.
- Complete workspace non-integration suite: **1,015 passed**,
  **118 subtests passed**, **7 integration tests deselected**.
- `.claude/system_test.py`: **74/74 passed**.
- `git diff --check`: passed.

Previously completed Checkpoint 4 live repository lifecycles remain covered for
project transitions, document revisions, approvals, procurement, and signing.

## 6. Live CLI lifecycle evidence

`test_merchant_cli_live.py` ran against only:

```text
database: coding_agent_merchant_test
role:     merchant_test
host:     127.0.0.1
port:     5434
```

It proved:

- Propose mode created no business row.
- A tampered apply failed proposal-hash validation and created no event.
- Merchant creation persisted exactly once.
- Replaying the same creation did not duplicate the Merchant or audit event.
- A fictitious UTF-8 contact imported and incremented Merchant version.
- A 26-step/29-dependency integration project instantiated from the installed
  immutable template.
- A UAT product identifier persisted once.
- Replaying identifier creation did not add another identifier or audit event.
- Read commands returned the committed Merchant and project state.
- Contact and identifier values were redacted from public JSON.
- Sensitive contact and identifier values did not enter audit JSON.
- Exactly four expected events existed before cleanup.
- `finally` cleanup removed every temporary Merchant, contact, project, step,
  dependency, identifier, and event.

## 7. Final read-only database state

The readiness proof confirmed:

- Database: `coding_agent_merchant_test`
- User: `merchant_test`
- Transaction mode: read-only
- Applied migrations: `1, 2, 3`
- Pending migrations: none
- Missing local versions: none
- Checksum conflicts: none
- Description conflicts: none
- Business rows in all 11 operational tables: zero
- Standard workflow templates: four
- Stored template identities, step counts, and dependency counts match the
  frozen local manifest.
- All three migration-3 unique indexes are installed.
- All required narrow CLI write privileges are present.
- Delete and broad contact/identifier update privileges are absent.

No runtime database migration or runtime business-data mutation was performed
during Checkpoint 5.

## 8. Known boundaries and deferred work

- Checkpoint 5 provides the CLI and persistence boundary; it does not register
  the `merchant-manager` agent.
- Direct invocation of the current CLI cannot authorize runtime writes. This is
  intentional until the trusted orchestration path is implemented.
- Proposal hashes are deterministic bindings. Persistent proposal issuance,
  expiry, and global one-time consumption are not part of this checkpoint.
- Private unredacted contact or identifier reads are not exposed.
- Runtime migration 3 remains pending until a separately authorized deployment.

## 9. Next checkpoint — Checkpoint 6

Checkpoint 6 registers the `merchant-manager` agent and connects it to the
completed CLI. The implementation order should be:

1. Define `.claude/agents/merchant-manager.md` with read/write boundaries.
2. Register the agent in `.claude/agents.json`.
3. Add the agent and routing rules to `.claude/commands/solve.md`.
4. Implement the agent-to-CLI invocation contract without exposing credentials.
5. Verify result reporting through the supported teammate message/task tools.
6. Test read routing, write proposal reporting, fail-closed confirmation, and
   non-dispatch when authority is missing.
7. Run the complete workspace and system regressions again.

Checkpoint 7 will then integrate intent classification, confirmation policy,
and the runtime-write authorization handoff.

## 10. Commit boundary

Before committing:

1. Review the exact staged file list.
2. Confirm no `.env`, credential, cache, archive, or real Merchant data is staged.
3. Run `git diff --cached --check`.
4. Commit the complete Checkpoint 5 implementation and this handoff together.
5. Push only to `feat/workspace-rag` after confirming the branch and remote.

