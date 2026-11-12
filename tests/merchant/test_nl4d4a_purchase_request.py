"""CP12H.NL4D4A: trusted Purchase Request confirmation (no database).

Approved policies: DEC-A0 (trusted local recording operator), DEC-P1a
(reference unique per Merchant and type), DEC-P1c (no reference
replacement), DEC-P2 (allowed when requires_procurement=false, with a note).

A valid new Purchase Request preview on the test database, judged with the
trusted operator, carries a NOT_AUTHORIZED operation; only the trusted
PostToolUse capture records it; only the user's own ``/solve Xác nhận ghi
nhận`` spends it; the preflight refuses anything that is not that exact
operation with the same operator, before any spend or database connection.
"""

from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace

import pytest

from claude.agents.tools.merchant import purchase_request as pr_contract
from claude.agents.tools.merchant.evidence_preview import BLOCKED, CLARIFY, VALID, build_evidence_preview
from claude.clients.merchant import operator_identity
from claude.hooks import merchant_direct_handoff as handoff
from claude.hooks import merchant_pending_confirmation as pending
from claude.hooks import merchant_preview_delivery
from claude.system.merchant_runtime_handoff import MerchantRuntimeHandoffError, validate_direct_scope
from tests.merchant.test_nl4b_fix1_routing_and_teammate import BUG_FIXER, parse
from tests.merchant.test_nl2e_p1_p2_p4 import (  # noqa: F401 (fixtures)
    CLI,
    LEAD,
    MM,
    intent_gate,
    isolated,
    post_bash,
    runtime_state,
    spawn,
)
from tests.merchant.test_nl4a_project_status import decide
from tests.merchant.test_nl4d2_evidence_discovery import (
    NAMED,
    P,
    P_LOTTE,
    P_PROC,
    P_TWIN,
    EvidenceReader,
    pr,
)

OPERATOR = "0d4a0000-0000-4000-8000-0000000000a0"
OTHER_OPERATOR = "0d4a0000-0000-4000-8000-0000000000b0"
OTHER_SESSION = "another-lead-session"
PROC = NAMED + " Procurement"
REQUEST = f"Ghi nhận Purchase Request PR-NL4D4A-001 cho {NAMED} trên database test"


@pytest.fixture(autouse=True)
def trusted_operator(monkeypatch):
    monkeypatch.setenv(operator_identity.OPERATOR_ENV, OPERATOR)


def preview(text=REQUEST, reader=None, target="test", operator="trusted"):
    status = operator_identity.operator_status() if operator == "trusted" else operator
    result = build_evidence_preview(text, reader or EvidenceReader(), database_target=target,
                                    operator=status)
    return json.loads(json.dumps(result, default=str))


def operation_of(text=REQUEST, reader=None):
    result = preview(text, reader)
    assert result["outcome"] == VALID, result["domain_validation"]
    assert result["requested_operation"] is not None, result["confirmation_blockers"]
    return result["requested_operation"]


def submit(text, session=LEAD, parser=None):
    class Replayed:
        def parse(self, request):
            return parse(request, BUG_FIXER)

    return intent_gate.run(
        {"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": text},
        parser_factory=parser or Replayed, env={},
    )


def put(operation, session=LEAD):
    return pending.record_pending_purchase_request(
        session, operation, run_id="run-src", task_id="task-src")


def status_of(session=LEAD):
    return [r["status"] for r in pending.load_records(session, pending.PURCHASE_REQUEST_KIND)]


def confirmed(operation):
    put(operation)
    output = submit("/solve Xác nhận ghi nhận")
    assert output.get("decision") != "block", output
    return runtime_state.load_state(LEAD)["run_id"]


def attempt(operation, *, run_id, owner=LEAD, argv=None, target="test"):
    return SimpleNamespace(
        owner_session_id=owner, teammate_name="merchant-manager", run_id=run_id,
        task_id="task-1", command="procurement update", database_target=target,
        arguments=tuple(argv if argv is not None else operation["argv"]),
    )


@pytest.fixture
def no_database(monkeypatch):
    def connect(_target):
        raise AssertionError("refused attempts never reach the database")

    monkeypatch.setattr(handoff, "_target_repository", connect)


def refused(attempt_):
    with pytest.raises(handoff.DirectPreflightRefused) as error:
        handoff.preflight_direct_execute(attempt_)
    return error.value.reason


# --------------------------------------------------------- DEC-A0: operator


@pytest.mark.parametrize("value,reason", [
    (None, "OPERATOR_IDENTITY_UNAVAILABLE"),
    ("", "OPERATOR_IDENTITY_UNAVAILABLE"),
    ("   ", "OPERATOR_IDENTITY_UNAVAILABLE"),
    ("not-a-uuid", "OPERATOR_IDENTITY_INVALID"),
    (OPERATOR.upper(), "OPERATOR_IDENTITY_INVALID"),
    (f" {OPERATOR}", "OPERATOR_IDENTITY_INVALID"),
    ("{" + OPERATOR + "}", "OPERATOR_IDENTITY_INVALID"),
    (OPERATOR.replace("-", ""), "OPERATOR_IDENTITY_INVALID"),
    ("00000000-0000-0000-0000-000000000000", "OPERATOR_IDENTITY_INVALID"),
])
def test_missing_or_malformed_operator_identity_is_refused(monkeypatch, value, reason):
    if value is None:
        monkeypatch.delenv(operator_identity.OPERATOR_ENV, raising=False)
    else:
        monkeypatch.setenv(operator_identity.OPERATOR_ENV, value)

    with pytest.raises(operator_identity.OperatorIdentityError) as error:
        operator_identity.trusted_operator_id()
    assert error.value.reason == reason

    result = preview()
    assert result["outcome"] == VALID                       # the domain still accepts it
    assert result["requested_operation"] is None
    assert result["confirmation_available"] is False
    assert result["confirmation_blockers"] == [reason]


def test_the_operator_never_comes_from_the_request_or_a_teammate():
    assert preview()["requested_operation"]["operator_id"] == OPERATOR
    # An operator named in the request is never read as one: the operation,
    # when there is one, still names only the configured operator.
    for forged in (f"{REQUEST} bởi operator Mallory", f"{REQUEST} operator {OTHER_OPERATOR}",
                   f"{REQUEST} --operator-id {OTHER_OPERATOR}"):
        operation = preview(forged)["requested_operation"]
        assert operation is None or operation["operator_id"] == OPERATOR
        assert OTHER_OPERATOR not in json.dumps(operation)
    # A preview without the trusted status (as a teammate could build) has none.
    assert preview(operator=None)["requested_operation"] is None
    with pytest.raises(operator_identity.OperatorIdentityError):
        operator_identity.require_operator(OTHER_OPERATOR)


# ------------------------------------------------- preview and operation


def test_a_valid_new_purchase_request_carries_its_exact_operation_as_data():
    result = preview()
    operation = result["requested_operation"]

    assert result["confirmation_available"] is True and result["executable"] is False
    assert result["authorization"] is None and result["read_only"] is True
    assert result["recording_operator"] == {"status": "TRUSTED", "operator_id": OPERATOR}
    assert operation["status"] == "NOT_AUTHORIZED" and operation["database_target"] == "test"
    assert (operation["project_id"], operation["reference"]) == (P, "PR-NL4D4A-001")
    assert operation["argv"] == [
        "procurement", "update", P, "--type", "PURCHASE_REQUEST",
        "--external-id", "PR-NL4D4A-001", "--merchant-code", "NL2_LIVE_BETA",
        "--operator-id", OPERATOR, "--expected-basis", operation["expected_basis"],
    ]
    assert operation["project_title"] == "Beta Nguyễn Văn Cừ Evidence"   # UTF-8 kept


def test_requires_procurement_false_is_allowed_with_the_informational_note():
    result = preview()                                      # Project P: requires_procurement=false

    assert result["resolved"]["project"]["requires_procurement"] is False
    assert [n["code"] for n in result["policy_notes"]] == ["PROCUREMENT_NOT_REQUIRED"]
    assert result["requested_operation"]["requires_procurement"] is False


def test_a_runtime_preview_is_never_confirmable():
    result = preview(target="runtime")

    assert result["outcome"] == VALID
    assert result["requested_operation"] is None
    assert result["confirmation_blockers"] == ["RUNTIME_EXECUTION_DISABLED"]


def test_a_duplicate_reference_on_another_project_of_the_merchant_is_blocked():
    reader = EvidenceReader(procurement=[dict(pr("PR-NL4D4A-001"), project_id=P_TWIN)])
    result = preview(reader=reader)

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == "PROCUREMENT_REFERENCE_DUPLICATE"
    assert result["requested_operation"] is None


def test_the_same_reference_at_another_merchant_is_allowed():
    reader = EvidenceReader(procurement=[dict(pr("PR-NL4D4A-001"), project_id=P_LOTTE)])

    assert operation_of(reader=reader)["reference"] == "PR-NL4D4A-001"


def test_the_same_reference_of_another_type_is_allowed():
    reader = EvidenceReader(procurement=[dict(pr("PR-NL4D4A-001"), project_id=P_TWIN,
                                              procurement_type="PURCHASE_ORDER")])

    assert operation_of(reader=reader)["reference"] == "PR-NL4D4A-001"


def test_a_reference_replacement_is_blocked():
    reader = EvidenceReader(procurement=[pr("PR-OLD")])
    result = preview(f"Ghi nhận Purchase Request PR-NEW-2 cho {PROC}", reader)

    assert result["outcome"] == BLOCKED
    assert result["domain_validation"]["error"]["code"] == (
        "PROCUREMENT_REFERENCE_REPLACEMENT_UNSUPPORTED")


def test_an_existing_purchase_request_record_is_never_confirmable():
    reader = EvidenceReader(procurement=[pr(None)])        # status only, no reference
    result = preview(f"Ghi nhận Purchase Request PR-NEW-2 cho {PROC}", reader)

    assert result["outcome"] == VALID                       # domain: an UPDATE
    assert result["domain_validation"]["plan"]["operation"] == "UPDATE"
    assert result["requested_operation"] is None
    assert result["confirmation_blockers"] == ["PURCHASE_REQUEST_ALREADY_RECORDED"]


@pytest.mark.parametrize("text", [
    f"Ghi nhận Purchase Order PO-1 cho {NAMED}",
    f"Ghi nhận Payment Request PAY-1 cho {NAMED}",
    f"Ghi nhận LEGAL đã phê duyệt CONTRACT cho {NAMED}",
    f"Ghi nhận CONTRACT revision hash abc cho {NAMED}",
    f"Ghi nhận Purchase Request PR-1 cho {NAMED} rồi xóa Merchant Beta Cinemas",
])
def test_no_other_evidence_write_is_ever_confirmable(text):
    result = preview(text)

    assert result["requested_operation"] is None
    assert result["confirmation_available"] is False


@pytest.mark.parametrize("edit", [
    lambda o: o.update(reference="PR-OTHER"),
    lambda o: o.update(operator_id=OTHER_OPERATOR),
    lambda o: o.update(database_target="runtime"),
    lambda o: o.update(status="AUTHORIZED"),
    lambda o: o.update(expected_basis="0" * 63),
    lambda o: o.update(project_version=True),
    lambda o: o.update(argv=o["argv"] + ["--status", "SUBMITTED"]),
    lambda o: o.update(argv=o["argv"][:6] + o["argv"][8:] + o["argv"][6:8]),
    lambda o: o.update(reference="-PR-1", argv=pr_contract.canonical_purchase_request_argv(
        {**o, "reference": "-PR-1"})),
    lambda o: o.update(reference="PR 1", argv=pr_contract.canonical_purchase_request_argv(
        {**o, "reference": "PR 1"})),
    lambda o: o.update(procurement_type="PURCHASE_ORDER"),
])
def test_edited_operations_are_rejected(edit):
    operation = operation_of()
    edit(operation)

    with pytest.raises(ValueError):
        pr_contract.validate_operation(operation)


# ------------------------------------------------- trusted capture (Post)


@pytest.fixture
def capture_run(isolated, monkeypatch):
    from claude.hooks import harness_team_identity

    assert spawn(isolated) is None
    monkeypatch.setattr(harness_team_identity, "verified_teammate_pane",
                        lambda owner, name: "7000:%7" if (owner, name) == (LEAD, MM) else None)
    command = f'{CLI} evidence preview --request "{REQUEST}" --test-database'
    return preview(), command


def capture(command, result):
    return merchant_preview_delivery.record_preview_evidence(
        post_bash(command, json.dumps(result, ensure_ascii=False, indent=2)))


def block(result):
    marker = merchant_preview_delivery.EVIDENCE_PREVIEW_MARKER
    return f"{marker}\n{json.dumps(result, ensure_ascii=False, separators=(',', ':'))}"


def test_a_verified_capture_is_the_only_creator_of_a_pending_purchase_request(capture_run):
    result, command = capture_run

    assert capture(command, result) is True
    (record,) = pending.live_records(LEAD, pending.PURCHASE_REQUEST_KIND)
    assert record["operation"] == result["requested_operation"]
    assert (record["operator_id"], record["reference"]) == (OPERATOR, "PR-NL4D4A-001")
    # Delivered exactly, the report is accepted.
    assert decide(f"PR-NL4D4A-001 can be recorded.\n{block(result)}") is None


@pytest.mark.parametrize("forge", [
    lambda r: r["requested_operation"].update(operator_id=OTHER_OPERATOR),
    lambda r: r["requested_operation"].update(reference="PR-NL4D4A-002"),
    lambda r: r.update(confirmation_available=False),
    lambda r: r.update(outcome="BLOCKED"),
    lambda r: r.update(evidence_type="PURCHASE_ORDER"),
    lambda r: r["requested_fields"].update(external_reference="PR-NL4D4A-002"),
    lambda r: r.update(requested_operation=None),
])
def test_a_forged_or_inconsistent_capture_records_nothing(capture_run, forge):
    result, command = capture_run
    forged = copy.deepcopy(result)
    forge(forged)

    assert capture(command, forged) is False
    assert pending.load_records(LEAD, pending.PURCHASE_REQUEST_KIND) == []


def test_a_capture_with_another_operator_than_the_hook_resolves_is_unverified(
        capture_run, monkeypatch):
    result, command = capture_run
    monkeypatch.setenv(operator_identity.OPERATOR_ENV, OTHER_OPERATOR)  # changed after preview

    assert capture(command, result) is False
    assert pending.load_records(LEAD, pending.PURCHASE_REQUEST_KIND) == []


# ----------------------------------------------------- confirmation (gate)


def test_valid_confirmation_yields_the_recorded_scope(isolated):
    operation = operation_of()
    put(operation)

    output = submit("/solve Xác nhận ghi nhận")

    state = runtime_state.load_state(LEAD)
    assert state["merchant_scope"]["argv"] == operation["argv"]
    assert state["merchant_scope"]["command"] == "procurement update"
    assert state["merchant_scope"]["database_target"] == "test"
    assert "PR-NL4D4A-001" in output["systemMessage"] and OPERATOR in output["systemMessage"]
    assert status_of() == ["CONFIRMED"]


def test_replayed_confirmation_is_refused(isolated):
    confirmed(operation_of())
    run_id = runtime_state.load_state(LEAD)["run_id"]

    output = submit("/solve Xác nhận ghi nhận")

    assert output["decision"] == "block" and "no pending Purchase Request" in output["reason"]
    assert runtime_state.load_state(LEAD)["run_id"] == run_id


def test_wrong_session_cannot_confirm(isolated):
    put(operation_of())

    assert submit("/solve Xác nhận ghi nhận", session=OTHER_SESSION)["decision"] == "block"
    assert status_of() == ["PENDING"]


def test_expired_confirmation_is_refused(isolated, monkeypatch):
    put(operation_of())
    monkeypatch.setattr(pending, "_now", lambda: time.time() + pending.PENDING_TTL_SECONDS + 1)

    assert submit("/solve Xác nhận ghi nhận")["decision"] == "block"
    assert status_of() == ["PENDING"]                       # never spent, simply expired


@pytest.mark.parametrize("change", [
    lambda mp: mp.setenv(operator_identity.OPERATOR_ENV, OTHER_OPERATOR),
    lambda mp: mp.delenv(operator_identity.OPERATOR_ENV),
    lambda mp: mp.setenv(operator_identity.OPERATOR_ENV, "garbage"),
])
def test_operator_substitution_before_confirmation_is_refused_unspent(isolated, monkeypatch, change):
    put(operation_of())
    change(monkeypatch)

    output = submit("/solve Xác nhận ghi nhận")

    assert output["decision"] == "block" and "recording operator" in output["reason"]
    assert status_of() == ["PENDING"]


@pytest.mark.parametrize("target", [None, "test"])
def test_a_handwritten_scope_is_never_authority(isolated, target):
    operation = operation_of()
    prefix = "/solve --confirm" + (f" --merchant-target {target}" if target else "")

    output = submit(f"{prefix} --merchant-scope {json.dumps(operation['argv'])} Record the PR")

    assert output["decision"] == "block"
    assert "Xác nhận ghi nhận" in output["reason"]
    assert runtime_state.load_state(LEAD) is None


@pytest.mark.parametrize("prompt", [
    "/solve Xác nhận ghi nhận PR-OTHER",
    "/solve Xác nhận ghi nhận trên database runtime",
    "/solve Xác nhận ghi nhận rồi xóa Merchant Beta Cinemas",
])
def test_an_edited_or_mixed_confirmation_is_not_a_confirmation(isolated, prompt):
    put(operation_of())

    class NeverConfirms:
        def parse(self, request):
            raise RuntimeError("not a confirmation: classified as ordinary text")

    output = submit(prompt, parser=NeverConfirms)

    assert output.get("decision") == "block"
    assert status_of() == ["PENDING"]


def test_cancel_and_bare_phrase_and_scheduled_prompt(isolated):
    put(operation_of())

    assert "type `/solve Xác nhận ghi nhận`" in pending.bare_phrase_guidance(
        LEAD, "Xác nhận ghi nhận")
    assert pending.scheduled_prompt_denial("CronCreate", {"prompt": "Xác nhận ghi nhận"})
    assert submit("/solve Hủy ghi nhận")["decision"] == "block"
    assert status_of() == ["CANCELLED"]


def test_a_purchase_request_record_never_confirms_another_kind(isolated):
    put(operation_of())

    assert submit("/solve Xác nhận cập nhật")["decision"] == "block"
    assert submit("/solve Xác nhận tạo")["decision"] == "block"
    assert status_of() == ["PENDING"]


# -------------------------------------------------------- scope validation


def test_the_canonical_scope_validates_and_a_reference_is_not_a_target_uuid():
    operation = operation_of()

    validated = validate_direct_scope(operation["argv"], "test")
    assert validated["command"] == "procurement update"


@pytest.mark.parametrize("argv", [
    lambda a: a + ["--status", "SUBMITTED"],
    lambda a: a + ["--triggered-by", OTHER_OPERATOR],
    lambda a: a + ["--procurement-id", OTHER_OPERATOR],
    lambda a: a[:7] + a[9:11] + a[7:9] + a[11:],          # reordered options
])
def test_a_non_canonical_purchase_request_scope_is_rejected(argv):
    operation = operation_of()

    with pytest.raises(MerchantRuntimeHandoffError):
        validate_direct_scope(argv(list(operation["argv"])), "test")


def test_a_retyped_scope_is_a_lifecycle_operation_that_needs_its_own_confirmation():
    """CP12H.MASTER: swapping the type for PURCHASE_ORDER gives the canonical
    *Purchase Order* argv form, so the scope syntax check accepts it; it can
    still only run as the user's own confirmed Purchase Order operation (the
    lifecycle preflight requires that pending record with the identical argv),
    never from a confirmed Purchase Request."""

    from claude.hooks.merchant_direct_handoff import is_lifecycle_attempt

    argv = list(operation_of()["argv"])
    retyped = argv[:4] + ["PURCHASE_ORDER"] + argv[5:]
    assert validate_direct_scope(retyped, "test")["command"] == "procurement update"
    assert is_lifecycle_attempt("procurement update", retyped, "test")
    assert not is_lifecycle_attempt("procurement update", argv, "test")


# ------------------------------------------------ preflight (before spend)


def test_scope_without_a_confirmed_record_is_refused(isolated, no_database):
    operation = operation_of()
    put(operation)

    assert refused(attempt(operation, run_id="run-x")) == "PURCHASE_REQUEST_CONFIRMATION_REQUIRED"
    assert status_of() == ["PENDING"]


def test_confirmation_of_another_run_or_session_is_refused(isolated, no_database):
    operation = operation_of()
    run_id = confirmed(operation)

    assert refused(attempt(operation, run_id="other")) == "PURCHASE_REQUEST_CONFIRMATION_REQUIRED"
    assert refused(attempt(operation, run_id=run_id, owner=OTHER_SESSION)) == (
        "PURCHASE_REQUEST_CONFIRMATION_REQUIRED")


@pytest.mark.parametrize("edit,target,reason", [
    (lambda a: a[:10] + [OTHER_OPERATOR] + a[11:], "test",            # model-generated actor
     "PURCHASE_REQUEST_CONFIRMATION_MISMATCH"),
    (lambda a: a[:6] + ["PR-NL4D4A-999"] + a[7:], "test", "PURCHASE_REQUEST_CONFIRMATION_MISMATCH"),
    (lambda a: a, "runtime", "RUNTIME_EXECUTION_DISABLED"),
], ids=["actor", "reference", "runtime"])
def test_changed_scope_is_refused(isolated, no_database, edit, target, reason):
    operation = operation_of()
    run_id = confirmed(operation)

    assert refused(attempt(operation, run_id=run_id, argv=edit(list(operation["argv"])),
                           target=target)) == reason


@pytest.mark.parametrize("change,reason", [
    (lambda mp: mp.setenv(operator_identity.OPERATOR_ENV, OTHER_OPERATOR),
     "OPERATOR_IDENTITY_CHANGED"),
    (lambda mp: mp.delenv(operator_identity.OPERATOR_ENV), "OPERATOR_IDENTITY_UNAVAILABLE"),
    (lambda mp: mp.setenv(operator_identity.OPERATOR_ENV, "x"), "OPERATOR_IDENTITY_INVALID"),
])
def test_operator_change_after_confirmation_is_refused_before_spend(
        isolated, no_database, monkeypatch, change, reason):
    operation = operation_of()
    run_id = confirmed(operation)
    change(monkeypatch)

    assert refused(attempt(operation, run_id=run_id)) == reason


def test_damaged_or_missing_record_is_refused(isolated, no_database):
    operation = operation_of()
    run_id = confirmed(operation)
    with pending._locked(LEAD, pending.PURCHASE_REQUEST_KIND) as records:
        records[0]["operation"]["reference"] = "PR-EDITED"          # argv no longer canonical
    assert refused(attempt(operation, run_id=run_id)) == "PURCHASE_REQUEST_CONFIRMATION_REQUIRED"

    pending.store_path(LEAD, pending.PURCHASE_REQUEST_KIND).unlink()
    assert refused(attempt(operation, run_id=run_id)) == "PURCHASE_REQUEST_CONFIRMATION_REQUIRED"


def test_a_step_or_project_store_never_authorizes_a_purchase_request(isolated, no_database):
    operation = operation_of()
    put(operation)
    with pending._locked(LEAD, pending.PURCHASE_REQUEST_KIND) as records:
        records[0].update(status=pending.CONFIRMED, confirmed_run_id="run-p")
    records = pending.load_records(LEAD, pending.PURCHASE_REQUEST_KIND)
    for kind in (pending.STEP_KIND, pending.PROJECT_KIND):
        pending.store_path(LEAD, kind).write_text(json.dumps(records), encoding="utf-8")
    pending.store_path(LEAD, pending.PURCHASE_REQUEST_KIND).unlink()

    assert refused(attempt(operation, run_id="run-p")) == "PURCHASE_REQUEST_CONFIRMATION_REQUIRED"


def test_valid_confirmation_reaches_the_database_rejudgement(isolated, monkeypatch):
    operation = operation_of()
    run_id = confirmed(operation)
    seen = []
    monkeypatch.setattr(handoff, "_target_repository", lambda target: seen.append(target) or "repo")
    monkeypatch.setattr(handoff, "_verify_purchase_request",
                        lambda attempt_, repository, op: seen.append((repository, op["reference"])))

    assert handoff.preflight_direct_execute(attempt(operation, run_id=run_id)) == "repo"
    assert seen == ["test", ("repo", "PR-NL4D4A-001")]


def test_runtime_stays_disabled_and_no_other_evidence_write_joined_test_mode():
    assert handoff.RUNTIME_DIRECT_EXECUTE_ENABLED is False
    assert not handoff.direct_execute_enabled("procurement update", "runtime")
    # CP12H.MASTER: these joined test mode, but only as the user's confirmed
    # lifecycle operation (lifecycle pending store); never on runtime.
    for command in ("document approve", "document revision-create", "project update",
                    "document sign"):
        assert handoff.direct_execute_enabled(command, "test")
        assert not handoff.direct_execute_enabled(command, "runtime")
    assert pr_contract.CONFIRMABLE_TARGETS == {"test"}


# --------------------------------------------- in-transaction re-judgement


class Reads:
    """In-memory reads for verify_purchase_request."""

    def __init__(self, reader):
        self.reader = reader

    def get_project_detail(self, project_id):
        return json.loads(json.dumps(self.reader.get_project_detail(project_id), default=str))

    def procurement_reference_holders(self, *args):
        return self.reader.procurement_reference_holders(*args)


def payload_of(operation):
    from claude.agents.tools.merchant import cli as merchant_cli

    args = merchant_cli.build_argument_parser().parse_args(
        ["--database", "runtime", *operation["argv"]])
    return merchant_cli.build_write_payload(args, "procurement update")


def test_verify_accepts_the_unchanged_operation_and_binds_the_operator():
    reader = EvidenceReader()
    operation = operation_of(reader=reader)

    plan = pr_contract.verify_purchase_request(Reads(reader), payload_of(operation), OPERATOR)
    assert (plan["operation"], plan["external_id"], plan["triggered_by"]) == (
        "INSERT", "PR-NL4D4A-001", OPERATOR)


@pytest.mark.parametrize("change,reason", [
    (lambda r: r.projects[0].update(version=5), "PURCHASE_REQUEST_BASIS_CHANGED"),
    (lambda r: r.procurement.append(dict(pr("PR-NL4D4A-001"), project_id=P_TWIN)),
     "PROCUREMENT_REFERENCE_DUPLICATE"),
    (lambda r: r.procurement.append(dict(pr("PR-X"), project_id=P)),
     "PROCUREMENT_REFERENCE_REPLACEMENT_UNSUPPORTED"),
    (lambda r: r.procurement.append(dict(pr("PR-NL4D4A-001"), project_id=P)),
     "PURCHASE_REQUEST_ALREADY_RECORDED"),
    (lambda r: r.procurement.append(dict(pr(None), project_id=P)),
     "PURCHASE_REQUEST_ALREADY_RECORDED"),
    (lambda r: r.projects[0].update(merchant_code="LOTTE"), "MERCHANT_MISMATCH"),
    (lambda r: r.projects[0].update(status="CANCELLED"), "PURCHASE_REQUEST_NOT_VALID"),
])
def test_verify_refuses_any_change_since_the_preview(change, reason):
    reader = EvidenceReader()
    operation = operation_of(reader=reader)
    change(reader)

    with pytest.raises(pr_contract.PurchaseRequestMismatch) as error:
        pr_contract.verify_purchase_request(Reads(reader), payload_of(operation), OPERATOR)
    assert error.value.reason == reason


def test_verify_refuses_another_operator_and_extra_fields():
    reader = EvidenceReader()
    payload = payload_of(operation_of(reader=reader))

    with pytest.raises(pr_contract.PurchaseRequestMismatch) as error:
        pr_contract.verify_purchase_request(Reads(reader), payload, OTHER_OPERATOR)
    assert error.value.reason == "OPERATOR_IDENTITY_CHANGED"

    for extra in ({"status": "SUBMITTED"}, {"triggered_by": OTHER_OPERATOR},
                  {"expected_version": 1}, {"procurement_type": "PURCHASE_ORDER"}):
        with pytest.raises(pr_contract.PurchaseRequestMismatch) as error:
            pr_contract.verify_purchase_request(Reads(reader), {**payload, **extra}, OPERATOR)
        assert error.value.reason == "PURCHASE_REQUEST_BASIS_REQUIRED"


def test_preview_and_verify_never_touch_a_project_title_reference():
    # P_PROC (requires procurement) also previews and verifies.
    reader = EvidenceReader()
    operation = operation_of(f"Ghi nhận Purchase Request PR-P1 cho {PROC}", reader)

    assert operation["project_id"] == P_PROC and operation["requires_procurement"] is True
    pr_contract.verify_purchase_request(Reads(reader), payload_of(operation), OPERATOR)


def test_a_clarifying_preview_carries_no_operation():
    result = preview(f"Ghi nhận Purchase Request cho {NAMED}")

    assert result["outcome"] == CLARIFY and result["requested_operation"] is None
