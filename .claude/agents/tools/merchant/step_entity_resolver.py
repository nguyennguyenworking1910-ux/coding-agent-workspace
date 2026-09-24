from __future__ import annotations

import re
import unicodedata
import uuid

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class StepEntityResolverError(ValueError):
    """Raised when the Step catalog or resolver input is invalid."""


class StepResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class StepMatchKind(str, Enum):
    UUID = "UUID"
    STEP_NAME = "STEP_NAME"
    CANDIDATE = "CANDIDATE"
    NONE = "NONE"


@dataclass(frozen=True)
class StepEntity:
    step_id: str
    project_id: str
    template_step_id: str

    branch_key: str | None
    step_name: str
    step_type: str | None

    status: str | None
    sequence_number: int
    version: int

    condition_key: str | None
    is_optional: bool | None


@dataclass(frozen=True)
class StepCandidate:
    step_id: str
    project_id: str
    template_step_id: str

    branch_key: str | None
    step_name: str
    step_type: str | None

    status: str | None
    sequence_number: int
    version: int

    condition_key: str | None
    is_optional: bool | None

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "project_id": self.project_id,
            "template_step_id": (
                self.template_step_id
            ),
            "branch_key": self.branch_key,
            "step_name": self.step_name,
            "step_type": self.step_type,
            "status": self.status,
            "sequence_number": (
                self.sequence_number
            ),
            "version": self.version,
            "condition_key": self.condition_key,
            "is_optional": self.is_optional,
        }


@dataclass(frozen=True)
class StepResolution:
    query: str
    project_id: str

    status: StepResolutionStatus
    match_kind: StepMatchKind
    resolved: bool

    step_id: str | None
    template_step_id: str | None

    branch_key: str | None
    step_name: str | None
    step_type: str | None

    step_status: str | None
    sequence_number: int | None
    version: int | None

    condition_key: str | None
    is_optional: bool | None

    candidates: tuple[
        StepCandidate,
        ...,
    ]

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "query": self.query,
            "project_id": self.project_id,
            "status": self.status.value,
            "match_kind": self.match_kind.value,
            "resolved": self.resolved,
            "step_id": self.step_id,
            "template_step_id": (
                self.template_step_id
            ),
            "branch_key": self.branch_key,
            "step_name": self.step_name,
            "step_type": self.step_type,
            "step_status": self.step_status,
            "sequence_number": (
                self.sequence_number
            ),
            "version": self.version,
            "condition_key": self.condition_key,
            "is_optional": self.is_optional,
            "candidates": [
                candidate.to_dict()
                for candidate
                in self.candidates
            ],
        }


def resolve_step_entity(
    query: Any,
    project_id: Any,
    steps: Sequence[
        Mapping[str, Any]
    ],
) -> StepResolution:
    """Resolve one Project Step inside one trusted Project.

    Resolution priority:

    1. exact project-step UUID
    2. exact normalized step_name
    3. conservative whole-token step_name candidate
    4. NOT_FOUND

    project_id is always applied before matching.

    branch_key is disambiguation metadata only. It never independently
    authorizes or selects a Step.
    """

    normalized_query_text = (
        _required_text(
            query,
            "query",
        )
    )

    trusted_project_id = (
        _required_uuid(
            project_id,
            "project_id",
        )
    )

    scoped_steps = _step_catalog(
        steps,
        trusted_project_id,
    )

    query_uuid = (
        _canonical_uuid_or_none(
            normalized_query_text
        )
    )

    # ------------------------------------------------------------
    # Exact project-step UUID.
    #
    # Important:
    # Do not fall back to names when the query itself is a UUID.
    # Do not match template_step_id here.
    # ------------------------------------------------------------

    if query_uuid is not None:
        matches = [
            step
            for step in scoped_steps
            if step.step_id
            == query_uuid
        ]

        return _terminal_resolution(
            query=normalized_query_text,
            project_id=trusted_project_id,
            match_kind=(
                StepMatchKind.UUID
            ),
            matches=matches,
        )

    normalized_query = (
        _normalize_label(
            normalized_query_text
        )
    )

    # ------------------------------------------------------------
    # Exact semantic Step name.
    # ------------------------------------------------------------

    exact_name_matches = [
        step
        for step in scoped_steps
        if (
            _normalize_label(
                step.step_name
            )
            == normalized_query
        )
    ]

    if exact_name_matches:
        return _terminal_resolution(
            query=normalized_query_text,
            project_id=trusted_project_id,
            match_kind=(
                StepMatchKind.STEP_NAME
            ),
            matches=exact_name_matches,
        )

    # ------------------------------------------------------------
    # Conservative whole-token candidate matching.
    #
    # Match step_name only.
    #
    # branch_key, step_type, status and condition_key provide context
    # to the caller but must never independently select a Step.
    # ------------------------------------------------------------

    candidate_matches = [
        step
        for step in scoped_steps
        if _whole_token_sequence_match(
            normalized_query,
            _normalize_label(
                step.step_name
            ),
        )
    ]

    return _terminal_resolution(
        query=normalized_query_text,
        project_id=trusted_project_id,
        match_kind=(
            StepMatchKind.CANDIDATE
            if candidate_matches
            else StepMatchKind.NONE
        ),
        matches=candidate_matches,
    )


def _step_catalog(
    steps: Sequence[
        Mapping[str, Any]
    ],
    project_id: str,
) -> tuple[
    StepEntity,
    ...,
]:
    if isinstance(
        steps,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        raise StepEntityResolverError(
            "steps must be a sequence of mappings"
        )

    seen_ids: set[str] = set()
    scoped: list[StepEntity] = []

    for raw_step in steps:
        if not isinstance(
            raw_step,
            Mapping,
        ):
            raise StepEntityResolverError(
                "each step must be a mapping"
            )

        step_id = _required_uuid(
            raw_step.get("id"),
            "step.id",
        )

        if step_id in seen_ids:
            raise StepEntityResolverError(
                f"Duplicate step id: {step_id}"
            )

        seen_ids.add(
            step_id
        )

        step_project_id = (
            _required_uuid(
                raw_step.get(
                    "project_id"
                ),
                "step.project_id",
            )
        )

        # Scope before semantic matching.
        if (
            step_project_id
            != project_id
        ):
            continue

        template_step_id = (
            _required_uuid(
                raw_step.get(
                    "template_step_id"
                ),
                "step.template_step_id",
            )
        )

        step_name = _required_text(
            raw_step.get(
                "step_name"
            ),
            "step.step_name",
        )

        sequence_number = (
            _required_positive_integer(
                raw_step.get(
                    "sequence_number"
                ),
                "step.sequence_number",
            )
        )

        version = (
            _required_positive_integer(
                raw_step.get(
                    "version"
                ),
                "step.version",
            )
        )

        is_optional = (
            _optional_boolean(
                raw_step.get(
                    "is_optional"
                ),
                "step.is_optional",
            )
        )

        scoped.append(
            StepEntity(
                step_id=step_id,
                project_id=(
                    step_project_id
                ),
                template_step_id=(
                    template_step_id
                ),
                branch_key=(
                    _optional_text(
                        raw_step.get(
                            "branch_key"
                        )
                    )
                ),
                step_name=step_name,
                step_type=(
                    _optional_text(
                        raw_step.get(
                            "step_type"
                        )
                    )
                ),
                status=(
                    _optional_text(
                        raw_step.get(
                            "status"
                        )
                    )
                ),
                sequence_number=(
                    sequence_number
                ),
                version=version,
                condition_key=(
                    _optional_text(
                        raw_step.get(
                            "condition_key"
                        )
                    )
                ),
                is_optional=(
                    is_optional
                ),
            )
        )

    return tuple(
        scoped
    )


def _terminal_resolution(
    *,
    query: str,
    project_id: str,
    match_kind: StepMatchKind,
    matches: Sequence[
        StepEntity
    ],
) -> StepResolution:
    ordered = tuple(
        sorted(
            matches,
            key=lambda step: (
                step.sequence_number,
                step.step_id,
            ),
        )
    )

    if len(ordered) == 1:
        step = ordered[0]

        return StepResolution(
            query=query,
            project_id=project_id,
            status=(
                StepResolutionStatus.RESOLVED
            ),
            match_kind=match_kind,
            resolved=True,
            step_id=step.step_id,
            template_step_id=(
                step.template_step_id
            ),
            branch_key=(
                step.branch_key
            ),
            step_name=step.step_name,
            step_type=step.step_type,
            step_status=step.status,
            sequence_number=(
                step.sequence_number
            ),
            version=step.version,
            condition_key=(
                step.condition_key
            ),
            is_optional=(
                step.is_optional
            ),
            candidates=(
                _candidate(
                    step
                ),
            ),
        )

    if len(ordered) > 1:
        return StepResolution(
            query=query,
            project_id=project_id,
            status=(
                StepResolutionStatus.AMBIGUOUS
            ),
            match_kind=match_kind,
            resolved=False,
            step_id=None,
            template_step_id=None,
            branch_key=None,
            step_name=None,
            step_type=None,
            step_status=None,
            sequence_number=None,
            version=None,
            condition_key=None,
            is_optional=None,
            candidates=tuple(
                _candidate(
                    step
                )
                for step
                in ordered
            ),
        )

    return StepResolution(
        query=query,
        project_id=project_id,
        status=(
            StepResolutionStatus.NOT_FOUND
        ),
        match_kind=(
            StepMatchKind.NONE
        ),
        resolved=False,
        step_id=None,
        template_step_id=None,
        branch_key=None,
        step_name=None,
        step_type=None,
        step_status=None,
        sequence_number=None,
        version=None,
        condition_key=None,
        is_optional=None,
        candidates=(),
    )


def _candidate(
    step: StepEntity,
) -> StepCandidate:
    return StepCandidate(
        step_id=step.step_id,
        project_id=step.project_id,
        template_step_id=(
            step.template_step_id
        ),
        branch_key=step.branch_key,
        step_name=step.step_name,
        step_type=step.step_type,
        status=step.status,
        sequence_number=(
            step.sequence_number
        ),
        version=step.version,
        condition_key=(
            step.condition_key
        ),
        is_optional=(
            step.is_optional
        ),
    )


def _normalize_label(
    value: str,
) -> str:
    normalized = (
        unicodedata.normalize(
            "NFKC",
            value,
        )
        .casefold()
    )

    normalized = re.sub(
        r"[^\w]+",
        " ",
        normalized,
        flags=re.UNICODE,
    )

    return " ".join(
        normalized.split()
    )


def _whole_token_sequence_match(
    query: str,
    candidate: str,
) -> bool:
    query_tokens = (
        query.split()
    )

    candidate_tokens = (
        candidate.split()
    )

    if not query_tokens:
        return False

    if (
        len(query_tokens)
        > len(candidate_tokens)
    ):
        return False

    window_size = len(
        query_tokens
    )

    return any(
        candidate_tokens[
            index:
            index + window_size
        ]
        == query_tokens
        for index in range(
            len(candidate_tokens)
            - window_size
            + 1
        )
    )


def _canonical_uuid_or_none(
    value: Any,
) -> str | None:
    try:
        return str(
            uuid.UUID(
                str(value).strip()
            )
        )
    except (
        ValueError,
        AttributeError,
        TypeError,
    ):
        return None


def _required_uuid(
    value: Any,
    field_name: str,
) -> str:
    canonical = (
        _canonical_uuid_or_none(
            value
        )
    )

    if canonical is None:
        raise StepEntityResolverError(
            f"{field_name} must be a valid UUID"
        )

    return canonical


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise StepEntityResolverError(
            f"{field_name} must be non-empty text"
        )

    normalized = (
        value.strip()
    )

    if not normalized:
        raise StepEntityResolverError(
            f"{field_name} must be non-empty text"
        )

    return normalized


def _optional_text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    text = str(
        value
    ).strip()

    return text or None


def _required_positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
        or value < 1
    ):
        raise StepEntityResolverError(
            f"{field_name} must be a positive integer"
        )

    return value


def _optional_boolean(
    value: Any,
    field_name: str,
) -> bool | None:
    if value is None:
        return None

    if not isinstance(
        value,
        bool,
    ):
        raise StepEntityResolverError(
            f"{field_name} must be a boolean"
        )

    return value