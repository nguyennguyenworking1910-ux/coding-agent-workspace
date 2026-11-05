"""Read-only Project creation preview and its trusted re-check.

``project_nl`` proposes plain-text candidates; this module binds them only
through the authoritative repository (Merchant catalog, Merchant projects,
installed workflow templates) and the existing pure resolvers and project
factory. It never writes, reserves, spends or issues authorization.

``assess_project_create`` evaluates one exact operation against current
state and derives its ``basis_hash`` and a deterministic Project ID. The
preview puts both into ``requested_operation``; a user who types that exact
operation as ``--merchant-scope`` confirms them. Trusted execution calls
``verify_project_create`` before spending authority and again inside the
write transaction, and refuses when anything the preview showed changed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Protocol

from .entity_resolution_primitives import _whole_token_sequence_match
from .entity_resolver import MerchantResolutionStatus, resolve_merchant_entity
from .project_factory import (
    ProjectInstantiationError,
    _validate_merchant_precondition,
    build_project_instantiation_plan,
)
from .project_nl import (
    PROJECT_CREATE,
    fold,
    interpret_project_request,
    without_role_label,
)
from .workflow import (
    PROJECT_TYPES,
    WorkflowDefinitionError,
    template_fingerprint,
    template_uuid,
)
from .workflow_templates import (
    STANDARD_WORKFLOW_TEMPLATES,
    get_standard_workflow_template,
)


READY = "READY_FOR_CONFIRMATION"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
BLOCKED = "BLOCKED"
NOT_PROJECT_CREATION = "NOT_PROJECT_CREATION"

PROCUREMENT_CONDITION = "requires_procurement"
# The variant fixes requires_procurement; see project_factory.
FIXED_PROCUREMENT = {
    "MEDIA_TOP_UP_NEW_DOCUMENT": True,
    "MEDIA_TOP_UP_EXISTING_DOCUMENT": False,
}
# The exact operation fields the basis covers. ``merchant_code`` is the
# user's explicit confirmation of the Merchant identity (P2): it is shown with
# the operation, bound into the basis and re-checked against the current
# Merchant before any spend and inside the write transaction.
OPERATION_FIELDS = (
    "merchant_id",
    "merchant_code",
    "project_type",
    "workflow_variant",
    "title",
    "requires_procurement",
    "payment_period_number",
    "reused_document_revision_id",
)
_PROJECT_ID_NAMESPACE = uuid.UUID("5b0a3c4e-6f1d-4c2a-9e57-2f9d6a1c8b30")


class ProjectPreviewReader(Protocol):
    def list_merchants(self) -> list[dict[str, Any]]: ...

    def list_projects(
        self, *, merchant_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]: ...

    def get_workflow_template(self, template_id: str) -> dict[str, Any] | None: ...


class ProjectPreviewMismatch(ValueError):
    """The confirmed operation no longer matches authoritative state."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def build_project_preview(
    request: str,
    reader: ProjectPreviewReader,
    *,
    merchant_hint: str | None = None,
    project_type_hint: str | None = None,
    title_hint: str | None = None,
    database_target: str | None = None,
) -> dict[str, Any]:
    """Return a read-only preview; never a write authorization."""

    interpretation = interpret_project_request(request)
    preview: dict[str, Any] = {
        "success": True,
        "mode": "PROJECT_PREVIEW",
        "preview_only": True,
        "executable": False,
        "authorization": None,
        "database_target": database_target,
        "request": request,
        "interpretation": interpretation.to_dict(),
        "candidate_hints": {
            "merchant": merchant_hint,
            "project_type": project_type_hint,
            "title": title_hint,
        },
        "merchant": None,
        "project": None,
        "fields": {},
        "missing_fields": [],
        "clarifications": [],
        "conflicts": [],
        "initial_steps": [],
        "requested_operation": None,
        "basis_hash": None,
    }
    questions: list[str] = preview["clarifications"]

    if interpretation.kind != PROJECT_CREATE:
        preview["outcome"] = NOT_PROJECT_CREATION
        questions.append(
            f"The request reads as {interpretation.kind}, not a Project "
            "creation; no Project preview was built."
        )
        return preview

    merchants = reader.list_merchants()
    merchant, site, merchant_question = resolve_merchant(
        merchants,
        interpretation.merchant_phrase,
        interpretation.site_phrase,
        merchant_hint,
    )
    if merchant_question:
        questions.append(merchant_question)

    project_type = _project_type(
        interpretation.project_type, project_type_hint, questions
    )
    template = (
        _template(project_type, interpretation.media_document, questions)
        if project_type
        else None
    )

    title = (title_hint or "").strip() or _title(merchants, merchant, site)

    fields: dict[str, Any] = {
        "merchant_id": merchant["merchant_id"] if merchant else None,
        "merchant_code": merchant["code"] if merchant else None,
        "project_type": project_type,
        "workflow_variant": template.variant if template else None,
        "title": title,
    }
    if title is None:
        questions.append(
            "What is the Project name (for a cinema opening, the cinema/site name)?"
        )
    if template is not None:
        has_procurement = any(
            step.condition_key == PROCUREMENT_CONDITION for step in template.steps
        )
        fields["requires_procurement"] = FIXED_PROCUREMENT.get(
            template.variant,
            interpretation.requires_procurement if has_procurement else False,
        )
        if fields["requires_procurement"] is None:
            questions.append(
                "Does this Project require procurement (a Purchase Request)?"
            )
        if template.project_type == "MEDIA_TOP_UP":
            fields["payment_period_number"] = None
            questions.append("Which payment period number is this top-up for?")
        if template.variant == "MEDIA_TOP_UP_EXISTING_DOCUMENT":
            fields["reused_document_revision_id"] = None
            questions.append("Which existing document revision is reused?")

    assessment = assess_project_create(reader, fields, merchants=merchants)
    if merchant is not None and assessment["merchant"] is not None:
        merchant.update(assessment["merchant"])

    preview["merchant"] = merchant
    preview["fields"] = fields
    preview["missing_fields"] = sorted(
        name for name, value in fields.items() if value is None
    )
    preview["conflicts"] = assessment["conflicts"]
    preview["project"] = {
        "requested_title": title,
        "project_type": project_type,
        "workflow_variant": template.variant if template else None,
        "template": assessment["template"],
    }
    preview["initial_steps"] = assessment["initial_steps"]
    preview["basis_hash"] = assessment["basis_hash"]

    if any(conflict["blocking"] for conflict in assessment["conflicts"]):
        preview["outcome"] = BLOCKED
    elif preview["missing_fields"] or questions:
        preview["outcome"] = NEEDS_CLARIFICATION
    else:
        preview["outcome"] = READY
        preview["requested_operation"] = _requested_operation(
            fields,
            assessment["project_id"],
            assessment["basis_hash"],
            merchant,
            database_target,
        )

    return preview


def assess_project_create(
    reader: ProjectPreviewReader,
    fields: dict[str, Any],
    *,
    merchants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check one exact project-create operation against current state.

    Returns the Merchant and template status, conflicts (blocking ones make
    the operation unfit to run), the initial steps, and, when the Merchant
    and template are known, ``basis_hash`` and the derived ``project_id``.
    """

    conflicts: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "merchant": None,
        "template": None,
        "conflicts": conflicts,
        "initial_steps": [],
        "basis_hash": None,
        "project_id": None,
    }

    merchant_id = _uuid_text(fields.get("merchant_id"))
    rows = merchants if merchants is not None else reader.list_merchants()
    row = next((r for r in rows if _uuid_text(r.get("id")) == merchant_id), None)
    if merchant_id is not None and row is None:
        conflicts.append(
            {"kind": "MERCHANT_NOT_FOUND", "blocking": True, "detail": merchant_id}
        )
    confirmed_code = fields.get("merchant_code")
    if row is not None and confirmed_code is not None and confirmed_code != row["code"]:
        conflicts.append(
            {
                "kind": "MERCHANT_CODE_MISMATCH",
                "blocking": True,
                "detail": "the confirmed Merchant code does not name this Merchant",
            }
        )
    merchant = (
        {
            "merchant_id": merchant_id,
            "code": row["code"],
            "name": row["name"],
            "account_status": str(row["account_status"]).upper(),
            "version": row["version"],
        }
        if row is not None
        else None
    )
    result["merchant"] = merchant

    template = None
    if fields.get("workflow_variant"):
        try:
            template = get_standard_workflow_template(fields["workflow_variant"])
        except WorkflowDefinitionError as error:
            conflicts.append(
                {"kind": "UNKNOWN_TEMPLATE", "blocking": True, "detail": str(error)}
            )
    if template is not None and template.project_type != fields.get("project_type"):
        conflicts.append(
            {
                "kind": "TEMPLATE_TYPE_MISMATCH",
                "blocking": True,
                "detail": f"{template.variant} is a {template.project_type} template",
            }
        )

    stored_template = None
    if template is not None:
        stored_template = reader.get_workflow_template(str(template_uuid(template)))
        result["template"] = _template_status(template, stored_template, conflicts)

    if merchant is not None and template is not None:
        try:
            _validate_merchant_precondition(template, merchant["account_status"])
        except ProjectInstantiationError as error:
            conflicts.append(
                {"kind": "MERCHANT_PRECONDITION", "blocking": True, "detail": str(error)}
            )

    projects: list[dict[str, Any]] = []
    if merchant is not None:
        projects = reader.list_projects(merchant_id=merchant_id)
        _duplicates(projects, fields.get("title"), fields.get("project_type"), conflicts)

    result["initial_steps"] = _initial_steps(template, merchant, fields)

    if merchant is not None and template is not None:
        basis = _basis_hash(merchant, template, stored_template, projects, fields)
        result["basis_hash"] = basis
        result["project_id"] = str(uuid.uuid5(_PROJECT_ID_NAMESPACE, basis))

    return result


def verify_project_create(
    reader: ProjectPreviewReader,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Refuse unless the confirmed operation still matches its preview.

    ``payload`` is the exact user-confirmed ``project create`` payload. It
    must carry the preview's ``expected_basis_hash`` and ``project_id``;
    the operation must still be ready (no blocking conflict) and recompute
    to the same basis.
    """

    expected = payload.get("expected_basis_hash")
    if not expected or not payload.get("project_id"):
        raise ProjectPreviewMismatch(
            "PREVIEW_BASIS_REQUIRED",
            "project create requires the preview's --project-id and --expected-basis",
        )

    if not payload.get("merchant_code"):
        raise ProjectPreviewMismatch(
            "MERCHANT_CONFIRMATION_REQUIRED",
            "project create requires the previewed --merchant-code",
        )

    fields = {name: payload.get(name) for name in OPERATION_FIELDS}
    assessment = assess_project_create(reader, fields)
    blocking = [c for c in assessment["conflicts"] if c["blocking"]]

    if blocking:
        raise ProjectPreviewMismatch(
            "PROJECT_NOT_READY", ", ".join(c["kind"] for c in blocking)
        )
    if assessment["basis_hash"] != expected:
        raise ProjectPreviewMismatch(
            "PREVIEW_BASIS_CHANGED",
            "the Merchant, its Projects, the template or the operation changed",
        )
    if _uuid_text(payload["project_id"]) != assessment["project_id"]:
        raise ProjectPreviewMismatch(
            "PROJECT_ID_MISMATCH", "the Project ID is not the previewed one"
        )

    return assessment


def _basis_hash(merchant, template, stored_template, projects, fields) -> str:
    basis = {
        "merchant": [
            merchant["merchant_id"],
            merchant["version"],
            merchant["account_status"],
        ],
        "template": [
            str(template_uuid(template)),
            template_fingerprint(template),
            _installed_metadata(stored_template),
        ],
        "projects": sorted(
            [
                _uuid_text(project["id"]),
                project.get("version"),
                project.get("status"),
                project.get("title"),
            ]
            for project in projects
        ),
        "operation": {
            name: (
                _uuid_text(fields.get(name))
                if name.endswith("_id")
                else fields.get(name)
            )
            for name in OPERATION_FIELDS
        },
    }
    return hashlib.sha256(
        json.dumps(basis, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _installed_metadata(stored: dict[str, Any] | None) -> dict[str, Any] | None:
    if stored is None:
        return None
    return {
        "name": stored.get("name"),
        "version": stored.get("version"),
        "variant": stored.get("variant"),
        "is_active": stored.get("is_active"),
    }


def _uuid_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError):
        return str(value)


def _catalog(merchants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"id": row["id"], "code": row["code"], "name": row["name"], "aliases": ()}
        for row in merchants
    ]


def _leading_merchant(catalog, phrase: str):
    """Longest leading part of ``phrase`` that names a Merchant, if any."""

    words = phrase.split()
    for size in range(len(words), 0, -1):
        attempt = resolve_merchant_entity(" ".join(words[:size]), catalog)
        if attempt.status != MerchantResolutionStatus.NOT_FOUND:
            return attempt, " ".join(words[:size]), " ".join(words[size:]) or None
    return None, None, phrase


def resolve_merchant(
    merchants: list[dict[str, Any]],
    phrase: str | None,
    site: str | None,
    hint: str | None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Bind the Merchant by its canonical identity, or explain why not."""

    catalog = _catalog(merchants)

    resolution = None
    matched_text = None
    if phrase:
        # "Beta | Nguyễn Văn Cừ": the rest of the phrase is the site.
        resolution, matched_text, rest = _leading_merchant(catalog, phrase)
        unlabelled = without_role_label(phrase)
        if resolution is None and unlabelled:
            # "Merchant Beta Cinemas": the label is syntax, not the name.
            resolution, matched_text, rest = _leading_merchant(catalog, unlabelled)
        if resolution is not None:
            site = site or rest

    if hint:
        hinted = resolve_merchant_entity(hint.strip(), catalog)
        if resolution is None and phrase is None:
            resolution, matched_text = hinted, hint.strip()
        elif not (
            hinted.resolved
            and resolution is not None
            and resolution.merchant_id == hinted.merchant_id
        ):
            return None, site, (
                f"The proposed Merchant candidate {hint!r} does not match the "
                "Merchant named in the request or is no longer current. "
                "Which Merchant is this Project for?"
            )

    if resolution is None or resolution.status == MerchantResolutionStatus.NOT_FOUND:
        return None, site, (
            "No existing Merchant matches "
            f"{(phrase or hint)!r}. Which existing Merchant is this Project for? "
            "(A Project request never creates a Merchant.)"
            if phrase or hint
            else "Which existing Merchant is this Project for?"
        )

    if not resolution.resolved:
        names = ", ".join(
            f"{candidate.name} ({candidate.code})" for candidate in resolution.candidates
        )
        return None, site, (
            f"{matched_text!r} matches several Merchants: {names}. Which one?"
        )

    return (
        {
            "merchant_id": resolution.merchant_id,
            "code": resolution.code,
            "name": resolution.name,
            "match_kind": resolution.match_kind.value,
            "matched_text": matched_text,
            # A partial (CANDIDATE) match is shown for explicit confirmation.
            "confirmation_required": resolution.match_kind.value == "CANDIDATE",
        },
        site,
        None,
    )


def _title(merchants, merchant, site) -> str | None:
    """"<Merchant words> <site>", unless the site already names the Merchant."""

    if merchant is None or not site:
        return None
    named, _, _ = _leading_merchant(_catalog(merchants), site)
    if named is not None and named.merchant_id == merchant["merchant_id"]:
        return site
    return f"{merchant['matched_text']} {site}"


def _project_type(
    extracted: str | None, hint: str | None, questions: list[str]
) -> str | None:
    hinted = (hint or "").strip().upper() or None

    if hinted is not None and hinted not in PROJECT_TYPES:
        questions.append(f"Unknown Project type candidate {hint!r}.")
        return extracted
    if extracted and hinted and extracted != hinted:
        questions.append(
            f"The request reads as {extracted} but the candidate says {hinted}. "
            "Which Project type is intended?"
        )
        return None
    if not (extracted or hinted):
        questions.append(
            "Which Project type is this: "
            + ", ".join(sorted(PROJECT_TYPES))
            + "?"
        )
    return extracted or hinted


def _template(project_type: str, media_document: str | None, questions: list[str]):
    templates = [
        template
        for template in STANDARD_WORKFLOW_TEMPLATES
        if template.project_type == project_type and template.is_active
    ]
    if project_type == "MEDIA_TOP_UP" and media_document:
        templates = [
            template
            for template in templates
            if template.variant.endswith(f"_{media_document}_DOCUMENT")
        ]
    variants = sorted({template.variant for template in templates})

    if len(variants) != 1:
        questions.append(
            f"No single workflow template fits {project_type}"
            + (f"; choose one of {', '.join(variants)}." if variants else ".")
        )
        return None

    return max(templates, key=lambda template: template.version)


def _template_status(template, stored, conflicts) -> dict[str, Any]:
    installed = _installed_metadata(stored) == {
        "name": template.name,
        "version": template.version,
        "variant": template.variant,
        "is_active": True,
    }
    if not installed:
        conflicts.append(
            {
                "kind": "TEMPLATE_NOT_INSTALLED",
                "blocking": True,
                "detail": f"{template.name} v{template.version} is not installed "
                "and active in the Merchant database",
            }
        )
    return {
        "name": template.name,
        "variant": template.variant,
        "version": template.version,
        "template_id": str(template_uuid(template)),
        "fingerprint": template_fingerprint(template),
        "installed": installed,
    }


def _duplicates(projects, title, project_type, conflicts) -> None:
    wanted = fold(title) if title else None

    for project in projects:
        existing = fold(project.get("title") or "")
        same_title = bool(
            wanted
            and existing
            and (
                _whole_token_sequence_match(wanted, existing)
                or _whole_token_sequence_match(existing, wanted)
            )
        )
        if not same_title:
            continue
        cancelled = project.get("status") == "CANCELLED"
        conflicts.append(
            {
                "kind": "POSSIBLE_DUPLICATE_PROJECT",
                "blocking": not cancelled,
                "project_id": _uuid_text(project["id"]),
                "title": project.get("title"),
                "project_type": project.get("project_type"),
                "status": project.get("status"),
                "same_project_type": project.get("project_type") == project_type,
            }
        )


def _initial_steps(template, merchant, fields) -> list[dict[str, Any]]:
    if template is None:
        return []

    by_sequence = {step.sequence_number: step for step in template.steps}
    plan = None
    if merchant is not None and fields.get("requires_procurement") is not None:
        try:
            # Pure planning only: the factory validates and lays out steps.
            plan = build_project_instantiation_plan(
                merchant_id=merchant["merchant_id"],
                merchant_status=merchant["account_status"],
                template=template,
                requires_procurement=fields["requires_procurement"],
                payment_period_number=fields.get("payment_period_number"),
                reused_document_revision_id=fields.get("reused_document_revision_id"),
                title=fields.get("title"),
            )
        except ProjectInstantiationError:
            plan = None

    if plan is not None:
        return [
            {
                "sequence": step["sequence_number"],
                "name": step["step_name"],
                "step_type": by_sequence[step["sequence_number"]].step_type,
                "branch_key": step["branch_key"],
                "initial_status": step["status"],
            }
            for step in plan.steps
        ]

    return [
        {
            "sequence": step.sequence_number,
            "name": step.name,
            "step_type": step.step_type,
            "branch_key": step.branch_key,
            "initial_status": None,
            "condition": step.condition_key,
        }
        for step in sorted(template.steps, key=lambda item: item.sequence_number)
    ]


DATABASE_TARGETS = ("runtime", "test")
REQUESTED_OPERATION_STATUS = "NOT_AUTHORIZED"
CONFIRMATION_DESCRIPTION = "Create the previewed Project"
OPERATION_NOTE = (
    "Preview data only. Nothing was reserved or written. Creating the Project "
    "requires the user to type confirmation_command exactly; it is refused if "
    "the Merchant, its Projects, the template or the operation changed."
)


def canonical_create_argv(operation: dict[str, Any]) -> list[str]:
    """The one argv form of a previewed ``project create`` (fixed order).

    Every confirmation field is explicit, procurement included, so a missing
    or reordered token is detectable rather than defaulted.
    """

    argv = [
        "project",
        "create",
        "--merchant-id",
        operation["merchant_id"],
        "--type",
        operation["project_type"],
        "--variant",
        operation["workflow_variant"],
        "--title",
        operation["title"],
        "--project-id",
        operation["project_id"],
        "--expected-basis",
        operation["expected_basis"],
        "--merchant-code",
        operation["merchant_code"],
        "--requires-procurement"
        if operation["requires_procurement"]
        else "--no-requires-procurement",
    ]
    if operation.get("payment_period_number") is not None:
        argv += ["--payment-period-number", str(operation["payment_period_number"])]
    if operation.get("reused_document_revision_id") is not None:
        argv += [
            "--reused-document-revision-id",
            operation["reused_document_revision_id"],
        ]
    return argv


def confirmation_command(argv: list[str], database_target: str) -> str:
    """The exact text the user types to confirm ``argv`` (Unicode kept)."""

    target = "--merchant-target test " if database_target == "test" else ""
    scope = json.dumps(argv, ensure_ascii=False, separators=(",", ":"))
    return f"/solve --confirm {target}--merchant-scope {scope} {CONFIRMATION_DESCRIPTION}"


_OPERATION_TEXT_FIELDS = (
    "merchant_id",
    "merchant_code",
    "merchant_name",
    "project_id",
    "project_type",
    "workflow_variant",
    "title",
    "expected_basis",
)


def validate_requested_operation(operation: Any) -> None:
    """Raise ValueError unless ``operation`` is one complete, canonical preview.

    Rejects truncated, reordered, re-encoded or reconstructed operations:
    the argv and the confirmation command must be exactly what the fields
    produce. It never grants authority.
    """

    if not isinstance(operation, dict):
        raise ValueError("requested_operation must be an object")
    if operation.get("command") != "project create":
        raise ValueError("requested_operation must be a project create")
    if operation.get("status") != REQUESTED_OPERATION_STATUS:
        raise ValueError("requested_operation must stay NOT_AUTHORIZED")
    if operation.get("database_target") not in DATABASE_TARGETS:
        raise ValueError("requested_operation has no valid database_target")
    for name in _OPERATION_TEXT_FIELDS:
        value = operation.get(name)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"requested_operation field {name} is missing")
    if not isinstance(operation.get("requires_procurement"), bool):
        raise ValueError("requested_operation must state requires_procurement")
    if not isinstance(operation.get("merchant_confirmation_required"), bool):
        raise ValueError("requested_operation must state merchant confirmation")
    if _uuid_text(operation["project_id"]) != operation["project_id"] or (
        _uuid_text(operation["merchant_id"]) != operation["merchant_id"]
    ):
        raise ValueError("requested_operation identifiers must be canonical UUIDs")

    argv = operation.get("argv")
    if not isinstance(argv, list) or argv != canonical_create_argv(operation):
        raise ValueError("requested_operation argv is not the canonical operation")
    if operation.get("confirmation_command") != confirmation_command(
        argv, operation["database_target"]
    ):
        raise ValueError("confirmation_command does not match the operation")


def _requested_operation(
    fields: dict[str, Any],
    project_id: str,
    basis_hash: str,
    merchant: dict[str, Any],
    database_target: str | None,
) -> dict[str, Any]:
    target = database_target or "runtime"
    operation = {
        "command": "project create",
        "status": REQUESTED_OPERATION_STATUS,
        "database_target": target,
        "merchant_id": fields["merchant_id"],
        "merchant_code": fields["merchant_code"],
        "merchant_name": merchant["name"],
        "merchant_match_kind": merchant.get("match_kind"),
        "merchant_matched_text": merchant.get("matched_text"),
        "merchant_confirmation_required": bool(
            merchant.get("confirmation_required")
        ),
        "project_id": project_id,
        "project_type": fields["project_type"],
        "workflow_variant": fields["workflow_variant"],
        "title": fields["title"],
        "requires_procurement": bool(fields["requires_procurement"]),
        "payment_period_number": fields.get("payment_period_number"),
        "reused_document_revision_id": fields.get("reused_document_revision_id"),
        "expected_basis": basis_hash,
    }
    operation["argv"] = canonical_create_argv(operation)
    operation["confirmation_command"] = confirmation_command(operation["argv"], target)
    operation["note"] = OPERATION_NOTE
    validate_requested_operation(operation)
    return operation
