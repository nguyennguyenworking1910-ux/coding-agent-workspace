-- Store the payment-cycle number required by Media Top Up workflows.
-- Non-Media-Top-Up projects must not carry a payment-period number.

ALTER TABLE merchant_ops.projects
ADD COLUMN payment_period_number INTEGER;

ALTER TABLE merchant_ops.projects
ADD CONSTRAINT projects_payment_period_scope_check
CHECK (
    (
        project_type = 'MEDIA_TOP_UP'
        AND payment_period_number IS NOT NULL
        AND payment_period_number >= 1
    )
    OR
    (
        project_type <> 'MEDIA_TOP_UP'
        AND payment_period_number IS NULL
    )
);