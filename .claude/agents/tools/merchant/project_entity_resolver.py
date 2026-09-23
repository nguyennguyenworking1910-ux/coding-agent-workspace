from __future__ import annotations

import re
import unicodedata
import uuid

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class ProjectEntityResolverError(ValueError):
    """Raised when the project catalog or resolver input is invalid."""


class ProjectResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class ProjectMatchKind(str, Enum):
    UUID = "UUID"
    TITLE = "TITLE"
    CANDIDATE = "CANDIDATE"
    NONE = "NONE"


@dataclass(frozen=True)
class ProjectEntity:
    project_id: str
    merchant_id: str
    title: str | None
    project_type: str | None
    workflow_variant: str | None
    status: str | None
    version: int | None


@dataclass(frozen=True)
class ProjectCandidate:
    project_id: str
    merchant_id: str
    title: str | None
    project_type: str | None
    workflow_variant: str | None
    status: str | None
    version: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "merchant_id": self.merchant_id,
            "title": self.title,
            "project_type": self.project_type,
            "workflow_variant": self.workflow_variant,
            "status": self.status,
            "version": self.version,
        }


@dataclass(frozen=True)
class ProjectResolution:
    query: str
    merchant_id: str
    status: ProjectResolutionStatus
    match_kind: ProjectMatchKind
    resolved: bool
    project_id: str | None
    title: str | None
    project_type: str | None
    workflow_variant: str | None
    project_status: str | None
    version: int | None
    candidates: tuple[ProjectCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "merchant_id": self.merchant_id,
            "status": self.status.value,
            "match_kind": self.match_kind.value,
            "resolved": self.resolved,
            "project_id": self.project_id,
            "title": self.title,
            "project_type": self.project_type,
            "workflow_variant": self.workflow_variant,
            "project_status": self.project_status,
            "version": self.version,
            "candidates": [
                candidate.to_dict()
                for candidate in self.candidates
            ],
        }


def resolve_project_entity(
    query: Any,
    merchant_id: Any,
    projects: Sequence[Mapping[str, Any]],
) -> ProjectResolution:
    normalized_query_text = _required_text(
        query,
        "query",
    )

    trusted_merchant_id = _required_uuid(
        merchant_id,
        "merchant_id",
    )

    scoped_projects = _project_catalog(
        projects,
        trusted_merchant_id,
    )

    query_uuid = _canonical_uuid_or_none(
        normalized_query_text
    )

    if query_uuid is not None:
        matches = [
            project
            for project in scoped_projects
            if project.project_id == query_uuid
        ]

        return _terminal_resolution(
            query=normalized_query_text,
            merchant_id=trusted_merchant_id,
            match_kind=ProjectMatchKind.UUID,
            matches=matches,
        )

    normalized_query = _normalize_label(
        normalized_query_text
    )

    title_matches = [
        project
        for project in scoped_projects
        if (
            project.title is not None
            and _normalize_label(project.title)
            == normalized_query
        )
    ]

    if title_matches:
        return _terminal_resolution(
            query=normalized_query_text,
            merchant_id=trusted_merchant_id,
            match_kind=ProjectMatchKind.TITLE,
            matches=title_matches,
        )

    candidate_matches = [
        project
        for project in scoped_projects
        if (
            project.title is not None
            and _whole_token_sequence_match(
                normalized_query,
                _normalize_label(project.title),
            )
        )
    ]

    return _terminal_resolution(
        query=normalized_query_text,
        merchant_id=trusted_merchant_id,
        match_kind=(
            ProjectMatchKind.CANDIDATE
            if candidate_matches
            else ProjectMatchKind.NONE
        ),
        matches=candidate_matches,
    )


def _project_catalog(
    projects: Sequence[Mapping[str, Any]],
    merchant_id: str,
) -> tuple[ProjectEntity, ...]:
    seen_ids: set[str] = set()
    scoped: list[ProjectEntity] = []

    for raw_project in projects:
        project_id = _required_uuid(
            raw_project.get("id"),
            "project.id",
        )

        if project_id in seen_ids:
            raise ProjectEntityResolverError(
                f"Duplicate project id: {project_id}"
            )

        seen_ids.add(project_id)

        project_merchant_id = _required_uuid(
            raw_project.get("merchant_id"),
            "project.merchant_id",
        )

        if project_merchant_id != merchant_id:
            continue

        scoped.append(
            ProjectEntity(
                project_id=project_id,
                merchant_id=project_merchant_id,
                title=_optional_text(
                    raw_project.get("title")
                ),
                project_type=_optional_text(
                    raw_project.get("project_type")
                ),
                workflow_variant=_optional_text(
                    raw_project.get(
                        "workflow_variant"
                    )
                ),
                status=_optional_text(
                    raw_project.get("status")
                ),
                version=_optional_positive_integer(
                    raw_project.get("version")
                ),
            )
        )

    return tuple(scoped)


def _terminal_resolution(
    *,
    query: str,
    merchant_id: str,
    match_kind: ProjectMatchKind,
    matches: Sequence[ProjectEntity],
) -> ProjectResolution:
    ordered = tuple(
        sorted(
            matches,
            key=lambda project: project.project_id,
        )
    )

    if len(ordered) == 1:
        project = ordered[0]

        return ProjectResolution(
            query=query,
            merchant_id=merchant_id,
            status=ProjectResolutionStatus.RESOLVED,
            match_kind=match_kind,
            resolved=True,
            project_id=project.project_id,
            title=project.title,
            project_type=project.project_type,
            workflow_variant=project.workflow_variant,
            project_status=project.status,
            version=project.version,
            candidates=(
                _candidate(project),
            ),
        )

    if len(ordered) > 1:
        return ProjectResolution(
            query=query,
            merchant_id=merchant_id,
            status=ProjectResolutionStatus.AMBIGUOUS,
            match_kind=match_kind,
            resolved=False,
            project_id=None,
            title=None,
            project_type=None,
            workflow_variant=None,
            project_status=None,
            version=None,
            candidates=tuple(
                _candidate(project)
                for project in ordered
            ),
        )

    return ProjectResolution(
        query=query,
        merchant_id=merchant_id,
        status=ProjectResolutionStatus.NOT_FOUND,
        match_kind=ProjectMatchKind.NONE,
        resolved=False,
        project_id=None,
        title=None,
        project_type=None,
        workflow_variant=None,
        project_status=None,
        version=None,
        candidates=(),
    )


def _candidate(
    project: ProjectEntity,
) -> ProjectCandidate:
    return ProjectCandidate(
        project_id=project.project_id,
        merchant_id=project.merchant_id,
        title=project.title,
        project_type=project.project_type,
        workflow_variant=project.workflow_variant,
        status=project.status,
        version=project.version,
    )


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFKC",
        value,
    ).casefold()

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
    query_tokens = query.split()
    candidate_tokens = candidate.split()

    if not query_tokens:
        return False

    if len(query_tokens) > len(candidate_tokens):
        return False

    window_size = len(query_tokens)

    return any(
        candidate_tokens[
            index:index + window_size
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
            uuid.UUID(str(value).strip())
        )
    except (ValueError, AttributeError, TypeError):
        return None


def _required_uuid(
    value: Any,
    field_name: str,
) -> str:
    canonical = _canonical_uuid_or_none(
        value
    )

    if canonical is None:
        raise ProjectEntityResolverError(
            f"{field_name} must be a valid UUID"
        )

    return canonical


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise ProjectEntityResolverError(
            f"{field_name} must be non-empty text"
        )

    normalized = value.strip()

    if not normalized:
        raise ProjectEntityResolverError(
            f"{field_name} must be non-empty text"
        )

    return normalized


def _optional_text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def _optional_positive_integer(
    value: Any,
) -> int | None:
    if value is None:
        return None

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
    ):
        raise ProjectEntityResolverError(
            "project.version must be a positive integer"
        )

    return value