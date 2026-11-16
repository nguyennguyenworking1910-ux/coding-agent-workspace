# CP12H.NL3A — Natural Language Project Understanding

Date: 2026-11-04 · Branch `feat/cp7-9-merchant-reliability` · Baseline `96c3c0e`

The uncommitted NL3 changes are preserved. Nothing was committed or pushed, and no live `/solve` Project Create was run.

## 1. Reproduction

Live run on 2026-11-04: lead `49f7c713`, teammate transcript `dd6e8672`. The request was:

> Tạo Project mở rạp Beta NL3 Confirmation Test cho Merchant Beta Cinemas trên database test, không cần Purchase Requisition

The folded text is `tao project mo rap beta nl3 confirmation test cho merchant beta cinemas tren database test khong can purchase requisition`.

Reproduced offline with the live catalog (`NL2_LIVE_BETA` "Beta Cinemas"):

| Field | Extracted | Result |
|---|---|---|
| merchant_phrase | `Merchant Beta Cinemas` | No existing Merchant matches |
| site_phrase | `Beta NL3 Confirmation Test` | correct |
| title | none | asks for the Project name |
| requires_procurement | `None` | asks whether procurement is required |

## 2. Root causes

| # | Symptom | Exact rule | Status |
|---|---|---|---|
| 1 | The Merchant phrase was "Merchant Beta Cinemas" | `_Words._phrase` skips only `_LEAD_WORDS` (`the a rap cinema project projects`). A role label after the anchor (`cho Merchant …`, `under merchant …`, `cho đối tác …`) stays in the phrase, and `_resolve_merchant` → `_leading_merchant` finds nothing for any leading part of "Merchant Beta Cinemas". | Fixed |
| 2 | "Title missing" | **Not a separate parser bug.** The site was extracted correctly. `_title()` builds the title only once the Merchant resolves, so it fails as a consequence of #1. The same request without "Merchant" was already READY with title `Beta NL3 Confirmation Test`. | Fixed by #1, and test-pinned |
| 3 | Procurement was not understood | The procurement noun regex in `_requires_procurement` had `purchase request` but not `purchase requisition`. The negation set had no "skip" form (`bỏ bước`, `bỏ qua`). | Fixed |
| 4 | A valid clarification was shown as a "delivery failure" | In `preview_delivery_decision`, `_READY_CLAIM` matched the **negated** prose "the outcome is not READY_FOR_CONFIRMATION". The gate denied the teammate's honest NEEDS_CLARIFICATION report and told it to relabel the *verified* result as `PREVIEW_DELIVERY_FAILED`. The lead then reported a delivery failure for a preview that had worked. | Fixed |

## 3. Parser and gate changes (78 lines across 4 files)

**`project_nl.py`**
- New `without_role_label(phrase)`. It strips one leading role label (`merchant(s)`, `đối tác`, `partner`, `nhà cung cấp`) only when more words follow.
- `_requires_procurement`:
  - The noun now covers `purchase requisition(s)` and `purchase request(s)`.
  - Negations now include `skip`, `bỏ qua` and `bỏ bước`. A bare `bỏ` is deliberately excluded, because it also folds from `bộ` ("bộ phận" = department).
  - Purchase Order and Payment Request are **not** procurement nouns.

**`project_preview.py` (`_resolve_merchant`)**
- The phrase is resolved **as written first**. Only when nothing matches and the phrase starts with a label is it retried without the label.
- So a Merchant actually named "Partner Cinemas" keeps its name.
- Resolution is still against the authoritative catalog. CANDIDATE matches keep `merchant_confirmation_required: true`, and ambiguity is still refused.

**`merchant_preview_delivery.py` (`preview_delivery_decision`)**
- A negated readiness mention ("not / không / chưa … READY_FOR_CONFIRMATION") is not a READY claim.
- For a **VERIFIED non-READY** preview (NEEDS_CLARIFICATION or BLOCKED):
  - a plain report of that outcome is delivered unchanged;
  - an operation block, argv, `--merchant-scope`, an affirmative READY claim, or a `PREVIEW_DELIVERY_FAILED` label is denied, with one instruction: resend as that outcome.
- UNVERIFIED and missing evidence keep the existing `PREVIEW_DELIVERY_FAILED` path. The READY path is unchanged.
- **Net effect: stricter, not weaker.** A verified clarification can no longer be mislabelled, and every operation-carrying report is still denied.

**`merchant-manager.md`**
- NEEDS_CLARIFICATION and BLOCKED are reported as that outcome, never as `PREVIEW_DELIVERY_FAILED`.

**Unchanged:** workflow templates, the PR/PO/Payment Request dependencies, the delivery contract fields, intent routing, and `RUNTIME_DIRECT_EXECUTE_ENABLED = False`.

## 4. RED/GREEN

`tests/merchant/test_nl3a_natural_language.py` has 34 tests.

| Stage | Result |
|---|---|
| RED: tests only, no fix | **18 failed**, 16 passed. The 16 are guard cases that must already hold: a Merchant named with a label word, a label-only phrase, candidate confirmation, ambiguity, a missing title, and PO and Payment Request not counting as procurement. |
| Fixes #1 and #3 | 5 failed (all delivery), 29 passed |
| Fix #4 | **34 passed** |

Coverage:

| Area | Tests |
|---|---|
| Exact live request | READY, `NL2_LIVE_BETA` by NAME (no candidate confirmation needed), title `Beta NL3 Confirmation Test`, `requires_procurement: false`, `NOT_AUTHORIZED`, `authorization: null`, `executable: false` |
| Role labels | `cho Merchant`, `cho merchant`, `cho đối tác`, `của`, `under merchant`, `under partner`; "Partner Cinemas" keeps its name; a label alone names no Merchant |
| Title and site | four Vietnamese/English forms with Unicode preserved in the title, argv and confirmation_command; a missing site asks for a name (no invented title) |
| Candidate and ambiguity | "Beta" alone gives CANDIDATE with `merchant_confirmation_required: true`; Beta Cinemas vs Beta Media gives no operation |
| Procurement | 7 negated PR phrases give `false`; "cần PR" and "cần mua sắm" give `true`; "không cần Purchase Order", "không cần Payment Request" and "bộ phận … Payment Request" give `None` |
| PR/PO/Payment Request | steps 6–7 (Purchase Request) SKIPPED; step 10 Purchase Order and step 11 Payment Request PENDING; 22 steps |
| Delivery | the live clarification report is delivered as-is; a verified clarification labelled `PREVIEW_DELIVERY_FAILED` is denied; a READY claim, an argv or `--merchant-scope`, or an operation block is still denied |

`tests/merchant/test_nl3a_natural_language_postgres.py` (1 test) runs the exact live request against the **real** test database Merchant `NL2_LIVE_BETA`. It returns READY with the expected operation, steps 6/7 SKIPPED and 10/11 PENDING. The whole-table snapshot is identical before and after (no mutation). This test was written after the fix. Its RED equivalent is the unit test above, which uses the same code path, and the original live failure.

The neighbouring suites (NL1 preview and routing, NL2E P1/P2/P4 and P4 delivery, NL2F, NL3) passed: **257 passed** together with NL3A.

## 5. Full regression

Run alone on the final code, 09:30:40–09:38:26Z: **3774 passed, 20 skipped, 1 xfailed, 97 subtests passed**, exit 0. That is the 3739 after NL3 plus 35 new tests, with no regressions.

| Check | Result |
|---|---|
| `system_test.py` | 80/80 |
| `git diff --check` | clean |
| `RUNTIME_DIRECT_EXECUTE_ENABLED` | `False` (`merchant_direct_handoff.py:63`) |
| Test DB integrity | **byte-identical** to the RC1 baseline (sha256 `a4a2fd39…a795`). The live Project, claims, ledger and fixtures are unchanged and no orphans remain. The runtime database was never opened: every test is test-role only. |

## 6. Live acceptance readiness

Retry with:

```
/solve Tạo Project mở rạp Beta NL3 Confirmation Test cho Merchant Beta Cinemas trên database test, không cần Purchase Requisition
```

Expected result:

1. A read-only preview with outcome `READY_FOR_CONFIRMATION`:
   - Merchant `NL2_LIVE_BETA`, matched by NAME
   - title `Beta NL3 Confirmation Test`
   - `requires_procurement: false`
   - steps 6–7 SKIPPED
   - the lead shows `/solve Xác nhận tạo <id8>`
2. Then type `/solve Xác nhận tạo <id8>`. The hook shows the exact operation, and the NL3 flow executes once on the test database.

## 7. Remaining limitations

1. **Rule-based parser.** The rules cover the phrases above and the existing corpus. New paraphrases may still produce NEEDS_CLARIFICATION, which fails safe (no invented fields).
2. **Title rule is unchanged.** When the site does not begin with the Merchant's name ("mở rạp Nguyễn Văn Cừ cho Beta Cinemas"), the title is `<matched Merchant text> <site>` ("Beta Cinemas Nguyễn Văn Cừ"). There is still no explicit "tên dự án là …" title syntax; adding one would be a new feature.
3. **Label stripping.** Only one leading label is stripped, and only as a fallback after an exact attempt fails.
4. **Negated readiness detection** looks back at most two words.
5. **Procurement phrasing.** "Purchase Requisition" and "PR" are treated as the procurement step. A user who says "PR" meaning something else would get `requires_procurement: false/true` from that word.

## 8. Recommendation

**GO for retrying the NL3 preview and the conversational confirmation on the test database.**

- The exact live request now previews READY offline and against the real `NL2_LIVE_BETA` row.
- A verified clarification is now delivered as a clarification.
- Fail-closed behaviour is intact.
- The full regression, `system_test.py` and database integrity all pass.

The confirmation step needs a fresh confirmation typed by the user.

**NO-GO for runtime.** Runtime Direct EXECUTE remains disabled.
