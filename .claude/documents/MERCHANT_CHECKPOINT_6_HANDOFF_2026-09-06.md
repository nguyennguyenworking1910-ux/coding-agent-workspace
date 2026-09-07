# Merchant Project Manager — Checkpoint 6 Handoff

**Date:** September 6, 2026
**Branch:** `feat/workspace-rag`
**Base commit:** `29733fd` (`Checkpoint 5 completed`)
**Completion commit:** `ba16daa` (`Complete Checkpoint 6 merchant manager agent`)
**Checkpoint:** 6 — Merchant Manager Agent Registration
**Status:** Complete, committed, and pushed to `feat/workspace-rag`

## 1. Outcome

Checkpoint 6 adds `merchant-manager` as the eighth Claude Code Agent Team teammate and connects
it to the Checkpoint 5 Merchant JSON CLI through a credential-safe operational adapter.

The teammate can:

- run the six allowlisted Merchant/project reads against the runtime target;
- prepare redacted proposals for the nine allowlisted write commands;
- preserve parallel workflow branches and all active steps in its report;
- use RAG only as supplemental, untrusted historical context;
- report the complete CLI-backed outcome to the lead through `SendMessage`.

Checkpoint 6 does not authorize runtime mutation. Confirmed runtime apply remains reserved for
the trusted intent/policy handoff in Checkpoint 7.

## 2. Agent registration

The new definition is:

```text
.claude/agents/merchant-manager.md
```

It has only these harness tools:

```text
Read, Bash, SendMessage, TaskUpdate
```

The frontmatter and `.claude/agents.json` agree on:

- id/name: `merchant-manager`;
- model: `haiku`;
- maximum turns: `12`;
- permission boundary: `write-confirming`;
- definition path and supported tools.

The `/solve` command now lists `merchant-manager` in its authorized teammate table and
dispatch roster. Presence in the registry does not independently authorize a run: the exact id
must still appear in the current envelope's `selected_agents`.

## 3. Operational routing boundary

Merchant operational work has one owner:

```text
merchant-manager
```

The routing rules enforce:

- Merchant-state reads route only to `merchant-manager`;
- write-intent proposals route only to `merchant-manager`;
- development roles may edit Merchant source code when separately authorized, but may not run
  operational Merchant CLI commands;
- the lead may not run the Merchant CLI as a fallback;
- missing `merchant-manager` authority stops dispatch;
- incomplete Merchant assignments stop rather than being reconstructed.

Every Merchant assignment declares the runtime target, authorized mode (`READ` or `PROPOSE`),
exact operation and filters/identifiers, credential prohibition, apply denial, and teammate
result-delivery requirement.

## 4. Credential-safe agent-to-CLI interface

The registered adapter is:

```text
.claude/agents/tools/merchant/agent_cli.py
```

Operational invocation is:

```text
python .claude/agents/tools/merchant/agent_cli.py <resource> <action> [arguments]
```

The adapter:

- prepends the fixed `runtime` database target internally;
- rejects database target, host, port, user, password, DSN, connection string, credential,
  secret, and token arguments;
- accepts only commands parsed by the existing fixed Merchant CLI contract;
- accepts reads and write `--propose` mode;
- rejects `--apply` before any repository factory is called;
- calls the existing CLI with `runtime_authorized=False` fixed internally;
- exposes no confirmation or runtime-authorization parameter;
- returns safe JSON for adapter-level failures without echoing payload values.

The adapter does not read an environment variable to acquire runtime-write authority. Setting a
confirmation-like environment variable or adding a confirmation-like CLI flag cannot unlock
apply.

## 5. Write and confirmation boundary

A successful write proposal returns the normalized command, runtime target, redacted payload,
proposal hash, and `requires_confirmation: true`. The teammate must state that no change has
been applied.

The proposal hash is deterministic payload binding. It is not:

- confirmation;
- a credential;
- runtime authorization;
- a bypass around `/solve` or the policy gate.

Checkpoint 6 rejects runtime apply even if the request carries a proposal hash, approval-like
wording, a confirmation-like flag, or an environment variable claiming authorization.

## 6. Result-delivery contract

The teammate must finish in this order:

1. Produce the CLI-backed result and complete report.
2. Mark its shared task complete with `TaskUpdate` when a task exists.
3. As its final action, send the complete report to `team-lead` with `SendMessage`.

The message body carries:

- operation;
- runtime target;
- authorized mode;
- redacted CLI JSON;
- exit outcome;
- confirmation state;
- failures;
- unresolved work.

`TaskUpdate`, pane text, and idle notifications are status signals only. They do not establish
result delivery. A failed message may be retried once, but the Merchant command must not be
repeated merely to recover message delivery.

## 7. Files added

- `.claude/agents/merchant-manager.md`
- `.claude/agents/tools/merchant/agent_cli.py`
- `tests/merchant/test_merchant_agent_cli.py`
- `tests/merchant/test_merchant_manager_agent.py`
- `tests/merchant/test_merchant_manager_registration.py`
- `tests/merchant/test_merchant_manager_team_contract.py`
- `.claude/documents/MERCHANT_CHECKPOINT_6_HANDOFF_2026-09-06.md`

## 8. Files updated

- `.claude/agents.json`
- `.claude/commands/solve.md`
- `.claude/system_test.py`
- `tests/test_rag_agent_integration.py`
- `README.md`
- `CLAUDE.md`
- `.claude/documents/ARCHITECTURE.md`
- `.claude/documents/README.md`

## 9. Verification evidence

Completed gates:

| Gate | Evidence |
|---|---:|
| Agent definition and RAG boundary | 24 passed |
| Registration and `/solve` routing | Focused tests passed; system 80/80 |
| Credential-safe agent CLI | Focused tests passed; system 80/80 |
| Team reporting and authority denial | 94 passed; system 80/80 |
| Final Checkpoint 6 focused regression | 102 passed |
| Complete Merchant non-integration regression | 1,036 passed, 8 deselected, 97 subtests passed |
| Root workspace non-integration regression | 1,107 passed, 8 deselected, 118 subtests passed |
| Final structural system validation | 80/80 passed |
| Post-commit clean-checkout system validation | 81/81 passed |
| `git diff --check` | Passed after every gate |

The final Windows regressions ran with Python 3.11.9 and pytest 9.1.1. Live integration tests
were explicitly excluded. The focused suite completed in 2.52 seconds, the Merchant regression
in 677.70 seconds, and the root workspace regression in 679.34 seconds.

The first unscoped workspace attempt also collected `rag-server/tests` with the root virtual
environment and failed during collection because RAG-only dependencies were not installed there.
It additionally caused a top-level `tests` package-name collision. This was a test-command scope
error, not a Checkpoint 6 product failure. The corrected authoritative command explicitly targeted
the root `tests` directory and produced the 1,107-pass result above. No source change or dependency
installation was used to hide that collection error.

No live Merchant write, migration, database bootstrap, or runtime database mutation was needed
for Checkpoint 6.

## 10. Known boundary

The agent is registered and its operational adapter is safe, but automatic Merchant intent
selection and confirmed runtime writes are not implemented in this checkpoint. Until
Checkpoint 7:

- the intent parser does not select `merchant-manager` for Merchant operations;
- the policy gate does not carry a Merchant proposal confirmation into apply authority;
- the adapter rejects every runtime apply;
- no command-line or environment workaround is permitted.

## 11. Next checkpoint — Checkpoint 7

Checkpoint 7 integrates Merchant intent and policy in this order:

1. Define Merchant read, proposal, and confirmed-apply operations in the intent classifier.
2. Route Merchant operational requests only to `merchant-manager`.
3. Ask clarification before dispatch when Merchant/project identifiers, the requested field, or
   required expected versions are ambiguous.
4. Treat proposal generation as non-mutating and require exact confirmation before apply.
5. Bind confirmation to the exact command, runtime target, payload, expected version, and
   proposal hash.
6. Implement a trusted in-process runtime-authorization handoff that has no CLI flag or
   environment-variable bypass.
7. Preserve no-envelope-no-run, external/destructive protections, tool budgets, and one-dispatch
   semantics.
8. Test read routing, proposal routing, stale/tampered confirmation denial, unauthorized-agent
   denial, and one-time confirmed apply behavior.
9. Run complete regressions and a separately authorized test-database live lifecycle.

Migration 3 remains unapplied to the runtime database. Any future runtime migration requires a
fresh read-only plan, checksum review, backup/readiness review, and explicit authorization.

## 12. Commit record

Checkpoint 6 was committed and pushed to `feat/workspace-rag` as:

```text
ba16daa Complete Checkpoint 6 merchant manager agent
```

Post-commit verification confirmed:

1. The remote branch head matches `ba16daa`.
2. The clean checkout has no modified or untracked files.
3. No `.env`, credential, cache, archive, or real Merchant data was committed.
4. `git show --check ba16daa` reports no whitespace errors.
5. The structural system validation passes 81/81 from the clean checkout.
