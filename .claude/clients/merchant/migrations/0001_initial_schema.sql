-- Merchant Project Manager initial operational schema.
-- Forward-only migration.
-- Checkpoint 2 must already have created:
--   1. merchant_ops schema
--   2. merchant_ops.schema_migrations
--   3. merchant_owner, merchant_app, merchant_alert, merchant_test roles

SET search_path TO merchant_ops, public;

CREATE TABLE merchant_ops.merchants (
    id UUID PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    region_code VARCHAR(10),
    account_status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID,
    version INT NOT NULL DEFAULT 1,

    CONSTRAINT merchants_account_status_check
        CHECK (
            account_status IN (
                'ONBOARDING',
                'ACTIVE',
                'INACTIVE',
                'SUSPENDED'
            )
        ),

    CONSTRAINT merchants_version_check
        CHECK (version > 0)
);

CREATE TABLE merchant_ops.merchant_contacts (
    id UUID PRIMARY KEY,
    merchant_id UUID NOT NULL,
    contact_type VARCHAR(50),
    name TEXT,
    email TEXT,
    phone TEXT,
    privacy_classification VARCHAR(50),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INT NOT NULL DEFAULT 1,

    CONSTRAINT merchant_contacts_merchant_fk
        FOREIGN KEY (merchant_id)
        REFERENCES merchant_ops.merchants(id),

    CONSTRAINT merchant_contacts_type_check
        CHECK (
            contact_type IS NULL
            OR contact_type IN (
                'PRIMARY',
                'BILLING',
                'TECHNICAL'
            )
        ),

    CONSTRAINT merchant_contacts_privacy_check
        CHECK (
            privacy_classification IS NULL
            OR privacy_classification IN (
                'PII',
                'SENSITIVE',
                'INTERNAL'
            )
        ),

    CONSTRAINT merchant_contacts_version_check
        CHECK (version > 0)
);

CREATE TABLE merchant_ops.workflow_templates (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    version INT NOT NULL,
    description TEXT,
    variant VARCHAR(100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT workflow_templates_version_check
        CHECK (version > 0),

    CONSTRAINT workflow_templates_name_version_unique
        UNIQUE (name, version)
);

CREATE TABLE merchant_ops.workflow_template_steps (
    id UUID PRIMARY KEY,
    template_id UUID NOT NULL,
    sequence_number INT NOT NULL,
    branch_key VARCHAR(100),
    step_type VARCHAR(50) NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    is_optional BOOLEAN NOT NULL DEFAULT FALSE,
    condition_key VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT workflow_template_steps_template_fk
        FOREIGN KEY (template_id)
        REFERENCES merchant_ops.workflow_templates(id),

    CONSTRAINT workflow_template_steps_sequence_check
        CHECK (sequence_number > 0),

    CONSTRAINT workflow_template_steps_type_check
        CHECK (
            step_type IN (
                'SEQUENTIAL',
                'PARALLEL_BRANCH',
                'CONDITIONAL',
                'APPROVAL_GATE'
            )
        ),

    CONSTRAINT workflow_template_steps_sequence_unique
        UNIQUE (template_id, sequence_number)
);

CREATE TABLE merchant_ops.workflow_template_dependencies (
    id UUID PRIMARY KEY,
    from_step_id UUID NOT NULL,
    to_step_id UUID NOT NULL,
    dependency_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT workflow_template_dependencies_from_fk
        FOREIGN KEY (from_step_id)
        REFERENCES merchant_ops.workflow_template_steps(id),

    CONSTRAINT workflow_template_dependencies_to_fk
        FOREIGN KEY (to_step_id)
        REFERENCES merchant_ops.workflow_template_steps(id),

    CONSTRAINT workflow_template_dependencies_type_check
        CHECK (
            dependency_type IN (
                'MUST_COMPLETE_BEFORE',
                'BLOCKS',
                'REQUIRES'
            )
        ),

    CONSTRAINT workflow_template_dependencies_no_self_check
        CHECK (from_step_id <> to_step_id),

    CONSTRAINT workflow_template_dependencies_edge_unique
        UNIQUE (from_step_id, to_step_id)
);

CREATE TABLE merchant_ops.projects (
    id UUID PRIMARY KEY,
    merchant_id UUID NOT NULL,
    project_type VARCHAR(50) NOT NULL,
    workflow_variant VARCHAR(100) NOT NULL,
    workflow_template_version_id UUID NOT NULL,
    reused_document_revision_id UUID,
    title TEXT,
    status VARCHAR(20) NOT NULL,
    requires_procurement BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID,
    version INT NOT NULL DEFAULT 1,

    CONSTRAINT projects_merchant_fk
        FOREIGN KEY (merchant_id)
        REFERENCES merchant_ops.merchants(id),

    CONSTRAINT projects_workflow_template_fk
        FOREIGN KEY (workflow_template_version_id)
        REFERENCES merchant_ops.workflow_templates(id),

    CONSTRAINT projects_type_check
        CHECK (
            project_type IN (
                'MEDIA_TOP_UP',
                'OPENING_NEW_CINEMA',
                'INTEGRATION_NEW_MERCHANT'
            )
        ),

    CONSTRAINT projects_status_check
        CHECK (
            status IN (
                'PLANNED',
                'IN_PROGRESS',
                'BLOCKED',
                'ON_HOLD',
                'COMPLETED',
                'CANCELLED'
            )
        ),

    CONSTRAINT projects_version_check
        CHECK (version > 0),

    CONSTRAINT projects_completion_check
        CHECK (
            status <> 'COMPLETED'
            OR completed_at IS NOT NULL
        )
);

CREATE TABLE merchant_ops.project_steps (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL,
    template_step_id UUID NOT NULL,
    branch_key VARCHAR(100),
    step_name TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    sequence_number INT NOT NULL,
    scheduled_start DATE,
    scheduled_completion DATE,
    actual_start TIMESTAMPTZ,
    actual_completion TIMESTAMPTZ,
    assigned_to UUID,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INT NOT NULL DEFAULT 1,

    CONSTRAINT project_steps_project_fk
        FOREIGN KEY (project_id)
        REFERENCES merchant_ops.projects(id),

    CONSTRAINT project_steps_template_step_fk
        FOREIGN KEY (template_step_id)
        REFERENCES merchant_ops.workflow_template_steps(id),

    CONSTRAINT project_steps_status_check
        CHECK (
            status IN (
                'PENDING',
                'READY',
                'IN_PROGRESS',
                'BLOCKED',
                'COMPLETED',
                'SKIPPED',
                'SUPERSEDED'
            )
        ),

    CONSTRAINT project_steps_sequence_check
        CHECK (sequence_number > 0),

    CONSTRAINT project_steps_version_check
        CHECK (version > 0),

    CONSTRAINT project_steps_schedule_check
        CHECK (
            scheduled_start IS NULL
            OR scheduled_completion IS NULL
            OR scheduled_completion >= scheduled_start
        ),

    CONSTRAINT project_steps_actual_completion_check
        CHECK (
            status <> 'COMPLETED'
            OR actual_completion IS NOT NULL
        )
);

CREATE TABLE merchant_ops.project_step_dependencies (
    id UUID PRIMARY KEY,
    from_step_id UUID NOT NULL,
    to_step_id UUID NOT NULL,
    dependency_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT project_step_dependencies_from_fk
        FOREIGN KEY (from_step_id)
        REFERENCES merchant_ops.project_steps(id),

    CONSTRAINT project_step_dependencies_to_fk
        FOREIGN KEY (to_step_id)
        REFERENCES merchant_ops.project_steps(id),

    CONSTRAINT project_step_dependencies_no_self_check
        CHECK (from_step_id <> to_step_id),

    CONSTRAINT project_step_dependencies_edge_unique
        UNIQUE (from_step_id, to_step_id)
);

CREATE TABLE merchant_ops.document_revisions (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL,
    document_type VARCHAR(100) NOT NULL,
    revision_number INT NOT NULL,
    content_hash TEXT NOT NULL,
    signed BOOLEAN NOT NULL DEFAULT FALSE,
    signed_at TIMESTAMPTZ,
    effective_date DATE,
    expiry_date DATE,
    superseded_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID,

    CONSTRAINT document_revisions_project_fk
        FOREIGN KEY (project_id)
        REFERENCES merchant_ops.projects(id),

    CONSTRAINT document_revisions_superseded_by_fk
        FOREIGN KEY (superseded_by)
        REFERENCES merchant_ops.document_revisions(id),

    CONSTRAINT document_revisions_revision_check
        CHECK (revision_number > 0),

    CONSTRAINT document_revisions_signing_check
        CHECK (
            (signed = FALSE AND signed_at IS NULL)
            OR
            (signed = TRUE AND signed_at IS NOT NULL)
        ),

    CONSTRAINT document_revisions_expiry_check
        CHECK (
            effective_date IS NULL
            OR expiry_date IS NULL
            OR expiry_date > effective_date
        ),

    CONSTRAINT document_revisions_revision_unique
        UNIQUE (
            project_id,
            document_type,
            revision_number
        )
);

ALTER TABLE merchant_ops.projects
    ADD CONSTRAINT projects_reused_document_revision_fk
    FOREIGN KEY (reused_document_revision_id)
    REFERENCES merchant_ops.document_revisions(id);

CREATE TABLE merchant_ops.document_approvals (
    id UUID PRIMARY KEY,
    document_revision_id UUID NOT NULL,
    approver_role VARCHAR(50) NOT NULL,
    approval_status VARCHAR(20) NOT NULL,
    approved_at TIMESTAMPTZ,
    approved_by UUID,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT document_approvals_revision_fk
        FOREIGN KEY (document_revision_id)
        REFERENCES merchant_ops.document_revisions(id),

    CONSTRAINT document_approvals_role_check
        CHECK (
            approver_role IN (
                'LEGAL',
                'ACCOUNTING',
                'PARTNER'
            )
        ),

    CONSTRAINT document_approvals_status_check
        CHECK (
            approval_status IN (
                'PENDING',
                'APPROVED',
                'REJECTED'
            )
        ),

    CONSTRAINT document_approvals_timestamp_check
        CHECK (
            approval_status <> 'APPROVED'
            OR approved_at IS NOT NULL
        ),

    CONSTRAINT document_approvals_role_unique
        UNIQUE (
            document_revision_id,
            approver_role
        )
);

CREATE TABLE merchant_ops.procurement_records (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL,
    procurement_type VARCHAR(50) NOT NULL,
    external_id VARCHAR(100),
    status VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INT NOT NULL DEFAULT 1,

    CONSTRAINT procurement_records_project_fk
        FOREIGN KEY (project_id)
        REFERENCES merchant_ops.projects(id),

    CONSTRAINT procurement_records_type_check
        CHECK (
            procurement_type IN (
                'PURCHASE_REQUEST',
                'PURCHASE_ORDER',
                'PAYMENT_REQUEST'
            )
        ),

    CONSTRAINT procurement_records_version_check
        CHECK (version > 0)
);

CREATE TABLE merchant_ops.integration_identifiers (
    id UUID PRIMARY KEY,
    project_id UUID,
    merchant_id UUID NOT NULL,
    identifier_type VARCHAR(50) NOT NULL,
    identifier_value TEXT NOT NULL,
    scope VARCHAR(20) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INT NOT NULL DEFAULT 1,

    CONSTRAINT integration_identifiers_project_fk
        FOREIGN KEY (project_id)
        REFERENCES merchant_ops.projects(id),

    CONSTRAINT integration_identifiers_merchant_fk
        FOREIGN KEY (merchant_id)
        REFERENCES merchant_ops.merchants(id),

    CONSTRAINT integration_identifiers_type_check
        CHECK (
            identifier_type IN (
                'AGENT',
                'MASTER_MID',
                'MID',
                'MERCHANT_CODE',
                'PARTNER_CODE',
                'PRODUCT_ID',
                'ORDER_GROUP_ID',
                'STORE_ID',
                'JIRA_TICKET'
            )
        ),

    CONSTRAINT integration_identifiers_scope_check
        CHECK (
            scope IN (
                'MASTER',
                'UAT',
                'PRODUCTION'
            )
        ),

    CONSTRAINT integration_identifiers_value_check
        CHECK (LENGTH(BTRIM(identifier_value)) > 0),

    CONSTRAINT integration_identifiers_version_check
        CHECK (version > 0),

    CONSTRAINT integration_identifiers_value_unique
        UNIQUE (
            identifier_type,
            identifier_value,
            scope
        )
);

CREATE TABLE merchant_ops.project_events (
    id UUID PRIMARY KEY,
    merchant_id UUID NOT NULL,
    project_id UUID,
    event_type VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID,
    change_summary TEXT,
    old_values JSONB,
    new_values JSONB,
    triggered_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT project_events_merchant_fk
        FOREIGN KEY (merchant_id)
        REFERENCES merchant_ops.merchants(id),

    CONSTRAINT project_events_project_fk
        FOREIGN KEY (project_id)
        REFERENCES merchant_ops.projects(id),

    CONSTRAINT project_events_entity_type_check
        CHECK (
            entity_type IN (
                'MERCHANT',
                'PROJECT',
                'STEP',
                'DOCUMENT',
                'PROCUREMENT'
            )
        ),

    CONSTRAINT project_events_valid_entity_check
        CHECK (
            (
                entity_type = 'MERCHANT'
                AND project_id IS NULL
                AND entity_id IS NOT NULL
            )
            OR
            (
                entity_type IN (
                    'PROJECT',
                    'STEP',
                    'DOCUMENT',
                    'PROCUREMENT'
                )
                AND project_id IS NOT NULL
                AND entity_id IS NOT NULL
            )
        )
);

CREATE TABLE merchant_ops.alert_deliveries (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL,
    project_step_id UUID,
    alert_type VARCHAR(50) NOT NULL,
    business_due_date DATE,
    condition_fingerprint VARCHAR(255),
    deduplication_key VARCHAR(255) NOT NULL,
    delivery_channel VARCHAR(50) NOT NULL,
    delivery_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    delivery_attempt_count INT NOT NULL DEFAULT 0,
    last_error_summary TEXT,
    delivered_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT alert_deliveries_project_fk
        FOREIGN KEY (project_id)
        REFERENCES merchant_ops.projects(id),

    CONSTRAINT alert_deliveries_project_step_fk
        FOREIGN KEY (project_step_id)
        REFERENCES merchant_ops.project_steps(id),

    CONSTRAINT alert_deliveries_type_check
        CHECK (
            alert_type IN (
                'OVERDUE',
                'DUE_TODAY',
                'DUE_SOON',
                'BLOCKED',
                'MISSING_GATE'
            )
        ),

    CONSTRAINT alert_deliveries_channel_check
        CHECK (
            delivery_channel IN (
                'INTERNAL',
                'EMAIL',
                'SLACK'
            )
        ),

    CONSTRAINT alert_deliveries_status_check
        CHECK (
            delivery_status IN (
                'PENDING',
                'SENT',
                'FAILED',
                'ACKNOWLEDGED'
            )
        ),

    CONSTRAINT alert_deliveries_attempt_check
        CHECK (delivery_attempt_count >= 0),

    CONSTRAINT alert_deliveries_condition_check
        CHECK (
            business_due_date IS NOT NULL
            OR condition_fingerprint IS NOT NULL
        ),

    CONSTRAINT alert_deliveries_acknowledgement_check
        CHECK (
            delivery_status <> 'ACKNOWLEDGED'
            OR acknowledged_at IS NOT NULL
        ),

    CONSTRAINT alert_deliveries_deduplication_unique
        UNIQUE (
            deduplication_key,
            delivery_channel
        )
);

CREATE INDEX merchants_account_status_idx
    ON merchant_ops.merchants(account_status);

CREATE INDEX projects_merchant_status_idx
    ON merchant_ops.projects(merchant_id, status);

CREATE INDEX projects_status_updated_idx
    ON merchant_ops.projects(status, updated_at);

CREATE INDEX project_steps_project_sequence_idx
    ON merchant_ops.project_steps(project_id, sequence_number);

CREATE INDEX project_steps_status_due_idx
    ON merchant_ops.project_steps(status, scheduled_completion);

CREATE INDEX project_step_dependencies_destination_idx
    ON merchant_ops.project_step_dependencies(to_step_id);

CREATE INDEX document_revisions_project_type_idx
    ON merchant_ops.document_revisions(
        project_id,
        document_type,
        revision_number
    );

CREATE INDEX document_approvals_revision_status_idx
    ON merchant_ops.document_approvals(
        document_revision_id,
        approval_status
    );

CREATE INDEX procurement_records_project_type_idx
    ON merchant_ops.procurement_records(
        project_id,
        procurement_type
    );

CREATE INDEX integration_identifiers_merchant_idx
    ON merchant_ops.integration_identifiers(
        merchant_id,
        identifier_type
    );

CREATE INDEX project_events_project_created_idx
    ON merchant_ops.project_events(project_id, created_at);

CREATE INDEX alert_deliveries_claim_idx
    ON merchant_ops.alert_deliveries(
        delivery_channel,
        delivery_status,
        updated_at,
        created_at
    );

CREATE INDEX alert_deliveries_project_idx
    ON merchant_ops.alert_deliveries(project_id, created_at);

REVOKE ALL
    ON ALL TABLES IN SCHEMA merchant_ops
    FROM PUBLIC;

GRANT USAGE
    ON SCHEMA merchant_ops
    TO merchant_app;

GRANT USAGE
    ON SCHEMA merchant_ops
    TO merchant_alert;

GRANT SELECT
    ON ALL TABLES IN SCHEMA merchant_ops
    TO merchant_app;

GRANT SELECT, INSERT, UPDATE
    ON TABLE
        merchant_ops.projects,
        merchant_ops.project_steps,
        merchant_ops.document_approvals,
        merchant_ops.procurement_records
    TO merchant_app;

GRANT INSERT
    ON TABLE merchant_ops.project_events
    TO merchant_app;

GRANT SELECT
    ON TABLE
        merchant_ops.projects,
        merchant_ops.project_steps,
        merchant_ops.project_step_dependencies,
        merchant_ops.workflow_templates,
        merchant_ops.workflow_template_steps,
        merchant_ops.document_revisions,
        merchant_ops.document_approvals,
        merchant_ops.procurement_records,
        merchant_ops.alert_deliveries
    TO merchant_alert;

GRANT SELECT, INSERT, UPDATE
    ON TABLE merchant_ops.alert_deliveries
    TO merchant_alert;