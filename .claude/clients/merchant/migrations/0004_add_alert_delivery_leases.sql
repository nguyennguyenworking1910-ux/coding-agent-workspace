-- Checkpoint 10: lease-safe Merchant alert delivery ownership.
--
-- This migration changes alert-delivery coordination state only. It does not
-- update Merchant, project, workflow, document, procurement, identifier,
-- template, event, or private catalog data.

ALTER TABLE merchant_ops.alert_deliveries
    ADD COLUMN claim_token UUID,
    ADD COLUMN claim_expires_at TIMESTAMPTZ,
    ADD COLUMN next_attempt_at TIMESTAMPTZ,
    ADD COLUMN last_attempt_at TIMESTAMPTZ,
    ADD COLUMN provider_message_id VARCHAR(255);

-- Existing delivery attempts predate explicit lease timestamps. Preserve the
-- recorded attempt chronology without changing any Merchant business record.
UPDATE merchant_ops.alert_deliveries
SET last_attempt_at = updated_at
WHERE delivery_attempt_count > 0
  AND last_attempt_at IS NULL;

ALTER TABLE merchant_ops.alert_deliveries
    DROP CONSTRAINT alert_deliveries_status_check,
    ADD CONSTRAINT alert_deliveries_status_check
        CHECK (
            delivery_status IN (
                'PENDING',
                'CLAIMED',
                'SENT',
                'FAILED',
                'DEAD_LETTER',
                'ACKNOWLEDGED'
            )
        ),
    ADD CONSTRAINT alert_deliveries_claim_state_check
        CHECK (
            (
                delivery_status = 'CLAIMED'
                AND claim_token IS NOT NULL
                AND claim_expires_at IS NOT NULL
                AND last_attempt_at IS NOT NULL
                AND claim_expires_at > last_attempt_at
                AND delivery_attempt_count >= 1
            )
            OR
            (
                delivery_status <> 'CLAIMED'
                AND claim_token IS NULL
                AND claim_expires_at IS NULL
            )
        ),
    ADD CONSTRAINT alert_deliveries_next_attempt_state_check
        CHECK (
            next_attempt_at IS NULL
            OR delivery_status IN ('PENDING', 'FAILED')
        ),
    ADD CONSTRAINT alert_deliveries_dead_letter_state_check
        CHECK (
            delivery_status <> 'DEAD_LETTER'
            OR last_attempt_at IS NOT NULL
        ),
    ADD CONSTRAINT alert_deliveries_provider_message_state_check
        CHECK (
            provider_message_id IS NULL
            OR (
                delivery_status IN ('SENT', 'ACKNOWLEDGED')
                AND provider_message_id = BTRIM(provider_message_id)
                AND CHAR_LENGTH(provider_message_id) BETWEEN 1 AND 255
            )
        );

DROP INDEX merchant_ops.alert_deliveries_claim_idx;

CREATE INDEX alert_deliveries_claim_idx
    ON merchant_ops.alert_deliveries (
        delivery_channel,
        delivery_status,
        next_attempt_at,
        claim_expires_at,
        created_at,
        id
    );
