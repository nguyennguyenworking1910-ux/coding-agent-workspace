import pytest

from claude.agents.tools.merchant.document_revision_entity_resolver import (
    DocumentRevisionEntityResolverError,
    DocumentRevisionMatchKind,
    DocumentRevisionResolutionStatus,
    DocumentRevisionScope,
    resolve_document_revision_entity,
)


MERCHANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MERCHANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

PROJECT_A1 = "11111111-1111-4111-8111-111111111111"
PROJECT_A2 = "22222222-2222-4222-8222-222222222222"
PROJECT_B1 = "33333333-3333-4333-8333-333333333333"

CONTRACT_1 = "41111111-1111-4111-8111-111111111111"
CONTRACT_2 = "42222222-2222-4222-8222-222222222222"
MEDIA_APPENDIX_1 = "43333333-3333-4333-8333-333333333333"
OTHER_MERCHANT_CONTRACT_1 = (
    "44444444-4444-4444-8444-444444444444"
)


def revision(
    revision_id,
    *,
    project_id=PROJECT_A1,
    merchant_id=MERCHANT_A,
    document_type="CONTRACT",
    revision_number=1,
    content_hash="sha256:test",
    signed=True,
    signed_at="2026-09-01T00:00:00+00:00",
    effective_date="2026-09-01",
    expiry_date=None,
    superseded_by=None,
):
    return {
        "id": revision_id,
        "project_id": project_id,
        "merchant_id": merchant_id,
        "document_type": document_type,
        "revision_number": revision_number,
        "content_hash": content_hash,
        "signed": signed,
        "signed_at": signed_at,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "superseded_by": superseded_by,
    }


REVISIONS = [
    revision(
        CONTRACT_1,
        revision_number=1,
        superseded_by=CONTRACT_2,
    ),
    revision(
        CONTRACT_2,
        revision_number=2,
    ),
    revision(
        MEDIA_APPENDIX_1,
        project_id=PROJECT_A2,
        document_type="MEDIA_APPENDIX",
        revision_number=1,
        signed=False,
        signed_at=None,
    ),
    revision(
        OTHER_MERCHANT_CONTRACT_1,
        project_id=PROJECT_B1,
        merchant_id=MERCHANT_B,
        document_type="CONTRACT",
        revision_number=1,
    ),
]


def test_project_scope_exact_uuid_resolves():
    result = resolve_document_revision_entity(
        CONTRACT_1,
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.match_kind == DocumentRevisionMatchKind.UUID
    assert result.scope == DocumentRevisionScope.PROJECT
    assert result.resolved is True
    assert result.revision_id == CONTRACT_1
    assert result.source_project_id == PROJECT_A1


def test_project_scope_uuid_from_sibling_project_is_not_found():
    result = resolve_document_revision_entity(
        MEDIA_APPENDIX_1,
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.NOT_FOUND
    assert result.resolved is False
    assert result.revision_id is None
    assert result.candidates == ()


def test_project_scope_uuid_from_other_merchant_is_not_found():
    result = resolve_document_revision_entity(
        OTHER_MERCHANT_CONTRACT_1,
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.NOT_FOUND
    assert result.revision_id is None
    assert result.candidates == ()


def test_project_scope_exact_revision_key_resolves():
    result = resolve_document_revision_entity(
        "CONTRACT#2",
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.match_kind == DocumentRevisionMatchKind.REVISION_KEY
    assert result.revision_id == CONTRACT_2
    assert result.revision_number == 2


def test_revision_key_is_case_insensitive_and_allows_space_around_hash():
    result = resolve_document_revision_entity(
        "contract # 2",
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.revision_id == CONTRACT_2


def test_unknown_revision_key_is_not_found():
    result = resolve_document_revision_entity(
        "CONTRACT#99",
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.NOT_FOUND
    assert result.revision_id is None


def test_project_scope_unique_document_type_resolves():
    catalog = [
        revision(
            CONTRACT_1,
            revision_number=1,
        )
    ]

    result = resolve_document_revision_entity(
        "contract",
        MERCHANT_A,
        catalog,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.match_kind == DocumentRevisionMatchKind.DOCUMENT_TYPE
    assert result.revision_id == CONTRACT_1


def test_project_scope_multiple_revisions_of_type_are_ambiguous():
    result = resolve_document_revision_entity(
        "CONTRACT",
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.AMBIGUOUS
    assert result.match_kind == DocumentRevisionMatchKind.DOCUMENT_TYPE
    assert result.resolved is False
    assert result.revision_id is None
    assert [
        candidate.revision_id
        for candidate in result.candidates
    ] == [
        CONTRACT_1,
        CONTRACT_2,
    ]


def test_project_scope_nonexistent_document_type_is_not_found():
    result = resolve_document_revision_entity(
        "PURCHASE_ORDER",
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.NOT_FOUND
    assert result.revision_id is None


def test_merchant_scope_exact_uuid_resolves_from_first_project():
    result = resolve_document_revision_entity(
        CONTRACT_2,
        MERCHANT_A,
        REVISIONS,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.scope == DocumentRevisionScope.MERCHANT
    assert result.project_id is None
    assert result.source_project_id == PROJECT_A1
    assert result.revision_id == CONTRACT_2


def test_merchant_scope_can_resolve_revision_from_sibling_project():
    result = resolve_document_revision_entity(
        MEDIA_APPENDIX_1,
        MERCHANT_A,
        REVISIONS,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.scope == DocumentRevisionScope.MERCHANT
    assert result.source_project_id == PROJECT_A2
    assert result.revision_id == MEDIA_APPENDIX_1


def test_merchant_scope_does_not_resolve_cross_merchant_revision():
    result = resolve_document_revision_entity(
        OTHER_MERCHANT_CONTRACT_1,
        MERCHANT_A,
        REVISIONS,
    )

    assert result.status == DocumentRevisionResolutionStatus.NOT_FOUND
    assert result.revision_id is None
    assert result.candidates == ()


def test_merchant_scope_revision_key_can_resolve_cross_project():
    result = resolve_document_revision_entity(
        "MEDIA_APPENDIX#1",
        MERCHANT_A,
        REVISIONS,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.revision_id == MEDIA_APPENDIX_1
    assert result.source_project_id == PROJECT_A2


def test_duplicate_compound_key_across_projects_is_ambiguous():
    sibling_contract = (
        "46666666-6666-4666-8666-666666666666"
    )

    catalog = [
        revision(
            CONTRACT_1,
            project_id=PROJECT_A1,
            document_type="CONTRACT",
            revision_number=1,
        ),
        revision(
            sibling_contract,
            project_id=PROJECT_A2,
            document_type="CONTRACT",
            revision_number=1,
        ),
    ]

    result = resolve_document_revision_entity(
        "CONTRACT#1",
        MERCHANT_A,
        catalog,
    )

    assert result.status == DocumentRevisionResolutionStatus.AMBIGUOUS
    assert result.match_kind == DocumentRevisionMatchKind.REVISION_KEY
    assert result.revision_id is None
    assert {
        candidate.project_id
        for candidate in result.candidates
    } == {
        PROJECT_A1,
        PROJECT_A2,
    }


def test_document_type_spanning_projects_is_ambiguous():
    sibling_contract = (
        "47777777-7777-4777-8777-777777777777"
    )

    catalog = [
        revision(
            CONTRACT_1,
            project_id=PROJECT_A1,
            document_type="CONTRACT",
            revision_number=1,
        ),
        revision(
            sibling_contract,
            project_id=PROJECT_A2,
            document_type="CONTRACT",
            revision_number=2,
        ),
    ]

    result = resolve_document_revision_entity(
        "CONTRACT",
        MERCHANT_A,
        catalog,
    )

    assert result.status == DocumentRevisionResolutionStatus.AMBIGUOUS
    assert len(result.candidates) == 2


def test_unsigned_revision_is_still_resolvable():
    result = resolve_document_revision_entity(
        MEDIA_APPENDIX_1,
        MERCHANT_A,
        REVISIONS,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.signed is False


def test_superseded_revision_is_still_resolvable():
    result = resolve_document_revision_entity(
        CONTRACT_1,
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.superseded_by == CONTRACT_2


def test_document_type_does_not_implicitly_select_latest_revision():
    result = resolve_document_revision_entity(
        "CONTRACT",
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.AMBIGUOUS
    assert result.revision_id is None


def test_valid_unknown_uuid_does_not_fall_back_to_semantic_matching():
    result = resolve_document_revision_entity(
        "49999999-9999-4999-8999-999999999999",
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.NOT_FOUND
    assert result.match_kind == DocumentRevisionMatchKind.NONE
    assert result.revision_id is None


def test_unique_whole_token_candidate_resolves():
    result = resolve_document_revision_entity(
        "appendix",
        MERCHANT_A,
        REVISIONS,
    )

    assert result.status == DocumentRevisionResolutionStatus.RESOLVED
    assert result.match_kind == DocumentRevisionMatchKind.CANDIDATE
    assert result.revision_id == MEDIA_APPENDIX_1


def test_arbitrary_substring_does_not_match_document_type():
    result = resolve_document_revision_entity(
        "pend",
        MERCHANT_A,
        REVISIONS,
    )

    assert result.status == DocumentRevisionResolutionStatus.NOT_FOUND
    assert result.revision_id is None


def test_candidate_ordering_is_deterministic():
    result = resolve_document_revision_entity(
        "CONTRACT",
        MERCHANT_A,
        list(reversed(REVISIONS[:2])),
        project_id=PROJECT_A1,
    )

    assert result.status == DocumentRevisionResolutionStatus.AMBIGUOUS
    assert [
        candidate.revision_id
        for candidate in result.candidates
    ] == [
        CONTRACT_1,
        CONTRACT_2,
    ]


def test_duplicate_revision_id_is_rejected():
    catalog = [
        REVISIONS[0],
        {
            **REVISIONS[0],
            "project_id": PROJECT_A2,
        },
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="Duplicate document revision id",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            catalog,
        )


def test_revision_number_must_be_positive_integer():
    catalog = [
        {
            **REVISIONS[0],
            "revision_number": 0,
        }
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="revision_number must be a positive integer",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            catalog,
        )


def test_revision_number_bool_is_rejected():
    catalog = [
        {
            **REVISIONS[0],
            "revision_number": True,
        }
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="revision_number must be a positive integer",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            catalog,
        )


def test_invalid_revision_uuid_is_rejected():
    catalog = [
        {
            **REVISIONS[0],
            "id": "not-a-revision-uuid",
        }
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="document_revision.id must be a valid UUID",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            catalog,
        )


def test_invalid_project_uuid_is_rejected():
    catalog = [
        {
            **REVISIONS[0],
            "project_id": "not-a-project-uuid",
        }
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="document_revision.project_id must be a valid UUID",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            catalog,
        )


def test_invalid_revision_merchant_uuid_is_rejected():
    catalog = [
        {
            **REVISIONS[0],
            "merchant_id": "not-a-merchant-uuid",
        }
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="document_revision.merchant_id must be a valid UUID",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            catalog,
        )


def test_invalid_trusted_merchant_uuid_is_rejected():
    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="merchant_id must be a valid UUID",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            "not-a-merchant-uuid",
            REVISIONS,
        )


def test_invalid_trusted_project_uuid_is_rejected():
    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="project_id must be a valid UUID",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            REVISIONS,
            project_id="not-a-project-uuid",
        )


def test_document_type_is_validated():
    catalog = [
        {
            **REVISIONS[0],
            "document_type": "bad type!",
        }
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="document_type must contain only uppercase",
    ):
        resolve_document_revision_entity(
            "anything",
            MERCHANT_A,
            catalog,
        )


def test_signed_must_be_boolean():
    catalog = [
        {
            **REVISIONS[0],
            "signed": "true",
        }
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="document_revision.signed must be a boolean",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            catalog,
        )


def test_invalid_superseded_by_uuid_is_rejected():
    catalog = [
        {
            **REVISIONS[0],
            "superseded_by": "not-a-uuid",
        }
    ]

    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="superseded_by must be a valid UUID or null",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            catalog,
        )


def test_missing_query_is_rejected():
    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="query must be non-empty text",
    ):
        resolve_document_revision_entity(
            "",
            MERCHANT_A,
            REVISIONS,
        )


def test_non_string_query_is_rejected():
    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="query must be non-empty text",
    ):
        resolve_document_revision_entity(
            None,
            MERCHANT_A,
            REVISIONS,
        )


def test_catalog_record_must_be_mapping():
    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="catalog records must be objects",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            ["not-a-record"],
        )


def test_catalog_itself_must_not_be_string():
    with pytest.raises(
        DocumentRevisionEntityResolverError,
        match="catalog must be a sequence of records",
    ):
        resolve_document_revision_entity(
            "CONTRACT",
            MERCHANT_A,
            "not-a-catalog",
        )


def test_empty_project_scope_returns_not_found():
    result = resolve_document_revision_entity(
        "CONTRACT",
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A2,
    )

    assert result.status == DocumentRevisionResolutionStatus.NOT_FOUND
    assert result.revision_id is None


def test_resolution_preserves_document_metadata():
    result = resolve_document_revision_entity(
        CONTRACT_1,
        MERCHANT_A,
        REVISIONS,
        project_id=PROJECT_A1,
    )

    assert result.revision_id == CONTRACT_1
    assert result.source_project_id == PROJECT_A1
    assert result.document_type == "CONTRACT"
    assert result.revision_number == 1
    assert result.signed is True
    assert result.superseded_by == CONTRACT_2


def test_resolution_to_dict_is_machine_stable():
    result = resolve_document_revision_entity(
        MEDIA_APPENDIX_1,
        MERCHANT_A,
        REVISIONS,
    )

    payload = result.to_dict()

    assert payload["query"] == MEDIA_APPENDIX_1
    assert payload["scope"] == "MERCHANT"
    assert payload["merchant_id"] == MERCHANT_A
    assert payload["project_id"] is None
    assert payload["status"] == "RESOLVED"
    assert payload["match_kind"] == "UUID"
    assert payload["resolved"] is True
    assert payload["revision_id"] == MEDIA_APPENDIX_1
    assert payload["source_project_id"] == PROJECT_A2
    assert payload["document_type"] == "MEDIA_APPENDIX"
    assert payload["revision_number"] == 1
    assert payload["signed"] is False
    assert isinstance(payload["candidates"], list)
    assert len(payload["candidates"]) == 1