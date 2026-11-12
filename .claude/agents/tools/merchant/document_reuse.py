"""Signed contract revision reuse across Projects (CP12H.MASTER-FIX).

Owner-approved for the Local Test MVP: a MEDIA_TOP_UP_EXISTING_DOCUMENT
Project may reuse an existing signed contract revision of **another Project
of the same Merchant**, bound explicitly and immutably at Project creation
(``projects.reused_document_revision_id``; migration 011 enforces it in the
database). Nothing is copied: no revision, approval, signature or file is
duplicated, and the source Project is never changed. The source revision
keeps its own attestation (``signing_attestation`` /
``evidence_status``); reuse never upgrades it.

Eligibility (conservative and explicit; one rule for the Project preview,
Project creation, the Purchase Order / Payment Request prerequisites):

- the revision exists and belongs to a Project of the same Merchant;
- its document type is CONTRACT;
- it is signed (``signed`` and ``signed_at``);
- it is not superseded (a superseded signed revision is not reusable);
- no REJECTED decision was recorded on it.

A matching content hash never authorizes reuse: only the bound revision id.
"""

from __future__ import annotations

from typing import Any

REUSABLE_DOCUMENT_TYPE = "CONTRACT"

NOT_FOUND = "REUSED_REVISION_NOT_FOUND"
OTHER_MERCHANT = "REUSED_REVISION_OTHER_MERCHANT"
NOT_A_CONTRACT = "REUSED_REVISION_NOT_A_CONTRACT"
NOT_SIGNED = "REUSED_REVISION_NOT_SIGNED"
SUPERSEDED = "REUSED_REVISION_SUPERSEDED"
REJECTED = "REUSED_REVISION_REJECTED"
SAME_PROJECT = "REUSED_REVISION_SAME_PROJECT"


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def reuse_blocker(merchant_id: Any, row: dict[str, Any] | None,
                  destination_project_id: Any = None) -> tuple[str, str] | None:
    """(code, message) when ``row`` may not be reused by a Project of
    ``merchant_id``; None when it is eligible."""

    if row is None:
        return NOT_FOUND, "The signed revision to reuse was not found."
    if _text(row.get("merchant_id")) != _text(merchant_id):
        return OTHER_MERCHANT, "The revision belongs to another Merchant's Project."
    if destination_project_id is not None and _text(row.get("project_id")) == _text(destination_project_id):
        return SAME_PROJECT, "A Project's own revision is not a reuse."
    if str(row.get("document_type") or "").upper() != REUSABLE_DOCUMENT_TYPE:
        return NOT_A_CONTRACT, "Only a signed CONTRACT revision can be reused."
    if not row.get("signed") or row.get("signed_at") is None:
        return NOT_SIGNED, "The revision is not signed."
    if row.get("superseded_by") is not None:
        return SUPERSEDED, "The revision was superseded and is no longer reusable."
    if any(str(a).upper().endswith(":REJECTED") for a in row.get("approvals") or []):
        return REJECTED, "A REJECTED decision was recorded on the revision."
    return None


def eligible(rows: list[dict[str, Any]], merchant_id: Any) -> list[dict[str, Any]]:
    return [row for row in rows if reuse_blocker(merchant_id, row) is None]


def summary(row: dict[str, Any]) -> dict[str, Any]:
    """What a preview shows about a reusable revision (no content hash)."""

    return {
        "revision_id": _text(row.get("id")),
        "source_project_id": _text(row.get("project_id")),
        "source_project_title": row.get("source_project_title"),
        "document_type": row.get("document_type"),
        "revision_number": row.get("revision_number"),
        "signed": bool(row.get("signed")),
        "signed_at": _text(row.get("signed_at")),
        # The source's own attestation; reuse never upgrades it.
        "signing_attestation": row.get("signing_attestation") or "UNSPECIFIED_LEGACY_SIGNING",
        "evidence_status": row.get("evidence_status"),
        "approvals": list(row.get("approvals") or []),
    }


def basis_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """The exact reused-revision state an operation is judged on."""

    if row is None:
        return None
    return {k: _text(row.get(k)) for k in (
        "id", "project_id", "merchant_id", "document_type", "revision_number", "signed",
        "signed_at", "superseded_by", "signing_attestation", "evidence_status")} | {
        "approvals": sorted(str(a) for a in row.get("approvals") or [])}


# One SQL source of truth for every reader (preview, transaction, locks).
REUSABLE_REVISIONS_SQL = """
    SELECT revision.id::text AS id,
           revision.project_id::text AS project_id,
           source.title AS source_project_title,
           source.merchant_id::text AS merchant_id,
           revision.document_type,
           revision.revision_number,
           revision.signed,
           revision.signed_at,
           revision.superseded_by::text AS superseded_by,
           to_jsonb(revision) ->> 'evidence_status' AS evidence_status,
           to_jsonb(revision) ->> 'signing_attestation' AS signing_attestation,
           COALESCE((SELECT array_agg(a.approver_role || ':' || a.approval_status
                                      ORDER BY a.approver_role)
                     FROM merchant_ops.document_approvals AS a
                     WHERE a.document_revision_id = revision.id), '{}') AS approvals
    FROM merchant_ops.document_revisions AS revision
    JOIN merchant_ops.projects AS source ON source.id = revision.project_id
    WHERE (%(merchant_id)s::uuid IS NULL OR source.merchant_id = %(merchant_id)s::uuid)
      AND (%(revision_id)s::uuid IS NULL OR revision.id = %(revision_id)s::uuid)
    ORDER BY source.title, revision.document_type, revision.revision_number, revision.id
"""


def read_reusable(executor: Any, merchant_id: Any = None, revision_id: Any = None,
                  *, lock: bool = False) -> list[dict[str, Any]]:
    """Revisions of a Merchant's Projects (or one revision) with their decisions.

    ``executor`` is a connection or cursor (``.execute(...).fetchall()``).
    ``lock`` takes FOR SHARE on the revision rows (write transactions).
    """

    sql = REUSABLE_REVISIONS_SQL + (" FOR SHARE OF revision" if lock else "")
    rows = executor.execute(sql, {"merchant_id": _text(merchant_id),
                                  "revision_id": _text(revision_id)}).fetchall()
    return [dict(row) for row in rows]
