# CP12H.NL4B-FIX2: Target Status Parsing & Clarification Completeness

- **Baseline:** `dd103bb73d5227366c2d49f23486ead96769a06f` on `feat/cp7-9-merchant-reliability`
- **State:** uncommitted, not pushed. All earlier NL4B and NL4B-FIX1 working-tree changes are kept.
- **Scope:** no live Step Update was run, and NL4C was not implemented.

## 1. Live failure

`/solve Đánh dấu bước Legal Review hoàn thành trên database test` returned `NEEDS_CLARIFICATION`:

- `target_status` was `null`;
- the only question was "Which status should the step move to…?";
- the missing Project was never asked about, and `candidates` was empty.

## 2. Root causes

There are two independent causes. The missing "là" is only the first one.

1. **Target status was only read from a connector clause or a state verb.**
   - `project_nl._target_status` recognises two forms:
     - `<connector> <state>`, where the connector is `là | thành | sang | về | as | to | into`;
     - a verb that names the state (`Hoàn thành bước`, `Start step`).
   - "đánh dấu" (mark) does not name a state, and "hoàn thành" here follows the step name directly with no connector. Neither form matches, so the status is `None`.
   - The first live run ("… của Project … **là** hoàn thành") passed only because of the connector.
   - The step name itself was extracted correctly: "hoàn thành" is already a stop pair, so the name ends there.
2. **The clarification stopped at the first missing field.**
   - `step_preview.build_step_update_preview` checked `target_status` first and returned immediately, before Project resolution ran.
   - So a request missing both fields only ever asked about one of them.
   - With the status fixed, the Project would have been asked about next, but only in a second round.

Related gaps found while reproducing (each covered by a test):

- "Đánh dấu Legal Review là hoàn thành" and "Mark Legal Review as completed" were classified `UNKNOWN`. Every update pattern needed the word `bước` or `step`.
- "Đã đánh dấu bước Legal Review hoàn thành chưa?" and "Did you mark the Legal Review step as completed?" were classified `STEP_UPDATE`. The explicit-verb pattern outranked the question check.
- Hedged wording ("Có lẽ đánh dấu …", "Maybe mark …") still requested a write. `step_preview` ignored `exploratory` entirely.

## 3. Minimal changes

| File | Change |
|---|---|
| `.claude/agents/tools/merchant/project_nl.py` | **Bare state.** `_BARE_STATES` matches `(đã) hoàn thành / xong`, `đang thực hiện / tiến hành / làm` and `bị chặn`. They count only after an explicit `đánh dấu / cập nhật / chuyển bước` and never when followed by `bước` (the verb form). The earliest state still ends the name clause; several different states give `None`. |
| | **Mark-as without a step noun.** `_MARK_AS` matches `đánh dấu / mark <name> là / as <state>`. The new `_Words.marked_name()` takes the name after the verb, and refuses when that name starts with a Project or Merchant noun ("Mark project X as completed" names no step). |
| | **Status questions are reads.** `_DONE_QUESTION` (`xong / hoàn thành chưa`, or a leading `did / have / has / was / is`) blocks `STEP_UPDATE` classification. |
| | **Hedged wording.** `_STEP_UNCERTAIN` sets `exploratory`, so `write_requested` is false. |
| | **Project after the state.** A Project named after the state clause ("… hoàn thành cho Project X") is still read. |
| `.claude/agents/tools/merchant/step_preview.py` | **New `missing` field** (backward-compatible addition). It lists, in fixed order, every field the request did not settle: `step`, `target_status`, `merchant`, `project`. Each gets one question in `clarifications`. Project resolution now always runs, so an absent or ambiguous Project is reported together with a missing status. A resolved Project is still returned. A negated or exploratory request asks and binds nothing. |
| | **Dependency labels.** `unmet_dependency_scope` (`DIRECT`, or `TRANSITIVE` only when every direct predecessor is done) and `unmet_transitive_dependencies` (every unfinished ancestor, sorted by sequence) are added. The `UNMET_DEPENDENCIES` message names the direct predecessors and, when the chain is longer, all unfinished earlier steps. |
| `.claude/agents/merchant-manager.md`, `.claude/commands/solve.md` | Relay rules: relay every question and `missing`; label direct versus transitive; name only steps listed in the evidence; never infer a step from a count or take a Project from an earlier assignment. |
| `tests/merchant/test_nl4b_fix2_clarification_and_dependencies.py` | 37 new tests. |

Unchanged:
- every existing JSON field and value (`unmet_dependencies` and `unmet_transitive_count` keep their meaning);
- the delivery verifier and the intent-gate read downgrade;
- `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

## 4. Dependency evidence audit (live step 4 preview)

The live preview of "Send reviewed revision to Partner" (step 4) reported `unmet_transitive_count: 3` but named only two steps. These are two different concepts from `dependencies.evaluate_dependency_readiness`:

| Field | Concept | Live value |
|---|---|---|
| `unmet_dependencies` | `unmet_direct_predecessor_ids`: direct edges into the step that are not COMPLETED | 2 Legal review, 3 Accounting review |
| `unmet_transitive_count` | `len(unmet_transitive_predecessor_ids)`: every ancestor in the predecessor closure that is not COMPLETED | 3 |

Readiness (`is_ready`) is decided on the transitive set.

- **Before:** the third ancestor was counted but not named. My earlier lead summary named it ("probably step 1") by inference. That was flagged as unverified at the time, but it should not have appeared at all.
- **Now:** `unmet_transitive_dependencies` lists every counted ancestor, the scope is explicit, and the relay rules forbid naming a step outside those lists.
- **Test:** `test_direct_and_transitive_dependencies_are_labelled` reproduces the live shape: direct `[2, 3]`, transitive `[1, 2, 3]`, count 3, and "1 Draft or renew document" named in the message.

## 5. RED / GREEN

- **RED:** the new file was run against the unfixed code: **21 failed, 16 passed**. The passing tests were already-correct cases: questions, negation, ambiguity, and read-only guards.
- **GREEN:** after the fix, **37 / 37 passed**.

| Area | Tests |
|---|---|
| The exact live request | parse → `Legal Review` / `COMPLETED` / no Project; preview → `missing == ["project"]`, one Project question, nothing guessed |
| Equivalent requests (VN and EN) | 6 forms, including bare `hoàn thành`, `đã hoàn thành`, `là`, `thành`, "Mark … as completed", "Complete the … step" |
| Project with a bare state | before the state, after it ("cho Project …"), and the English "of Project … as" form |
| Missing fields | target only (Project resolved and returned); target and Project; step; nothing missing |
| Ambiguous Project | two "Nguyễn Văn Cừ" Projects returned as grounded candidates; none is bound |
| Status questions versus updates | 5 questions, including "Đã đánh dấu … chưa?" and "Did you mark …?" |
| Negation and uncertainty | 7 forms (Đừng, Không, không hoàn thành, Do not, Có nên, Có lẽ, Maybe); each preview asks |
| Conflicts | two states, or "Mark project X as completed", never bind both fields |
| Direct versus transitive | labelled lists, count, and message; empty when dependencies are met |
| Read-only | no `argv`, confirmation, scope, `requested_operation` or `pending`; the reader is unchanged; the live request routes through the intent gate as `merchant_read` / `read_only` / target `test` / no scope |

## 6. Full regression

| Check | Result |
|---|---|
| Targeted NL4B (`test_nl4b_step_preview`, `_fix1_`, `_fix2_`) | **101 passed** |
| NL1–NL4 and step/intent subset | 714 passed |
| PostgreSQL (`test_nl4b_step_preview_postgres`, `test_nl4a_project_status_postgres`, `test_nl1_project_preview_postgres`) on `coding_agent_merchant_test` | **21 passed**, not skipped |
| Full suite `pytest tests` | **3972 passed**, 20 skipped (opt-in live or runtime gates, unchanged), 1 xfailed, 0 failed |
| `python .claude/system_test.py` | ALL TESTS PASSED |
| `git diff --check` | clean |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` (`.claude/hooks/merchant_direct_handoff.py:63`) |

## 7. Database integrity (test database, read-only check)

Row counts are identical to the NL4B baseline:

| Table | Rows |
|---|---|
| merchants | 2 |
| projects | 3 |
| project_steps | 70 |
| project_step_dependencies | 70 |
| project_events | 7 |
| merchant_execution_claims | 18 |
| merchant_execution_ledger | 2 |
| `PYTEST%` Merchants | 0 |

Every other table has 0 rows, except `schema_migrations` (6) and the templates (4 / 64 / 68).

- **Hash:** sha256 over every `merchant_ops` base table (per-table count plus md5 of rows ordered as text, then JSON with sorted keys) is `1636f0cb9ac89532b4b4e70ff2759f71c4c6bf4990d9fd86a11dbaecb4c0809c`. It was the same after the full suite and after a separate PostgreSQL run.
- **Why the hash differs from the earlier reports:** they reported `71d315c9…22a7`, but their exact hashing recipe isn't recorded, and I couldn't reproduce it. So `1636f0cb…` is a new baseline from this run's own method, not a comparison against the old one.
- **Events:** 7 events means no step transition was written. The PostgreSQL fixtures also assert a byte-identical whole-table snapshot after every preview.

## 8. Remaining limitations

- **Routing without a step noun or Project.** A request such as "Mark Legal Review as completed" with no "step" and no Project reaches the intent gate's Merchant routing only through the model, because FIX1's deterministic rule needs a Project phrase. The parser and preview handle it, and the gate still downgrades it to a read.
- **Bare states are limited.** Only `hoàn thành`, `xong`, `đang thực hiện / tiến hành / làm` and `bị chặn` are read after `đánh dấu / cập nhật / chuyển bước`. `sẵn sàng`, `bỏ qua` and `bị thay thế` still need a connector ("là", "thành"); otherwise the preview asks.
- **Step titles that start with a state word.** A title like "Hoàn thành hồ sơ" combined with a bare state asks rather than binding.
- **`missing` is always present.** It is `[]` when nothing is missing. Older consumers ignore it, and the delivery verifier compares the whole object, so the field is carried through exactly.
- **The running teammate is stale.** `merchant-manager.md` changed, so the `merchant-manager` teammate in the current session is now `STALE_DEFINITION`. The live retest needs a fresh Claude Code session.
- **Step Update confirmation still does not exist (NL4C).**

## 9. Live retest (fresh Claude Code session, psmux)

Run each `/solve` command below.

1. `/solve Đánh dấu bước Legal Review hoàn thành trên database test`
   - Expect `NEEDS_CLARIFICATION` with `query.step_reference = "Legal Review"`, `query.target_status = "COMPLETED"`, `missing = ["project"]` and one Project question.
   - `project`, `step` and `candidates` are empty. No write, no authorization.
2. `/solve Đánh dấu bước Legal Review của Project Beta Nguyễn Văn Cừ hoàn thành trên database test`
   - Expect `BLOCKED` with `TRANSITION_NOT_ALLOWED` and `UNMET_DEPENDENCIES`, scope `DIRECT`, direct `[1]`, transitive `[1]`.
3. `/solve Mark the Send reviewed revision to Partner step of Project Beta NL3 Confirmation Test as completed on test database`
   - Expect `BLOCKED` with direct `[2 Legal review, 3 Accounting review]`, transitive `[1, 2, 3]` and count 3, with the summary naming only those.
4. `/solve Bước Legal Review của Project Beta Nguyễn Văn Cừ đã hoàn thành chưa trên database test?`
   - Expect a Project status read, not a step preview.

Afterwards, re-run the integrity check. It must still give `1636f0cb…809c` with 7 events.

## 10. GO / NO-GO

**GO for the NL4B-FIX2 code**, conditional on the live retest above. The parsing and clarification defects are fixed and covered by tests, the dependency evidence is labelled, the full regression is green, the database is unchanged, and runtime Direct EXECUTE stays disabled.

**Final NL4B acceptance:** GO after retests 1–4 pass in a fresh session. NO-GO if retest 1 still asks for the status, or if any summary names a dependency missing from the CLI lists.
