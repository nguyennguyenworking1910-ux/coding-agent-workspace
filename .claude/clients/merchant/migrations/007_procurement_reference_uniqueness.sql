-- CP12H.NL4D4A (DEC-P1a): a procurement reference is unique within
-- (merchant_id, procurement_type, reference).
--
-- procurement_records stores only project_id, so the Merchant is carried on
-- the row and pinned to its Project by a composite foreign key (ON UPDATE
-- CASCADE keeps it equal if a Project ever changes Merchant). The partial
-- unique index is the database-level guarantee: of two concurrent
-- transactions recording the same reference, at most one commits.
--
-- No business value is changed or deleted: the new column is derived from
-- each row's own Project. If a duplicate already exists, CREATE UNIQUE INDEX
-- fails and the whole migration rolls back (fail closed); nothing is merged.
--
-- The runner is forward-only. Manual reversal, as the owner, in one
-- transaction:
--   DROP INDEX merchant_ops.procurement_records_merchant_type_reference_unique_idx;
--   ALTER TABLE merchant_ops.procurement_records
--       DROP CONSTRAINT procurement_records_project_merchant_fk;
--   ALTER TABLE merchant_ops.procurement_records DROP COLUMN merchant_id;
--   DROP INDEX merchant_ops.projects_id_merchant_unique_idx;
--   DELETE FROM merchant_ops.schema_migrations WHERE version = 7;

ALTER TABLE merchant_ops.procurement_records
    ADD COLUMN merchant_id UUID;

UPDATE merchant_ops.procurement_records AS procurement
SET merchant_id = project.merchant_id
FROM merchant_ops.projects AS project
WHERE project.id = procurement.project_id;

ALTER TABLE merchant_ops.procurement_records
    ALTER COLUMN merchant_id SET NOT NULL;

CREATE UNIQUE INDEX projects_id_merchant_unique_idx
    ON merchant_ops.projects (id, merchant_id);

ALTER TABLE merchant_ops.procurement_records
    ADD CONSTRAINT procurement_records_project_merchant_fk
        FOREIGN KEY (project_id, merchant_id)
        REFERENCES merchant_ops.projects (id, merchant_id)
        ON UPDATE CASCADE;

CREATE UNIQUE INDEX procurement_records_merchant_type_reference_unique_idx
    ON merchant_ops.procurement_records (
        merchant_id,
        procurement_type,
        external_id
    )
    WHERE external_id IS NOT NULL;
