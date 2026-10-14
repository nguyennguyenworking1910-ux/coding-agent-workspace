-- Merchant Direct Execute: PostgreSQL execution claims.
-- Claim takeover must be explicitly authorized.
-- Lock this row within the same transaction as domain writes.

CREATE TABLE merchant_ops.merchant_execution_claims (
    operation_key TEXT PRIMARY KEY,

    payload_hash CHAR(64) NOT NULL,

    execution_attempt_id UUID NOT NULL,

    claim_generation BIGINT NOT NULL DEFAULT 1,

    claim_status TEXT NOT NULL DEFAULT 'ACTIVE',

    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT merchant_claim_payload_hash_format
        CHECK (payload_hash ~ '^[0-9a-f]{64}$'),

    CONSTRAINT merchant_claim_generation_positive
        CHECK (claim_generation >= 1),

    CONSTRAINT merchant_claim_status_allowed
        CHECK (
            claim_status IN (
                'ACTIVE',
                'COMPLETED',
                'REVOKED'
            )
        )
);
