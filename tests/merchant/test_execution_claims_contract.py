"""Fail-first contract for PostgreSQL execution claims."""

import importlib
import uuid

import pytest


def claim_module():
    return importlib.import_module(
        "claude.clients.merchant.execution_claims"
    )


def test_claim_service_exposes_explicit_contract():
    module = claim_module()

    assert callable(module.acquire_execution_claim)
    assert callable(module.complete_execution_claim)
    assert issubclass(
        module.ExecutionClaimConflictError,
        Exception,
    )


def test_claim_acquisition_requires_attempt_identity():
    module = claim_module()

    assert hasattr(module, "ExecutionClaimToken")

    token_fields = getattr(
        module.ExecutionClaimToken,
        "__dataclass_fields__",
        {},
    )

    assert {
        "operation_key",
        "payload_hash",
        "execution_attempt_id",
        "claim_generation",
    } <= set(token_fields)


def test_claim_api_does_not_expose_implicit_takeover():
    module = claim_module()

    import inspect

    signature = inspect.signature(
        module.acquire_execution_claim
    )

    assert "connection" in signature.parameters
    assert "operation_key" in signature.parameters
    assert "payload_hash" in signature.parameters
    assert "execution_attempt_id" in signature.parameters

    for forbidden in (
        "force",
        "force_takeover",
        "auto_takeover",
        "ignore_generation",
    ):
        assert forbidden not in signature.parameters