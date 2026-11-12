-- CP12H.MASTER (DEC-SIMPLIFY, OWNER_APPROVED 2026-11-12, Local Test MVP):
-- operator-recorded approval decisions and operator-attested signing.
--
-- document_approvals.approved_by names the approver. The confirmation-first
-- MVP records decisions through a trusted local operator who is NOT the
-- approver, so the recorder gets its own column and approved_by stays NULL
-- for those rows (nothing is fabricated). decided_at is the decision date
-- the user stated (or the recording time); for APPROVED rows the existing
-- approved_at carries the same instant.
--
-- An APPROVED or REJECTED decision is final: the row can no longer be
-- updated (trigger document_approvals_decision_immutable). DELETE is not
-- granted to the application role.
--
-- document_revisions.signing_attestation = 'OPERATOR_ATTESTED_SIGNED' marks
-- a signature the local operator attested. It claims no cryptographic or
-- file verification. It may only be set on a signed revision, and once a
-- revision is signed its signed/signed_at/signing_attestation can never
-- change (extended document_revisions_evidence_immutable trigger).
--
-- No existing row is changed (all new columns are NULL).
--
-- The runner is forward-only. Manual reversal, as the owner, in one
-- transaction, only while no row uses the new columns: drop trigger
-- document_approvals_decision_immutable and function
-- merchant_ops.reject_decided_approval_change(); restore
-- merchant_ops.reject_document_evidence_change() from migration 008; drop
-- constraint document_revisions_signing_attestation_check and the columns
-- signing_attestation, recorded_by, decided_at; delete schema_migrations
-- version 10.

ALTER TABLE merchant_ops.document_approvals
    ADD COLUMN recorded_by UUID,
    ADD COLUMN decided_at TIMESTAMPTZ,
    ADD CONSTRAINT document_approvals_decided_at_check
        CHECK (decided_at IS NULL OR approval_status IN ('APPROVED', 'REJECTED'));

ALTER TABLE merchant_ops.document_revisions
    ADD COLUMN signing_attestation VARCHAR(40),
    ADD CONSTRAINT document_revisions_signing_attestation_check
        CHECK (signing_attestation IS NULL
               OR (signing_attestation = 'OPERATOR_ATTESTED_SIGNED' AND signed));

CREATE FUNCTION merchant_ops.reject_decided_approval_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.approval_status IN ('APPROVED', 'REJECTED') THEN
        RAISE EXCEPTION 'a recorded approval decision is final'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER document_approvals_decision_immutable
    BEFORE UPDATE ON merchant_ops.document_approvals
    FOR EACH ROW EXECUTE FUNCTION merchant_ops.reject_decided_approval_change();

CREATE OR REPLACE FUNCTION merchant_ops.reject_document_evidence_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.content_hash IS DISTINCT FROM OLD.content_hash
        OR NEW.evidence_status IS DISTINCT FROM OLD.evidence_status
        OR NEW.document_file_id IS DISTINCT FROM OLD.document_file_id
        OR NEW.original_file_name IS DISTINCT FROM OLD.original_file_name
    THEN
        RAISE EXCEPTION 'document revision content and evidence are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.signed AND (
        NEW.signed IS DISTINCT FROM OLD.signed
        OR NEW.signed_at IS DISTINCT FROM OLD.signed_at
        OR NEW.signing_attestation IS DISTINCT FROM OLD.signing_attestation
    ) THEN
        RAISE EXCEPTION 'a signed document revision stays signed as recorded'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
