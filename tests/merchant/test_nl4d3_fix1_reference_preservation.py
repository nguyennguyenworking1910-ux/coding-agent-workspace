"""CP12H.NL4D3-FIX1: the procurement reference is preserved exactly as typed.

Live failure: "Ghi nhận Purchase Order PO-NL4D3-001 cho Project Beta NL4C2B
Step Acceptance trên database test" was previewed with the reference
"NL4D3-001" (and PR-NL4D3-001 likewise). Every stage before
``evidence_preview._reference`` carried the full text; that extractor
restarted its match after the "PO-" prefix.

A reference is a whole token: never shortened, never rebuilt. The only
normalizations are documented and safe: surrounding quotes or brackets and
trailing sentence punctuation (. , ! ? :) are removed, and the token is NFC
normalized. Anything ambiguous or unsafe asks instead (NEEDS_CLARIFICATION).
"""

from __future__ import annotations

import copy
import json
import unicodedata

import pytest

from claude.agents.tools.merchant.evidence_preview import BLOCKED, CLARIFY, VALID
from tests.merchant.test_nl2e_p1_p2_p4 import CLI, LEAD, MM, isolated, post_bash, spawn  # noqa: F401
from tests.merchant.test_nl4a_project_status import decide
from tests.merchant.test_nl4d2_evidence_discovery import NAMED, P, EvidenceReader, revision
from tests.merchant.test_nl4d3_evidence_write_previews import assert_grants_nothing, block, preview

LIVE_PO = ("Ghi nhận Purchase Order PO-NL4D3-001 cho Project Beta NL4C2B Step Acceptance "
           "trên database test")
LIVE_PR = ("Ghi nhận Purchase Request số PR-NL4D3-001 cho Project Beta NL4C2B Step Acceptance "
           "trên database test")


def live_reader(**kwargs):
    reader = EvidenceReader(**kwargs)
    reader.projects[0]["title"] = "Beta NL4C2B Step Acceptance"
    return reader


def reference(result):
    return result["requested_fields"].get("external_reference")


# ------------------------------------------------------------ the live requests


@pytest.mark.parametrize("text,expected,outcome", [
    (LIVE_PO, "PO-NL4D3-001", BLOCKED),     # needs a signed revision (unchanged)
    (LIVE_PR, "PR-NL4D3-001", VALID),
])
def test_the_live_requests_keep_the_exact_reference(text, expected, outcome):
    result = preview(text, live_reader())

    assert reference(result) == expected
    assert result["outcome"] == outcome
    assert result["project_id"] == P
    assert_grants_nothing(result)


def test_the_domain_receives_the_reference_unchanged():
    result = preview(LIVE_PR, live_reader())

    assert result["domain_validation"]["plan"]["external_id"] == "PR-NL4D3-001"
    # Domain semantics are unchanged: a PR on a no-procurement Project is
    # still valid, with the informational note.
    assert [n["code"] for n in result["policy_notes"]] == ["PROCUREMENT_NOT_REQUIRED"]


# ------------------------------------------------------------- reference shapes


@pytest.mark.parametrize("kind,ref", [
    ("Purchase Request", "PR-NL4D3-001"),
    ("Purchase Order", "PO-NL4D3-001"),
    ("Payment Request", "PAY-NL4D3-001"),
    ("Purchase Request", "PR-2026-0001"),
    ("Purchase Order", "PO/2026/001"),
    ("Purchase Request", "PR_2026_001"),
    ("Purchase Request", "ABC-123-XYZ"),
    ("Purchase Request", "pr-nl4d3-001"),
    ("Purchase Request", "ĐH-2026-001"),
    ("Purchase Request", "PR.2026.001"),
])
def test_a_reference_is_kept_whole(kind, ref):
    result = preview(f"Ghi nhận {kind} {ref} cho {NAMED}.",
                     EvidenceReader(revisions=[revision(P, 1, signed=True)]))

    assert reference(result) == ref


@pytest.mark.parametrize("written", [
    '"PR-NL4D3-001"', "'PR-NL4D3-001'", "`PR-NL4D3-001`", "“PR-NL4D3-001”",
    "(PR-NL4D3-001)", "PR-NL4D3-001,", "PR-NL4D3-001:", "số PR-NL4D3-001",
    "number PR-NL4D3-001", "#PR-NL4D3-001",
])
def test_quotes_brackets_and_sentence_punctuation_are_the_only_normalization(written):
    result = preview(f"Ghi nhận Purchase Request {written} cho {NAMED}.")

    assert reference(result) == "PR-NL4D3-001"


def test_a_decomposed_unicode_reference_is_nfc_normalized():
    ref = unicodedata.normalize("NFD", "ĐH-Hà-2026-001")
    result = preview(f"Ghi nhận Purchase Request {ref} cho {NAMED}.")

    assert reference(result) == unicodedata.normalize("NFC", ref)


def test_a_bare_number_counts_only_after_a_keyword_or_the_record_name():
    anchored = preview(f"Ghi nhận Purchase Request số 2026001 cho {NAMED}.")
    named = preview(f"Ghi nhận Purchase Request 2026001 cho {NAMED}.")
    prose = preview(f"Ghi nhận Purchase Request PR-7 cho {NAMED} năm 2026.")

    assert reference(anchored) == "2026001"
    assert reference(named) == "2026001"
    assert reference(prose) == "PR-7"


def test_a_project_title_token_is_never_the_reference():
    result = preview("Ghi nhận Purchase Request NL4C2B-001 cho Project Beta NL4C2B Step Acceptance",
                     live_reader())

    assert reference(result) == "NL4C2B-001"


# ------------------------------------------------------- fail closed: ask


@pytest.mark.parametrize("text", [
    f"Ghi nhận Purchase Request PR-001 và PR-002 cho {NAMED}",               # two references
    f"Ghi nhận Purchase Request PR-001 thay cho PR-000 cho {NAMED}",
    f"Ghi nhận Purchase Request PR-001\nPR-002 cho {NAMED}",                  # newline
    f"Ghi nhận Purchase Request cho {NAMED}",                                  # missing
    f"Ghi nhận Purchase Request PR - 001 cho {NAMED}",                         # spaced
    f'Ghi nhận Purchase Request "PR 001" cho {NAMED}',                         # quoted, spaced
    f"Ghi nhận Purchase Request PR-001';DROP TABLE merchant_ops.projects;-- cho {NAMED}",
    f"Ghi nhận Purchase Request PR-001;rm cho {NAMED}",
    f"Ghi nhận Purchase Request PR-001$(whoami) cho {NAMED}",
    f"Ghi nhận Purchase Request PR-001|ls cho {NAMED}",
    f"Ghi nhận Purchase Request PR-001&& cho {NAMED}",
    f"Ghi nhận Purchase Request PR-001> cho {NAMED}",
    f"Ghi nhận Purchase Request PR-\x00001 cho {NAMED}",                        # control char
    f"Ghi nhận Purchase Request PR-001\x1b[2J cho {NAMED}",
    f"Ghi nhận Purchase Request PR-001- cho {NAMED}",                           # dangling separator
])
def test_ambiguous_or_unsafe_references_ask(text):
    result = preview(text)

    assert result["outcome"] == CLARIFY
    assert result["missing_required_fields"] == ["external_reference"]
    assert reference(result) is None
    assert result["domain_validation"]["status"] == "NOT_EVALUATED"
    assert_grants_nothing(result)


@pytest.mark.parametrize("text", [
    f"Ghi nhận Purchase Request PR-NL4D3-001 cho {NAMED} rồi xóa Merchant Beta Cinemas",
    f"Đừng ghi nhận Purchase Request PR-NL4D3-001 cho {NAMED}",
])
def test_mixed_or_negated_requests_still_ask(text):
    result = preview(text)

    assert result["outcome"] == CLARIFY
    assert_grants_nothing(result)


def test_domain_rules_are_unchanged_for_an_exact_reference():
    too_long = preview(f"Ghi nhận Purchase Request PR-{'9' * 120} cho {NAMED}.")
    payment = preview(f"Ghi nhận Payment Request PAY-NL4D3-001 cho {NAMED}.",
                      EvidenceReader(revisions=[revision(P, 1, signed=True)]))

    assert too_long["outcome"] == BLOCKED                       # the domain's 100-character rule
    assert payment["outcome"] == BLOCKED                         # needs a Purchase Order number
    assert reference(payment) == "PAY-NL4D3-001"


# ------------------------------------------------------- delivery integrity


@pytest.fixture
def live_run(isolated, monkeypatch):
    from claude.hooks import harness_team_identity

    assert spawn(isolated) is None
    monkeypatch.setattr(harness_team_identity, "verified_teammate_pane",
                        lambda owner, name: "7000:%7" if (owner, name) == (LEAD, MM) else None)
    result = preview(LIVE_PR, live_reader())
    command = f'{CLI} evidence preview --request "{LIVE_PR}" --test-database'
    return result, command, json.dumps(result, ensure_ascii=False, indent=2)


def test_the_teammate_cannot_change_the_delivered_reference(live_run):
    from claude.hooks import merchant_preview_delivery

    result, command, stdout = live_run
    assert merchant_preview_delivery.record_preview_evidence(post_bash(command, stdout))

    assert decide(f"PR-NL4D3-001 would be recorded; nothing was changed.\n{block(result)}") is None
    for altered in ("NL4D3-001", "PR-NL4D3-002", "PR-NL4D3-001 "):
        forged = copy.deepcopy(result)
        forged["requested_fields"]["external_reference"] = altered
        assert decide(block(forged)) is not None, altered
