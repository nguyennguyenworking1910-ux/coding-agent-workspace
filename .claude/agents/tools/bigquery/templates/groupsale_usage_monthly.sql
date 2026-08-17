-- description: Monthly Group Sale usage by merchant, usage type, and Group Sale key.
--   Implements groupsale_usage_rules.md section 6, with the DECLARE'd dates replaced by
--   bound parameters so the reporting window comes from the request. Ticket usage is
--   aggregated from CINEMA_FACT_BOOKING_GROUPSALE_V2 and eligible BHD/Beta combo usage
--   from CINEMA_FACT_CONCESSION_INAPP_V2; the two grains are aggregated independently and
--   then UNION ALL'd, never joined. Pass null for anything the request did not mention.
-- params:
--   merchant: STRING - Beta, Lotte, Galaxy, CGV, BHD, or Unknown; null for all
--   usage_type: STRING - TICKET or COMBO; null for both
--   start_date: STRING - YYYY-MM-DD, inclusive; null defaults to 2026-01-01
--   end_date: STRING - YYYY-MM-DD, inclusive; null defaults to today

WITH request AS (
  -- Normalise the two filter values once. NULL survives every function here, which is
  -- what keeps "not mentioned in the request" distinct from "matched nothing".
  SELECT
    LOWER(TRIM(REGEXP_REPLACE(@merchant, r'\s+', ' '))) AS merchant_input,
    UPPER(TRIM(@usage_type))                            AS usage_type_input
),

guard AS (
  -- A filter value that matches no merchant or usage type must fail the query. Returning
  -- zero rows instead would be read as "no usage", which is the one wrong answer that
  -- looks like a right one.
  SELECT
    IF(
      (SELECT merchant_input FROM request) IS NULL
        OR (SELECT merchant_input FROM request)
             IN ('beta', 'lotte', 'galaxy', 'cgv', 'bhd', 'unknown'),
      TRUE,
      ERROR(
        'Unknown merchant: ' || IFNULL(@merchant, 'NULL') ||
        '. Expected Beta, Lotte, Galaxy, CGV, BHD, or Unknown (to review unmapped keys).'
      )
    ) AS merchant_ok,
    IF(
      (SELECT usage_type_input FROM request) IS NULL
        OR (SELECT usage_type_input FROM request) IN ('TICKET', 'COMBO'),
      TRUE,
      ERROR(
        'Unknown usage_type: ' || IFNULL(@usage_type, 'NULL') ||
        '. Expected TICKET or COMBO.'
      )
    ) AS usage_type_ok
),

groupsale_base AS (
  SELECT
    booking_date,
    core_tran_id,
    groupsale_key,
    COALESCE(tickets_groupsales, 0) AS qty_used,

    -- Merchant rules: groupsale_usage_rules.md section 3. First match wins.
    CASE
      WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'LOTTE') THEN 'Lotte'
      WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'BHD')   THEN 'BHD'
      WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'BETA')  THEN 'Beta'
      WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'GLX')   THEN 'Galaxy'
      WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'CGV')   THEN 'CGV'
      ELSE 'Unknown'
    END AS merchant,

    -- BHD ticket base price, encoded in the key as BHD_GROUPSALE_<amount>K.
    CASE
      WHEN REGEXP_CONTAINS(UPPER(groupsale_key), r'BHD_GROUPSALE_\d+K')
      THEN SAFE_CAST(
             REGEXP_EXTRACT(UPPER(groupsale_key), r'BHD_GROUPSALE_(\d+)K') AS INT64
           ) * 1000
    END AS ticket_base_price

  FROM `project-5400504384186300846.MBI_DA.CINEMA_FACT_BOOKING_GROUPSALE_V2`
  -- Bounds are written inline, not joined in from a CTE, so BigQuery can still prune on
  -- booking_date. PARSE_DATE yields NULL for a null param (so the default applies) and
  -- fails loudly on a malformed one.
  WHERE booking_date BETWEEN IFNULL(PARSE_DATE('%Y-%m-%d', @start_date), DATE '2026-01-01')
                         AND IFNULL(PARSE_DATE('%Y-%m-%d', @end_date), CURRENT_DATE())
    AND groupsale_key IS NOT NULL
    -- Lets BigQuery skip this table entirely when only combos were asked for.
    AND (@usage_type IS NULL OR UPPER(TRIM(@usage_type)) = 'TICKET')
),

ticket_monthly_usage AS (
  SELECT
    DATE_TRUNC(booking_date, MONTH)    AS usage_month,
    merchant,
    'TICKET'                           AS usage_type,
    groupsale_key,
    COUNT(DISTINCT core_tran_id)       AS trans,
    SUM(qty_used)                      AS qty_used,

    -- BHD is debit-controlled; every other merchant is quantity-controlled and carries a
    -- NULL debit rather than a zero, so the two can never be summed by accident.
    CASE
      WHEN merchant = 'BHD'
      THEN SUM(CAST(qty_used AS NUMERIC) * CAST(ticket_base_price AS NUMERIC))
    END AS debit_used

  FROM groupsale_base
  GROUP BY usage_month, merchant, usage_type, groupsale_key
),

combo_base AS (
  SELECT
    booking_date,
    core_tran_id,

    CASE
      WHEN UPPER(merchant_name) LIKE '%BHD%'  THEN 'BHD'
      WHEN UPPER(merchant_name) LIKE '%BETA%' THEN 'Beta'
    END AS merchant,

    CAST(combo_code AS STRING) AS combo_code,
    combo_base_price

  FROM `project-5400504384186300846.MBI_DA.CINEMA_FACT_CONCESSION_INAPP_V2`
  WHERE booking_date BETWEEN IFNULL(PARSE_DATE('%Y-%m-%d', @start_date), DATE '2026-01-01')
                         AND IFNULL(PARSE_DATE('%Y-%m-%d', @end_date), CURRENT_DATE())
    AND combo_name IS NOT NULL
    AND TRIM(combo_name) != ''
    -- Eligible combo codes only: groupsale_usage_rules.md sections 4.1 and 4.5.
    AND (
      (UPPER(merchant_name) LIKE '%BHD%'
        AND CAST(combo_code AS STRING) IN ('662613', '662614'))
      OR
      (UPPER(merchant_name) LIKE '%BETA%'
        AND CAST(combo_code AS STRING) IN ('COMBO030158-09', 'COMBO030159-09'))
    )
    -- Skip this table when only tickets were asked for, or when the merchant asked about
    -- has no Group Sale combos at all.
    AND (@usage_type IS NULL OR UPPER(TRIM(@usage_type)) = 'COMBO')
    AND (@merchant IS NULL OR LOWER(TRIM(@merchant)) IN ('bhd', 'beta'))
),

combo_monthly_usage AS (
  SELECT
    DATE_TRUNC(booking_date, MONTH)                        AS usage_month,
    merchant,
    'COMBO'                                                 AS usage_type,
    CONCAT(UPPER(merchant), '_COMBO_', combo_code)          AS groupsale_key,
    -- CORE_TRAN_ID is FLOAT64 in this table and INT64 in the booking table; cast to an
    -- exact type before counting distinct values (schemas doc section 8).
    COUNT(DISTINCT CAST(core_tran_id AS INT64))             AS trans,
    COUNT(*)                                                AS qty_used,

    CASE
      WHEN merchant = 'BHD'
      -- NUMERIC '0.8' rather than the float 0.8: this is a VND money column, and a
      -- NUMERIC * FLOAT64 product would come back as FLOAT64 and also disagree with the
      -- ticket branch's type across the UNION ALL.
      THEN SUM(CAST(combo_base_price AS NUMERIC) * NUMERIC '0.8')
    END AS debit_used

  FROM combo_base
  GROUP BY usage_month, merchant, usage_type, groupsale_key
),

combined_usage AS (
  SELECT * FROM ticket_monthly_usage
  UNION ALL
  SELECT * FROM combo_monthly_usage
)

SELECT
  u.usage_month,
  u.merchant,
  u.usage_type,
  u.groupsale_key,
  u.trans,
  u.qty_used,
  u.debit_used,

  -- Cumulative totals run across the months inside the requested window only, so a
  -- narrow window is not a lifetime-to-date figure.
  SUM(u.qty_used) OVER (
    PARTITION BY u.merchant, u.usage_type, u.groupsale_key
    ORDER BY u.usage_month
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS cumulative_qty_used,

  CASE
    WHEN u.merchant = 'BHD'
    THEN SUM(COALESCE(u.debit_used, NUMERIC '0')) OVER (
           PARTITION BY u.merchant, u.usage_type, u.groupsale_key
           ORDER BY u.usage_month
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
         )
  END AS cumulative_debit_used

FROM combined_usage AS u
CROSS JOIN guard AS g
WHERE g.merchant_ok
  AND g.usage_type_ok
  -- Both filters partition-align with the window functions above, so filtering here does
  -- not distort a cumulative total.
  AND (@merchant IS NULL OR LOWER(u.merchant) = (SELECT merchant_input FROM request))
  AND (@usage_type IS NULL OR u.usage_type = (SELECT usage_type_input FROM request))
ORDER BY u.usage_month, u.merchant, u.usage_type, u.groupsale_key
