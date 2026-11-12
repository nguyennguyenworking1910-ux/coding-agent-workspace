-- CP12H.NL4D5A1b (DEC-D4, D4b, D4c, D4f; Local Test MVP): managed document
-- file metadata and legacy revision classification.
--
-- document_files describes one content-addressed blob of the immutable local
-- store (document_store.py). Blobs are deduplicated globally by SHA-256: a
-- shared digest grants nothing; access and authorization stay with the
-- Project-owned revision that references the file. A row records that trusted
-- code verified the bytes at ingestion (verified_at); it does NOT prove the
-- file still exists: only document_store.verify_object does.
--
-- Every existing revision is classified UNVERIFIED_LEGACY (DEC-D4f) by the
-- column default; no value is changed, no file is fabricated, and no hash is
-- matched to a file. A revision is MANAGED only when inserted with a file whose
-- hash equals its content_hash (composite FK). The classification, file link,
-- hash and filename of a revision can never change after insert, so a legacy
-- revision can never become trusted evidence retroactively.
--
-- Approvals, signing, Projects and Steps are not touched.
--
-- The runner is forward-only. Manual reversal, as the owner, in one transaction:
--   DROP TRIGGER document_revisions_evidence_immutable ON merchant_ops.document_revisions;
--   DROP TRIGGER document_files_immutable ON merchant_ops.document_files;
--   ALTER TABLE merchant_ops.document_revisions
--       DROP CONSTRAINT document_revisions_document_file_fk,
--       DROP COLUMN original_file_name, DROP COLUMN document_file_id,
--       DROP COLUMN evidence_status;
--   DROP TABLE merchant_ops.document_files;
--   DROP FUNCTION merchant_ops.reject_document_evidence_change();
--   DROP FUNCTION merchant_ops.reject_document_file_change();
--   DELETE FROM merchant_ops.schema_migrations WHERE version = 8;

CREATE TABLE merchant_ops.document_files (
    id UUID PRIMARY KEY,
    sha256 CHAR(64) NOT NULL,
    content_hash TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    file_type VARCHAR(10) NOT NULL,
    media_type TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    created_by UUID NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT document_files_sha256_format
        CHECK (sha256 ~ '^[0-9a-f]{64}$'),

    CONSTRAINT document_files_content_hash_derived
        CHECK (content_hash = 'sha256:' || sha256),

    CONSTRAINT document_files_size_range
        CHECK (byte_size BETWEEN 1 AND 26214400),

    CONSTRAINT document_files_type_allowed
        CHECK (
            (file_type = 'PDF' AND media_type = 'application/pdf')
            OR (file_type = 'DOCX' AND media_type =
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            OR (file_type = 'PNG' AND media_type = 'image/png')
            OR (file_type = 'JPEG' AND media_type = 'image/jpeg')
        ),

    CONSTRAINT document_files_storage_key_derived
        CHECK (storage_key = 'sha256/' || substr(sha256, 1, 2) || '/' || sha256),

    CONSTRAINT document_files_sha256_unique UNIQUE (sha256),

    CONSTRAINT document_files_storage_key_unique UNIQUE (storage_key),

    CONSTRAINT document_files_id_content_hash_unique UNIQUE (id, content_hash)
);

ALTER TABLE merchant_ops.document_revisions
    ADD COLUMN evidence_status VARCHAR(30) NOT NULL DEFAULT 'UNVERIFIED_LEGACY',
    ADD COLUMN document_file_id UUID,
    ADD COLUMN original_file_name TEXT;

ALTER TABLE merchant_ops.document_revisions
    ADD CONSTRAINT document_revisions_evidence_status_check
        CHECK (evidence_status IN ('UNVERIFIED_LEGACY', 'MANAGED')),

    ADD CONSTRAINT document_revisions_managed_file_check
        CHECK ((evidence_status = 'MANAGED') = (document_file_id IS NOT NULL)),

    ADD CONSTRAINT document_revisions_original_file_name_check
        CHECK (
            original_file_name IS NULL
            OR (
                evidence_status = 'MANAGED'
                AND char_length(original_file_name) BETWEEN 1 AND 200
                AND original_file_name = btrim(original_file_name)
                AND original_file_name !~ '[[:cntrl:]<>:"/|?*]'
                AND strpos(original_file_name, chr(92)) = 0
                AND original_file_name = normalize(original_file_name, NFC)
            )
        ),

    ADD CONSTRAINT document_revisions_document_file_fk
        FOREIGN KEY (document_file_id, content_hash)
        REFERENCES merchant_ops.document_files (id, content_hash);

CREATE INDEX document_revisions_document_file_idx
    ON merchant_ops.document_revisions (document_file_id)
    WHERE document_file_id IS NOT NULL;

CREATE FUNCTION merchant_ops.reject_document_file_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'document_files rows are immutable'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER document_files_immutable
    BEFORE UPDATE OR DELETE ON merchant_ops.document_files
    FOR EACH ROW EXECUTE FUNCTION merchant_ops.reject_document_file_change();

CREATE FUNCTION merchant_ops.reject_document_evidence_change()
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
    RETURN NEW;
END;
$$;

CREATE TRIGGER document_revisions_evidence_immutable
    BEFORE UPDATE ON merchant_ops.document_revisions
    FOR EACH ROW EXECUTE FUNCTION merchant_ops.reject_document_evidence_change();

-- Read access only. Inserting file metadata becomes possible only with the
-- document execution checkpoint (NL4D5A3), as a separate reviewed grant.
GRANT SELECT ON TABLE merchant_ops.document_files TO merchant_app;
