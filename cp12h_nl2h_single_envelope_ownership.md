# CP12H.NL2H — Single Intent Envelope Ownership

Branch `feat/cp7-9-merchant-reliability`, baseline `204bcde`. NL1–NL2G uncommitted changes
preserved. Nothing committed or pushed. No live Project Create was run.

## 1. Confirmed root cause

The blocked `/solve --confirm` run received two envelopes for one prompt: hook `54b1e519…`/run
`52b4cc44…` and bridge `c4b49b71…`/run `b48233cc…`, with identical scope hashes.

| Question | Finding | Evidence |
|---|---|---|
| Which entry point runs first | **UserPromptSubmit**, then UserPromptExpansion, then the `!` bridge. | Hooks docs: "If the [UserPromptSubmit] hook blocks the prompt, the command doesn't run, so shell commands the skill injects with `!` don't run either". Session transcript: the Submit context is stamped 04:22:24.793. The expanded `/solve` body is stamped 04:22:42.766, 18 s later, which is one more classifier call. |
| Who creates and persists the run | **Both.** Each event ran the parser, minted a `run_id`, and wrote run state and the envelope. | `intent_gate.run` before the fix: every non-deduplicated event reached `factory().parse()`, `uuid4()`, `save_state`, `save_intent_envelope`. |
| Does either overwrite the other | **Yes.** Expansion overwrote Submit's state and envelope. The bridge rendered Expansion's run B. Submit's `additionalContext` still carried run A. | Reproduction below. |
| Why both classify | The only deduplication sat in the **Submit** branch and assumed Expansion ran first. In the real order Submit found no matching run and classified. Expansion had no dedupe branch at all and classified again. | `intent_gate.py`, the `if hook_event_name == "UserPromptSubmit":` block (removed). |
| Is the intent model invoked twice | **Yes**, once per event. That explains the different `complexity_score` (0 vs 2) and `reasons`. | RED: Expansion with no pre-parsed envelope reached the real parser (`Configuration …` error). |
| Can identical-text submissions be distinguished | Not from the payload: there is no prompt id, only `session_id` and `prompt`. They are distinguished by a single-use claim lifecycle instead (§2). Neither `raw_request` nor `scope_hash` is a key. | Hooks docs input schemas. |

Exact reproduction (real subprocesses, same scoped Beta prompt; script
`scratchpad/repro.py`):

```text
== PRE-FIX ==
hook additionalContext : 54b1e519-submit    c09401f0-…   (run A)
expansion output       : {"hookSpecificOutput": {"hookEventName": "UserPromptExpansion"}}   (re-classified)
bridge rendered        : c4b49b71-expansion 5f346414-…   (run B)
persisted state run_id : 5f346414-…                      (B overwrote A)
scope_hash equal       : True
== FIXED ==
hook additionalContext : 54b1e519-submit    752243f8-…
expansion output       : {}
bridge rendered        : 54b1e519-submit    752243f8-…
persisted state run_id : 752243f8-…
scope_hash equal       : True
```

## 2. Authoritative envelope lifecycle

**UserPromptSubmit is the only owner.** It is the only event that classifies and the only one
that creates a run.

1. **Submit** first validates the syntax: flags, `--merchant-target`, `--merchant-scope`, and
   `validate_direct_scope`.
2. **Submit** revokes any earlier `intent_claim`, so a failed new submission cannot leave an old
   claim consumable.
3. **Submit** classifies once. The parsed or pre-parsed payload has `run_id`, `merchant_scope`,
   `merchant_database_target` and `confirmed` **stripped**; only the hook sets them.
4. **Submit** mints `run_id` locally (`uuid4`). It writes the envelope (now carrying `run_id`)
   first, then the run state with
   `intent_claim = {run_id, request_id, prompt_sha256, issued_by: UserPromptSubmit, issued_at,
   consumed_at: null}`. The state write is the commit point.
5. **Expansion** re-runs the deterministic syntax and scope validation. It **never classifies**.
   Under the state lock it consumes the claim exactly once, and only if all of these hold:
   - the claim was issued by Submit and is unconsumed;
   - `prompt_sha256` equals the digest of this exact parsed prompt;
   - it is no more than 30 s old;
   - claim, state and envelope agree on `run_id`, `request_id` and `merchant_scope`.

   Otherwise Expansion returns `decision: block`.
6. **Bridge** renders the envelope only if the same claim, state and envelope agree and the claim
   was consumed no more than 30 s ago. Otherwise it exits 2 and nothing is rendered.

The result is one classification, one `request_id` and one `run_id` per prompt. A separate
submission with identical text always gets a new run.

## 3. Changes made

| File | Change |
|---|---|
| `.claude/hooks/intent_gate.py` | Removed the Expansion-first dedupe branch. Added `TRUSTED_ENVELOPE_FIELDS`, `prompt_digest`, `claim_matches_run`, `consume_intent_claim`, `revoke_intent_claim`. Expansion consumes or blocks. Submit strips trusted fields, adds envelope `run_id`, and writes the envelope before the state with its claim. |
| `.claude/hooks/intent_envelope_bridge.py` | Refuses a missing, stale, unconsumed or mismatched claim. Docstring corrected to the real order. |
| `tests/test_nl2h_single_envelope_ownership.py` (new) | 15 real-subprocess integration tests of Submit, then Expansion, then bridge. psycopg connects are recorded and refused. `NL2H_HOOKS_DIR` lets the same tests run against pre-fix hooks. |
| `tests/test_intent_expansion_submit_idempotency.py` | Rewritten to the real order: Submit classifies, and Expansion is silent and does not reclassify. |
| `tests/merchant/test_direct_scope_end_to_end.py` | Order test now runs Submit then Expansion. The changed-authorization test now asserts that a different prompt's Expansion is blocked and cannot consume the claim. |
| `tests/merchant/test_cp12h5b_identity_and_routing.py`, `tests/merchant/test_direct_execute_end_to_end.py` | Classification setup events changed from Expansion to Submit (the owner). |

`RUNTIME_DIRECT_EXECUTE_ENABLED = False` is unchanged. No change to the policy gate, handoff,
lifecycle, or dispatcher.

## 4. RED/GREEN evidence

The RED copy is the pre-fix `intent_gate.py` and `intent_envelope_bridge.py`, rebuilt verbatim
from the original reads saved in this session's transcript. The rest of `.claude/hooks` and
`.claude/system` is current.

| # | Requirement | Test | RED (pre-fix) | GREEN |
|---|---|---|---|---|
| 1–4, 11 | One run; same `request_id`/`run_id`/scope/target across hook, bridge and state; no reclassification; no DB access | `test_submit_expansion_bridge_share_exactly_one_run` | FAIL (Expansion re-classified) | pass |
| 5 | Identical-text submissions are separate runs; a consumed claim cannot be replayed | `test_separate_submissions_are_separate_runs_and_claims_are_single_use` | FAIL | pass |
| 6 | Concurrent sessions isolated | `test_concurrent_sessions_do_not_overwrite_each_other` | FAIL | pass |
| 6 | Concurrent Submits in one session never render a mixed run | `test_concurrent_submits_in_one_session_never_render_a_mixed_run` | FAIL | pass |
| 7 | Stale claim and stale consumption rejected | `test_stale_claim_is_rejected`, `test_stale_consumption_is_not_rendered` | FAIL | pass |
| 8 | Mismatched envelope (`run_id`, `request_id`, `merchant_scope`) rejected; a different prompt cannot consume | `test_mismatched_envelope_is_rejected[×3]`, `test_expansion_of_a_different_prompt_cannot_consume_the_claim` | FAIL | pass |
| 9 | A failed Submit leaves nothing Expansion, the bridge or a write can use; a failed resubmit revokes the old claim; Expansion alone fails closed | `test_failed_submit_cannot_be_completed_by_expansion`, `test_failed_resubmit_revokes_the_previous_claim`, `test_expansion_without_any_submit_fails_closed` | FAIL | pass |
| — | A pre-parsed or model envelope cannot supply `run_id`, scope, target or confirmation | `test_preparsed_envelope_cannot_supply_run_identity_or_scope` | FAIL | pass |
| 10 | Read-only preview path intact (`merchant_read`, target `test`, no scope) | `test_read_only_preview_flow_is_intact` | FAIL | pass |

RED: **15 failed**. GREEN: **15 passed**.

## 5. Full regression

| Run | Result |
|---|---|
| NL2H integration (real subprocesses) | 15 passed |
| Focused: NL2H, idempotency, direct scope, CP12H.5B, direct execute end-to-end, NL1 routing | 104 passed |
| Full `pytest tests`, first run (PostgreSQL configured) | 3694 passed, **1 failed**: `test_hook_utf8_boundaries.py::test_envelope_bridge_prints_the_exact_request` rendered the bridge without the Expansion step, which is now refused by design. Test updated to Submit, then Expansion, then bridge (11/11). |
| Full `pytest tests`, final run | **3695 passed, 20 skipped, 1 xfailed, 97 subtests passed**, 0 failed (4m49s) |
| `python .claude/system_test.py` | 100% pass |
| `git diff --check` | clean |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` (`merchant_direct_handoff.py:63`) |

The test database `coding_agent_merchant_test` was snapshotted read-only before the suites and
after both full runs. The snapshots are **identical**:

| Check | Result |
|---|---|
| Beta fixture `NL2_LIVE_BETA` | `6e0c1a2b-…`, "Beta Cinemas", ACTIVE, version 1, unchanged |
| Previewed Project `30fffeaf-…` | does not exist |
| Historical claims | 16, all COMPLETED (same as the NL2F baseline) |
| Ledger | 0 rows |
| `PYTEST*` Merchants / `pytest:` claims left | 0 / 0 |
| md5 hashes | merchants `094d5dba…`, projects `1e91b4a3…`, steps `abeb9e49…`, claims `d6217d8c…`: same as NL2F |

Intent processing made **no database connection**. psycopg connects were recorded and refused
in every NL2H subprocess, and the log stayed empty. No new run state was left under
`.claude/runtime`; the tests use temporary directories.

## 6. Remaining security limitations

- **Hook order is an assumption, verified only for this runtime.** The order comes from the
  hooks docs and the v2.1.317 transcript. If a future Claude Code fired Expansion before
  Submit, every expanded `/solve` would be blocked at Expansion. That is fail-closed, not unsafe.
- **The prompt binding is the parsed prompt text.** Expansion's `prompt` must parse the same as
  Submit's. A runtime that rewrites one of them (for example, pasted-content markers) blocks the
  run.
- **Claude Code exposes no submission identifier.** Two identical submissions are kept apart by
  claim revocation, single-use consumption and a 30 s TTL, not by a harness prompt id.
- **Only Submit's `additionalContext` reaches an unexpanded `/solve`.** In that case there is no
  bridge and no consumption. It is the same single run.
- **Per-session state is single-slot (pre-existing).** A new submission replaces the previous
  run's state, including one a teammate still owns. Concurrent Submits in one session can leave
  state and envelope disagreeing; that case is refused, not merged.
- **No run state means no policy decision (pre-existing).** The policy gate does not decide an
  Agent dispatch when no run state exists. No write authority can exist without a persisted
  scope, but that dispatch path is not itself denied.

## 7. GO / NO-GO

**GO** to retry the controlled test-database Project creation once. Use a **new Claude Code
session**: this session already has the earlier hook modules loaded, so the new code applies
from the next hook process, but a fresh session removes any doubt. Retry with the exact
confirmation command from the preview.

Conditions:

- The lead must see **exactly one** `request_id` and `run_id`, identical in the Submit context
  and the `/solve` body. Any second envelope, or a bridge error, means stop.
- Run a fresh `project preview` first if anything may have changed. `--expected-basis` is
  recomputed before spend and in the write transaction, and a changed basis is refused.
- Production Direct EXECUTE stays disabled. This GO covers `--merchant-target test` only.
