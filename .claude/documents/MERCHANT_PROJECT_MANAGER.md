# Merchant Project Manager — Phase 4 Architecture Contract

**Status:** Authoritative Design Document
**Phase:** 4 (Checkpoint 1: Architecture Contract)
**Last Updated:** August 28, 2026
**Timezone:** Asia/Ho_Chi_Minh

---

## Executive Summary

This document defines the authoritative architecture for the Merchant Project Manager system — a Claude-driven operational tool for coordinating complex, multi-phase merchant onboarding workflows. The system operates as a conversational agent backed by PostgreSQL state and optional historical context from RAG, managing workflow orchestration, document review, procurement, and merchant integration lifecycle.

**Core Components:**
1. **merchant-manager** — conversational agent for reading project state and executing confirmed updates
2. **PostgreSQL merchant operational store** — authoritative state for merchants, projects, workflows, and audit events
3. **merchant-alert-worker** — future non-agent notification system (Phase 4B)

---

## 1. Goals and Non-Goals

### Goals
✅ Centralize merchant and project state in PostgreSQL with complete audit history
✅ Support three project types with four workflow variants, templates, conditional steps, and dependencies
✅ Enforce document review and approval gates before signing
✅ Enable parallel workflow branches (UAT and Production)
✅ Provide safe, conversational agent access to read and update project state
✅ Maintain separation between read authority (agent queries), write authority (confirmed mutations), and alert delivery (Phase 4B worker)
✅ Support UTF-8 merchant names and Vietnamese project context
✅ Protect privacy of real contact and integration data

### Non-Goals
❌ Replace the existing RAG system or PostgreSQL for historical data
❌ Create a separate PostgreSQL server or container (use existing PostgreSQL)
❌ Create a separate host port (use existing port 5434)
❌ Implement alert delivery in Phase 4A (Phase 4B only)
❌ Create multiple agents for different merchant workflows
❌ Store real PII or sensitive identifiers in documentation or fixtures

### Design Creates (On Shared PostgreSQL)
✅ Separate databases: `coding_agent_merchant` (runtime), `coding_agent_merchant_test` (tests)
✅ Separate schema: `merchant_ops` (not `rag_schema`)
✅ Separate roles: `merchant_owner`, `merchant_app`, `merchant_alert`, `merchant_test`
✅ Separate migrations: `merchant_ops.schema_migrations` (not `rag_schema_migrations`)

---

## 2. Component Boundaries

### merchant-manager Agent
- **Type:** Claude Code subagent (`.claude/agents/merchant-manager.md`)
- **Runtime:** Interactive, read-only and write-confirming
- **Responsibilities:**
  - Answer read-only questions about merchant and project state
  - Show proposed changes before executing confirmed updates
  - Enforce confirmation policy for state mutations
  - Call appropriate CLI commands through Bash
  - Never mutate PostgreSQL directly
  - Never commit or push

### PostgreSQL Operational Store
- **Type:** Shared PostgreSQL server (existing, port 5434)
- **New Database:** `coding_agent_merchant` (runtime), `coding_agent_merchant_test` (tests)
- **New Schema:** `merchant_ops`
- **Shared Server Risk:** Both RAG and Merchant databases on same server; restarting PostgreSQL, deleting volume, or `docker compose down -v` affects both
- **Authoritative For:** Current merchant state, project definitions, workflow state, document revisions, procurement status, integration identifiers, audit events
- **Not Authoritative For:** Historical context (RAG), real-time alerts (Phase 4B worker)

### merchant-alert-worker (Phase 4B)
- **Type:** Non-agent worker process (Python or scheduled task)
- **Runtime:** Windows Task Scheduler or external deterministic scheduler
- **Trigger:** Periodic or event-driven execution outside Claude Code
- **Responsibilities:**
  - Read deadline and workflow state from PostgreSQL
  - Calculate overdue, due-today, and due-soon deadlines
  - Identify blocked projects and missing gates
  - Deliver notifications (Phase 4B implementation)
  - Write alert-delivery and acknowledgement state only
  - Never update project workflow state
- **Independence:** Must operate without an active Claude Code session

### RAG System (Boundary)
- **Role:** Supplemental historical context only
- **Authoritative:** No — PostgreSQL is authoritative
- **Used For:** Indexed workspace documentation, prior discussion history
- **Not Used For:** Current merchant state, project definitions, workflow state
- **Trust Model:** Retrieved content is untrusted reference data

---

## 3. Repository Paths

### Project Structure

```text
.claude/
├── agents/
│   ├── merchant-manager.md          [NEW] Agent definition
│   └── tools/
│       └── merchant/                [NEW] CLI commands and workflow orchestration
│           ├── __init__.py
│           ├── cli.py               CLI entry point (merchant command)
│           ├── read_commands.py     Read-only state queries
│           └── write_commands.py    State mutation commands (propose/apply pattern)
│
├── clients/
│   └── merchant/                    [NEW] PostgreSQL configuration, client, migrations
│       ├── __init__.py
│       ├── client.py                PostgreSQL connection wrapper
│       ├── repository.py            Data access layer
│       └── migrations/
│           ├── versions/
│           │   ├── 001_initial_schema.sql
│           │   └── ... (forward-only, version + checksum)
│           └── migrate.py           Migration runner (uses merchant_owner role)
│
└── documents/
    ├── MERCHANT_PROJECT_MANAGER.md  [NEW] This document
    └── README.md                    [UPDATED] Index the new doc

agents.json                          [UPDATED] Register merchant-manager
.env.example                         [UPDATED] Add MERCHANT_* variables
.gitignore                           [CHECKED] Excludes .env, credentials, fixtures

tests/
└── merchant/                        [NEW] Unit and integration tests
    └── test_merchant.py
```

**Key Rules:**
- Follow dependency direction: agents → tools → clients
- Do not create `docker-compose.merchant.yml` (use existing PostgreSQL server on port 5434)
- `.claude/agents/tools/merchant/` contains CLI and workflow logic
- `.claude/clients/merchant/` contains PostgreSQL client, migrations, and data access
- Tests under `tests/merchant/`

---

## 4. Shared PostgreSQL Topology

### Existing Setup
- **Container Image:** `pgvector/pgvector:0.8.6-pg16-bookworm` (configured in `docker-compose.rag.yml`)
- **Runtime Status:** PostgreSQL 16 and pgvector 0.8.6 verified for RAG system
- **Host:** 127.0.0.1
- **Port:** 5434 (container 5432)
- **Volume:** Single `coding_agent_rag_pgdata`
- **Merchant Requirement:** Does not require pgvector; shares PostgreSQL server for efficiency

### New Merchant Databases
```sql
CREATE DATABASE coding_agent_merchant;
CREATE DATABASE coding_agent_merchant_test;
```

### Isolation Strategy
- **Separate Databases:** RAG and Merchant must never share `coding_agent_merchant`
- **Separate Schemas:** Merchant uses `merchant_ops` schema (not `rag_schema`)
- **Separate Roles:** New roles for Merchant (do not reuse `rag_user`)
- **Separate Migrations:** `merchant_ops.schema_migrations` table for Merchant (separate from RAG migrations)

### Shared-Server Risks (Document These)
1. **Restart Impact:** Restarting PostgreSQL stops both RAG and Merchant systems
2. **Volume Loss:** Deleting `coding_agent_rag_pgdata` volume destroys both databases
3. **Destructive Down:** `docker compose down -v` deletes data for both systems
4. **Backup Strategy:** RAG and Merchant require separate `pg_dump` backups
5. **Migration Path:** Merchant may move to its own PostgreSQL server later (not now)
6. **Recovery:** Losing the volume means losing both RAG and Merchant operational data

---

## 5. Database and Role Isolation

### Roles

#### merchant_owner
- **Purpose:** Owns Merchant database objects; runs forward-only migrations
- **Privileges:**
  - `GRANT CONNECT ON DATABASE coding_agent_merchant TO merchant_owner`
  - `GRANT USAGE ON SCHEMA merchant_ops TO merchant_owner`
  - `GRANT CREATE ON SCHEMA merchant_ops TO merchant_owner`
  - `GRANT ALL ON ALL TABLES IN SCHEMA merchant_ops TO merchant_owner`
  - Create, alter, drop objects within `merchant_ops`
- **Usage:** Migrations only (never used by merchant-manager at runtime)
- **Credential:** Configured via `.env` (separate variable); never printed or logged
- **Not in .env:** Keep actual migration owner password in secured bootstrap configuration, not in `.env`

#### merchant_app
- **Purpose:** Runtime application role; used by merchant-manager agent CLI
- **Read Privileges:**
  - `GRANT CONNECT ON DATABASE coding_agent_merchant TO merchant_app`
  - `GRANT USAGE ON SCHEMA merchant_ops TO merchant_app`
  - `GRANT SELECT ON ALL TABLES IN SCHEMA merchant_ops TO merchant_app`
- **Write Privileges (for mutable tables):**
  - `GRANT SELECT, INSERT, UPDATE ON merchant_ops.projects, merchant_ops.project_steps, merchant_ops.document_approvals, merchant_ops.procurement_records TO merchant_app`
  - `GRANT INSERT ON merchant_ops.project_events TO merchant_app` (audit only — never UPDATE or DELETE)
  - `GRANT USAGE ON ALL SEQUENCES IN SCHEMA merchant_ops TO merchant_app` (for nextval during INSERT)
- **Restrictions:**
  - Cannot connect to `coding_agent_rag` or any other database
  - Cannot `CREATE`, `ALTER`, `DROP` objects or modify schema
  - Cannot UPDATE or DELETE from `project_events` (immutable audit trail)
  - Cannot access sequences' UPDATE privileges
- **Usage:** All runtime read and confirmed-write queries from CLI and agent

#### merchant_alert
- **Purpose:** Future Phase 4B alert worker role (non-agent process)
- **Read Privileges (workflow state only):**
  - `GRANT CONNECT ON DATABASE coding_agent_merchant TO merchant_alert`
  - `GRANT USAGE ON SCHEMA merchant_ops TO merchant_alert`
  - `GRANT SELECT ON merchant_ops.projects, merchant_ops.project_steps, merchant_ops.workflow_templates, merchant_ops.document_revisions TO merchant_alert`
- **Write Privileges (alert delivery only):**
  - `GRANT INSERT, UPDATE ON merchant_ops.alert_deliveries TO merchant_alert`
  - `GRANT USAGE ON merchant_ops.alert_deliveries_id_seq TO merchant_alert`
- **Explicit Restrictions:**
  - Cannot SELECT from `merchant_contacts` or `integration_identifiers` (no PII/secret access)
  - Cannot UPDATE or DELETE from `project_events` or any workflow tables
  - Cannot UPDATE project workflow state
  - Cannot access `rag_schema` or any other database

#### merchant_test
- **Purpose:** Unit and integration test role
- **Privileges:**
  - `GRANT CONNECT ON DATABASE coding_agent_merchant_test TO merchant_test`
  - `GRANT ALL ON SCHEMA merchant_ops IN DATABASE coding_agent_merchant_test TO merchant_test`
- **Restrictions:**
  - Cannot connect to `coding_agent_merchant` or `coding_agent_rag`
  - Tests fail closed if the database name does not end with `_test`

### Revoke PUBLIC

```sql
REVOKE CONNECT ON DATABASE coding_agent_merchant FROM PUBLIC;
REVOKE USAGE ON SCHEMA merchant_ops FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA merchant_ops FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA merchant_ops FROM PUBLIC;
```

---

## 6. Environment Configuration

### Unified .env File
Continue using the single root `.env` file. Do not create `docker-compose.merchant.yml` or separate `.env` files.

### New Environment Variables

```bash
# Merchant Database Connection
MERCHANT_DB_HOST=127.0.0.1
MERCHANT_DB_PORT=5434
MERCHANT_DB_NAME=coding_agent_merchant
MERCHANT_DB_USER=merchant_app
MERCHANT_DB_PASSWORD=<random-local-password>
MERCHANT_DB_SSLMODE=prefer

# Test Database
MERCHANT_TEST_DB_NAME=coding_agent_merchant_test

# Timezone (business logic)
MERCHANT_TIMEZONE=Asia/Ho_Chi_Minh
```

### Notes
- **MERCHANT_DB_PASSWORD:** Set during initialization; never committed to Git
- **MERCHANT_TEST_DB_NAME:** Used by tests only; must connect as `merchant_test` role
- **MERCHANT_DB_SSLMODE:** `prefer` allows both SSL and non-SSL connections (local dev)
- **MERCHANT_TIMEZONE:** All deadline calculations use this timezone
- **Connection String:** Constructed from individual variables (not a single `DATABASE_URL`)
- **Secrets:** Do not include in documentation, logs, or examples

---

## 7. Privacy and UTF-8 Rules

### Privacy Classification
Real contact names, emails, phone numbers, document paths, project records, agent IDs, MIDs, partnerCodes, Product IDs, orderGroupIDs, Store IDs, and JIRA tickets must not be:
- ❌ Committed to Git
- ❌ Added to fixtures or examples
- ❌ Added to documentation
- ❌ Printed in ordinary logs
- ❌ Ingested into RAG

### Default CLI Output
- **Merchant Identification:** Merchant codes and business names are shown (e.g., "CGV Cinema", "Lotte Cinema", "BHD") to identify merchants in dashboard output
- **Contact Redaction:** Contact names, emails, phone numbers remain redacted
- **Integration Redaction:** Integration identifier values (MID, partnerCode, PRODUCT_ID, etc.) remain redacted; scope labels shown
- **Private Access:** If private contact access is required later, design as separate explicitly authorized operation with distinct policy classification

### UTF-8 Support
- **Requirement:** Support UTF-8 Merchant names, Vietnamese project names, Vietnamese notes
- **Initial Catalog:** 22 Merchant records with exact UTF-8 values (imported during private runtime initialization, not in documentation)
- **Encoding:** All text columns use `TEXT` with server encoding `UTF8`
- **No Real Data:** This architecture document contains fictitious values only

---

## 8. Proposed Schema

### Key Design Principles
- **UUID Identifiers:** All primary keys are UUID, not sequential integers
- **Timestamps:** Event timestamps use `TIMESTAMPTZ` (timezone-aware)
- **Date-Only:** Use `DATE` only for date-only business deadlines (not timestamps)
- **Status Constraints:** Use `CHECK` constraints for controlled status values
- **Optimistic Locking:** Integer `version` fields for concurrent-update safety
- **JSONB:** Only for supplementary metadata, never for authoritative state
- **Immutable History:** Append-only audit and revision tables
- **Forward-Only Migrations:** No rollback; every schema change is versioned and checksummed

### Tables

#### merchant_ops.schema_migrations
**Purpose:** Versioned migration tracking (separate from RAG); append-only record of applied migrations
```sql
CREATE TABLE merchant_ops.schema_migrations (
  version INT PRIMARY KEY,
  checksum TEXT NOT NULL,
  description TEXT,
  executed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  execution_time_ms INT
);
```

**Note:** A migration row is inserted only after successful execution within the transaction. No applied flag is needed; the presence of a row indicates success. If a migration fails, the entire transaction rolls back and no row is created.

#### merchant_ops.merchants
**Purpose:** Merchant master records with lifecycle state
```sql
CREATE TABLE merchant_ops.merchants (
  id UUID PRIMARY KEY,
  code VARCHAR(50) NOT NULL UNIQUE,  -- E.g., "MERCHANT_001" (shown in output; identifies BHD, CGV, Lotte, etc.)
  name TEXT NOT NULL,                -- Merchant business name (UTF-8 allowed)
  region_code VARCHAR(10),
  account_status VARCHAR(20) NOT NULL CHECK (account_status IN (
    'ONBOARDING', 'ACTIVE', 'INACTIVE', 'SUSPENDED'
  )),
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  created_by UUID,
  version INT NOT NULL CHECK (version > 0) DEFAULT 1
);
```

**Note:** INTEGRATION_NEW_MERCHANT_STANDARD operates on ONBOARDING merchants. Status transitions to ACTIVE only after integration completion gates pass. OPENING_NEW_CINEMA_STANDARD and MEDIA_TOP_UP workflows require ACTIVE merchants.

#### merchant_ops.merchant_contacts
**Purpose:** Contact records (redacted in output)
```sql
CREATE TABLE merchant_ops.merchant_contacts (
  id UUID PRIMARY KEY,
  merchant_id UUID NOT NULL REFERENCES merchant_ops.merchants(id),
  contact_type VARCHAR(50) CHECK (contact_type IN ('PRIMARY', 'BILLING', 'TECHNICAL')),
  name TEXT,                          -- Real name (redacted in output)
  email TEXT,                          -- Real email (redacted in output)
  phone TEXT,                          -- Real phone (redacted in output)
  privacy_classification VARCHAR(50),  -- 'PII', 'SENSITIVE', 'INTERNAL'
  is_primary BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  version INT DEFAULT 1
);
```

#### merchant_ops.projects
**Purpose:** Project records with immutable workflow-template binding and state
```sql
CREATE TABLE merchant_ops.projects (
  id UUID PRIMARY KEY,
  merchant_id UUID NOT NULL REFERENCES merchant_ops.merchants(id),
  project_type VARCHAR(50) NOT NULL CHECK (project_type IN (
    'MEDIA_TOP_UP', 'OPENING_NEW_CINEMA', 'INTEGRATION_NEW_MERCHANT'
  )),
  workflow_variant VARCHAR(100) NOT NULL,  -- E.g., 'MEDIA_TOP_UP_NEW_DOCUMENT'
  workflow_template_version_id UUID NOT NULL REFERENCES merchant_ops.workflow_templates(id),
  reused_document_revision_id UUID REFERENCES merchant_ops.document_revisions(id),
  title TEXT,
  status VARCHAR(20) NOT NULL CHECK (status IN (
    'PLANNED', 'IN_PROGRESS', 'BLOCKED', 'ON_HOLD', 'COMPLETED', 'CANCELLED'
  )),
  requires_procurement BOOLEAN DEFAULT false,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  created_by UUID,
  version INT NOT NULL CHECK (version > 0) DEFAULT 1
);
```

**Note:** `workflow_template_version_id` binds project to exact immutable template version. Existing projects retain their workflow when a template changes. `reused_document_revision_id` references a signed document from a prior project for Media Top Up reuse.

#### merchant_ops.workflow_templates
**Purpose:** Immutable workflow template definitions
```sql
CREATE TABLE merchant_ops.workflow_templates (
  id UUID PRIMARY KEY,
  name VARCHAR(100) NOT NULL,           -- E.g., 'MEDIA_TOP_UP_NEW_DOCUMENT'
  version INT NOT NULL,                 -- Incremented when template changes
  description TEXT,
  variant VARCHAR(100),
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(name, version)
);
```

#### merchant_ops.workflow_template_steps
**Purpose:** Steps within a workflow template with branch and condition metadata
```sql
CREATE TABLE merchant_ops.workflow_template_steps (
  id UUID PRIMARY KEY,
  template_id UUID NOT NULL REFERENCES merchant_ops.workflow_templates(id),
  sequence_number INT NOT NULL CHECK (sequence_number > 0),
  branch_key VARCHAR(100),  -- E.g., 'document_branch', 'uat_branch', 'production_branch'
  step_type VARCHAR(50) NOT NULL CHECK (step_type IN (
    'SEQUENTIAL', 'PARALLEL_BRANCH', 'CONDITIONAL', 'APPROVAL_GATE'
  )),
  name TEXT NOT NULL,
  description TEXT,
  is_optional BOOLEAN DEFAULT false,
  condition_key VARCHAR(100),  -- E.g., 'requires_procurement', 'is_new_merchant' (allowlisted only, never executable code)
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(template_id, sequence_number)
);
```

**Note:** `branch_key` groups parallel steps (e.g., all steps in 'uat_branch'). `condition_key` references allowlisted conditions only; never stored SQL or code. Conditions are evaluated in application logic with explicit business rules.

#### merchant_ops.workflow_template_dependencies
**Purpose:** Dependency edges between template steps
```sql
CREATE TABLE merchant_ops.workflow_template_dependencies (
  id UUID PRIMARY KEY,
  from_step_id UUID NOT NULL REFERENCES merchant_ops.workflow_template_steps(id),
  to_step_id UUID NOT NULL REFERENCES merchant_ops.workflow_template_steps(id),
  dependency_type VARCHAR(50) CHECK (dependency_type IN (
    'MUST_COMPLETE_BEFORE', 'BLOCKS', 'REQUIRES'
  )),
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(from_step_id, to_step_id)
);
```

#### merchant_ops.project_steps
**Purpose:** Instantiated workflow steps for a specific project, bound to template and branch
```sql
CREATE TABLE merchant_ops.project_steps (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES merchant_ops.projects(id),
  template_step_id UUID NOT NULL REFERENCES merchant_ops.workflow_template_steps(id),
  branch_key VARCHAR(100),  -- Copied from template; groups parallel steps
  step_name TEXT NOT NULL,
  status VARCHAR(20) NOT NULL CHECK (status IN (
    'PENDING', 'READY', 'IN_PROGRESS', 'BLOCKED', 'COMPLETED', 'SKIPPED', 'SUPERSEDED'
  )),
  sequence_number INT NOT NULL CHECK (sequence_number > 0),
  scheduled_start DATE,
  scheduled_completion DATE,
  actual_start TIMESTAMPTZ,
  actual_completion TIMESTAMPTZ,
  assigned_to UUID,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  version INT NOT NULL CHECK (version > 0) DEFAULT 1
);
```

**Note:** Status transitions and dependencies are validated at mutation time. `branch_key` is immutable (copied from template); allows grouping parallel steps in a single query.

#### merchant_ops.project_step_dependencies
**Purpose:** Dependency edges between project steps with acyclic validation
```sql
CREATE TABLE merchant_ops.project_step_dependencies (
  id UUID PRIMARY KEY,
  from_step_id UUID NOT NULL REFERENCES merchant_ops.project_steps(id),
  to_step_id UUID NOT NULL REFERENCES merchant_ops.project_steps(id),
  dependency_type VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(from_step_id, to_step_id),
  CONSTRAINT no_self_dependency CHECK (from_step_id <> to_step_id)
);
```

**Validation Rules:**
- Dependency satisfaction is derived from predecessor-step status; never stored as independently mutable
- A `to_step` is only READY when all `from_steps` are COMPLETED
- Both steps must belong to the same project (validated at mutation time)
- Acyclic validation: prevent circular dependencies (detect in application logic)
- Self-dependencies explicitly rejected by constraint

#### merchant_ops.document_revisions
**Purpose:** Versioned document records with immutable content and one-way signing transition
```sql
CREATE TABLE merchant_ops.document_revisions (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES merchant_ops.projects(id),
  document_type VARCHAR(100) NOT NULL,  -- E.g., 'MERCHANT_AGREEMENT'
  revision_number INT NOT NULL CHECK (revision_number > 0),
  content_hash TEXT NOT NULL,           -- Checksum of immutable document content
  signed BOOLEAN NOT NULL DEFAULT false,  -- Immutable once set to true
  signed_at TIMESTAMPTZ,                -- Timestamp of signing (one-way transition)
  effective_date DATE,                  -- Document validity start date
  expiry_date DATE,                     -- Document validity end date (nullable if no expiry)
  superseded_by UUID REFERENCES merchant_ops.document_revisions(id),
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  created_by UUID,
  UNIQUE(project_id, document_type, revision_number)
);
```

**Notes:**
- Document content is immutable (content_hash is authoritative)
- Signing is a one-way transition: once signed=true, remains true
- For MEDIA_TOP_UP_EXISTING_DOCUMENT validation, the gate checks:
  - A signed document exists (signed = true, signed_at IS NOT NULL)
  - Document is effective (effective_date ≤ business_date)
  - Document is not expired (expiry_date IS NULL OR expiry_date > business_date)
  - Payment period number ≥ 2 (stored in project, not in document)
- Payment period is tracked in the payment project/cycle, not the annual document

#### merchant_ops.document_approvals
**Purpose:** Approval state for specific document revisions
```sql
CREATE TABLE merchant_ops.document_approvals (
  id UUID PRIMARY KEY,
  document_revision_id UUID NOT NULL REFERENCES merchant_ops.document_revisions(id),
  approver_role VARCHAR(50) CHECK (approver_role IN ('LEGAL', 'ACCOUNTING', 'PARTNER')),
  approval_status VARCHAR(20) CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
  approved_at TIMESTAMPTZ,
  approved_by UUID,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(document_revision_id, approver_role)
);
```

#### merchant_ops.procurement_records
**Purpose:** Purchase Request and Purchase Order tracking
```sql
CREATE TABLE merchant_ops.procurement_records (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES merchant_ops.projects(id),
  procurement_type VARCHAR(50) CHECK (procurement_type IN (
    'PURCHASE_REQUEST', 'PURCHASE_ORDER', 'PAYMENT_REQUEST'
  )),
  external_id VARCHAR(100),             -- PR/PO number (e.g., "JRA-12345")
  status VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  version INT DEFAULT 1
);
```

#### merchant_ops.integration_identifiers
**Purpose:** Integration identifiers (AGENT, MASTER_MID, MID, PRODUCT_ID, etc.; sensitive values redacted)
```sql
CREATE TABLE merchant_ops.integration_identifiers (
  id UUID PRIMARY KEY,
  project_id UUID REFERENCES merchant_ops.projects(id),
  merchant_id UUID NOT NULL REFERENCES merchant_ops.merchants(id),
  identifier_type VARCHAR(50) NOT NULL CHECK (identifier_type IN (
    'AGENT', 'MASTER_MID', 'MID', 'MERCHANT_CODE', 'PARTNER_CODE', 'PRODUCT_ID', 'ORDER_GROUP_ID', 'STORE_ID', 'JIRA_TICKET'
  )),
  identifier_value TEXT NOT NULL,       -- Redacted in default output
  scope VARCHAR(20) NOT NULL CHECK (scope IN ('MASTER', 'UAT', 'PRODUCTION')),
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  version INT NOT NULL CHECK (version > 0) DEFAULT 1,
  UNIQUE(identifier_type, identifier_value, scope)
);
```

**Scope Rules:**
- `MASTER`: Created in pre-document gates; shared across project lifecycle (AGENT, MASTER_MID)
- `UAT`: Environment-specific (MID, PRODUCT_ID, ORDER_GROUP_ID, STORE_ID)
- `PRODUCTION`: Environment-specific (MID, PRODUCT_ID, ORDER_GROUP_ID, STORE_ID)
- **Collision Prevention:** Same identifier_value cannot exist in both UAT and PRODUCTION scope (enforced by UNIQUE constraint and application validation)
- **Scope Validation:** project_id must belong to merchant_id; scope must align with identifier type requirements

#### merchant_ops.project_events
**Purpose:** Append-only audit log of all state changes (projects, merchants, workflow)
```sql
CREATE TABLE merchant_ops.project_events (
  id UUID PRIMARY KEY,
  merchant_id UUID NOT NULL REFERENCES merchant_ops.merchants(id),
  project_id UUID REFERENCES merchant_ops.projects(id),
  event_type VARCHAR(100) NOT NULL,    -- E.g., 'MERCHANT_CREATED', 'PROJECT_CREATED', 'STEP_COMPLETED', 'DOCUMENT_APPROVED'
  entity_type VARCHAR(50) NOT NULL,    -- 'MERCHANT', 'PROJECT', 'STEP', 'DOCUMENT', 'PROCUREMENT'
  entity_id UUID,
  change_summary TEXT,                 -- Never includes PII, credentials, or integration secret values
  old_values JSONB,                    -- Redacted values only
  new_values JSONB,                    -- Redacted values only
  triggered_by UUID,                   -- User ID or system agent ID
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT valid_entity CHECK (
    (entity_type = 'MERCHANT' AND project_id IS NULL AND entity_id IS NOT NULL) OR
    (entity_type IN ('PROJECT', 'STEP', 'DOCUMENT', 'PROCUREMENT') AND project_id IS NOT NULL AND entity_id IS NOT NULL)
  )
);
```

**Audit Rules:**
- Bulk operations (e.g., contact import) record counts and safe summaries, never PII
- Each successful apply command creates exactly one event
- State mutation and its audit event commit atomically; both succeed or both fail
- Append-only: never UPDATE or DELETE from project_events
- Sensitive values (contact names, emails, integration identifiers) never stored in old_values/new_values/change_summary

#### merchant_ops.alert_deliveries
**Purpose:** Alert delivery state with stable deduplication for Phase 4B worker
```sql
CREATE TABLE merchant_ops.alert_deliveries (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES merchant_ops.projects(id),
  project_step_id UUID REFERENCES merchant_ops.project_steps(id),
  alert_type VARCHAR(50) NOT NULL CHECK (alert_type IN (
    'OVERDUE', 'DUE_TODAY', 'DUE_SOON', 'BLOCKED', 'MISSING_GATE'
  )),
  business_due_date DATE,               -- Business date for the deadline (null if alert is condition-based)
  condition_fingerprint VARCHAR(255),   -- Deterministic fingerprint for conditional alerts (e.g., missing approval gate ID)
  deduplication_key VARCHAR(255) NOT NULL,  -- Deterministic key = hash(project_id, alert_type, business_due_date OR condition_fingerprint, delivery_channel)
  delivery_channel VARCHAR(50) NOT NULL,  -- 'EMAIL', 'SLACK', 'INTERNAL'
  delivery_status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (delivery_status IN ('PENDING', 'SENT', 'FAILED', 'ACKNOWLEDGED')),
  delivery_attempt_count INT NOT NULL DEFAULT 0 CHECK (delivery_attempt_count >= 0),
  last_error_summary TEXT,
  delivered_at TIMESTAMPTZ,
  acknowledged_at TIMESTAMPTZ,
  acknowledged_by UUID,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(deduplication_key, delivery_channel)
);
```

**Deduplication Rules:**
- Deduplication key is stable across repeated worker runs (uses business_due_date, not current_timestamp)
- Does not include freshly calculated timestamps
- Components: project_id, alert_type, (business_due_date OR condition_fingerprint), delivery_channel
- Unique constraint prevents duplicate deliveries
- FOR UPDATE SKIP LOCKED prevents claiming the same alert twice
- Idempotent retry behavior: safely re-deliver if worker crashes

---

## 9. Workflow Template Model

### Design Principles
- **Immutable Templates:** Workflow templates are versioned; existing projects retain their instantiated workflow when a template changes
- **Sequence + Dependencies:** A sequence number alone is insufficient; explicit dependency edges prevent invalid cycles
- **Conditional Steps:** Steps may be optional or conditional based on project properties
- **Parallel Branches:** Multiple active steps may run concurrently (e.g., UAT and Production)
- **Approval Gates:** Steps enforce approval requirements before proceeding
- **Document Revision Loops:** Rejected document revisions create new revisions; old approvals are not carried forward
- **Supersede and Reopen:** Steps may be superseded or reopened without breaking the audit trail

### Three Project Types, Four Workflow Variants

#### 1. MEDIA_TOP_UP_NEW_DOCUMENT
**When to Use:** New media top-up with new or renewed document
**Requires:** Legal review, Accounting review, Partner approval, Purchase Request
**requires_procurement:** Always `true`

**Parallel Branches:**

*Document Branch:*
1. Draft or renew document
2. Legal review (parallel with Accounting)
3. Accounting review (parallel with Legal)
4. Send reviewed revision to Partner
5. Receive Partner feedback
6. [If Partner changes reviewed version: create new revision, supersede prior, repeat Legal+Accounting]
7. Record Partner approval
8. Signing gate validation
9. Sign document

*Procurement Branch:*
1. Create Purchase Request
2. Record PR number

**Signing Gate Requirements:**
- Latest document revision approved by Legal
- Latest document revision approved by Accounting
- Latest document revision approved by Partner
- Valid PR number recorded

**After Signing:**
1. Create Purchase Order
2. Create Payment Request
3. Close payment period

#### 2. MEDIA_TOP_UP_EXISTING_DOCUMENT
**When to Use:** Only when signed annual document remains valid
**Preconditions:**
- Signed document exists
- Document remains valid
- Payment period is 2 or later
- No amendment or renewal required

**Workflow:**
1. Validate existing document (gate)
2. Create Purchase Order
3. Create Payment Request
4. Close payment period

**Else:** Propose MEDIA_TOP_UP_NEW_DOCUMENT

#### 3. OPENING_NEW_CINEMA_STANDARD
**When to Use:** Onboarding new cinema location with ACTIVE merchant
**Precondition:** Merchant status must be ACTIVE
**Document Review:** Always mandatory; uses reusable DOCUMENT_REVIEW_AND_SIGNING subprocess
**requires_procurement:** Configurable (default `false`)

**Document and Procurement Branches (parallel during review):**
- Document review and signing are mandatory (legal, accounting, partner approvals)
- Procurement (PR) is optional; when enabled, runs in parallel with document review
- When procurement is enabled, PR number must be recorded before signing gate validation
- After signing: PO and Payment Request are created (not before signing)

**After Signing, Two Parallel Branches (UAT and Production, no dependency between them):**

*Production Branch:*
1. Create Production agent
2. Configure service list
3. Send Production information to Partner

*UAT Branch:*
1. Configure UAT agent
2. Configure Product ID or orderGroupID
3. Configure MID or partnerCode (scope: UAT)
4. Send UAT information to Partner
5. Create JIRA ticket
6. Test
7. Complete UAT acceptance

**Project Completion Requirements:**
- Signed document
- Completed Production branch
- Completed UAT acceptance
- Completed optional procurement (if enabled)
- UAT identifiers and Production identifiers remain separate (no dependencies between branches)

#### 4. INTEGRATION_NEW_MERCHANT_STANDARD
**When to Use:** Onboarding a new Merchant for the first time
**Precondition:** Merchant must be in ONBOARDING status; reject if ACTIVE
**Uniqueness:** Do not create duplicate Merchant or Master MID

**Pre-Document Gates (validation):**
1. AML check
2. Partner information checking
3. Master Merchant identity creation or validation

**Then Follow:**
1. Document review and signing (reusable DOCUMENT_REVIEW_AND_SIGNING subprocess)
2. Optional procurement (parallel with document review, if enabled)
3. Production branch (same as OPENING_NEW_CINEMA_STANDARD)
4. UAT branch (same as OPENING_NEW_CINEMA_STANDARD)

**Merchant Activation:**
- Merchant status promoted from ONBOARDING to ACTIVE only after all integration completion gates pass
- Status transition is atomic with final project completion

**For Existing ACTIVE Merchant:**
- Reject INTEGRATION_NEW_MERCHANT_STANDARD
- Propose OPENING_NEW_CINEMA_STANDARD instead

---

## 10. Workflow State Model

### State Definitions

#### Step Statuses
- **PENDING:** Step is defined but not ready to start (preconditions not met)
- **READY:** Preconditions met; step may be started
- **IN_PROGRESS:** Step is currently executing
- **BLOCKED:** Step cannot proceed due to a blocking condition (e.g., missing approval)
- **COMPLETED:** Step finished successfully
- **SKIPPED:** Step was bypassed (optional step in a different workflow path)
- **SUPERSEDED:** Step was replaced by a newer version (e.g., document revision loop)

#### Project Statuses
- **PLANNED:** Project created; workflow not yet started
- **IN_PROGRESS:** One or more steps are active
- **BLOCKED:** One or more blocking conditions prevent forward progress
- **ON_HOLD:** Project temporarily paused (not the same as BLOCKED)
- **COMPLETED:** All required steps completed successfully
- **CANCELLED:** Project cancelled and will not proceed

### Concurrency & Optimistic Locking
- **Multiple Active Steps:** A project may have multiple steps in `IN_PROGRESS` or `READY` simultaneously (e.g., UAT and Production branches)
- **Optimistic Version:** Each mutable entity (project, step, procurement) has an integer `version` field
- **Conflict Detection:** Before mutation, verify `version` matches the database record
- **Rollback on Conflict:** Retry the read+propose cycle; do not auto-merge conflicting updates

### Dependency Validation
- **Acyclic Graph:** Prevent circular dependencies between steps
- **Transitive Closure:** If A depends on B and B depends on C, ensure A cannot be marked READY until C is COMPLETED
- **Superseded Steps:** Reopened or superseded steps do not break dependency chains; use explicit dependency edges

---

## 11. Document Approval Gates

### Review and Signing Workflow

**Phase 1: Draft or Renew**
- Create initial or renewal document revision (revision_number = 1)

**Phase 2: Parallel Review (Legal & Accounting)**
- Legal reviews and either approves or rejects
- Accounting reviews and either approves or rejects
- Both may review in parallel

**Phase 3: Revision Loop**
- If Legal or Accounting reject: document author creates new revision (revision_number = 2)
- Previous revision is superseded (superseded_by = new_revision_id)
- New revision must go through Legal and Accounting again
- Old approvals are not carried forward to the new revision

**Phase 4: Partner Review**
- Send Legal+Accounting-approved revision to Partner
- Partner reviews and either approves or provides feedback
- If feedback: author creates new revision, repeat Legal+Accounting+Partner

**Phase 5: Signing Gate Validation**
Before signing is permitted:
- `document_approvals` must have APPROVED entries for (LEGAL, ACCOUNTING, PARTNER) on the same revision
- All three approvals must reference the same `document_revision_id`
- The revision must be the latest non-superseded revision
- If `requires_procurement = true`: a valid PR number must be recorded in `procurement_records`

**Phase 6: Signing**
- Sign the document (execute signing ceremony)
- Record in event audit trail
- Mark step COMPLETED

### Approval Tracking
```sql
INSERT INTO merchant_ops.document_approvals (
  document_revision_id,
  approver_role,
  approval_status,
  approved_at,
  approved_by,
  notes
) VALUES (?, ?, 'APPROVED', CURRENT_TIMESTAMP, ?, ?);
```

---

## 12. Procurement Rules

### Purchase Request (PR)
- **Timing:** Created in parallel with document review (MEDIA_TOP_UP) or after signing gates (OPENING_NEW_CINEMA)
- **Recorded:** External PR number (e.g., "JRA-12345") stored in `procurement_records`
- **Gate:** If `requires_procurement = true`, signing gate requires valid PR number

### Purchase Order (PO)
- **Created:** After document signing (or after all preconditions met)
- **Depends:** Document signing must be complete

### Payment Request
- **Created:** After PO
- **Depends:** PO must exist

### Payment Period Closure
- **Final Step:** Closes the payment cycle
- **Depends:** Payment Request must exist

---

## 13. UAT and Production Separation

### Identity Management
- **Master Identifiers:** MASTER_MID, MERCHANT_CODE, PARTNER_CODE created in pre-document gates (INTEGRATION_NEW_MERCHANT) or before Production (OPENING_NEW_CINEMA)
- **UAT Environment:** Separate Product ID, orderGroupID, MID, partnerCode for testing
- **Production Environment:** Separate Product ID, orderGroupID, MID, partnerCode for live operations

### Storage & Privacy
```sql
INSERT INTO merchant_ops.integration_identifiers (
  merchant_id, project_id,
  identifier_type, identifier_value,
  environment, is_active, privacy_classification
) VALUES (?, ?, 'PRODUCT_ID', '...', 'UAT', true, 'SENSITIVE');
```

### Constraint
- **No Collision:** UAT and Production identifiers remain separate and must not collide
- **Redaction:** All identifier_value fields are redacted in default CLI output

---

## 14. Transactions and Concurrency

### Transaction Boundaries
All project mutations must follow:
1. **Begin Transaction:** Start read+write transaction with appropriate isolation level
2. **Validate Optimistic Version:** Read current `version` from database
3. **Validate Dependencies & Gates:** Check preconditions, unmet gates, blocked dependencies
4. **Apply Mutation:** INSERT/UPDATE state-changing operations
5. **Append Event:** INSERT exactly one row into `project_events` audit table
6. **Commit:** All changes committed atomically
7. **Verify Result:** Read back and display the new state

### Failure Recovery
- **Atomic Commit:** State mutation and exactly one corresponding project event commit together within one transaction
- **Rollback on Failure:** Any validation failure causes complete rollback of both state change and event
- **No Partial State:** If transaction fails, no partial schema state remains
- **Conflict Handling:** Version conflict (concurrent update) returns to step 1 (read+propose again)
- **Statement Timeout:** All queries must respect `statement_timeout` setting
- **Lock Timeout:** Write operations may use `lock_timeout` to avoid indefinite waits
- **Event Integrity:** Sensitive values (credentials, full contact details, integration identifier values) must not enter `project_events` old_values, new_values, or change_summary fields

### Example: Step Completion
```python
# Read + validate
tx = conn.begin()
current_version = read_project_step(step_id).version
gate_status = check_gates(step_id)

if not gate_status.all_met:
    tx.rollback()
    raise GatesNotMetError(...)

# Mutate
update_project_step(step_id, status='COMPLETED', version=current_version + 1)
append_audit_event('STEP_COMPLETED', step_id, {...})

# Commit
tx.commit()

# Verify
return read_project_step(step_id)
```

### Alert Claiming (Phase 4B)
- **Deduplication:** Alerts must use deterministic deduplication (content-based, not ID-based)
- **Claiming:** Use `FOR UPDATE SKIP LOCKED` to avoid claiming the same alert twice
- **Idempotent Delivery:** Safe to retry without creating duplicate notifications

---

## 15. Merchant Activation

Merchant activation transitions merchants from ONBOARDING to ACTIVE status after all integration workflow gates pass.

### Single Merchant Activation

**Syntax:**
```
python .claude/agents/tools/merchant/agent_cli.py merchant activate \
  --propose \
  --merchant-id <MERCHANT_UUID> \
  --expected-version <VERSION_INT> \
  --reason "<REASON_TEXT>" \
  --triggered-by <USER_UUID>
```

**Proposal Output:**
- Contains `proposal_hash`, `confirmation_hash`, and `confirmation_token`
- Includes normalized payload with merchant_id, expected_version, and reason
- `requires_confirmation: true` (user must provide confirmation token to apply)

**Apply Syntax (via orchestration only):**
```
# APPLY MODE IS NOT AVAILABLE VIA ORDINARY CLI
# Orchestration performs the mutation through trusted in-process handoff only
```

**Behavior:**
- Only ONBOARDING → ACTIVE is valid; already ACTIVE is a conflict (not fake success)
- `expected_version` protects against concurrent modifications
- Updates merchant status and version atomically
- Inserts exactly one redacted audit event in same transaction
- Never fabricates event_id for never-inserted events
- No fake success or artificial events for already-ACTIVE merchants

### Batch Merchant Activation

**Preflight (read-only proposal):**
```
python .claude/scripts/merchant_activation_preflight.py --database runtime
```

Validates:
- Current merchants with ONBOARDING status
- Exact sorted manifest: merchant_id, code, account_status, version
- Expected count matches actual database count
- Builds deterministic manifest SHA256

**Syntax:**
```
python .claude/agents/tools/merchant/agent_cli.py merchant activate-all \
  --propose \
  --from-status ONBOARDING \
  --expected-count <COUNT_INT> \
  --reason "<REASON_TEXT>" \
  --triggered-by <USER_UUID>
```

**Critical Protections:**
- Manifest binding: proposal includes exact sorted list of (merchant_id, code, account_status, version)
- Expected count ALONE is not sufficient; manifest membership and state must be identical
- Same-count membership drift (different merchant IDs, different codes, or different statuses) → rejection
- Version drift → rejection (any merchant version changed since proposal) → rejection
- SELECT FOR UPDATE locks all proposed merchants before manifest verification
- Manifest rebuilt from locked rows and compared to proposal exactly

**Apply:**
- All or nothing atomicity: all updates + all events succeed or entire batch rolls back
- One redacted audit event per successfully activated merchant
- Identical proposal hash cannot silently activate a different merchant set

**Batch Failure Examples:**
- Proposal merchant [A, B, C]; apply finds [A, B, D] → rejected (membership drift)
- Proposal merchant A v2; apply finds A v3 → rejected (version drift)
- Proposal status ONBOARDING; apply finds status ACTIVE → rejected (status conflict)

### Workflow-Triggered Activation

When the canonical `activate_merchant` step of `INTEGRATION_NEW_MERCHANT_STANDARD` workflow reaches COMPLETED status:

1. **Lookup:** Load persisted project, step, and dependency metadata from database
2. **Authorize:** Verify step is canonical activation step (template_step_uuid match, no caller inference)
3. **Validate:** Check all required dependency steps are COMPLETED
4. **Activate:** Call merchant activation using same database cursor and transaction
5. **Atomicity:** Step transition + merchant update + audit event in one transaction
6. **Rollback:** Any failure (dependency validation, activation conflict, version mismatch) rolls back entire transaction including step transition

**Failures:**
- Missing dependencies → REJECT and roll back step
- Merchant already ACTIVE → REJECT and roll back step
- Version conflict → REJECT and roll back step
- Update rowcount ≠ 1 → REJECT and roll back step

### Safety Guidelines

**Database Targets:**
- Use `runtime` for user-initiated operations (through merchant-manager teammate)
- Use `test` only for explicit development/readiness tests
- Never substitute test target for runtime when runtime is requested
- Test database is isolated and reserved; do not treat it as failover

**Confirmation Handling:**
- `confirmation_token` is displayed by CLI; user enters it when prompted
- **Never** copy-paste confirmation phrases directly as shell commands
- **Always** wait for the confirmation prompt before entering token
- Confirmation is entered interactively only when CLI asks; it is not a flag or environment variable

**No Real Data in Documentation:**
- Merchant IDs are placeholders (not real UUIDs from catalogs)
- Confirmations are redacted; hashes and tokens are not printed in plain text
- Credentials, passwords, and contact data remain internal to CLI
- Private catalog records and identifiers never appear in documentation or examples

---

## 16. Migration Strategy

### Forward-Only Design
- **No Rollbacks:** Migrations are applied once and never undone
- **Versioned Checksums:** Each migration has version + checksum in `merchant_ops.schema_migrations`
- **Atomicity:** One migration executes as a single transaction
- **Serialization:** Concurrent migration attempts are serialized; second attempt detects applied migration

### Migration Execution
1. **Lock:** Acquire PostgreSQL advisory lock or exclusive table lock on `merchant_ops.schema_migrations`
2. **Check:** Verify migration version not already applied; if applied, verify checksum matches
3. **Conflict:** If version exists with different checksum, fail immediately (corrupted or conflicting migration history)
4. **Execute:** Run migration SQL within one transaction
5. **Record:** INSERT into `merchant_ops.schema_migrations` only after successful execution
6. **Commit:** Entire transaction (schema changes + migration record) commit together
7. **Rollback:** If any step fails, complete transaction rollback; no partial schema state remains
8. **Release:** Lock released; next migration may proceed

### Migration Requirements
- **Ownership:** `merchant_owner` role only (never `merchant_app`)
- **Atomicity:** Entire migration (schema + record) commits as one transaction; all-or-nothing
- **No Partial State:** Failed migration rolls back completely; never leaves schema partially migrated
- **Idempotent Checks:** Safe to retry failed migrations (lock prevents concurrent execution)
- **Serialization:** Concurrent migration attempts blocked until first completes (via lock)

### Example File Structure
```text
.claude/clients/merchant/migrations/versions/
├── 001_initial_schema.sql
├── 002_add_merchant_contacts.sql
├── 003_add_procurement_tables.sql
└── 004_add_alert_deliveries.sql
```

### Using psycopg 3
```python
# Preferred: psycopg 3 unless established project convention conflicts
from psycopg import connect
from psycopg.sql import SQL, Identifier

conn = connect("...")
cursor = conn.cursor()
cursor.execute(SQL("SELECT * FROM {} WHERE id = %s").format(
    Identifier("merchant_ops", "merchants")
), [merchant_id])
```

---

## 16. CLI Contracts

### Read-Only Commands
All read-only commands return JSON unless otherwise specified.

#### `merchant list`
List all merchants with optional filters
```bash
merchant list [--status ONBOARDING|ACTIVE|INACTIVE|SUSPENDED]
```
Returns: Array of merchant objects (codes and names shown; contact data redacted)

#### `project list`
List projects with optional filters
```bash
project list [--merchant-id <id>] [--status PLANNED|IN_PROGRESS|BLOCKED|...]
```
Returns: Array of project objects

#### `project show <project_id>`
Show complete project state including all active steps, document revisions, approvals, procurement
```bash
project show <project_id>
```
Returns: Project object with full details (contact data redacted)

#### `project history <project_id>`
Show complete audit trail of all project events
```bash
project history <project_id> [--limit 50]
```
Returns: Array of event objects in chronological order

#### `project blockers <project_id>`
List all blocking conditions preventing project progress
```bash
project blockers <project_id>
```
Returns: Array of blocker objects (missing gates, failed dependencies, etc.)

#### `project alerts <project_id>`
List all alerts for a project (Phase 4A calculation only)
```bash
project alerts <project_id>
```
Returns: Array of alert objects (overdue, due-soon, blocked, missing gates)

### Write Commands
Write commands follow a propose-apply pattern. The agent (not the CLI) controls confirmation.

#### `merchant create --propose`
Show proposed merchant without applying
```bash
merchant create --propose --code <code> --name <name> --region <region>
```
Returns: Proposed merchant object for agent review

#### `merchant create --apply`
Apply confirmed merchant creation
```bash
merchant create --apply --code <code> --name <name> --region <region> --expected-version <version>
```
Flow:
1. Validate inputs and expected version
2. Verify authorization context from controlled orchestration
3. Execute transactionally
4. Return created merchant or failure

**Note:** CLI never prompts for interactive confirmation. Confirmation happens at intent-envelope and policy-gate level, controlled by `/solve` orchestration.

#### `contact import`
Bulk import merchant contacts (redacted in output)
```bash
contact import --propose --merchant-id <id> --file <csv>
contact import --apply --merchant-id <id> --file <csv> --expected-version <version>
```

#### `project create`
Create a new project with initial workflow steps
```bash
project create --propose --merchant-id <id> --type MEDIA_TOP_UP --variant MEDIA_TOP_UP_NEW_DOCUMENT
project create --apply --merchant-id <id> --type MEDIA_TOP_UP --variant MEDIA_TOP_UP_NEW_DOCUMENT --expected-version <version>
```

#### `project update`
Update project properties
```bash
project update --propose <project_id> --status IN_PROGRESS
project update --apply <project_id> --status IN_PROGRESS --expected-version <version>
```

#### `step update`
Update a project step state
```bash
step update --propose <step_id> --status COMPLETED --assigned-to <user_id>
step update --apply <step_id> --status COMPLETED --assigned-to <user_id> --expected-version <version>
```

#### `document revision-create`
Create a new document revision
```bash
document revision-create --propose <project_id> --type MERCHANT_AGREEMENT
document revision-create --apply <project_id> --type MERCHANT_AGREEMENT
```

#### `document approve`
Propose and approve a document
```bash
document approve --propose <revision_id> --role LEGAL --status APPROVED [--notes "Looks good"]
document approve --apply <revision_id> --role LEGAL --status APPROVED --expected-version <version> --proposal-hash <hash> [--notes "Looks good"]
```

#### `procurement update`
Propose and record procurement milestone
```bash
procurement update --propose <project_id> --type PURCHASE_REQUEST --external-id JRA-12345
procurement update --apply <project_id> --type PURCHASE_REQUEST --external-id JRA-12345 --expected-version <version> --proposal-hash <hash>
```

#### `integration identifier-set`
Propose and set an integration identifier
```bash
integration identifier-set --propose <merchant_id> <project_id> --type PRODUCT_ID --value <val> --scope UAT
integration identifier-set --apply <merchant_id> <project_id> --type PRODUCT_ID --value <val> --scope UAT --proposal-hash <hash>
```

**Note:** All write operations use propose/apply pattern. Apply requires expected-version (for existing entities) or proposal-hash binding (for new entities). CLI never displays confirmation prompts; confirmation is owned by intent envelope and policy gate.

### CLI Contract Properties
- **Non-Interactive:** CLI never prompts for terminal input; fails rather than waits
- **Parameterization:** All queries use parameterized queries (no SQL injection risk)
- **Schema Qualification:** All table references are fully qualified (`merchant_ops.table_name`)
- **Search Path Control:** Explicit `SET search_path` in connection
- **Statement Timeout:** All queries respect statement timeout
- **Lock Timeout:** Write operations use lock timeout where appropriate
- **Credentials:** Never exposed in logs or command output; never printed to stdout
- **Redaction:** Default output redacts contact names, emails, phones, and integration identifiers
- **Private Access:** If private contact access is required later, design as separate authorized operation with explicit policy classification and audit trail

---

## 17. Agent Response Contract

### Example 1: MEDIA_TOP_UP_NEW_DOCUMENT Project
Project with document review only; no UAT/Production branches.

```json
{
  "merchant": {
    "code": "MERCHANT_001",
    "name": "CGV Cinema",
    "status": "ACTIVE"
  },
  "project": {
    "id": "<project_id>",
    "type": "MEDIA_TOP_UP",
    "workflow_variant": "MEDIA_TOP_UP_NEW_DOCUMENT",
    "overall_status": "IN_PROGRESS",
    "requires_procurement": true
  },
  "document_status": {
    "latest_revision": 2,
    "approval_status": {
      "legal": "APPROVED",
      "accounting": "APPROVED",
      "partner": "PENDING"
    },
    "signed": false,
    "signing_gate": {
      "legal_approved": true,
      "accounting_approved": true,
      "partner_approved": false,
      "pr_recorded": true,
      "all_requirements_met": false
    }
  },
  "procurement_status": {
    "purchase_request": "PR-2026-001",
    "purchase_order": null,
    "payment_request": null
  },
  "active_steps": [
    {
      "id": "<step_id>",
      "name": "Partner Review",
      "branch_key": "document_branch",
      "status": "IN_PROGRESS",
      "assigned_to": "<user_id>",
      "scheduled_completion": "2026-09-05",
      "blockers": []
    }
  ],
  "branch_progress": {
    "document_branch": {
      "status": "IN_PROGRESS",
      "current_step": "Partner Review",
      "next_steps": ["Signing Gate", "Sign Document", "Create PO"]
    }
  },
  "unmet_gates": [
    {
      "gate_type": "SIGNING_GATE",
      "required_conditions": ["PARTNER_APPROVAL"],
      "unmet": ["PARTNER_APPROVAL"]
    }
  ],
  "blockers": [
    {
      "type": "MISSING_APPROVAL",
      "description": "Waiting for Partner approval on document revision 2"
    }
  ],
  "next_actions": [
    "Send document revision 2 to Partner for approval"
  ],
  "deadlines": {
    "project_deadline": "2026-10-01",
    "document_due": "2026-09-05"
  },
  "warnings": [
    {
      "type": "DUE_SOON",
      "due_date": "2026-09-05",
      "days_remaining": 3,
      "description": "Document partner approval due 2026-09-05"
    }
  ]
}
```

### Example 2: OPENING_NEW_CINEMA_STANDARD Project (After Signing)
Project with parallel UAT and Production branches after document signing.

```json
{
  "merchant": {
    "code": "MERCHANT_002",
    "name": "Lotte Cinema",
    "status": "ACTIVE"
  },
  "project": {
    "id": "<project_id>",
    "type": "OPENING_NEW_CINEMA",
    "workflow_variant": "OPENING_NEW_CINEMA_STANDARD",
    "overall_status": "IN_PROGRESS",
    "requires_procurement": false
  },
  "document_status": {
    "latest_revision": 1,
    "approval_status": {
      "legal": "APPROVED",
      "accounting": "APPROVED",
      "partner": "APPROVED"
    },
    "signed": true,
    "signed_at": "2026-08-28T10:00:00Z"
  },
  "active_steps": [
    {
      "id": "<step_id>",
      "name": "Configure Production Agent",
      "branch_key": "production_branch",
      "status": "IN_PROGRESS",
      "assigned_to": "<user_id>",
      "scheduled_completion": "2026-09-10",
      "blockers": []
    },
    {
      "id": "<step_id>",
      "name": "Configure UAT Agent",
      "branch_key": "uat_branch",
      "status": "IN_PROGRESS",
      "assigned_to": "<user_id>",
      "scheduled_completion": "2026-09-10",
      "blockers": []
    }
  ],
  "branch_progress": {
    "production_branch": {
      "status": "IN_PROGRESS",
      "current_step": "Configure Production Agent",
      "next_steps": ["Configure Service List", "Send Info to Partner"]
    },
    "uat_branch": {
      "status": "IN_PROGRESS",
      "current_step": "Configure UAT Agent",
      "next_steps": ["Set Product ID", "Send Info to Partner", "Test", "UAT Acceptance"]
    }
  },
  "active_integrations": {
    "production": {
      "MID": "PROD_MID_12345",
      "scope": "PRODUCTION"
    },
    "uat": {
      "MID": "UAT_MID_12345",
      "scope": "UAT"
    }
  },
  "blockers": [],
  "next_actions": [
    "Configure service list for production",
    "Complete UAT setup and acceptance"
  ],
  "deadlines": {
    "project_deadline": "2026-10-15",
    "production_due": "2026-09-30",
    "uat_due": "2026-09-25"
  }
}
```

**Response Contract Rules:**
- Include merchant code (shown) and name (shown for identification)
- Do not show only one current step when multiple are active; show all active steps with branch keys
- MEDIA_TOP_UP variants contain only document_branch, no UAT/Production
- OPENING_NEW_CINEMA and INTEGRATION_NEW_MERCHANT contain parallel uat_branch and production_branch (no dependency between them)
- All returned owner fields, deadlines, and derived statuses must be either stored in schema or explicitly documented as calculated

---

## 18. Intent and Policy Proposal

This checkpoint proposes but does not implement:

- **Read Routing:** Requests for project state route to read-only CLI commands via merchant-manager agent
- **Write Routing:** Requests to update state route to write commands with confirmation via merchant-manager agent
- **Clarification:** Ambiguous requests (e.g., "update the project") ask the user which field to update
- **Confirmation:** All write commands show proposed changes and require explicit user approval
- **CLI Allowlisting:** A whitelist of permitted CLI commands (merchant, project, step, document, procurement, integration)
- **Unauthorized-Agent Denial:** Only merchant-manager may execute merchant/project commands
- **Tool-Call Accounting:** Each tool call counts against the run's `max_total_tool_calls` budget
- **Envelope Enforcement:** No-envelope-no-run preservation; `/solve` must validate the intent envelope
- **Destructive & External Mutation Protection:** Existing protections in `policy_gate.py` apply to Merchant operations

---

## 19. Alert Boundary

### Alert Query Contract (Global, Phase 4A)
Read-only alert calculation across all merchants and projects.

```bash
project alerts [--merchant-id <id>] [--project-id <id>] [--alert-type <type>] [--due-date-before <date>]
```

**Filters (all optional):**
- `--merchant-id`: Filter to specific merchant (e.g., for merchant-focused dashboard)
- `--project-id`: Filter to specific project
- `--alert-type`: Filter by alert type (OVERDUE, DUE_TODAY, DUE_SOON, BLOCKED, MISSING_GATE)
- `--due-date-before`: Filter to deadlines before or on specified date

**Returns:** Array of alert objects with:
- project, step, alert type
- business due date or condition fingerprint
- delivery status
- suggested delivery channel

### Phase 4A (This Architecture)
Calculate but do not deliver alerts:
- **Overdue:** Steps with `scheduled_completion` before today
- **Due Today:** Steps with `scheduled_completion` equal to today
- **Due Soon:** Steps with `scheduled_completion` within next 7 days (configurable window)
- **Blocked & Overdue:** Steps with BLOCKED status and past deadline
- **Missing Gates:** Signing gates or approval gates with unmet requirements
- **Workflow Blockers:** Blocked dependencies or failed preconditions

### Phase 4B (Future, Not This Checkpoint)
Deliver notifications:
- **Worker Type:** Non-agent process (Python script or scheduled task)
- **Runtime:** Windows Task Scheduler or external deterministic scheduler
- **Independence:** Must operate without an active Claude Code session
- **Delivery Channels:** Email, Slack, internal notification system
- **Deduplication:** Deterministic deduplication to avoid sending the same alert twice
- **Acknowledgement:** Record when user acknowledges alert
- **State Management:** Write-only to `alert_deliveries` table; never update project workflow state

---

## 20. Testing Strategy

### Business Rule Tests
- Workflow template dependency cycles are prevented
- Superseded steps do not carry old approvals
- Document revision loops require all approvals on latest revision
- Signing gate validates correct approvals and PR number
- UAT and Production identifiers remain separate
- Existing-Document Media Top Up requires valid preconditions
- New-Merchant Integration rejects existing active merchants

### PostgreSQL Integration Tests
- Transactions roll back completely on validation failure
- Optimistic version conflicts trigger read+propose retry
- Statement and lock timeouts are enforced
- Connection pooling works under load
- Multiple concurrent projects do not interfere

### Migration Tests
- Forward-only migrations apply exactly once
- Checksum mismatch on applied migration is rejected
- Failed migration rolls back completely
- Version sequences have no gaps
- merchant_ops.schema_migrations table is properly initialized

### Role and Grant Tests
- merchant_app can read all tables, write to permitted tables only
- merchant_app cannot access rag_schema
- merchant_alert can only read workflow state and write alert state
- merchant_test cannot connect to runtime databases
- PUBLIC privileges are revoked

### Transaction Safety Tests
- Concurrent step updates are serialized
- Concurrent document approvals do not race
- Alert claiming with `FOR UPDATE SKIP LOCKED` prevents duplicates
- Successful state mutation and corresponding project event commit together
- Failed mutation transaction rolls back both state and event
- Sensitive values (credentials, full contact details, integration values) never enter project_events

### Workflow Engine Tests
- Steps transition through valid state sequences
- Dependencies block invalid transitions
- Parallel branches allow multiple active steps
- Conditional logic routes to correct branch
- Approval gates block forward progress until satisfied

### Deadline Calculation Tests
- Overdue, due-today, due-soon calculations are correct
- MERCHANT_TIMEZONE is applied consistently
- Business day calculations respect weekends and holidays (if applicable)

### Contact and Integration Data Redaction Tests
- Default CLI output redacts `merchant_contacts` names, emails, phones
- Default CLI output redacts `integration_identifiers` values
- Tests use fictitious values only
- No generic redaction bypass; private access requires separate authorized operation

### Additional Required Tests
- **Project/Workflow Types:** Exactly three types and four variants
- **Merchant Lifecycle:** ONBOARDING → ACTIVE promotion, reject existing ACTIVE for INTEGRATION_NEW_MERCHANT_STANDARD
- **Existing-Document Reuse:** Same merchant, effective/expiry date validation, payment_period >= 2
- **Workflow-Template Binding:** Projects bound to immutable template versions, template changes don't affect existing projects
- **Branch Keys:** Branch metadata immutable, parallel steps grouped by branch_key
- **Condition Keys:** Allowlisted conditions only, no executable code
- **Integration Identifiers:** MASTER/UAT/PRODUCTION scopes, no collision across scopes
- **Alert Deduplication:** Stable key (business_due_date or condition_fingerprint, not current_timestamp), FOR UPDATE SKIP LOCKED, idempotent retry
- **Non-Interactive CLI:** CLI never prompts; confirmation owned by orchestration
- **Propose/Apply Contracts:** Binding to proposal-hash or expected-version, atomicity of mutations
- **UTF-8 Support:** Merchant names and Vietnamese project context
- **Audit Immutability:** project_events append-only, sensitive values redacted
- **Default Privileges:** New tables receive correct merchant_app grants
- **Global Alerts:** Query across merchants and projects with filters

### CLI Contract Tests
- `project show` returns complete state with all branches
- `project blockers` identifies all blocking conditions
- `project alerts` calculates all alert types
- Write commands show proposed changes before confirmation
- Confirmation prompt is mandatory and explicit

### UTF-8 Tests
- Vietnamese merchant names store and retrieve correctly
- Vietnamese project notes remain legible
- UTF-8 characters in contact data do not corrupt
- All text columns handle emoji and special characters

### System Tests
- `.claude/system_test.py` validates all migration versions exist
- `.claude/system_test.py` validates no real PII in fixtures
- No credentials or passwords committed to Git
- `.gitignore` excludes `.env`, real fixtures, and PII files

### Database Tests Fail Closed
- Tests run only against databases ending with `_test`
- Attempting to connect to `coding_agent_merchant` fails with permission error
- Attempting to mutate any database outside tests fails safely

---

## 21. Implementation Checkpoints

### Checkpoint 1: Architecture Contract ✅ (This Document)
- Authoritative design document
- All components, tables, workflows, boundaries defined
- Ready for next phase

### Checkpoint 2: Shared PostgreSQL Bootstrap
- Create `coding_agent_merchant` and `coding_agent_merchant_test` databases
- Create roles: `merchant_owner`, `merchant_app`, `merchant_alert`, `merchant_test`
- Initialize `merchant_ops.schema_migrations` table in `merchant_ops` schema
- Verify role isolation and grant structure
- Add environment variables to `.env.example`

### Checkpoint 3: Versioned Migrations and Database Client
- Create `.claude/clients/merchant/migrations/versions/001_initial_schema.sql`
- Implement migration runner (`.claude/clients/merchant/migrations/migrate.py`)
- Create PostgreSQL wrapper client (`.claude/clients/merchant/client.py`)
- Create data access repository (`.claude/clients/merchant/repository.py`)
- Implement parameterized query execution
- Add statement and lock timeouts
- Verify transaction boundaries

### Checkpoint 4: Workflow Engine and Templates
- Create `merchant_ops.workflow_templates` and related tables
- Implement workflow template loader
- Implement step state machine (valid transitions)
- Implement dependency validation (acyclic, transitive closure)
- Implement gate validators (signing, approval)
- Implement parallel branch resolver

### Checkpoint 5: Read and Write CLI
- Implement `merchant list`, `project list`, `project show`, `project history`, `project blockers`, `project alerts`
- Implement write commands with propose/apply pattern: `merchant create`, `contact import`, `project create`, `project update`, `step update`, `document revision-create`, `document approve`, `procurement update`, `integration identifier-set`
- Propose mode: show exact payload, bind with proposal-hash or capture uniqueness
- Apply mode: require expected-version (existing) or proposal-hash (new), execute transaction
- Implement redaction for contact and integration data (merchant codes and names shown; emails, phones, identifiers redacted)
- CLI must never prompt for interactive input; fail rather than wait
- Test all CLI contracts match propose/apply pattern

### Checkpoint 6: merchant-manager Agent Registration
- Create `.claude/agents/merchant-manager.md` subagent definition
- Register in `.claude/agents.json`
- Add team member row to `.claude/commands/solve.md`
- Implement agent→CLI tool interface
- Verify SendMessage and TaskUpdate for reporting

### Checkpoint 7: Intent and Policy Integration
- Propose intent routing (read vs. write commands)
- Propose confirmation policy for write commands
- Propose CLI allowlisting in `policy_gate.py`
- Verify no-envelope-no-run enforcement in `/solve`
- Verify destructive and external mutation protections

### Checkpoint 8: Deadline and Alert Calculation
- Implement overdue/due-today/due-soon calculation
- Implement blocked-and-overdue detection
- Implement missing-gate detection
- Implement workflow-blocker detection
- Implement `project alerts` CLI command
- Test with various deadline scenarios

### Checkpoint 9: Private Runtime Initialization
- Import real Merchant catalog (22 records with UTF-8 names) from private runtime source
- Keep real data outside Git and RAG ingestion
- Create test fixtures with fictitious values only
- Verify all merchants initialize in correct status (ONBOARDING or ACTIVE as appropriate)
- Test real workflow transitions with runtime data

### Checkpoint 10: Phase 4B Alert Worker (Future)
- Design merchant-alert-worker (non-agent process)
- Implement alert deduplication strategy
- Implement `FOR UPDATE SKIP LOCKED` alert claiming
- Implement delivery channels (email, Slack, internal)
- Verify independence from Claude Code session

---

## 22. Backup and Recovery

### Backup Strategy
- **Separate Backups:** RAG and Merchant require separate `pg_dump` backups
- **Database Backups:** Per-database `pg_dump` captures schema, data, and object ownership
- **Role Backup:** PostgreSQL roles are cluster-global; backup roles separately or use reproducible bootstrap procedure
- **Frequency:** Daily automated backups recommended
- **Retention:** Keep minimum 7 days of backups
- **Verification:** Periodic restore tests to verify backup integrity

### Backup Commands (Platform-Neutral for Windows/Linux/macOS)
```bash
# Merchant database
pg_dump -h 127.0.0.1 -p 5434 -U merchant_owner --file merchant_backup_YYYYMMDD.sql coding_agent_merchant

# RAG database
pg_dump -h 127.0.0.1 -p 5434 -U rag_user --file rag_backup_YYYYMMDD.sql coding_agent_rag

# Roles (cluster-global; kept in secure location or bootstrap procedure, not per-database dump)
# psql -h 127.0.0.1 -p 5434 -U postgres --file roles_backup_YYYYMMDD.sql -c "\du+"
```

**Note:** Use `--file` (or `-f`) instead of shell redirection (>`). This ensures commands work in Windows PowerShell and other environments. Roles are cluster-global and require separate backup or reproducible bootstrap procedure; plain database dumps do not include role definitions.

### Recovery Procedure
1. **Verify Backup:** Confirm backup file integrity
2. **Restore:** `psql -h 127.0.0.1 -p 5434 -U merchant_owner coding_agent_merchant < backup.sql`
3. **Verify Schema:** Confirm all tables and roles exist
4. **Test Queries:** Run sanity checks on critical tables
5. **Alert Stakeholders:** Notify team of recovery completion

### Point-in-Time Recovery
- **WAL Archiving:** Not configured in Phase 4A; implement in future if needed
- **Binary Backup:** Volume snapshots or container-level backups as alternative

---

## 23. Risks and Assumptions

### Identified Risks
| Risk | Impact | Mitigation |
|------|--------|-----------|
| Shared PostgreSQL server | Both systems down if DB restarts | Separate servers in future; current setup is temporary |
| Single volume for both databases | Complete data loss if volume deleted | Maintain separate, verified backups for each system |
| UTF-8 validation | Data corruption or search failures | Test UTF-8 indexing and character collation early |
| Concurrent workflow updates | Race conditions or corrupted state | Optimistic locking + transaction rollback on conflict |
| Missing audit trail | Cannot reconstruct history on failure | Append-only events table; no updates or deletes to events |
| Contact PII exposure | Privacy violation | CLI redaction by default; access control via roles |

### Assumptions
1. **PostgreSQL Availability:** The existing shared PostgreSQL instance is available and maintained; Merchant Manager does not require the pgvector extension
2. **Network Connectivity:** 127.0.0.1:5434 is accessible from Claude Code session and scheduler process
3. **Role Separation:** Database users (merchant_owner, merchant_app, merchant_alert) can be created and grants enforced
4. **Transaction Semantics:** SERIALIZABLE isolation is available when needed for high-concurrency operations
5. **Timezone:** All timestamps are stored as TIMESTAMPTZ; MERCHANT_TIMEZONE is applied in application logic
6. **Unicode Collation:** PostgreSQL server uses UTF-8 encoding (verified on initialization)

---

## 24. Summary and Next Steps

### Document Scope
This architecture contract defines the **authoritative design** for Phase 4 Merchant Project Manager, encompassing:
- ✅ System components and boundaries
- ✅ PostgreSQL schema and role isolation
- ✅ Four major workflow types
- ✅ Document review and approval gates
- ✅ Transaction and concurrency model
- ✅ CLI contracts and agent response formats
- ✅ Testing and migration strategies
- ✅ Privacy and UTF-8 requirements

### What Is Not Included
- ❌ Python implementation code
- ❌ Database container configuration
- ❌ Environment initialization scripts
- ❌ Real merchant or project data
- ❌ Agent definition body (reserved for Checkpoint 6)
- ❌ Phase 4B alert worker implementation (reserved for Checkpoint 10)

### Ready for Next Checkpoint
This document is complete and ready to serve as input for Checkpoint 2 (PostgreSQL bootstrap) and subsequent implementation phases. All architects, developers, and agents should read this document before implementing any Merchant Project Manager features.

---

**Document Status:** Complete
**Approval:** Awaiting review
**Next Review:** After Checkpoint 2 completion
