from __future__ import annotations

import pytest

from claude.agents.tools.merchant.step_entity_resolver import (
    StepEntityResolverError,
    resolve_step_entity,
)


PROJECT_A = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
)

PROJECT_B = (
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
)

STEP_UAT = (
    "11111111-1111-4111-8111-111111111111"
)

STEP_PROD = (
    "22222222-2222-4222-8222-222222222222"
)

STEP_OTHER = (
    "33333333-3333-4333-8333-333333333333"
)

TEMPLATE_UAT = (
    "44444444-4444-4444-8444-444444444444"
)

TEMPLATE_PROD = (
    "55555555-5555-4555-8555-555555555555"
)

TEMPLATE_OTHER = (
    "66666666-6666-4666-8666-666666666666"
)


def step(
    step_id=STEP_UAT,
    *,
    project_id=PROJECT_A,
    template_step_id=TEMPLATE_UAT,
    branch_key="uat_branch",
    step_name="Run UAT test",
    step_type="PARALLEL_BRANCH",
    status="READY",
    sequence_number=20,
    version=1,
    condition_key=None,
    is_optional=False,
):
    return {
        "id": step_id,
        "project_id": project_id,
        "template_step_id": (
            template_step_id
        ),
        "branch_key": branch_key,
        "step_name": step_name,
        "step_type": step_type,
        "status": status,
        "sequence_number": (
            sequence_number
        ),
        "version": version,
        "condition_key": (
            condition_key
        ),
        "is_optional": (
            is_optional
        ),
    }


def catalog():
    return [
        step(),
        step(
            STEP_PROD,
            template_step_id=(
                TEMPLATE_PROD
            ),
            branch_key=(
                "production_branch"
            ),
            step_name=(
                "Run Production test"
            ),
            sequence_number=16,
        ),
        step(
            STEP_OTHER,
            project_id=PROJECT_B,
            template_step_id=(
                TEMPLATE_OTHER
            ),
            branch_key=(
                "uat_branch"
            ),
            step_name=(
                "Run UAT test"
            ),
            sequence_number=20,
        ),
    ]


def test_exact_uuid_resolves():
    result = resolve_step_entity(
        STEP_UAT,
        PROJECT_A,
        catalog(),
    )

    assert (
        result.status.value
        == "RESOLVED"
    )

    assert (
        result.match_kind.value
        == "UUID"
    )

    assert result.resolved is True
    assert result.step_id == STEP_UAT
    assert result.project_id == PROJECT_A
    assert result.branch_key == "uat_branch"
    assert result.step_name == "Run UAT test"
    assert result.sequence_number == 20
    assert result.version == 1


def test_exact_name_resolves():
    result = resolve_step_entity(
        "Run UAT test",
        PROJECT_A,
        catalog(),
    )

    assert (
        result.status.value
        == "RESOLVED"
    )

    assert (
        result.match_kind.value
        == "STEP_NAME"
    )

    assert result.step_id == STEP_UAT


def test_name_resolution_is_case_insensitive():
    result = resolve_step_entity(
        "run uat TEST",
        PROJECT_A,
        catalog(),
    )

    assert result.resolved is True
    assert result.step_id == STEP_UAT


def test_nfkc_equivalent_name_resolves():
    result = resolve_step_entity(
        "Ｒｕｎ UAT test",
        PROJECT_A,
        catalog(),
    )

    assert result.resolved is True
    assert result.step_id == STEP_UAT


def test_candidate_whole_token_sequence_resolves():
    result = resolve_step_entity(
        "UAT test",
        PROJECT_A,
        catalog(),
    )

    assert result.resolved is True

    assert (
        result.match_kind.value
        == "CANDIDATE"
    )

    assert result.step_id == STEP_UAT


def test_project_scope_prevents_cross_project_match():
    result = resolve_step_entity(
        "Run UAT test",
        PROJECT_B,
        catalog(),
    )

    assert result.resolved is True
    assert result.step_id == STEP_OTHER

    assert (
        result.project_id
        == PROJECT_B
    )


def test_uuid_from_other_project_is_not_found():
    result = resolve_step_entity(
        STEP_OTHER,
        PROJECT_A,
        catalog(),
    )

    assert (
        result.status.value
        == "NOT_FOUND"
    )

    assert result.resolved is False
    assert result.step_id is None
    assert result.candidates == ()


def test_uuid_query_never_falls_back_to_name():
    fake_uuid = (
        "77777777-7777-4777-8777-777777777777"
    )

    values = [
        step(
            step_name=fake_uuid
        )
    ]

    result = resolve_step_entity(
        fake_uuid,
        PROJECT_A,
        values,
    )

    assert (
        result.status.value
        == "NOT_FOUND"
    )

    assert result.step_id is None


def test_duplicate_exact_step_names_are_ambiguous():
    second = step(
        STEP_PROD,
        template_step_id=(
            TEMPLATE_PROD
        ),
        branch_key=(
            "production_branch"
        ),
        step_name=(
            "Run UAT test"
        ),
        sequence_number=21,
    )

    result = resolve_step_entity(
        "Run UAT test",
        PROJECT_A,
        [
            step(),
            second,
        ],
    )

    assert (
        result.status.value
        == "AMBIGUOUS"
    )

    assert result.resolved is False
    assert result.step_id is None

    assert [
        candidate.step_id
        for candidate
        in result.candidates
    ] == [
        STEP_UAT,
        STEP_PROD,
    ]


def test_candidate_matches_can_be_ambiguous():
    values = [
        step(
            STEP_UAT,
            step_name="Run UAT smoke test",
            sequence_number=20,
        ),
        step(
            STEP_PROD,
            template_step_id=(
                TEMPLATE_PROD
            ),
            step_name="Run UAT regression test",
            sequence_number=21,
        ),
    ]

    result = resolve_step_entity(
        "Run UAT",
        PROJECT_A,
        values,
    )

    assert (
        result.status.value
        == "AMBIGUOUS"
    )

    assert (
        result.match_kind.value
        == "CANDIDATE"
    )

    assert len(
        result.candidates
    ) == 2


def test_no_match_returns_not_found():
    result = resolve_step_entity(
        "Unknown workflow step",
        PROJECT_A,
        catalog(),
    )

    assert (
        result.status.value
        == "NOT_FOUND"
    )

    assert (
        result.match_kind.value
        == "NONE"
    )

    assert result.resolved is False
    assert result.step_id is None
    assert result.candidates == ()


def test_branch_key_alone_does_not_match():
    result = resolve_step_entity(
        "uat_branch",
        PROJECT_A,
        catalog(),
    )

    assert (
        result.status.value
        == "NOT_FOUND"
    )

    assert result.step_id is None


def test_step_type_alone_does_not_match():
    result = resolve_step_entity(
        "PARALLEL_BRANCH",
        PROJECT_A,
        catalog(),
    )

    assert (
        result.status.value
        == "NOT_FOUND"
    )


def test_template_step_id_does_not_resolve_as_step_id():
    result = resolve_step_entity(
        TEMPLATE_UAT,
        PROJECT_A,
        catalog(),
    )

    assert (
        result.status.value
        == "NOT_FOUND"
    )

    assert result.step_id is None


def test_candidate_preserves_branch_context():
    result = resolve_step_entity(
        "Run UAT test",
        PROJECT_A,
        catalog(),
    )

    candidate = (
        result.candidates[0]
    )

    assert (
        candidate.step_id
        == STEP_UAT
    )

    assert (
        candidate.project_id
        == PROJECT_A
    )

    assert (
        candidate.template_step_id
        == TEMPLATE_UAT
    )

    assert (
        candidate.branch_key
        == "uat_branch"
    )

    assert (
        candidate.step_name
        == "Run UAT test"
    )

    assert (
        candidate.step_type
        == "PARALLEL_BRANCH"
    )

    assert (
        candidate.status
        == "READY"
    )

    assert (
        candidate.sequence_number
        == 20
    )

    assert candidate.version == 1
    assert candidate.is_optional is False


def test_ambiguous_candidates_use_workflow_order():
    first_id = (
        "ffffffff-ffff-4fff-8fff-ffffffffffff"
    )

    second_id = (
        "00000000-0000-4000-8000-000000000001"
    )

    values = [
        step(
            first_id,
            step_name="Review",
            sequence_number=20,
        ),
        step(
            second_id,
            template_step_id=(
                TEMPLATE_PROD
            ),
            step_name="Review",
            sequence_number=10,
        ),
    ]

    result = resolve_step_entity(
        "Review",
        PROJECT_A,
        values,
    )

    assert [
        candidate.step_id
        for candidate
        in result.candidates
    ] == [
        second_id,
        first_id,
    ]


def test_duplicate_step_ids_are_rejected():
    values = [
        step(),
        step(
            STEP_UAT,
            project_id=PROJECT_B,
        ),
    ]

    with pytest.raises(
        StepEntityResolverError,
        match="Duplicate step id",
    ):
        resolve_step_entity(
            "Run UAT test",
            PROJECT_A,
            values,
        )


def test_invalid_trusted_project_id_is_rejected():
    with pytest.raises(
        StepEntityResolverError,
        match="project_id must be a valid UUID",
    ):
        resolve_step_entity(
            "Run UAT test",
            "not-a-uuid",
            catalog(),
        )


def test_invalid_step_id_is_rejected():
    values = [
        step(
            step_id="not-a-uuid"
        )
    ]

    with pytest.raises(
        StepEntityResolverError,
        match="step.id must be a valid UUID",
    ):
        resolve_step_entity(
            "Run UAT test",
            PROJECT_A,
            values,
        )


def test_invalid_template_step_id_is_rejected():
    values = [
        step(
            template_step_id=(
                "not-a-uuid"
            )
        )
    ]

    with pytest.raises(
        StepEntityResolverError,
        match=(
            "step.template_step_id must be a valid UUID"
        ),
    ):
        resolve_step_entity(
            "Run UAT test",
            PROJECT_A,
            values,
        )


def test_missing_step_name_is_rejected():
    values = [
        step(
            step_name=""
        )
    ]

    with pytest.raises(
        StepEntityResolverError,
        match=(
            "step.step_name must be non-empty text"
        ),
    ):
        resolve_step_entity(
            "Run UAT test",
            PROJECT_A,
            values,
        )


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        True,
        "1",
    ],
)
def test_invalid_sequence_number_is_rejected(
    value,
):
    values = [
        step(
            sequence_number=value
        )
    ]

    with pytest.raises(
        StepEntityResolverError,
        match=(
            "step.sequence_number must be a positive integer"
        ),
    ):
        resolve_step_entity(
            "Run UAT test",
            PROJECT_A,
            values,
        )


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        True,
        "1",
    ],
)
def test_invalid_version_is_rejected(
    value,
):
    values = [
        step(
            version=value
        )
    ]

    with pytest.raises(
        StepEntityResolverError,
        match=(
            "step.version must be a positive integer"
        ),
    ):
        resolve_step_entity(
            "Run UAT test",
            PROJECT_A,
            values,
        )


def test_invalid_is_optional_is_rejected():
    values = [
        step(
            is_optional="false"
        )
    ]

    with pytest.raises(
        StepEntityResolverError,
        match=(
            "step.is_optional must be a boolean"
        ),
    ):
        resolve_step_entity(
            "Run UAT test",
            PROJECT_A,
            values,
        )


def test_blank_query_is_rejected():
    with pytest.raises(
        StepEntityResolverError,
        match="query must be non-empty text",
    ):
        resolve_step_entity(
            "   ",
            PROJECT_A,
            catalog(),
        )


def test_diacritics_are_not_silently_removed():
    values = [
        step(
            step_name="Phê duyệt Legal"
        )
    ]

    result = resolve_step_entity(
        "Phe duyet Legal",
        PROJECT_A,
        values,
    )

    assert (
        result.status.value
        == "NOT_FOUND"
    )