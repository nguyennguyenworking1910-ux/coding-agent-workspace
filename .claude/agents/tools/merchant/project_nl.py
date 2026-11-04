"""Deterministic Vietnamese/English interpretation of Merchant project requests.

Pure text analysis: no repository, database, CLI or model access. The result
names what the user talks about (``kind``) and plain-text entity candidates.
Candidates are never identities: only trusted resolution against the
authoritative repository can bind them (see ``project_preview``).

A write is requested only by an affirmative creation or update. Negated,
exploratory, preview-only and question wording never requests one.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass


PROJECT_CREATE = "PROJECT_CREATE"
MERCHANT_CREATE = "MERCHANT_CREATE"
PROJECT_LIST = "PROJECT_LIST"
PROJECT_STATUS = "PROJECT_STATUS"
STEP_UPDATE = "STEP_UPDATE"
MIXED = "MIXED"
UNKNOWN = "UNKNOWN"

# Patterns run on fold()ed text: casefolded, accents removed, đ -> d,
# punctuation -> spaces, single-spaced.
_PROJECT_NOUN = r"(?:projects?|du an|duan)"
_MERCHANT_NOUN = r"(?:merchants?|doi tac|nha cung cap|partner)"
_CREATE_VERB = (
    r"(?:tao(?: moi)?|khoi tao|lap|them|create|add|set up|setup|"
    r"start|open|new)"
)

# Project type keywords. Each phrase may be followed by the site name.
_TYPE_PHRASES = (
    ("OPENING_NEW_CINEMA", r"(?:mo|khai truong|mo moi)(?: (?:them|moi))? rap(?: moi)?"),
    ("OPENING_NEW_CINEMA", r"rap moi"),
    ("OPENING_NEW_CINEMA", r"(?:new )?cinema opening"),
    ("OPENING_NEW_CINEMA", r"open(?:ing)?(?: (?:a|the|new))* cinema"),
    ("OPENING_NEW_CINEMA", r"new cinema"),
    ("MEDIA_TOP_UP", r"(?:media top ?up|top ?up media|nap media)"),
    # Only with a Merchant noun: bare "integration" is usually code work.
    (
        "INTEGRATION_NEW_MERCHANT",
        r"(?:tich hop|integrat(?:e|ion)(?: of)?)(?: (?:a|new|moi))* "
        r"(?:merchant|doi tac)",
    ),
)

_NEGATION = (
    r"\b(?:khong|dung|chua|ko|do not|don t|dont|never|not|no need to|"
    r"must not|should not)\b(?: \w+){0,3}? "
    + _CREATE_VERB
    + r"\b"
)
_PREVIEW = (
    r"\b(?:preview|dry run|xem truoc|xem thu|chi xem|chi de xuat|"
    r"proposal only|without (?:creating|saving|applying))\b"
)
_EXPLORATORY = (
    r"\b(?:should (?:i|we)|co nen|nen tao khong|how (?:do|to|can|would)|"
    r"lam (?:sao|the nao)|nhu the nao|what if|neu tao|is it possible|"
    r"co the tao .* khong|can we\b.*\?)"
)
_STEP_UPDATE = (
    r"\b(?:(?:cap nhat|hoan thanh|danh dau|chuyen) buoc|"
    r"buoc .{0,40} (?:da )?(?:xong|hoan thanh)|"
    r"(?:update|complete|mark|finish|close) (?:the )?(?:\w+ ){0,3}step)\b"
)
_STATUS = (
    r"\b(?:dang o buoc nao|o buoc nao|buoc nao|buoc hien tai|tien do|"
    r"trang thai|which step|what step|current step|status of|progress of|"
    r"where is)\b"
)
_LIST = (
    r"\b(?:(?:cac|nhung|danh sach|liet ke)(?: \w+){0,2} " + _PROJECT_NOUN
    + r"|" + _PROJECT_NOUN + r" (?:hien tai|hien co|dang chay)"
    + r"|(?:list|show|what|which|current|existing)(?: \w+){0,2} projects)\b"
)

# Words that end a name phrase.
_STOP_WORDS = frozenset(
    "cho cua o tai la gi va for of at in to with and is are dang nao "
    "project projects please nhe nha giup minh toi khong without co can "
    "khi voi under thuoc tren on database db".split()
)
_STOP_PAIRS = frozenset({"hien tai", "hien co", "du an", "la gi"})
# Words skipped at the start of a name phrase.
_LEAD_WORDS = frozenset({"the", "a", "rap", "cinema", "project", "projects"})


@dataclass(frozen=True)
class ProjectRequestInterpretation:
    """Plain-text candidates extracted from one request. Never identities."""

    kind: str
    write_requested: bool
    negated: bool
    preview_only: bool
    exploratory: bool
    question: bool
    project_type: str | None
    merchant_phrase: str | None
    site_phrase: str | None
    project_phrase: str | None
    requires_procurement: bool | None
    media_document: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def fold(value: str) -> str:
    """Casefold, strip accents (đ -> d), turn punctuation into spaces."""

    decomposed = unicodedata.normalize("NFD", value.casefold())
    text = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    ).replace("đ", "d")
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def interpret_project_request(request: str) -> ProjectRequestInterpretation:
    """Classify one request and extract plain-text entity candidates."""

    if not isinstance(request, str) or not request.strip():
        raise ValueError("request must be non-empty text")

    words = _Words(request)
    text = words.folded

    negated = re.search(_NEGATION, text) is not None
    preview_only = re.search(_PREVIEW, text) is not None
    exploratory = re.search(_EXPLORATORY, fold_keep_question(request)) is not None
    question = "?" in request or re.search(r"\b(?:la gi|nao|khong)$", text) is not None

    project_type, type_end = _project_type(text)
    named_cinema = re.search(
        r"\bopen(?:ing)? (?:(?:a|the|new) )*((?:\w+ ){1,6}?)cinemas?\b", text
    )
    if project_type is None and named_cinema:
        # "open Beta Nguyễn Văn Cừ cinema": the name sits before "cinema".
        project_type = "OPENING_NEW_CINEMA"
    has_project = re.search(rf"\b{_PROJECT_NOUN}\b", text) is not None
    creates_merchant = (
        re.search(
            rf"\b{_CREATE_VERB}(?: (?:a|an|mot|new|moi))* {_MERCHANT_NOUN}\b",
            text,
        )
        is not None
    )
    # A preview verb ("xem trước dự án mở rạp ...") asks about a creation
    # too; preview_only keeps it from requesting a write.
    creates_project = (
        has_project or project_type is not None
    ) and re.search(
        rf"\b(?:{_CREATE_VERB}|preview|xem truoc|xem thu|dry run)\b"
        rf"(?: \w+){{0,4}} (?:{_PROJECT_NOUN}\b|"
        + "|".join(pattern for _, pattern in _TYPE_PHRASES)
        + r")",
        text,
    ) is not None

    if re.search(_STEP_UPDATE, text):
        kind = STEP_UPDATE
    elif creates_merchant and creates_project:
        kind = MIXED
    elif creates_merchant:
        kind = MERCHANT_CREATE
    elif creates_project:
        kind = PROJECT_CREATE
    elif has_project and re.search(_STATUS, text):
        kind = PROJECT_STATUS
    elif re.search(_LIST, text):
        kind = PROJECT_LIST
    else:
        kind = UNKNOWN

    merchant_phrase = site_phrase = project_phrase = None

    if kind == PROJECT_CREATE:
        site_phrase = (
            words.between(*named_cinema.span(1))
            if named_cinema and type_end is None
            else words.phrase_after(type_end) if type_end else None
        )
        merchant_phrase = words.phrase_after_word(("cho", "for", "cua", "of"))
        owner = words.phrase_after_word(("under", "thuoc"))
        if owner is not None:
            # "... for Beta Nguyễn Văn Cừ under Beta Cinemas": the owner
            # names the Merchant; the "for" phrase is the site.
            site_phrase = site_phrase or merchant_phrase
            merchant_phrase = owner
        elif merchant_phrase is None and site_phrase is not None:
            # "mở rạp Beta Nguyễn Văn Cừ": the merchant leads the site name.
            merchant_phrase, site_phrase = site_phrase, None
    elif kind == PROJECT_LIST:
        merchant_phrase = words.phrase_after_word(("cua", "of", "for", "cho"))
    elif kind == PROJECT_STATUS:
        project_phrase = words.phrase_after_word(
            ("project", "projects", "du an")
        ) or words.phrase_after_word(("of",))

    write_requested = (
        kind in {PROJECT_CREATE, MERCHANT_CREATE, STEP_UPDATE, MIXED}
        and not (negated or preview_only or exploratory)
    )

    return ProjectRequestInterpretation(
        kind=kind,
        write_requested=write_requested,
        negated=negated,
        preview_only=preview_only,
        exploratory=exploratory,
        question=question,
        project_type=project_type,
        merchant_phrase=merchant_phrase,
        site_phrase=site_phrase,
        project_phrase=project_phrase,
        requires_procurement=_requires_procurement(text),
        media_document=_media_document(text),
    )


def fold_keep_question(value: str) -> str:
    """fold() but keep '?' so question-shaped patterns can see it."""

    return " ".join(fold(part) + "?" for part in value.split("?"))[:-1]


_TEST_WORD = r"(?:test|testing|thu nghiem|kiem thu)"
_DATABASE_WORD = r"(?:database|db|co so du lieu|csdl)"
_TEST_DATABASE = re.compile(
    rf"\b(?:{_TEST_WORD} {_DATABASE_WORD}|{_DATABASE_WORD} {_TEST_WORD})\b"
)
_TEST_DATABASE_NEGATION = frozenset({"khong", "not", "no", "never", "without", "chang"})


def requests_test_database(request: str) -> bool:
    """True when the user's own words ask for the Merchant test database.

    Deterministic over the user's request text (never a model's output). A
    negation within the four preceding words ("không dùng database test",
    "not on the test database") keeps the runtime target.
    """

    if not isinstance(request, str):
        return False

    text = fold(request)

    for match in _TEST_DATABASE.finditer(text):
        before = text[: match.start()].split()[-4:]
        if not _TEST_DATABASE_NEGATION.intersection(before):
            return True

    return False


def _project_type(text: str) -> tuple[str | None, int | None]:
    found = [
        (match.start(), match.end(), project_type)
        for project_type, pattern in _TYPE_PHRASES
        for match in re.finditer(rf"\b{pattern}\b", text)
    ]
    types = {project_type for _, _, project_type in found}

    if len(types) != 1:
        # None, or several conflicting types: let resolution ask.
        return None, None

    _, end, project_type = max(found, key=lambda item: item[1])
    return project_type, end


def _requires_procurement(text: str) -> bool | None:
    noun = r"(?:procurement|purchase request|mua sam|de nghi mua|\bpr\b)"
    if re.search(
        rf"\b(?:khong|no|without|not|chua|ko)\b(?: \w+){{0,3}} {noun}", text
    ):
        return False
    if re.search(noun, text):
        return True
    return None


def _media_document(text: str) -> str | None:
    if re.search(r"\b(?:existing|current|hien co|cu) (?:document|hop dong|tai lieu)\b", text):
        return "EXISTING"
    if re.search(r"\b(?:new|renew|moi|gia han) (?:document|hop dong|tai lieu)\b", text):
        return "NEW"
    return None


class _Words:
    """Original words aligned with their folded forms."""

    def __init__(self, request: str) -> None:
        self.original: list[str] = []
        self.folded_words: list[str] = []
        self.starts: list[int] = []
        # True when punctuation separates a word from the one before it.
        self.breaks: list[bool] = []
        position = 0
        previous_end = 0
        text = unicodedata.normalize("NFC", request)

        for match in re.finditer(r"\w+", text):
            folded = fold(match.group())
            if folded:
                self.original.append(match.group())
                self.folded_words.append(folded)
                self.starts.append(position)
                self.breaks.append(
                    re.search(r"[,.;:!?()]", text[previous_end:match.start()])
                    is not None
                )
                position += len(folded) + 1
            previous_end = match.end()

        self.folded = " ".join(self.folded_words)

    def between(self, start: int, end: int) -> str | None:
        """Original words whose folded text lies within [start, end)."""

        phrase = [
            word
            for word, folded, word_start in zip(
                self.original, self.folded_words, self.starts
            )
            if word_start >= start and word_start + len(folded) <= end
        ]
        return " ".join(phrase) or None

    def phrase_after(self, end: int) -> str | None:
        """Name phrase starting at the first word after folded offset ``end``."""

        start = next(
            (index for index, word_start in enumerate(self.starts) if word_start >= end),
            len(self.original),
        )
        return self._phrase(start)

    def phrase_after_word(self, anchors: tuple[str, ...]) -> str | None:
        for anchor in anchors:
            parts = anchor.split()
            for index in range(len(self.folded_words) - len(parts) + 1):
                if self.folded_words[index:index + len(parts)] == parts:
                    phrase = self._phrase(index + len(parts))
                    if phrase:
                        return phrase
        return None

    def _pair(self, index: int) -> str:
        return " ".join(self.folded_words[index:index + 2])

    def _phrase(self, start: int) -> str | None:
        while start < len(self.original) and (
            self.folded_words[start] in _LEAD_WORDS
            or self._pair(start) == "du an"
        ):
            start += 2 if self._pair(start) == "du an" else 1

        end = start
        while end < len(self.original) and not (
            (end > start and self.breaks[end])
            or self.folded_words[end] in _STOP_WORDS
            or self._pair(end) in _STOP_PAIRS
        ):
            end += 1

        return " ".join(self.original[start:end]) or None
