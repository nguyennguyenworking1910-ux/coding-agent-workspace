-- Add concurrency support and least privileges for confirmed CLI writes.
-- This migration does not mutate Merchant business records.

CREATE UNIQUE INDEX integration_identifiers_binding_unique_idx
    ON merchant_ops.integration_identifiers (
        merchant_id,
        project_id,
        identifier_type,
        scope
    )
    NULLS NOT DISTINCT;

CREATE UNIQUE INDEX integration_identifiers_environment_value_unique_idx
    ON merchant_ops.integration_identifiers (
        identifier_type,
        identifier_value
    )
    WHERE scope IN ('UAT', 'PRODUCTION');

CREATE UNIQUE INDEX procurement_records_project_type_unique_idx
    ON merchant_ops.procurement_records (
        project_id,
        procurement_type
    );

GRANT INSERT
    ON TABLE
        merchant_ops.merchants,
        merchant_ops.merchant_contacts,
        merchant_ops.project_step_dependencies,
        merchant_ops.document_revisions,
        merchant_ops.integration_identifiers
    TO merchant_app;

GRANT UPDATE (updated_at, version)
    ON TABLE merchant_ops.merchants
    TO merchant_app;

GRANT UPDATE (superseded_by)
    ON TABLE merchant_ops.document_revisions
    TO merchant_app;

GRANT UPDATE (
    identifier_value,
    is_active,
    updated_at,
    version
)
    ON TABLE merchant_ops.integration_identifiers
    TO merchant_app;
