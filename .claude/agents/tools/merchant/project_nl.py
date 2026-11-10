"""Deterministic Vietnamese/English interpretation of Merchant project requests.

Pure text analysis: no repository, database, CLI or model access. The result
names what the user talks about (``kind``) and plain-text entity candidates.
Candidates are never identities: only trusted resolution against the
authoritative repository can bind them (see ``project_preview``).

A write is requested only by an affirmative creation or update. Negated,
exploratory, preview-only and question wording never requests one.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import asdict, dataclass


PROJECT_CREATE = "PROJECT_CREATE"
MERCHANT_CREATE = "MERCHANT_CREATE"
PROJECT_LIST = "PROJECT_LIST"
PROJECT_STATUS = "PROJECT_STATUS"
STEP_UPDATE = "STEP_UPDATE"
# CP12H.NL4D2: a read-only question about document revisions, approvals,
# procurement records or the evidence a workflow gate still lacks.
EVIDENCE_STATUS = "EVIDENCE_STATUS"
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
# An update verb that names the step: never inferred from a state word.
_STEP_UPDATE_EXPLICIT = (
    r"\b(?:(?:cap nhat|hoan thanh|danh dau|chuyen|bat dau|bo qua) buoc|"
    r"(?:update|complete|mark|finish|close|start|skip) (?:the )?(?:\w+ ){0,6}step)\b"
)
# The explicit verbs, or a step stated as done ("bước X đã xong").
_STEP_UPDATE = (
    _STEP_UPDATE_EXPLICIT + r"|\bbuoc .{0,40} (?:da )?(?:xong|hoan thanh)\b"
)
# A question about steps ("Những bước nào đã hoàn thành ...?") is a read.
_STEP_QUESTION = (
    r"\b(?:buoc nao|nhung buoc|cac buoc|buoc dang cho|dang cho|con vuong|"
    r"vuong o dau|bi vuong|which steps?|what steps?|pending steps|"
    r"remaining steps|(?:list|show)(?: me)?(?: all)?(?: the)? steps|"
    # "Bước X đã hoàn thành chưa?" asks; it does not mark anything.
    r"(?:xong|hoan thanh) chua|(?:is|has) (?:the )?(?:\w+ ){0,4}step)\b"
)
_STATUS = (
    r"\b(?:dang o buoc nao|o buoc nao|buoc nao|buoc hien tai|tien do|"
    r"trang thai|which step|what step|current step|status of|progress of|"
    r"where is)\b"
)
# A collection operation over Projects: a list verb, or a plural/"all"
# determiner, whose object is the Project noun. The words in between may not
# name steps ("liệt kê các bước của Project X" is about one Project). English
# needs the plural ("show me the status of project X" is one Project);
# Vietnamese nouns have none.
_NOT_STEP = r"(?: (?!buoc\b|steps?\b)\w+)"
_LIST_OPERATION = (
    rf"\b(?:(?:liet ke|danh sach){_NOT_STEP}{{0,3}} {_PROJECT_NOUN}"
    rf"|(?:list|show(?: me)? all){_NOT_STEP}{{0,3}} projects"
    rf"|(?:tat ca|cac|nhung){_NOT_STEP}{{0,2}} {_PROJECT_NOUN}"
    rf"|all{_NOT_STEP}{{0,2}} projects)\b"
)
# CP12H.NL4B: the state a step update asks for. Folded phrases, longest first
# within a state; values are the domain's step statuses (state_machine).
_TARGET_STATES = (
    ("IN_PROGRESS", r"dang thuc hien|dang tien hanh|dang lam|in progress|in-progress|started"),
    ("COMPLETED", r"hoan thanh|da xong|xong|completed|complete|done|finished"),
    ("READY", r"san sang|ready"),
    ("BLOCKED", r"bi chan|tam chan|blocked"),
    ("SKIPPED", r"bo qua|skipped|skip"),
    ("SUPERSEDED", r"bi thay the|superseded"),
)
# "... là hoàn thành", "... thành đang thực hiện", "... as in progress".
_STATE_CONNECTOR = r"(?:la|thanh|sang|ve|as|to|into)"
_ANY_STATE = "|".join(pattern for _, pattern in _TARGET_STATES)
# CP12H.NL4B-FIX2: "Đánh dấu Legal Review là hoàn thành", "Mark X as completed":
# an explicit mark verb and a connector clause name a step without the noun.
# CP12H.NL4C2B-FIX: no word-count cap on the name: a long step title plus a
# Project name ("Draft or renew document của Project Beta NL4C2B Step
# Acceptance") is still a mark; the shortest name before a connector wins.
_MARK_AS = (
    rf"\b(?:danh dau|mark) (?:\w+ )+?{_STATE_CONNECTOR} "
    rf"(?:(?:da|duoc|the|be) )?(?:{_ANY_STATE})\b"
)
# A state stated right after the name with no connector ("Đánh dấu bước Legal
# Review hoàn thành"). Only phrases that already end a name phrase (stop words
# and pairs), so a state word inside a step title ("Complete UAT acceptance")
# is never read as the target.
_BARE_STATES = (
    ("COMPLETED", r"(?:da )?(?:hoan thanh|xong)"),
    ("IN_PROGRESS", r"(?:dang thuc hien|dang tien hanh|dang lam)"),
    ("BLOCKED", r"bi chan"),
)
_BARE_STATE_VERB = r"\b(?:danh dau|cap nhat|chuyen) buoc\b"
# A yes/no question about a step's state is a read, even with an update verb
# ("Đã đánh dấu bước X hoàn thành chưa?", "Did you mark ... ?").
_DONE_QUESTION = r"\b(?:xong|hoan thanh) chua\b|^(?:did|have|has|was|is) "
# Hedged wording never requests a write: "Có lẽ đánh dấu ...", "Maybe mark ...".
_STEP_UNCERTAIN = (
    r"\b(?:co le|hinh nhu|chac la|khong biet co|co nen|maybe|perhaps|"
    r"not sure|should (?:i|we)|i think)\b"
)
# CP12H.NL4B-FIX2B: a second action joined to a step update ("... và lên lịch
# họp", "... rồi xóa merchant", "... and then delete ...") makes the request
# MIXED: it is never downgraded to the single-step read-only preview.
_FURTHER_ACTION = (
    r"\b(?:va|roi|sau do|dong thoi|and|then|also|plus)(?: \w+){0,2}? "
    r"(?:tao|xoa|sua|them|gui|len lich|dat lich|cap nhat|danh dau|chuyen|duyet|"
    r"kich hoat|thuc thi|trien khai|chay|huy|doi|thay doi|nhap|gan|hoan thanh|"
    r"bat dau|bo qua|create|delete|remove|fix|update|add|send|schedule|book|"
    r"deploy|run|set|change|approve|activate|execute|cancel|mark|complete|start|"
    r"skip|import|assign|email|notify|edit|refactor|implement)\b"
)
# A verb that itself names the state: "Hoàn thành bước X", "Start step 2".
_STATE_VERBS = (
    ("COMPLETED", r"^(?:hoan thanh|complete|finish|close)$"),
    ("IN_PROGRESS", r"^(?:bat dau|start)$"),
    ("SKIPPED", r"^(?:bo qua|skip)$"),
)
_STEP_NEGATION = (
    r"\b(?:khong|dung|chua|ko|do not|don t|dont|never|not)\b(?: \w+){0,2}? "
    r"(?:cap nhat|danh dau|hoan thanh|chuyen|bat dau|update|mark|complete|start|set)\b"
)
# Weaker list wording, after status: "project hiện có", "which projects".
_LIST = (
    r"\b(?:" + _PROJECT_NOUN + r" (?:hien tai|hien co|dang chay)"
    + r"|(?:list|show|what|which|current|existing)(?: \w+){0,2} projects)\b"
)
# "trạng thái từng Project", "each project's step": fields asked per item.
_PER_ITEM = r"\b(?:tung|each|every|all|tat ca|moi(?= (?:projects?|du an)\b))\b"

# Words that end a name phrase.
_STOP_WORDS = frozenset(
    "cho cua o tai la gi va for of at in to with and is are dang nao "
    "project projects please nhe nha giup minh toi khong without co can "
    "khi voi under thuoc tren on database db "
    # A verb after a name: "Project X depends on ...", "Project X bị vướng".
    "depend depends waiting waits blocked bi "
    # "Project X completed?", "Project X đã hoàn thành chưa?" (pairs below:
    # a bare "da" also folds from "Đà" as in "Đà Nẵng").
    "completed finished done".split()
)
_STOP_PAIRS = frozenset(
    {"hien tai", "hien co", "du an", "la gi", "da hoan", "da xong", "hoan thanh",
     # CP12H.NL4D2: "Project X còn thiếu ...", "Project X đã có Purchase Order".
     "con thieu", "con cho", "da co", "da duoc", "da duyet", "da ky"}
)
# CP12H.NL4D2: what an evidence question is about (folded). Never a write:
# the question shape is required and an imperative write verb excludes it.
_EVIDENCE_NOUN = (
    r"\b(?:giay to|tai lieu|ho so|chung tu|phe duyet|duyet|approvals?|approved|"
    r"evidence|documents?|revisions?|phien ban|purchase (?:order|request|requisition)s?|"
    r"payment requests?|de nghi thanh toan|don dat hang|yeu cau mua hang|"
    r"dieu kien|signing gate|chu ky|da ky|signed|signature|requirements?|required)\b"
)
# CP12H.NL4D2-FIX1: "What blocks Step 8?", "Bước 8 bị chặn vì sao?", "Bước X còn
# thiếu gì?": a named step plus a blocker question asks what it lacks.
_STEP_BLOCKER = (
    r"\b(?:bi chan|vi sao|tai sao|why|blocks?|blocked|blocking|con thieu|thieu gi|"
    r"missing)\b"
)
# A step-completion question stays a status read even when the step's title
# names a document or approval ("Bước Record Partner approval đã xong chưa?").
_COMPLETION_QUESTION = r"\b(?:xong|hoan thanh) chua\b|\b(?:completed|finished|done)\b"
_EVIDENCE_ASK = (
    r"\b(?:chua|nao|gi|con thieu|thieu|missing|which|what|list|show|liet ke|"
    r"danh sach|dang cho|blocks?|blocked|blocking|has|have|is|are|did|does|xem)\b"
)
_EVIDENCE_WRITE_START = (
    r"^(?:(?:hay|vui long|please) )?(?:ghi nhan|tai len|upload|dinh kem|attach|record|"
    r"register|them|add|tao|create|approve|phe duyet|duyet|ky|sign|cap nhat|update|"
    r"set|xoa|delete)\b"
)
# Trailing question particles and demonstratives never belong to a name:
# "... Project X chưa?"; "Project này" names no Project (no trusted binding).
_QUESTION_PARTICLES = frozenset({"chua", "khong", "nhi", "vay", "nay", "this"})
# Words skipped at the start of a name phrase.
_LEAD_WORDS = frozenset({"the", "a", "rap", "cinema", "project", "projects"})
# Anchor collocations that are not "owned by" / "for": "phụ thuộc" (depends),
# "thuộc vào" (depends on), "cho biết" (tell). Folded words.
_NOT_NAME_BEFORE = {"thuoc": frozenset({"phu", "le", "tuy"})}
_NOT_NAME_AFTER = {
    "thuoc": frozenset({"vao"}),
    "cho": frozenset({"biet", "xem", "hoi"}),
}
# A step is never a Merchant or Project name ("của bước khác").
_STEP_NOUNS = frozenset({"buoc", "step", "steps"})
# Update verbs that end an English name read backwards from "step".
_STEP_VERBS = frozenset(
    {"mark", "update", "complete", "finish", "close", "set", "start", "skip", "move"}
)


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
    # CP12H.NL4B, STEP_UPDATE only: the step as written ("Legal Review", "1")
    # and the requested domain status, or None when unclear or conflicting.
    step_reference: str | None = None
    target_status: str | None = None

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

    # A noun inside a Project or Merchant name ("Project X Evidence") never
    # makes a request an evidence question.
    covered = words._entity_name_words()
    unnamed = " ".join(w for n, w in enumerate(words.folded_words) if n not in covered)
    evidence_read = (
        (
            re.search(_EVIDENCE_NOUN, unnamed) is not None
            or (words.names_a_step() and re.search(_STEP_BLOCKER, unnamed) is not None)
        )
        and (question or re.search(_EVIDENCE_ASK, text) is not None)
        and re.search(_EVIDENCE_WRITE_START, text) is None
        and re.search(_COMPLETION_QUESTION, text) is None
    )
    kind = _classify(text, has_project, creates_merchant, creates_project, evidence_read)
    if kind == STEP_UPDATE and re.search(_FURTHER_ACTION, text):
        kind = MIXED
    # "giấy tờ và phê duyệt" names evidence; only a second action outside
    # the evidence nouns ("..., rồi xóa Merchant") makes it MIXED.
    if kind == EVIDENCE_STATUS and re.search(_FURTHER_ACTION, re.sub(_EVIDENCE_NOUN, " ", text)):
        kind = MIXED

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
        # The first owner in reading order: "projects for Beta ... status of each".
        merchant_phrase = words.owner_phrase(("cua", "of", "for", "cho", "thuoc", "under"))
    elif kind in (PROJECT_STATUS, EVIDENCE_STATUS):
        project_phrase = words.phrase_after_word(
            ("project", "projects", "du an")
        ) or words.phrase_after_word(("of",))
        # "Project X của Lotte Cinema": the owner, not "của Project X".
        merchant_phrase = words.owner_phrase(("cua", "of", "thuoc", "under"))
        if kind == EVIDENCE_STATUS:
            project_phrase = _without_question_particle(project_phrase)
            merchant_phrase = _without_question_particle(merchant_phrase)

    step_reference = target_status = None
    if kind == EVIDENCE_STATUS:
        step_reference = words.step_reference()
    if kind == STEP_UPDATE:
        negated = negated or re.search(_STEP_NEGATION, text) is not None
        exploratory = exploratory or re.search(_STEP_UNCERTAIN, text) is not None
        target_status, clause_start = _target_status(text)
        # Names end where the state clause begins: "... Test thành đang thực hiện".
        subject = words.before(clause_start) if clause_start is not None else words
        step_reference = subject.step_reference()
        if step_reference is None and not subject.names_a_step():
            # "Mark Legal Review as completed": the name follows the mark verb.
            step_reference = subject.marked_name()
        # "... hoàn thành cho Project X": a Project may follow the state.
        project_phrase = subject.phrase_after_word(
            ("project", "projects", "du an")
        ) or words.phrase_after_word(("project", "projects", "du an"))
        merchant_phrase = subject.owner_phrase(("cua", "of", "thuoc", "under"))

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
        step_reference=step_reference,
        target_status=target_status,
    )


def _target_status(text: str) -> tuple[str | None, int | None]:
    """(requested status, folded offset where its clause starts).

    A connector clause ("là hoàn thành", "as in progress") decides; otherwise
    a verb that names the state ("Hoàn thành bước X"). Several different
    states, or none, give None: the preview asks instead of guessing.
    """

    found = []
    for status, pattern in _TARGET_STATES:
        for match in re.finditer(
            rf"\b{_STATE_CONNECTOR}(?: (?:da|duoc|the|be))? ({pattern})\b", text
        ):
            found.append((match.start(), status))

    step_noun = re.search(_BARE_STATE_VERB, text)
    if step_noun:
        # The bare state after "bước <name>"; never the verb "hoàn thành bước".
        for status, pattern in _BARE_STATES:
            for match in re.finditer(rf"\b{pattern}\b(?! buoc\b)", text):
                if match.start() > step_noun.end():
                    found.append((match.start(), status))

    if found:
        states = {status for _, status in found}
        start = min(offset for offset, _ in found)
        return (states.pop() if len(states) == 1 else None), start

    verb = re.search(
        r"\b(hoan thanh|bat dau|bo qua) buoc\b"
        r"|\b(complete|finish|close|start|skip) (?:the )?(?:\w+ ){0,3}step\b",
        text,
    )
    if verb:
        word = verb.group(1) or verb.group(2)
        for status, pattern in _STATE_VERBS:
            if re.search(pattern, word):
                return status, None
    return None, None


# Role labels that may precede a Merchant name ("cho Merchant Beta Cinemas").
_ROLE_LABELS = (("merchant",), ("merchants",), ("doi", "tac"), ("partner",), ("nha", "cung", "cap"))


def without_role_label(phrase: str | None) -> str | None:
    """``phrase`` minus a leading role label, or None when it has none.

    Only a label followed by more words; the caller tries the phrase as
    written first, so a Merchant actually named "Partner Cinemas" keeps it.
    """

    words = (phrase or "").split()
    folded = [fold(word) for word in words]

    for label in _ROLE_LABELS:
        if tuple(folded[: len(label)]) == label and len(words) > len(label):
            return " ".join(words[len(label):])

    return None


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


def _without_question_particle(phrase: str | None) -> str | None:
    words = (phrase or "").split()
    while words and fold(words[-1]) in _QUESTION_PARTICLES:
        words.pop()
    return " ".join(words) or None


def _classify(
    text: str,
    has_project: bool,
    creates_merchant: bool,
    creates_project: bool,
    evidence_read: bool = False,
) -> str:
    """The primary operation, in precedence order. Writes first, then reads.

    For reads, the operation is decided by its object, not by the fields the
    user asks to see: "liệt kê tất cả Project ... trạng thái từng Project"
    lists Projects (with their status); a step question about one Project
    ("liệt kê các bước của Project X") is a status read. A list verb plus a
    step question without a per-item word ("liệt kê Project X đang ở bước
    nào") stays a single-Project status read, which asks when no Project is
    named rather than guessing.
    """

    step_question = re.search(_STEP_QUESTION, text) is not None

    if not re.search(_DONE_QUESTION, text) and (
        re.search(_STEP_UPDATE_EXPLICIT, text)
        or (re.search(_STEP_UPDATE + "|" + _MARK_AS, text) and not step_question)
    ):
        return STEP_UPDATE
    if creates_merchant and creates_project:
        return MIXED
    if creates_merchant:
        return MERCHANT_CREATE
    if creates_project:
        return PROJECT_CREATE
    if evidence_read:
        return EVIDENCE_STATUS
    if re.search(_LIST_OPERATION, text) and (
        not step_question or re.search(_PER_ITEM, text)
    ):
        return PROJECT_LIST
    if step_question or (has_project and re.search(_STATUS, text)):
        return PROJECT_STATUS
    if re.search(_LIST, text):
        return PROJECT_LIST
    return UNKNOWN


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
    # Purchase Requisition (PR) only: Purchase Order and Payment Request are
    # later, always-present steps and say nothing about procurement.
    noun = (
        r"(?:procurement|purchase requisitions?|purchase requests?|mua sam|"
        r"de nghi mua|\bpr\b)"
    )
    # "bỏ (qua) bước": a bare "bo" also folds from "bộ" (department).
    if re.search(
        rf"\b(?:khong|no|without|not|chua|ko|skip|bo qua|bo buoc)\b(?: \w+){{0,3}} {noun}",
        text,
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
                if self.folded_words[index:index + len(parts)] == parts and (
                    self._introduces_name(index, len(parts))
                ):
                    phrase = self._phrase(index + len(parts))
                    if phrase:
                        return phrase
        return None

    def owner_phrase(self, anchors: tuple[str, ...]) -> str | None:
        """Phrase after an anchor that does not introduce a Project noun."""

        for index, word in enumerate(self.folded_words):
            following = index + 1
            if (
                word in anchors
                and self._introduces_name(index, 1)
                and self.folded_words[following] not in ("project", "projects")
                and self._pair(following) != "du an"
            ):
                phrase = self._phrase(following)
                if phrase:
                    return phrase
        return None

    def before(self, end: int) -> "_Words":
        """The words whose folded text starts before folded offset ``end``."""

        prefix = copy.copy(self)
        count = sum(1 for start in self.starts if start < end)
        for name in ("original", "folded_words", "starts", "breaks"):
            setattr(prefix, name, getattr(self, name)[:count])
        prefix.folded = " ".join(prefix.folded_words)
        return prefix

    def step_reference(self) -> str | None:
        """The step as written: "bước Legal Review", "step 1", "the X step".

        A number after "bước số" / "step number" / "step #" is kept as digits;
        it is matched against the stored sequence number, never a title.
        """

        found = []
        covered = self._entity_name_words()
        reference_end = 0
        for index, word in enumerate(self.folded_words):
            # CP12H.NL4C2B-FIX: "Step" inside a Project or Merchant name
            # ("Project Beta NL4C2B Step Acceptance") or inside the step
            # title already found is part of that name, not another step.
            if word in ("buoc", "step") and index not in covered and index >= reference_end:
                reference, reference_end = self._step_at(index)
                if reference and reference not in found:
                    found.append(reference)
        # "bước 1 và bước 2": several steps in one request ask instead.
        return found[0] if len(found) == 1 else None

    def names_a_step(self) -> bool:
        """Whether a step noun is written outside every Project/Merchant name."""

        covered = self._entity_name_words()
        return any(
            word in _STEP_NOUNS and index not in covered
            for index, word in enumerate(self.folded_words)
        )

    def _entity_name_words(self) -> set[int]:
        """Indices of the words naming a Project or Merchant after its noun."""

        covered: set[int] = set()
        for index, word in enumerate(self.folded_words):
            length = 2 if self._pair(index) == "du an" else 1 if word in (
                "project", "projects", "merchant", "merchants",
            ) else 0
            if length and self._introduces_name(index, length):
                start, end = self._span(index + length)
                covered.update(range(start, end))
        return covered

    def marked_name(self) -> str | None:
        """The name after "đánh dấu" / "mark" when no step noun is written.

        Never a Project or Merchant: "Mark project X as done" names no step.
        """

        for index, word in enumerate(self.folded_words):
            pair = self._pair(index)
            start = index + 2 if pair == "danh dau" else index + 1 if word == "mark" else None
            if start is None or start >= len(self.folded_words):
                continue
            first = self.folded_words[start]
            if first in ("project", "projects", "merchant", "merchants") or self._pair(start) in (
                "du an", "doi tac",
            ):
                return None
            return self._phrase(start)
        return None

    def _step_at(self, index: int) -> tuple[str | None, int]:
        """(reference, index just past it) for the step noun at ``index``."""

        following = index + 1
        while following < len(self.folded_words) and self.folded_words[following] in (
            "so", "number", "no",
        ):
            following += 1
        if following < len(self.folded_words) and self.folded_words[following].isdigit():
            return self.folded_words[following], following + 1
        start, end = self._span(following)
        if end > start:
            return " ".join(self.original[start:end]), end
        # "Mark the Legal review step of ...": the name precedes "step".
        # Never "bước": "Đánh dấu bước hoàn thành" names no step (FIX2B).
        if self.folded_words[index] != "step":
            return None, index + 1
        start = index
        while start > 0 and self.folded_words[start - 1] not in _STEP_VERBS:
            start -= 1
        name = [w for w in self.original[start:index] if fold(w) not in ("the", "a")]
        return " ".join(name) or None, index + 1

    def _introduces_name(self, index: int, length: int) -> bool:
        """Whether the anchor at ``index`` introduces a name, by its context.

        "thuộc Beta Cinemas" names an owner; "phụ thuộc vào bước khác",
        "tùy thuộc vào", "cho biết" and "của bước khác" do not.
        """

        anchor = " ".join(self.folded_words[index:index + length])
        following = index + length
        if following >= len(self.folded_words):
            return False
        before = self.folded_words[index - 1] if index else None
        after = self.folded_words[following]
        return not (
            before in _NOT_NAME_BEFORE.get(anchor, ())
            or after in _NOT_NAME_AFTER.get(anchor, ())
            or after in _STEP_NOUNS
        )

    def _pair(self, index: int) -> str:
        return " ".join(self.folded_words[index:index + 2])

    def _phrase(self, start: int) -> str | None:
        start, end = self._span(start)
        return " ".join(self.original[start:end]) or None

    def _span(self, start: int) -> tuple[int, int]:
        """[start, end) of the name phrase beginning at word ``start``."""

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

        return start, end
