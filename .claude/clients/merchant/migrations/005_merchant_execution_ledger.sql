-- Merchant Direct Execute idempotency ledger.
-- This migration contains no runtime data modification.

CREATE TABLE merchant_ops.merchant_execution_ledger (
    operation_key TEXT PRIMARY KEY,
    payload_hash CHAR(64) NOT NULL,
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT merchant_execution_hash_format
        CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT merchant_execution_result_object
        CHECK (
            result IS NULL
            OR jsonb_typeof(result) = 'object'
        )
);
