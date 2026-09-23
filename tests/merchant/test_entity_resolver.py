"""Tests for deterministic Merchant entity resolution."""

from __future__ import annotations

import pytest
import uuid

from claude.agents.tools.merchant.entity_resolver import (
    MerchantEntity,
    MerchantEntityResolverError,
    MerchantMatchKind,
    MerchantResolutionStatus,
    resolve_merchant_entity,
)


CGV_ID = (
    "2da7ab08-1eda-5ca2-b28e-f94f3e1be0d0"
)

LOTTE_ID = (
    "9e718abc-47d3-587e-a71e-5967bea119a5"
)

BETA_ID = (
    "a6949851-958d-51df-95b8-07cdf8065291"
)

BETA_PHU_MY_ID = (
    "5b4c9bc1-bad3-5b03-9bdc-604f5adb3f26"
)


@pytest.fixture
def catalog():
    return (
        MerchantEntity(
            merchant_id=CGV_ID,
            code="CGV",
            name="CGV",
            aliases=(
                "CJ CGV",
                "CGV Cinema",
            ),
        ),
        MerchantEntity(
            merchant_id=LOTTE_ID,
            code="LOTTE_CINEMA",
            name="LOTTE CINEMA",
            aliases=(
                "Lotte",
            ),
        ),
        MerchantEntity(
            merchant_id=BETA_ID,
            code="BETA_CINEMA",
            name="BETA CINEMA",
            aliases=(
                "Beta",
            ),
        ),
        MerchantEntity(
            merchant_id=BETA_PHU_MY_ID,
            code="BETA_PHU_MY",
            name="BETA PHÚ MỸ",
            aliases=(),
        ),
    )


def test_exact_uuid_has_highest_precedence(
    catalog,
):
    result = resolve_merchant_entity(
        CGV_ID,
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.RESOLVED
    )

    assert result.match_kind == (
        MerchantMatchKind.UUID
    )

    assert result.merchant_id == CGV_ID


def test_exact_code_is_case_insensitive(
    catalog,
):
    result = resolve_merchant_entity(
        "  cgv  ",
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.RESOLVED
    )

    assert result.match_kind == (
        MerchantMatchKind.CODE
    )

    assert result.merchant_id == CGV_ID


def test_code_precedes_name():
    first_id = (
        "00000000-0000-0000-0000-000000000001"
    )

    second_id = (
        "00000000-0000-0000-0000-000000000002"
    )

    catalog = (
        MerchantEntity(
            merchant_id=first_id,
            code="SPECIAL",
            name="First Merchant",
        ),
        MerchantEntity(
            merchant_id=second_id,
            code="SECOND",
            name="SPECIAL",
        ),
    )

    result = resolve_merchant_entity(
        "SPECIAL",
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.RESOLVED
    )

    assert result.match_kind == (
        MerchantMatchKind.CODE
    )

    assert result.merchant_id == first_id


def test_exact_normalized_name_handles_spacing_and_punctuation(
    catalog,
):
    result = resolve_merchant_entity(
        "lotte---cinema",
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.RESOLVED
    )

    assert result.match_kind == (
        MerchantMatchKind.NAME
    )

    assert result.merchant_id == LOTTE_ID


def test_exact_alias_resolves(
    catalog,
):
    result = resolve_merchant_entity(
        "CJ CGV",
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.RESOLVED
    )

    assert result.match_kind == (
        MerchantMatchKind.ALIAS
    )

    assert result.merchant_id == CGV_ID


def test_unique_candidate_resolves(
    catalog,
):
    result = resolve_merchant_entity(
        "lotte",
        (
            MerchantEntity(
                merchant_id=LOTTE_ID,
                code="LOTTE_CINEMA",
                name="LOTTE CINEMA VIETNAM",
            ),
        ),
    )

    assert result.status == (
        MerchantResolutionStatus.RESOLVED
    )

    assert result.match_kind == (
        MerchantMatchKind.CANDIDATE
    )

    assert result.merchant_id == LOTTE_ID


def test_duplicate_exact_alias_fails_closed_as_ambiguous():
    first_id = (
        "00000000-0000-0000-0000-000000000001"
    )

    second_id = (
        "00000000-0000-0000-0000-000000000002"
    )

    catalog = (
        MerchantEntity(
            merchant_id=first_id,
            code="BETA_ONE",
            name="Beta One",
            aliases=(
                "Beta",
            ),
        ),
        MerchantEntity(
            merchant_id=second_id,
            code="BETA_TWO",
            name="Beta Two",
            aliases=(
                "Beta",
            ),
        ),
    )

    result = resolve_merchant_entity(
        "beta",
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.AMBIGUOUS
    )

    assert result.match_kind == (
        MerchantMatchKind.ALIAS
    )

    assert result.merchant_id is None

    assert [
        candidate.code
        for candidate in result.candidates
    ] == [
        "BETA_ONE",
        "BETA_TWO",
    ]


def test_multiple_candidate_matches_are_sorted():
    first_id = (
        "00000000-0000-0000-0000-000000000001"
    )

    second_id = (
        "00000000-0000-0000-0000-000000000002"
    )

    catalog = (
        MerchantEntity(
            merchant_id=second_id,
            code="BETA_TWO",
            name="Beta Two",
        ),
        MerchantEntity(
            merchant_id=first_id,
            code="BETA_ONE",
            name="Beta One",
        ),
    )

    result = resolve_merchant_entity(
        "beta",
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.AMBIGUOUS
    )

    assert result.match_kind == (
        MerchantMatchKind.CANDIDATE
    )

    assert [
        candidate.code
        for candidate in result.candidates
    ] == [
        "BETA_ONE",
        "BETA_TWO",
    ]


def test_unknown_merchant_is_not_found(
    catalog,
):
    result = resolve_merchant_entity(
        "UNKNOWN MERCHANT",
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.NOT_FOUND
    )

    assert result.match_kind == (
        MerchantMatchKind.NONE
    )

    assert result.merchant_id is None
    assert result.candidates == ()


def test_unknown_uuid_does_not_fall_through_to_name():
    unknown_uuid = (
        "00000000-0000-0000-0000-000000000999"
    )

    catalog = (
        MerchantEntity(
            merchant_id=(
                "00000000-0000-0000-0000-000000000001"
            ),
            code="TEST",
            name=unknown_uuid,
        ),
    )

    result = resolve_merchant_entity(
        unknown_uuid,
        catalog,
    )

    assert result.status == (
        MerchantResolutionStatus.NOT_FOUND
    )

    assert result.match_kind == (
        MerchantMatchKind.UUID
    )


@pytest.mark.parametrize(
    "query",
    (
        "",
        "   ",
        None,
    ),
)
def test_blank_or_non_text_query_is_rejected(
    query,
    catalog,
):
    with pytest.raises(
        MerchantEntityResolverError
    ):
        resolve_merchant_entity(
            query,
            catalog,
        )


def test_duplicate_merchant_id_is_rejected():
    merchant_id = (
        "00000000-0000-0000-0000-000000000001"
    )

    catalog = (
        MerchantEntity(
            merchant_id=merchant_id,
            code="ONE",
            name="One",
        ),
        MerchantEntity(
            merchant_id=merchant_id,
            code="TWO",
            name="Two",
        ),
    )

    with pytest.raises(
        MerchantEntityResolverError,
        match="duplicate merchant_id",
    ):
        resolve_merchant_entity(
            "ONE",
            catalog,
        )


def test_mapping_records_accept_id_field(
    catalog,
):
    result = resolve_merchant_entity(
        "CGV",
        (
            {
                "id": CGV_ID,
                "code": "CGV",
                "name": "CGV",
                "aliases": [
                    "CJ CGV",
                ],
            },
        ),
    )

    assert result.status == (
        MerchantResolutionStatus.RESOLVED
    )

    assert result.merchant_id == CGV_ID


def test_resolution_to_dict_is_machine_readable(
    catalog,
):
    result = resolve_merchant_entity(
        "CGV",
        catalog,
    )

    assert result.to_dict() == {
        "query": "CGV",
        "status": "RESOLVED",
        "match_kind": "CODE",
        "resolved": True,
        "merchant_id": CGV_ID,
        "code": "CGV",
        "name": "CGV",
        "candidates": [
            {
                "merchant_id": CGV_ID,
                "code": "CGV",
                "name": "CGV",
            }
        ],
    }


def test_mapping_records_accept_uuid_object_id():
    result = resolve_merchant_entity(
        "CGV",
        (
            {
                "id": uuid.UUID(
                    CGV_ID
                ),
                "code": "CGV",
                "name": "CGV",
                "aliases": (),
            },
        ),
    )

    assert result.status == (
        MerchantResolutionStatus.RESOLVED
    )

    assert result.match_kind == (
        MerchantMatchKind.CODE
    )

    assert result.merchant_id == CGV_ID