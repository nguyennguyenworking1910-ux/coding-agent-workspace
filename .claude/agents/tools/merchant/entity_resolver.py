"""Pure deterministic Merchant entity resolution.

This module contains no repository, database, CLI, or LLM access.

Resolution precedence is fixed:

1. exact UUID
2. exact Merchant code
3. exact normalized Merchant name
4. exact normalized alias
5. deterministic candidate matching

A unique match may be bound. Multiple matches fail closed as AMBIGUOUS.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class MerchantEntityResolverError(ValueError):
    """Raised when resolver input violates the deterministic contract."""


class MerchantResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class MerchantMatchKind(str, Enum):
    UUID = "UUID"
    CODE = "CODE"
    NAME = "NAME"
    ALIAS = "ALIAS"
    CANDIDATE = "CANDIDATE"
    NONE = "NONE"


@dataclass(frozen=True)
class MerchantEntity:
    merchant_id: str
    code: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class MerchantCandidate:
    merchant_id: str
    code: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return {
            "merchant_id": self.merchant_id,
            "code": self.code,
            "name": self.name,
        }


@dataclass(frozen=True)
class MerchantResolution:
    query: str
    status: MerchantResolutionStatus
    match_kind: MerchantMatchKind
    merchant_id: str | None
    code: str | None
    name: str | None
    candidates: tuple[MerchantCandidate, ...]

    @property
    def resolved(self) -> bool:
        return (
            self.status
            == MerchantResolutionStatus.RESOLVED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status.value,
            "match_kind": self.match_kind.value,
            "resolved": self.resolved,
            "merchant_id": self.merchant_id,
            "code": self.code,
            "name": self.name,
            "candidates": [
                candidate.to_dict()
                for candidate in self.candidates
            ],
        }


def resolve_merchant_entity(
    query: Any,
    merchants: Sequence[
        MerchantEntity | Mapping[str, Any]
    ],
) -> MerchantResolution:
    """Resolve one Merchant reference using fixed deterministic precedence."""

    normalized_query = _require_query(
        query
    )

    entities = _normalize_entities(
        merchants
    )

    # ------------------------------------------------------------
    # 1. Exact UUID
    # ------------------------------------------------------------
    uuid_query = _canonical_uuid_or_none(
        normalized_query
    )

    if uuid_query is not None:
        matches = tuple(
            entity
            for entity in entities
            if entity.merchant_id
            == uuid_query
        )

        return _terminal_resolution(
            normalized_query,
            MerchantMatchKind.UUID,
            matches,
        )

    # ------------------------------------------------------------
    # 2. Exact Merchant code
    # ------------------------------------------------------------
    code_query = _normalize_code(
        normalized_query
    )

    code_matches = tuple(
        entity
        for entity in entities
        if _normalize_code(
            entity.code
        )
        == code_query
    )

    if code_matches:
        return _terminal_resolution(
            normalized_query,
            MerchantMatchKind.CODE,
            code_matches,
        )

    # ------------------------------------------------------------
    # 3. Exact normalized Merchant name
    # ------------------------------------------------------------
    label_query = _normalize_label(
        normalized_query
    )

    name_matches = tuple(
        entity
        for entity in entities
        if _normalize_label(
            entity.name
        )
        == label_query
    )

    if name_matches:
        return _terminal_resolution(
            normalized_query,
            MerchantMatchKind.NAME,
            name_matches,
        )

    # ------------------------------------------------------------
    # 4. Exact alias
    # ------------------------------------------------------------
    alias_matches = tuple(
        entity
        for entity in entities
        if any(
            _normalize_label(alias)
            == label_query
            for alias in entity.aliases
        )
    )

    if alias_matches:
        return _terminal_resolution(
            normalized_query,
            MerchantMatchKind.ALIAS,
            alias_matches,
        )

    # ------------------------------------------------------------
    # 5. Candidate matching
    #
    # Candidate matching is intentionally conservative:
    # the normalized query must occur as a whole token sequence
    # inside the normalized code, name, or alias.
    #
    # One candidate -> deterministic unique resolution.
    # Multiple candidates -> fail closed.
    # ------------------------------------------------------------
    candidate_matches = tuple(
        entity
        for entity in entities
        if _is_candidate_match(
            label_query,
            entity,
        )
    )

    if candidate_matches:
        return _terminal_resolution(
            normalized_query,
            MerchantMatchKind.CANDIDATE,
            candidate_matches,
        )

    return MerchantResolution(
        query=normalized_query,
        status=(
            MerchantResolutionStatus.NOT_FOUND
        ),
        match_kind=(
            MerchantMatchKind.NONE
        ),
        merchant_id=None,
        code=None,
        name=None,
        candidates=(),
    )


def _terminal_resolution(
    query: str,
    match_kind: MerchantMatchKind,
    matches: Sequence[MerchantEntity],
) -> MerchantResolution:
    unique_matches = _unique_entities(
        matches
    )

    ordered = tuple(
        sorted(
            unique_matches,
            key=lambda entity: (
                _normalize_code(
                    entity.code
                ),
                entity.merchant_id,
            ),
        )
    )

    candidates = tuple(
        MerchantCandidate(
            merchant_id=entity.merchant_id,
            code=entity.code,
            name=entity.name,
        )
        for entity in ordered
    )

    # ------------------------------------------------------------
    # No exact match at this precedence level.
    #
    # Important for UUID resolution: once the query is recognized
    # as a valid UUID, it must not fall through to code/name/alias
    # matching. A missing UUID is deterministically NOT_FOUND.
    # ------------------------------------------------------------
    if not ordered:
        return MerchantResolution(
            query=query,
            status=(
                MerchantResolutionStatus.NOT_FOUND
            ),
            match_kind=match_kind,
            merchant_id=None,
            code=None,
            name=None,
            candidates=(),
        )

    if len(
        ordered
    ) == 1:
        selected = ordered[0]

        return MerchantResolution(
            query=query,
            status=(
                MerchantResolutionStatus.RESOLVED
            ),
            match_kind=match_kind,
            merchant_id=(
                selected.merchant_id
            ),
            code=selected.code,
            name=selected.name,
            candidates=candidates,
        )

    return MerchantResolution(
        query=query,
        status=(
            MerchantResolutionStatus.AMBIGUOUS
        ),
        match_kind=match_kind,
        merchant_id=None,
        code=None,
        name=None,
        candidates=candidates,
    )


def _normalize_entities(
    merchants: Sequence[
        MerchantEntity | Mapping[str, Any]
    ],
) -> tuple[MerchantEntity, ...]:
    if isinstance(
        merchants,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        raise MerchantEntityResolverError(
            "Merchant catalog must be a sequence of records"
        )

    normalized: list[
        MerchantEntity
    ] = []

    seen_ids: set[str] = set()

    for raw_entity in merchants:
        entity = _normalize_entity(
            raw_entity
        )

        if entity.merchant_id in seen_ids:
            raise MerchantEntityResolverError(
                "Merchant catalog contains duplicate merchant_id: "
                f"{entity.merchant_id}"
            )

        seen_ids.add(
            entity.merchant_id
        )

        normalized.append(
            entity
        )

    return tuple(
        normalized
    )


def _normalize_entity(
    value: MerchantEntity | Mapping[str, Any],
) -> MerchantEntity:
    if isinstance(
        value,
        MerchantEntity,
    ):
        merchant_id = value.merchant_id
        code = value.code
        name = value.name
        aliases: Any = value.aliases

    elif isinstance(
        value,
        Mapping,
    ):
        merchant_id = value.get(
            "merchant_id",
            value.get(
                "id"
            ),
        )

        code = value.get(
            "code"
        )

        name = value.get(
            "name"
        )

        aliases = value.get(
            "aliases",
            (),
        )

    else:
        raise MerchantEntityResolverError(
            "Merchant catalog records must be objects"
        )

    canonical_id = (
        _canonical_uuid_or_none(
            merchant_id
        )
    )

    if canonical_id is None:
        raise MerchantEntityResolverError(
            "Merchant merchant_id must be a valid UUID"
        )

    canonical_code = (
        _require_nonempty_text(
            code,
            "Merchant code",
        )
    )

    canonical_name = (
        _require_nonempty_text(
            name,
            "Merchant name",
        )
    )

    canonical_aliases = (
        _normalize_aliases(
            aliases
        )
    )

    return MerchantEntity(
        merchant_id=canonical_id,
        code=canonical_code,
        name=canonical_name,
        aliases=canonical_aliases,
    )


def _normalize_aliases(
    aliases: Any,
) -> tuple[str, ...]:
    if aliases is None:
        return ()

    if isinstance(
        aliases,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        raise MerchantEntityResolverError(
            "Merchant aliases must be a sequence of strings"
        )

    if not isinstance(
        aliases,
        Iterable,
    ):
        raise MerchantEntityResolverError(
            "Merchant aliases must be a sequence of strings"
        )

    normalized: list[str] = []
    seen: set[str] = set()

    for alias in aliases:
        text = _require_nonempty_text(
            alias,
            "Merchant alias",
        )

        key = _normalize_label(
            text
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        normalized.append(
            text
        )

    return tuple(
        normalized
    )


def _unique_entities(
    merchants: Sequence[MerchantEntity],
) -> tuple[MerchantEntity, ...]:
    unique: dict[
        str,
        MerchantEntity,
    ] = {}

    for entity in merchants:
        unique[
            entity.merchant_id
        ] = entity

    return tuple(
        unique.values()
    )


def _is_candidate_match(
    normalized_query: str,
    entity: MerchantEntity,
) -> bool:
    if len(
        normalized_query
    ) < 2:
        return False

    searchable_values = (
        _normalize_label(
            entity.code
        ),
        _normalize_label(
            entity.name
        ),
        *(
            _normalize_label(
                alias
            )
            for alias in entity.aliases
        ),
    )

    return any(
        _contains_token_sequence(
            value,
            normalized_query,
        )
        for value in searchable_values
    )


def _contains_token_sequence(
    value: str,
    query: str,
) -> bool:
    if not value or not query:
        return False

    return (
        value == query
        or value.startswith(
            query + " "
        )
        or value.endswith(
            " " + query
        )
        or (
            " " + query + " "
        )
        in (
            " " + value + " "
        )
    )


def _require_query(
    value: Any,
) -> str:
    return _require_nonempty_text(
        value,
        "Merchant query",
    )


def _require_nonempty_text(
    value: Any,
    field_name: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise MerchantEntityResolverError(
            f"{field_name} must be text"
        )

    normalized = (
        unicodedata.normalize(
            "NFKC",
            value,
        )
        .strip()
    )

    if not normalized:
        raise MerchantEntityResolverError(
            f"{field_name} must not be empty"
        )

    return normalized


def _canonical_uuid_or_none(
    value: Any,
) -> str | None:
    if isinstance(
        value,
        uuid.UUID,
    ):
        return str(
            value
        )

    if not isinstance(
        value,
        str,
    ):
        return None

    text = value.strip()

    if not text:
        return None

    try:
        return str(
            uuid.UUID(
                text
            )
        )
    except (
        ValueError,
        AttributeError,
    ):
        return None


def _normalize_code(
    value: str,
) -> str:
    return (
        unicodedata.normalize(
            "NFKC",
            value,
        )
        .strip()
        .casefold()
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

    characters = [
        character
        if character.isalnum()
        else " "
        for character in normalized
    ]

    return re.sub(
        r"\s+",
        " ",
        "".join(
            characters
        ),
    ).strip()