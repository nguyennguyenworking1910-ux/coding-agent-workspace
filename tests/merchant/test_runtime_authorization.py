"""Checkpoint 7.4 opaque, one-use Merchant runtime authorization tests."""

import copy
import inspect
import json
import pickle
import threading

import pytest

from claude.agents.tools.merchant.cli_contract import (
    MAX_RUNTIME_AUTHORIZATION_TTL_SECONDS,
    RuntimeApplyAuthorization,
    RuntimeAuthorizationConsumedError,
    RuntimeAuthorizationExpiredError,
    RuntimeWriteDeniedError,
    build_proposal,
    issue_runtime_apply_authorization,
    require_apply_authorization,
)
from claude.agents.tools.merchant.cli import (
    dispatch_write_command,
    main as merchant_cli_main,
)
from claude.agents.tools.merchant.write_commands import (
    MerchantWriteCommands,
)


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
PAYLOAD = {
    "project_id": PROJECT_ID,
    "status": "IN_PROGRESS",
    "expected_version": 3,
    "occurred_at": None,
    "triggered_by": None,
    "allow_reopen": False,
}


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


class RecordingHandler:
    def __init__(self, *, error=None):
        self.calls = []
        self.error = error

    def __call__(self, payload):
        self.calls.append(payload)

        if self.error is not None:
            raise self.error

        return {"status": "committed"}


def _proposal(payload=None):
    return build_proposal(
        "project update",
        "runtime",
        payload or PAYLOAD,
    ).to_dict()


def _receipt(confirmation, **changes):
    receipt = {
        "operation": "merchant_apply",
        "subagent_type": "merchant-manager",
        "teammate_name": "merchant-manager",
        "confirmation_hash": confirmation[
            "confirmation_hash"
        ],
    }
    receipt.update(changes)
    return receipt


def _authorization(*, clock=None, ttl_seconds=60.0):
    proposal = _proposal()
    confirmation = proposal["confirmation"]
    authorization = issue_runtime_apply_authorization(
        confirmation,
        _receipt(confirmation),
        ttl_seconds=ttl_seconds,
        clock=clock,
    )
    return proposal, authorization


def test_runtime_authorization_cannot_be_constructed_directly():
    with pytest.raises(
        RuntimeWriteDeniedError,
        match="issued only by trusted orchestration",
    ):
        RuntimeApplyAuthorization()

    with pytest.raises(
        RuntimeWriteDeniedError,
        match="issuer is not trusted",
    ):
        RuntimeApplyAuthorization._issued(
            {},
            expires_at=1.0,
            clock=lambda: 0.0,
            issuer_seal=object(),
        )


def test_boolean_authority_parameter_is_removed_from_apply_chain():
    signatures = (
        inspect.signature(require_apply_authorization),
        inspect.signature(MerchantWriteCommands.apply),
        inspect.signature(dispatch_write_command),
        inspect.signature(merchant_cli_main),
    )

    for signature in signatures:
        assert "runtime_authorized" not in signature.parameters


def test_boolean_or_plain_object_cannot_authorize_runtime_apply():
    for value in (True, 1, object(), {}):
        with pytest.raises(
            RuntimeWriteDeniedError,
            match="exact in-process authorization",
        ):
            require_apply_authorization(
                "project update",
                "runtime",
                runtime_authorization=value,
                payload=PAYLOAD,
                proposal_hash="0" * 64,
            )


def test_capability_is_not_copyable_picklable_or_json_serializable():
    _proposal_result, authorization = _authorization()

    with pytest.raises(TypeError):
        copy.copy(authorization)

    with pytest.raises(TypeError):
        copy.deepcopy(authorization)

    with pytest.raises(TypeError):
        pickle.dumps(authorization)

    with pytest.raises(TypeError):
        json.dumps(authorization)

    assert "token" not in repr(authorization).lower()
    assert "payload" not in repr(authorization).lower()


def test_exact_runtime_apply_consumes_capability_and_calls_handler_once():
    proposal, authorization = _authorization()
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": handler}
    )

    result = commands.apply(
        "project update",
        "runtime",
        PAYLOAD,
        proposal_hash=proposal["proposal_hash"],
        runtime_authorization=authorization,
    )

    assert result["success"] is True
    assert result["database"] == "runtime"
    assert authorization.consumed is True
    assert handler.calls == [PAYLOAD]


def test_successful_capability_cannot_be_replayed():
    proposal, authorization = _authorization()
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": handler}
    )

    commands.apply(
        "project update",
        "runtime",
        PAYLOAD,
        proposal_hash=proposal["proposal_hash"],
        runtime_authorization=authorization,
    )

    with pytest.raises(RuntimeAuthorizationConsumedError):
        commands.apply(
            "project update",
            "runtime",
            PAYLOAD,
            proposal_hash=proposal["proposal_hash"],
            runtime_authorization=authorization,
        )

    assert len(handler.calls) == 1


def test_expired_capability_is_consumed_without_calling_handler():
    clock = FakeClock()
    proposal, authorization = _authorization(
        clock=clock,
        ttl_seconds=5.0,
    )
    clock.value += 5.0
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": handler}
    )

    with pytest.raises(RuntimeAuthorizationExpiredError):
        commands.apply(
            "project update",
            "runtime",
            PAYLOAD,
            proposal_hash=proposal["proposal_hash"],
            runtime_authorization=authorization,
        )

    assert authorization.consumed is True
    assert handler.calls == []


@pytest.mark.parametrize(
    ("command", "payload", "proposal_hash"),
    (
        ("step update", PAYLOAD, None),
        (
            "project update",
            {**PAYLOAD, "status": "BLOCKED"},
            None,
        ),
        (
            "project update",
            {**PAYLOAD, "expected_version": 4},
            None,
        ),
        ("project update", PAYLOAD, "0" * 64),
    ),
)
def test_any_apply_mismatch_consumes_capability(
    command,
    payload,
    proposal_hash,
):
    proposal, authorization = _authorization()

    with pytest.raises(
        RuntimeWriteDeniedError,
        match="does not match the confirmed proposal",
    ):
        require_apply_authorization(
            command,
            "runtime",
            runtime_authorization=authorization,
            payload=payload,
            proposal_hash=(
                proposal["proposal_hash"]
                if proposal_hash is None
                else proposal_hash
            ),
        )

    assert authorization.consumed is True

    with pytest.raises(RuntimeAuthorizationConsumedError):
        require_apply_authorization(
            "project update",
            "runtime",
            runtime_authorization=authorization,
            payload=PAYLOAD,
            proposal_hash=proposal["proposal_hash"],
        )


def test_handler_failure_still_consumes_capability():
    proposal, authorization = _authorization()
    handler = RecordingHandler(error=ValueError("write failed"))
    commands = MerchantWriteCommands(
        {"project update": handler}
    )

    with pytest.raises(ValueError, match="write failed"):
        commands.apply(
            "project update",
            "runtime",
            PAYLOAD,
            proposal_hash=proposal["proposal_hash"],
            runtime_authorization=authorization,
        )

    with pytest.raises(RuntimeAuthorizationConsumedError):
        commands.apply(
            "project update",
            "runtime",
            PAYLOAD,
            proposal_hash=proposal["proposal_hash"],
            runtime_authorization=authorization,
        )

    assert len(handler.calls) == 1


def test_concurrent_replay_allows_exactly_one_handler_call():
    proposal, authorization = _authorization()
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": handler}
    )
    barrier = threading.Barrier(3)
    outcomes = []

    def apply_once():
        barrier.wait()

        try:
            commands.apply(
                "project update",
                "runtime",
                PAYLOAD,
                proposal_hash=proposal["proposal_hash"],
                runtime_authorization=authorization,
            )
            outcomes.append("success")
        except RuntimeAuthorizationConsumedError:
            outcomes.append("consumed")

    threads = [
        threading.Thread(target=apply_once),
        threading.Thread(target=apply_once),
    ]

    for thread in threads:
        thread.start()

    barrier.wait()

    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["consumed", "success"]
    assert len(handler.calls) == 1


@pytest.mark.parametrize(
    "receipt_change",
    (
        {"operation": "merchant_propose"},
        {"subagent_type": "coder"},
        {"teammate_name": ""},
        {"confirmation_hash": "0" * 64},
        {"unexpected": "field"},
    ),
)
def test_issuance_requires_exact_policy_dispatch_receipt(
    receipt_change,
):
    proposal = _proposal()
    confirmation = proposal["confirmation"]

    with pytest.raises(
        RuntimeWriteDeniedError,
        match="exact accepted dispatch receipt",
    ):
        issue_runtime_apply_authorization(
            confirmation,
            _receipt(confirmation, **receipt_change),
        )


def test_issuance_revalidates_confirmation_hash():
    proposal = _proposal()
    confirmation = {
        **proposal["confirmation"],
        "confirmation_hash": "0" * 64,
    }

    with pytest.raises(
        RuntimeWriteDeniedError,
        match="confirmation is missing or malformed",
    ):
        issue_runtime_apply_authorization(
            confirmation,
            _receipt(confirmation),
        )


@pytest.mark.parametrize(
    "ttl",
    (
        False,
        0,
        -1,
        float("inf"),
        MAX_RUNTIME_AUTHORIZATION_TTL_SECONDS + 1,
    ),
)
def test_issuance_rejects_untrusted_ttl(ttl):
    proposal = _proposal()
    confirmation = proposal["confirmation"]

    with pytest.raises(RuntimeWriteDeniedError, match="TTL"):
        issue_runtime_apply_authorization(
            confirmation,
            _receipt(confirmation),
            ttl_seconds=ttl,
        )


def test_test_database_apply_remains_available_without_capability():
    handler = RecordingHandler()
    commands = MerchantWriteCommands(
        {"project update": handler}
    )
    proposal = commands.propose(
        "project update",
        "test",
        PAYLOAD,
    )

    commands.apply(
        "project update",
        "test",
        PAYLOAD,
        proposal_hash=proposal["proposal_hash"],
    )

    assert handler.calls == [PAYLOAD]
