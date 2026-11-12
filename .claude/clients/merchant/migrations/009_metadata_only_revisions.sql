-- CP12H.NL4D-S1 (DEC-SIMPLIFY-a, OWNER_APPROVED 2026-11-12, Local Test MVP):
-- METADATA_ONLY document revisions.
--
-- A METADATA_ONLY revision is one the local operator confirmed without a
-- file. It is NOT verified file evidence: it has no document_files link
-- (document_revisions_managed_file_check), no original filename
-- (document_revisions_original_file_name_check) and a content_hash fixed to
-- 'metadata-only:<revision id>', which can never look like, or match, a
-- SHA-256 digest. UNVERIFIED_LEGACY keeps meaning "unknown provenance" and
-- stays the column default, so any path that does not choose a class
-- explicitly still produces UNVERIFIED_LEGACY. MANAGED is unchanged.
--
-- No existing row is changed. The classification of a row can never change
-- after insert (trigger document_revisions_evidence_immutable, migration 008),
-- so neither legacy nor METADATA_ONLY rows can be upgraded to MANAGED.
--
-- The runner is forward-only. Manual reversal, as the owner, in one
-- transaction, only while no METADATA_ONLY row exists:
--   ALTER TABLE merchant_ops.document_revisions
--       DROP CONSTRAINT document_revisions_metadata_only_content_check,
--       DROP CONSTRAINT document_revisions_evidence_status_check,
--       ADD CONSTRAINT document_revisions_evidence_status_check
--           CHECK (evidence_status IN ('UNVERIFIED_LEGACY', 'MANAGED'));
--   DELETE FROM merchant_ops.schema_migrations WHERE version = 9;

ALTER TABLE merchant_ops.document_revisions
    DROP CONSTRAINT document_revisions_evidence_status_check,

    ADD CONSTRAINT document_revisions_evidence_status_check
        CHECK (evidence_status IN ('UNVERIFIED_LEGACY', 'METADATA_ONLY', 'MANAGED')),

    ADD CONSTRAINT document_revisions_metadata_only_content_check
        CHECK (evidence_status <> 'METADATA_ONLY' OR content_hash = 'metadata-only:' || id::text);
