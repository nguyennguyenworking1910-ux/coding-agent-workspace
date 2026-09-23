import pytest

from claude.agents.tools.merchant.project_entity_resolver import (
    ProjectEntityResolverError,
    ProjectMatchKind,
    ProjectResolutionStatus,
    resolve_project_entity,
)


MERCHANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MERCHANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

PROJECT_2026 = "11111111-1111-4111-8111-111111111111"
PROJECT_2027 = "22222222-2222-4222-8222-222222222222"
OTHER_MERCHANT_PROJECT = (
    "33333333-3333-4333-8333-333333333333"
)


PROJECTS = [
    {
        "id": PROJECT_2026,
        "merchant_id": MERCHANT_A,
        "title": "CGV Media Top Up 2026",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "status": "PLANNED",
        "version": 1,
    },
    {
        "id": PROJECT_2027,
        "merchant_id": MERCHANT_A,
        "title": "CGV Media Top Up 2027",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "status": "IN_PROGRESS",
        "version": 2,
    },
    {
        "id": OTHER_MERCHANT_PROJECT,
        "merchant_id": MERCHANT_B,
        "title": "CGV Media Top Up 2026",
        "project_type": "MEDIA_TOP_UP",
        "workflow_variant": "STANDARD",
        "status": "PLANNED",
        "version": 1,
    },
]


def test_exact_uuid_resolves():
    result = resolve_project_entity(
        PROJECT_2026,
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.match_kind == ProjectMatchKind.UUID
    assert result.resolved is True
    assert result.project_id == PROJECT_2026


def test_uuid_from_another_merchant_is_not_found():
    result = resolve_project_entity(
        OTHER_MERCHANT_PROJECT,
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.NOT_FOUND
    assert result.resolved is False
    assert result.project_id is None
    assert result.candidates == ()


def test_unknown_valid_uuid_does_not_fall_back():
    result = resolve_project_entity(
        "99999999-9999-4999-8999-999999999999",
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.NOT_FOUND
    assert result.match_kind == ProjectMatchKind.NONE
    assert result.project_id is None


def test_exact_title_resolves():
    result = resolve_project_entity(
        "CGV Media Top Up 2026",
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.match_kind == ProjectMatchKind.TITLE
    assert result.project_id == PROJECT_2026


def test_exact_title_is_case_insensitive():
    result = resolve_project_entity(
        "cgv media top up 2026",
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.project_id == PROJECT_2026


def test_exact_title_ignores_outer_whitespace():
    result = resolve_project_entity(
        "   CGV Media Top Up 2026   ",
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.project_id == PROJECT_2026


def test_nfkc_normalization_is_supported():
    projects = [
        {
            **PROJECTS[0],
            "title": "ＣＧＶ Media Top Up 2026",
        }
    ]

    result = resolve_project_entity(
        "CGV Media Top Up 2026",
        MERCHANT_A,
        projects,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.project_id == PROJECT_2026


def test_punctuation_normalization_is_supported():
    projects = [
        {
            **PROJECTS[0],
            "title": "CGV - Media Top Up: 2026",
        }
    ]

    result = resolve_project_entity(
        "CGV Media Top Up 2026",
        MERCHANT_A,
        projects,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.project_id == PROJECT_2026


def test_unique_whole_token_candidate_resolves():
    result = resolve_project_entity(
        "Top Up 2027",
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.match_kind == ProjectMatchKind.CANDIDATE
    assert result.project_id == PROJECT_2027


def test_multiple_whole_token_candidates_are_ambiguous():
    result = resolve_project_entity(
        "Media Top Up",
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.AMBIGUOUS
    assert result.match_kind == ProjectMatchKind.CANDIDATE
    assert result.resolved is False
    assert result.project_id is None
    assert len(result.candidates) == 2


def test_arbitrary_substring_does_not_match():
    result = resolve_project_entity(
        "edia Top",
        MERCHANT_A,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.NOT_FOUND
    assert result.project_id is None


def test_exact_title_does_not_cross_merchant_boundary():
    result = resolve_project_entity(
        "CGV Media Top Up 2026",
        MERCHANT_B,
        PROJECTS,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.project_id == OTHER_MERCHANT_PROJECT


def test_other_merchant_projects_never_appear_as_candidates():
    result = resolve_project_entity(
        "Media Top Up",
        MERCHANT_A,
        PROJECTS,
    )

    candidate_ids = {
        candidate.project_id
        for candidate in result.candidates
    }

    assert candidate_ids == {
        PROJECT_2026,
        PROJECT_2027,
    }

    assert OTHER_MERCHANT_PROJECT not in candidate_ids


def test_missing_query_is_rejected():
    with pytest.raises(ProjectEntityResolverError):
        resolve_project_entity(
            "",
            MERCHANT_A,
            PROJECTS,
        )


def test_non_string_query_is_rejected():
    with pytest.raises(ProjectEntityResolverError):
        resolve_project_entity(
            None,
            MERCHANT_A,
            PROJECTS,
        )


def test_invalid_merchant_id_is_rejected():
    with pytest.raises(ProjectEntityResolverError):
        resolve_project_entity(
            "CGV Media Top Up 2026",
            "not-a-uuid",
            PROJECTS,
        )


def test_duplicate_project_id_is_rejected():
    duplicate_catalog = [
        PROJECTS[0],
        {
            **PROJECTS[0],
            "title": "Duplicate Project",
        },
    ]

    with pytest.raises(ProjectEntityResolverError):
        resolve_project_entity(
            "CGV",
            MERCHANT_A,
            duplicate_catalog,
        )


def test_null_title_is_allowed():
    projects = [
        {
            **PROJECTS[0],
            "title": None,
        }
    ]

    result = resolve_project_entity(
        PROJECT_2026,
        MERCHANT_A,
        projects,
    )

    assert result.status == ProjectResolutionStatus.RESOLVED
    assert result.project_id == PROJECT_2026
    assert result.title is None


def test_invalid_project_uuid_is_rejected():
    projects = [
        {
            **PROJECTS[0],
            "id": "not-a-project-uuid",
        }
    ]

    with pytest.raises(ProjectEntityResolverError):
        resolve_project_entity(
            "anything",
            MERCHANT_A,
            projects,
        )


def test_invalid_project_merchant_id_is_rejected():
    projects = [
        {
            **PROJECTS[0],
            "merchant_id": "not-a-merchant-uuid",
        }
    ]

    with pytest.raises(ProjectEntityResolverError):
        resolve_project_entity(
            "anything",
            MERCHANT_A,
            projects,
        )


def test_candidate_ordering_is_deterministic():
    reversed_projects = [
        PROJECTS[1],
        PROJECTS[0],
    ]

    result = resolve_project_entity(
        "Media Top Up",
        MERCHANT_A,
        reversed_projects,
    )

    assert result.status == ProjectResolutionStatus.AMBIGUOUS

    assert [
        candidate.project_id
        for candidate in result.candidates
    ] == [
        PROJECT_2026,
        PROJECT_2027,
    ]


def test_project_metadata_is_preserved():
    result = resolve_project_entity(
        PROJECT_2027,
        MERCHANT_A,
        PROJECTS,
    )

    assert result.project_id == PROJECT_2027
    assert result.title == "CGV Media Top Up 2027"
    assert result.project_type == "MEDIA_TOP_UP"
    assert result.workflow_variant == "STANDARD"
    assert result.project_status == "IN_PROGRESS"
    assert result.version == 2


def test_diacritics_are_not_stripped():
    projects = [
        {
            **PROJECTS[0],
            "title": "CGV Phú Mỹ 2026",
        }
    ]

    result = resolve_project_entity(
        "CGV Phu My 2026",
        MERCHANT_A,
        projects,
    )

    assert result.status == ProjectResolutionStatus.NOT_FOUND
    assert result.project_id is None


def test_empty_scoped_catalog_returns_not_found():
    result = resolve_project_entity(
        "Anything",
        MERCHANT_B,
        PROJECTS[:2],
    )

    assert result.status == ProjectResolutionStatus.NOT_FOUND
    assert result.resolved is False
    assert result.project_id is None


def test_resolution_to_dict_is_machine_stable():
    result = resolve_project_entity(
        PROJECT_2026,
        MERCHANT_A,
        PROJECTS,
    )

    payload = result.to_dict()

    assert payload["query"] == PROJECT_2026
    assert payload["merchant_id"] == MERCHANT_A
    assert payload["status"] == "RESOLVED"
    assert payload["match_kind"] == "UUID"
    assert payload["resolved"] is True
    assert payload["project_id"] == PROJECT_2026
    assert isinstance(payload["candidates"], list)
    assert len(payload["candidates"]) == 1