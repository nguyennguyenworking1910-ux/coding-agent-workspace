-- CP12H.MASTER-FIX (owner-approved, Local Test MVP): signed contract
-- revision reuse across Projects of the same Merchant.
--
-- The relationship already exists (projects.reused_document_revision_id,
-- FK projects_reused_document_revision_fk). This migration makes it
-- explicit and safe in the database itself:
--
-- - at insert, a reused revision must belong to another Project of the
--   same Merchant, be a signed (signed and signed_at) CONTRACT revision and
--   not be superseded;
-- - the binding is immutable: it can never be added, replaced or removed
--   after the Project is created.
--
-- Nothing is copied: no revision, approval, signature or file is
-- duplicated, and the source Project is not changed. No existing row is
-- changed (the trigger fires only on later inserts and updates).
--
-- The runner is forward-only. Manual reversal, as the owner, in one
-- transaction: DROP TRIGGER projects_reused_revision_binding ON
-- merchant_ops.projects; DROP FUNCTION
-- merchant_ops.check_reused_revision_binding(); DELETE FROM
-- merchant_ops.schema_migrations WHERE version = 11.

CREATE FUNCTION merchant_ops.check_reused_revision_binding()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.reused_document_revision_id IS DISTINCT FROM OLD.reused_document_revision_id THEN
            RAISE EXCEPTION 'a Project''s reused document revision is fixed at creation'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.reused_document_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM merchant_ops.document_revisions AS revision
        JOIN merchant_ops.projects AS source ON source.id = revision.project_id
        WHERE revision.id = NEW.reused_document_revision_id
          AND source.merchant_id = NEW.merchant_id
          AND source.id <> NEW.id
          AND upper(revision.document_type) = 'CONTRACT'
          AND revision.signed
          AND revision.signed_at IS NOT NULL
          AND revision.superseded_by IS NULL
    ) THEN
        RAISE EXCEPTION 'a reused document revision must be a signed, current CONTRACT '
                        'revision of another Project of the same Merchant'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER projects_reused_revision_binding
    BEFORE INSERT OR UPDATE OF reused_document_revision_id ON merchant_ops.projects
    FOR EACH ROW EXECUTE FUNCTION merchant_ops.check_reused_revision_binding();
