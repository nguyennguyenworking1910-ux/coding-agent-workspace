from __future__ import annotations

import re
import unicodedata
import uuid

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class DocumentRevisionEntityResolverError(ValueError):
    """Raised when the document revision catalog or resolver input is invalid."""


class DocumentRevisionResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class DocumentRevisionMatchKind(str, Enum):
    UUID = "UUID"
    REVISION_KEY = "REVISION_KEY"
    DOCUMENT_TYPE = "DOCUMENT_TYPE"
    CANDIDATE = "CANDIDATE"
    NONE = "NONE"


class DocumentRevisionScope(str, Enum):
    PROJECT = "PROJECT"
    MERCHANT = "MERCHANT"


@dataclass(frozen=True)
class DocumentRevisionEntity:
    revision_id: str
    project_id: str
    merchant_id: str
    document_type: str
    revision_number: int
    content_hash: str | None
    signed: bool
    signed_at: str | None
    effective_date: str | None
    expiry_date: str | None
    superseded_by: str | None


@dataclass(frozen=True)
class DocumentRevisionCandidate:
    revision_id: str
    project_id: str
    merchant_id: str
    document_type: str
    revision_number: int
    signed: bool
    superseded_by: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "project_id": self.project_id,
            "merchant_id": self.merchant_id,
            "document_type": self.document_type,
            "revision_number": self.revision_number,
            "signed": self.signed,
            "superseded_by": self.superseded_by,
        }


@dataclass(frozen=True)
class DocumentRevisionResolution:
    query: str
    scope: DocumentRevisionScope
    merchant_id: str
    project_id: str | None
    status: DocumentRevisionResolutionStatus
    match_kind: DocumentRevisionMatchKind
    resolved: bool
    revision_id: str | None
    source_project_id: str | None
    document_type: str | None
    revision_number: int | None
    signed: bool | None
    superseded_by: str | None
    candidates: tuple[DocumentRevisionCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "scope": self.scope.value,
            "merchant_id": self.merchant_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "match_kind": self.match_kind.value,
            "resolved": self.resolved,
            "revision_id": self.revision_id,
            "source_project_id": self.source_project_id,
            "document_type": self.document_type,
            "revision_number": self.revision_number,
            "signed": self.signed,
            "superseded_by": self.superseded_by,
            "candidates": [
                candidate.to_dict()
                for candidate in self.candidates
            ],
        }


def resolve_document_revision_entity(
    query: Any,
    merchant_id: Any,
    revisions: Sequence[Mapping[str, Any]],
    *,
    project_id: Any = None,
) -> DocumentRevisionResolution:
    """Resolve a revision inside a trusted Merchant or Project scope."""

    normalized_query_text = _required_text(query, "query")
    trusted_merchant_id = _required_uuid(merchant_id, "merchant_id")

    if project_id is None:
        scope = DocumentRevisionScope.MERCHANT
        trusted_project_id = None
    else:
        scope = DocumentRevisionScope.PROJECT
        trusted_project_id = _required_uuid(project_id, "project_id")

    scoped_revisions = _revision_catalog(
        revisions,
        trusted_merchant_id,
        trusted_project_id,
    )

    query_uuid = _canonical_uuid_or_none(normalized_query_text)

    if query_uuid is not None:
        matches = [
            revision
            for revision in scoped_revisions
            if revision.revision_id == query_uuid
        ]

        return _terminal_resolution(
            query=normalized_query_text,
            scope=scope,
            merchant_id=trusted_merchant_id,
            project_id=trusted_project_id,
            match_kind=DocumentRevisionMatchKind.UUID,
            matches=matches,
        )

    parsed_key = _parse_revision_key(normalized_query_text)

    if parsed_key is not None:
        query_document_type, query_revision_number = parsed_key

        matches = [
            revision
            for revision in scoped_revisions
            if (
                revision.document_type == query_document_type
                and revision.revision_number == query_revision_number
            )
        ]

        return _terminal_resolution(
            query=normalized_query_text,
            scope=scope,
            merchant_id=trusted_merchant_id,
            project_id=trusted_project_id,
            match_kind=DocumentRevisionMatchKind.REVISION_KEY,
            matches=matches,
        )

    normalized_query = _normalize_label(normalized_query_text)

    document_type_matches = [
        revision
        for revision in scoped_revisions
        if _normalize_label(revision.document_type) == normalized_query
    ]

    if document_type_matches:
        return _terminal_resolution(
            query=normalized_query_text,
            scope=scope,
            merchant_id=trusted_merchant_id,
            project_id=trusted_project_id,
            match_kind=DocumentRevisionMatchKind.DOCUMENT_TYPE,
            matches=document_type_matches,
        )

    candidate_matches = [
        revision
        for revision in scoped_revisions
        if _whole_token_sequence_match(
            normalized_query,
            _normalize_label(revision.document_type),
        )
    ]

    return _terminal_resolution(
        query=normalized_query_text,
        scope=scope,
        merchant_id=trusted_merchant_id,
        project_id=trusted_project_id,
        match_kind=(
            DocumentRevisionMatchKind.CANDIDATE
            if candidate_matches
            else DocumentRevisionMatchKind.NONE
        ),
        matches=candidate_matches,
    )


def _revision_catalog(
    revisions: Sequence[Mapping[str, Any]],
    merchant_id: str,
    project_id: str | None,
) -> tuple[DocumentRevisionEntity, ...]:
    if isinstance(revisions, (str, bytes, bytearray)):
        raise DocumentRevisionEntityResolverError(
            "Document revision catalog must be a sequence of records"
        )

    seen_ids: set[str] = set()
    scoped: list[DocumentRevisionEntity] = []

    for raw_revision in revisions:
        if not isinstance(raw_revision, Mapping):
            raise DocumentRevisionEntityResolverError(
                "Document revision catalog records must be objects"
            )

        revision_id = _required_uuid(
            raw_revision.get("revision_id", raw_revision.get("id")),
            "document_revision.id",
        )

        if revision_id in seen_ids:
            raise DocumentRevisionEntityResolverError(
                f"Duplicate document revision id: {revision_id}"
            )

        seen_ids.add(revision_id)

        revision_project_id = _required_uuid(
            raw_revision.get("project_id"),
            "document_revision.project_id",
        )

        revision_merchant_id = _required_uuid(
            raw_revision.get("merchant_id"),
            "document_revision.merchant_id",
        )

        document_type = _required_document_type(
            raw_revision.get("document_type")
        )

        revision_number = _required_positive_integer(
            raw_revision.get("revision_number"),
            "document_revision.revision_number",
        )

        content_hash = _optional_text(raw_revision.get("content_hash"))
        signed = _required_bool(
            raw_revision.get("signed"),
            "document_revision.signed",
        )
        signed_at = _optional_scalar_text(raw_revision.get("signed_at"))
        effective_date = _optional_scalar_text(
            raw_revision.get("effective_date")
        )
        expiry_date = _optional_scalar_text(raw_revision.get("expiry_date"))
        superseded_by = _optional_uuid(
            raw_revision.get("superseded_by"),
            "document_revision.superseded_by",
        )

        if revision_merchant_id != merchant_id:
            continue

        if project_id is not None and revision_project_id != project_id:
            continue

        scoped.append(
            DocumentRevisionEntity(
                revision_id=revision_id,
                project_id=revision_project_id,
                merchant_id=revision_merchant_id,
                document_type=document_type,
                revision_number=revision_number,
                content_hash=content_hash,
                signed=signed,
                signed_at=signed_at,
                effective_date=effective_date,
                expiry_date=expiry_date,
                superseded_by=superseded_by,
            )
        )

    return tuple(scoped)


def _terminal_resolution(
    *,
    query: str,
    scope: DocumentRevisionScope,
    merchant_id: str,
    project_id: str | None,
    match_kind: DocumentRevisionMatchKind,
    matches: Sequence[DocumentRevisionEntity],
) -> DocumentRevisionResolution:
    ordered = tuple(
        sorted(
            matches,
            key=lambda revision: (
                revision.document_type,
                revision.revision_number,
                revision.project_id,
                revision.revision_id,
            ),
        )
    )

    if len(ordered) == 1:
        revision = ordered[0]

        return DocumentRevisionResolution(
            query=query,
            scope=scope,
            merchant_id=merchant_id,
            project_id=project_id,
            status=DocumentRevisionResolutionStatus.RESOLVED,
            match_kind=match_kind,
            resolved=True,
            revision_id=revision.revision_id,
            source_project_id=revision.project_id,
            document_type=revision.document_type,
            revision_number=revision.revision_number,
            signed=revision.signed,
            superseded_by=revision.superseded_by,
            candidates=(_candidate(revision),),
        )

    if len(ordered) > 1:
        return DocumentRevisionResolution(
            query=query,
            scope=scope,
            merchant_id=merchant_id,
            project_id=project_id,
            status=DocumentRevisionResolutionStatus.AMBIGUOUS,
            match_kind=match_kind,
            resolved=False,
            revision_id=None,
            source_project_id=None,
            document_type=None,
            revision_number=None,
            signed=None,
            superseded_by=None,
            candidates=tuple(_candidate(revision) for revision in ordered),
        )

    return DocumentRevisionResolution(
        query=query,
        scope=scope,
        merchant_id=merchant_id,
        project_id=project_id,
        status=DocumentRevisionResolutionStatus.NOT_FOUND,
        match_kind=DocumentRevisionMatchKind.NONE,
        resolved=False,
        revision_id=None,
        source_project_id=None,
        document_type=None,
        revision_number=None,
        signed=None,
        superseded_by=None,
        candidates=(),
    )


def _candidate(
    revision: DocumentRevisionEntity,
) -> DocumentRevisionCandidate:
    return DocumentRevisionCandidate(
        revision_id=revision.revision_id,
        project_id=revision.project_id,
        merchant_id=revision.merchant_id,
        document_type=revision.document_type,
        revision_number=revision.revision_number,
        signed=revision.signed,
        superseded_by=revision.superseded_by,
    )


def _parse_revision_key(value: str) -> tuple[str, int] | None:
    match = re.fullmatch(
        r"\s*([A-Za-z][A-Za-z0-9_]{0,99})\s*#\s*([1-9][0-9]*)\s*",
        unicodedata.normalize("NFKC", value),
    )

    if match is None:
        return None

    return match.group(1).upper(), int(match.group(2))


def _required_document_type(value: Any) -> str:
    if not isinstance(value, str):
        raise DocumentRevisionEntityResolverError(
            "document_revision.document_type must be text"
        )

    normalized = unicodedata.normalize("NFKC", value).strip().upper()

    if re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", normalized) is None:
        raise DocumentRevisionEntityResolverError(
            "document_revision.document_type must contain only uppercase "
            "letters, digits, and underscores and must start with a letter"
        )

    return normalized


def _normalize_label(
    value: str,
) -> str:
    normalized = unicodedata.normalize(
        "NFKC",
        value,
    ).casefold()

    # Document types use underscores as structural separators.
    # Treat them like punctuation/whitespace for semantic matching
    # so MEDIA_APPENDIX becomes "media appendix".
    normalized = normalized.replace(
        "_",
        " ",
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
    query_tokens = query.split()
    candidate_tokens = candidate.split()

    if not query_tokens:
        return False

    if len(query_tokens) > len(candidate_tokens):
        return False

    window_size = len(query_tokens)

    return any(
        candidate_tokens[index:index + window_size] == query_tokens
        for index in range(
            len(candidate_tokens) - window_size + 1
        )
    )


def _canonical_uuid_or_none(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError, TypeError):
        return None


def _required_uuid(
    value: Any,
    field_name: str,
) -> str:
    canonical = _canonical_uuid_or_none(value)

    if canonical is None:
        raise DocumentRevisionEntityResolverError(
            f"{field_name} must be a valid UUID"
        )

    return canonical


def _optional_uuid(
    value: Any,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    canonical = _canonical_uuid_or_none(value)

    if canonical is None:
        raise DocumentRevisionEntityResolverError(
            f"{field_name} must be a valid UUID or null"
        )

    return canonical


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise DocumentRevisionEntityResolverError(
            f"{field_name} must be non-empty text"
        )

    normalized = unicodedata.normalize("NFKC", value).strip()

    if not normalized:
        raise DocumentRevisionEntityResolverError(
            f"{field_name} must be non-empty text"
        )

    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def _optional_scalar_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def _required_positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DocumentRevisionEntityResolverError(
            f"{field_name} must be a positive integer"
        )

    return value


def _required_bool(
    value: Any,
    field_name: str,
) -> bool:
    if not isinstance(value, bool):
        raise DocumentRevisionEntityResolverError(
            f"{field_name} must be a boolean"
        )

    return value