# Group Sale Usage Measurement Rules

## 1. Purpose

This document defines how Group Sale usage must be measured for Beta, Lotte, Galaxy, CGV, and BHD. The output is intended to provide a consistent monthly usage dataset by merchant and Group Sale key.

This phase measures usage only. Opening inventory, remaining inventory, depletion forecasting, and expiry-risk monitoring are outside the current scope.

## 2. Source tables

| Source table | Purpose | Primary quantity field |
|---|---|---|
| `project-5400504384186300846.MBI_DA.CINEMA_FACT_BOOKING_GROUPSALE_V2` | Measures Group Sale ticket usage for Beta, Lotte, Galaxy, CGV, and BHD. | `tickets_groupsales` |
| `project-5400504384186300846.MBI_DA.CINEMA_FACT_CONCESSION_INAPP_V2` | Measures eligible BHD and Beta Group Sale combo usage. | One qualifying record is currently treated as one combo. |

The two tables have different grains and must not be joined directly for usage counting. Their results should first be aggregated independently and then combined with `UNION ALL`.

## 3. Merchant identification rules

Merchants in the ticket table are derived from the prefix or identifying text contained in `groupsale_key`.

| Condition applied to `UPPER(groupsale_key)` | Normalized merchant |
|---|---|
| Contains `LOTTE` | `Lotte` |
| Contains `BHD` | `BHD` |
| Contains `BETA` | `Beta` |
| Contains `GLX` | `Galaxy` |
| Contains `CGV` | `CGV` |
| Does not match a configured rule | `Unknown` |

Rows assigned to `Unknown` must be reviewed to determine whether a new merchant prefix needs to be added.

## 4. Usage rules by merchant

### 4.1 Beta

Beta's Group Sale ticket input is defined as a number of tickets. Ticket usage is therefore measured by summing `tickets_groupsales` from the booking Group Sale table.

Beta also has Group Sale combos. Only the following `combo_code` values are currently included:

- `COMBO030158-09`
- `COMBO030159-09`

For the current data grain, each qualifying row in the concession table is treated as one combo used. Beta ticket usage and Beta combo usage must remain separate because their measurement units are different.

| Usage type | Usage calculation | Measurement unit |
|---|---|---|
| Beta ticket | `SUM(tickets_groupsales)` | Tickets |
| Beta combo | `COUNT(*)` for the eligible combo codes | Combos |

### 4.2 Lotte

Lotte's Group Sale input is defined as a number of tickets. Usage is measured by summing `tickets_groupsales` for keys identified as Lotte.

| Usage calculation | Measurement unit |
|---|---|
| `SUM(tickets_groupsales)` | Tickets |

### 4.3 Galaxy

Galaxy's Group Sale input is defined as a number of tickets. Galaxy is identified by `GLX` in `groupsale_key`, and usage is measured by summing `tickets_groupsales`.

| Usage calculation | Measurement unit |
|---|---|
| `SUM(tickets_groupsales)` | Tickets |

### 4.4 CGV

CGV's Group Sale input is defined as a number of tickets. Usage is measured by summing `tickets_groupsales` for keys containing `CGV`.

| Usage calculation | Measurement unit |
|---|---|
| `SUM(tickets_groupsales)` | Tickets |

### 4.5 BHD

BHD is a special case because its Group Sale input is a monetary debit balance rather than a fixed ticket quantity. Every eligible ticket or combo usage deducts a monetary amount from that balance.

Quantity should still be retained for operational reporting and reconciliation, but the primary BHD usage measure is `debit_used` in VND.

#### BHD ticket debit

The ticket base price is encoded in `groupsale_key`. Examples include:

| `groupsale_key` | Extracted ticket base price |
|---|---:|
| `BHD_GROUPSALE_70K` | 70,000 VND |
| `BHD_GROUPSALE_80K` | 80,000 VND |
| `BHD_GROUPSALE_90K` | 90,000 VND |

The numeric value before `K` is extracted and multiplied by `1,000`.

```text
BHD ticket debit used = tickets_groupsales × extracted ticket base price
```

Example: ten tickets under `BHD_GROUPSALE_80K` deduct `10 × 80,000 = 800,000 VND` from the BHD debit balance.

#### BHD combo debit

Only the following BHD combo codes are currently included:

- `662613`
- `662614`

For this rule, `combo_base_price` in the concession data is treated as the customer selling price. The amount deducted from the BHD debit balance is 80% of that stored price.

```text
BHD combo debit used = qualifying combo quantity × combo_base_price × 80%
```

Under the current one-row-per-combo assumption, the row-level formula is:

```text
BHD combo debit used per row = combo_base_price × 0.8
```

Example: one qualifying combo with `combo_base_price = 90,000 VND` deducts `72,000 VND` from the BHD debit balance.

## 5. KPI definitions

| KPI | Definition |
|---|---|
| `usage_month` | First calendar date of the booking month, generated with `DATE_TRUNC(booking_date, MONTH)`. |
| `merchant` | Normalized cinema merchant derived from the Group Sale key or `merchant_name`. |
| `usage_type` | `TICKET` or `COMBO`. |
| `groupsale_key` | Original ticket Group Sale key or a generated combo usage key. |
| `trans` | Number of distinct `core_tran_id` values within the month and usage key. |
| `qty_used` | Tickets: sum of `tickets_groupsales`. Combos: count of qualifying combo rows. |
| `debit_used` | BHD only: monetary amount deducted for eligible tickets and combos. |
| `cumulative_qty_used` | Running total quantity by merchant, usage type, and Group Sale key. |
| `cumulative_debit_used` | Running BHD debit usage by usage type and Group Sale key. |

Ticket and combo quantities must not be added together into a single physical quantity KPI. For BHD, `debit_used` is the controlling usage measure; `qty_used` is supporting operational information.

## 6. Monthly usage SQL template

The following BigQuery template implements the rules above. It preserves monthly quantities for all merchants and adds the BHD debit calculation.

```sql
DECLARE start_date DATE DEFAULT DATE '2026-01-01';
DECLARE end_date   DATE DEFAULT DATE '2026-08-14';

WITH groupsale_base AS (
    SELECT
        booking_date,
        core_tran_id,
        groupsale_key,
        COALESCE(tickets_groupsales, 0) AS qty_used,

        CASE
            WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'LOTTE')
                THEN 'Lotte'
            WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'BHD')
                THEN 'BHD'
            WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'BETA')
                THEN 'Beta'
            WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'GLX')
                THEN 'Galaxy'
            WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'CGV')
                THEN 'CGV'
            ELSE 'Unknown'
        END AS merchant,

        CASE
            WHEN REGEXP_CONTAINS(
                UPPER(groupsale_key),
                r'BHD_GROUPSALE_\d+K'
            )
            THEN SAFE_CAST(
                REGEXP_EXTRACT(
                    UPPER(groupsale_key),
                    r'BHD_GROUPSALE_(\d+)K'
                ) AS INT64
            ) * 1000
        END AS ticket_base_price

    FROM `project-5400504384186300846.MBI_DA.CINEMA_FACT_BOOKING_GROUPSALE_V2`
    WHERE booking_date BETWEEN start_date AND end_date
        AND groupsale_key IS NOT NULL
),

ticket_monthly_usage AS (
    SELECT
        DATE_TRUNC(booking_date, MONTH) AS usage_month,
        merchant,
        'TICKET' AS usage_type,
        groupsale_key,
        COUNT(DISTINCT core_tran_id) AS trans,
        SUM(qty_used) AS qty_used,

        CASE
            WHEN merchant = 'BHD'
            THEN SUM(
                CAST(qty_used AS NUMERIC)
                * CAST(ticket_base_price AS NUMERIC)
            )
        END AS debit_used

    FROM groupsale_base
    GROUP BY
        usage_month,
        merchant,
        usage_type,
        groupsale_key
),

combo_base AS (
    SELECT
        booking_date,
        core_tran_id,

        CASE
            WHEN UPPER(merchant_name) LIKE '%BHD%' THEN 'BHD'
            WHEN UPPER(merchant_name) LIKE '%BETA%' THEN 'Beta'
        END AS merchant,

        CAST(combo_code AS STRING) AS combo_code,
        combo_base_price

    FROM `project-5400504384186300846.MBI_DA.CINEMA_FACT_CONCESSION_INAPP_V2`
    WHERE booking_date BETWEEN start_date AND end_date
        AND combo_name IS NOT NULL
        AND TRIM(combo_name) != ''
        AND (
            (
                UPPER(merchant_name) LIKE '%BHD%'
                AND CAST(combo_code AS STRING) IN (
                    '662613',
                    '662614'
                )
            )
            OR
            (
                UPPER(merchant_name) LIKE '%BETA%'
                AND CAST(combo_code AS STRING) IN (
                    'COMBO030158-09',
                    'COMBO030159-09'
                )
            )
        )
),

combo_monthly_usage AS (
    SELECT
        DATE_TRUNC(booking_date, MONTH) AS usage_month,
        merchant,
        'COMBO' AS usage_type,

        CONCAT(
            UPPER(merchant),
            '_COMBO_',
            combo_code
        ) AS groupsale_key,

        COUNT(DISTINCT core_tran_id) AS trans,
        COUNT(*) AS qty_used,

        CASE
            WHEN merchant = 'BHD'
            THEN SUM(
                CAST(combo_base_price AS NUMERIC) * 0.8
            )
        END AS debit_used

    FROM combo_base
    GROUP BY
        usage_month,
        merchant,
        usage_type,
        groupsale_key
),

combined_usage AS (
    SELECT * FROM ticket_monthly_usage

    UNION ALL

    SELECT * FROM combo_monthly_usage
)

SELECT
    usage_month,
    merchant,
    usage_type,
    groupsale_key,
    trans,
    qty_used,
    debit_used,

    SUM(qty_used) OVER (
        PARTITION BY
            merchant,
            usage_type,
            groupsale_key
        ORDER BY usage_month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_qty_used,

    CASE
        WHEN merchant = 'BHD'
        THEN SUM(COALESCE(debit_used, 0)) OVER (
            PARTITION BY
                merchant,
                usage_type,
                groupsale_key
            ORDER BY usage_month
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    END AS cumulative_debit_used

FROM combined_usage
ORDER BY
    usage_month,
    merchant,
    usage_type,
    groupsale_key;
```

## 7. Validation requirements

Before using the output for debit reconciliation or inventory control, validate the following assumptions:

- Each qualifying row in `CINEMA_FACT_CONCESSION_INAPP_V2` represents exactly one combo. If a dedicated quantity field exists, replace `COUNT(*)` with the sum of that field.
- `combo_base_price` represents the customer selling price to which the 80% BHD debit rule must be applied.
- Every BHD ticket Group Sale key follows the format `BHD_GROUPSALE_<amount>K`.
- Refunded, cancelled, failed, or reversed transactions have either already been excluded from the source tables or must be filtered using an agreed transaction-status rule.
- A transaction should be counted only once within a merchant, usage type, Group Sale key, and month.
- The reporting end date is inclusive. With `end_date = DATE '2026-08-14'`, August 2026 is a partial month.

## 8. Expected interpretation

| Merchant and product | Primary usage KPI | Supporting KPI |
|---|---|---|
| Beta tickets | `qty_used` in tickets | `trans` |
| Beta combos | `qty_used` in combos | `trans` |
| Lotte tickets | `qty_used` in tickets | `trans` |
| Galaxy tickets | `qty_used` in tickets | `trans` |
| CGV tickets | `qty_used` in tickets | `trans` |
| BHD tickets | `debit_used` in VND | `qty_used`, `trans` |
| BHD combos | `debit_used` in VND | `qty_used`, `trans` |

The resulting dataset provides the usage layer required for later inventory and depletion forecasting. Those later calculations should consume these normalized quantities and BHD debit amounts rather than reinterpreting the raw transaction tables.
