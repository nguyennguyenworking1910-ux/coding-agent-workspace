# Group Sale Source Table Schemas

## 1. Purpose and scope

This document describes the two BigQuery source tables used for Group Sale usage measurement:

- `project-5400504384186300846.MBI_DA.CINEMA_FACT_BOOKING_GROUPSALE_V2`
- `project-5400504384186300846.MBI_DA.CINEMA_FACT_CONCESSION_INAPP_V2`

The booking table supplies Group Sale ticket usage. The concession table supplies eligible BHD and Beta combo usage. The source tables have different grains and should be aggregated separately before their results are combined.

BigQuery displays `INTEGER` as an alias of `INT64` and `FLOAT` as an alias of `FLOAT64`. All fields shown in the supplied schema screenshots are `NULLABLE`.

## 2. Table summary

| Table | Business purpose | Usage grain applied by the reporting query | Primary usage measure |
|---|---|---|---|
| `CINEMA_FACT_BOOKING_GROUPSALE_V2` | Stores Group Sale ticket booking facts. | Merchant, `groupsale_key`, and booking period. | `SUM(tickets_groupsales)` |
| `CINEMA_FACT_CONCESSION_INAPP_V2` | Stores in-app concession/combo booking facts. | Merchant, `combo_code`, and booking period. | `COUNT(*)` under the current one-row-per-combo assumption. |

## 3. `CINEMA_FACT_BOOKING_GROUPSALE_V2`

### 3.1 Fully qualified name

```text
project-5400504384186300846.MBI_DA.CINEMA_FACT_BOOKING_GROUPSALE_V2
```

### 3.2 Confirmed schema

| Field name | BigQuery type | Mode | Operational description | Group Sale usage relevance |
|---|---|---|---|---|
| `core_tran_id` | `INT64` | `NULLABLE` | Core transaction identifier. | Used by `COUNT(DISTINCT core_tran_id)` to calculate transaction count. |
| `booking_date` | `DATE` | `NULLABLE` | Booking date. | Used for reporting-period filters and monthly aggregation. |
| `extras` | `STRING` | `NULLABLE` | Additional source information stored as text. | Not currently used by the usage query. |
| `groupsale_key` | `STRING` | `NULLABLE` | Group Sale identifier containing the merchant prefix and, for BHD tickets, the ticket price. | Primary classification and usage-grouping field. |
| `tickets_groupsales` | `INT64` | `NULLABLE` | Number of Group Sale tickets applied to the transaction. | Summed to calculate ticket quantity used. |
| `total_amount_groupsale` | `INT64` | `NULLABLE` | Total Group Sale amount recorded for the row. | Available for amount reconciliation; not required for basic quantity measurement. |
| `amount_groupsale` | `FLOAT64` | `NULLABLE` | Group Sale amount recorded by the source. | Available for amount analysis; its exact unit semantics should be confirmed with the data owner. |
| `be_fee` | `FLOAT64` | `NULLABLE` | BE fee recorded for the transaction. | Not currently used by the usage query. |

The operational descriptions above are based on field names and the reporting rules supplied for this analysis. The BigQuery source schema itself does not contain field descriptions.

### 3.3 Fields used in the monthly usage query

```sql
SELECT
    booking_date,
    core_tran_id,
    groupsale_key,
    tickets_groupsales
FROM `project-5400504384186300846.MBI_DA.CINEMA_FACT_BOOKING_GROUPSALE_V2`;
```

### 3.4 Merchant classification from `groupsale_key`

| Value contained in `UPPER(groupsale_key)` | Normalized merchant |
|---|---|
| `LOTTE` | `Lotte` |
| `BHD` | `BHD` |
| `BETA` | `Beta` |
| `GLX` | `Galaxy` |
| `CGV` | `CGV` |
| No configured match | `Unknown` |

### 3.5 BHD ticket-price extraction

BHD ticket price is embedded in `groupsale_key` and extracted with the following expression:

```sql
SAFE_CAST(
    REGEXP_EXTRACT(
        UPPER(groupsale_key),
        r'BHD_GROUPSALE_(\d+)K'
    ) AS INT64
) * 1000
```

Examples:

| `groupsale_key` | Extracted price |
|---|---:|
| `BHD_GROUPSALE_70K` | 70,000 VND |
| `BHD_GROUPSALE_80K` | 80,000 VND |
| `BHD_GROUPSALE_90K` | 90,000 VND |

## 4. `CINEMA_FACT_CONCESSION_INAPP_V2`

### 4.1 Fully qualified name

```text
project-5400504384186300846.MBI_DA.CINEMA_FACT_CONCESSION_INAPP_V2
```

### 4.2 Confirmed and query-referenced schema

| Field name | BigQuery type | Mode | Evidence | Operational description | Group Sale usage relevance |
|---|---|---|---|---|---|
| `CORE_TRAN_ID` | `FLOAT64` | `NULLABLE` | Supplied BigQuery schema screenshot. | Core transaction identifier. | Used by `COUNT(DISTINCT CORE_TRAN_ID)` to calculate transaction count. |
| `BOOKING_DATE` | `DATE` | `NULLABLE` | Supplied BigQuery schema screenshot. | Booking date. | Used for date filters and monthly aggregation. |
| `DETAIL_AMOUNT` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Detailed amount information stored as text. | Not currently used. |
| `EXTRAS` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Additional source information stored as text. | Not currently used. |
| `ORIGINAL_AMOUNT` | `FLOAT64` | `NULLABLE` | Supplied BigQuery schema screenshot. | Original booking amount. | Not currently used. |
| `SEAT_AMOUNT` | `INT64` | `NULLABLE` | Supplied BigQuery schema screenshot. | Seat-related amount or count as defined by the source. | Not currently used; exact semantics require source confirmation. |
| `CONCESSION_ORI_AMOUNT` | `FLOAT64` | `NULLABLE` | Supplied BigQuery schema screenshot. | Original concession amount. | Available for reconciliation but not used by the current quantity rule. |
| `ERROR_CORE_CODE` | `FLOAT64` | `NULLABLE` | Supplied BigQuery schema screenshot. | Core-processing error code. | May support success/failure filtering after an approved rule is defined. |
| `ERROR_CORE_MESSAGE` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Core-processing error message. | May support transaction-quality review. |
| `CONCESSIONS` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Concession details stored as text. | Not currently parsed by the usage query. |
| `TOTAL_TICKET` | `FLOAT64` | `NULLABLE` | Supplied BigQuery schema screenshot. | Total ticket value or count as defined by the source. | Not used for combo quantity measurement. |
| `MERCHANT_NAME` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Cinema merchant name. | Identifies BHD and Beta combo records. |
| `SERVICE_CODE` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Source service identifier. | Not currently used. |
| `FILM_ID` | `INT64` | `NULLABLE` | Supplied BigQuery schema screenshot. | Film identifier. | Optional analysis dimension; not currently used. |
| `FILM_NAME` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Film name. | Optional analysis dimension; not currently used. |
| `SCHEDULE_TIME` | `DATETIME` | `NULLABLE` | Supplied BigQuery schema screenshot. | Scheduled show time. | Optional analysis dimension; not currently used. |
| `SEGMENT_BOOKING` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Booking segment or platform classification. | Optional reporting dimension; not currently used. |
| `COMBO_CODE` | `STRING` | `NULLABLE` | Referenced by the supplied working SQL and required by alphanumeric Beta codes. Verify through `INFORMATION_SCHEMA`. | Combo identifier. | Filters eligible BHD and Beta Group Sale combos and creates the synthetic combo usage key. |
| `COMBO_NAME` | `STRING` | `NULLABLE` | Supplied BigQuery schema screenshot. | Combo display name. | Used to exclude empty combo records and for descriptive reporting. |
| `COMBO_BASE_PRICE` | `INT64` | `NULLABLE` | Supplied BigQuery schema screenshot. | Combo price stored in the source data. | Used in the BHD debit calculation under the agreed 80% rule. |

Only the columns visible in the supplied screenshot or referenced by the supplied SQL are documented here. The table may contain additional columns below the visible screenshot area.

### 4.3 Fields used in the monthly usage query

```sql
SELECT
    booking_date,
    core_tran_id,
    merchant_name,
    combo_code,
    combo_name,
    combo_base_price
FROM `project-5400504384186300846.MBI_DA.CINEMA_FACT_CONCESSION_INAPP_V2`;
```

### 4.4 Eligible Group Sale combo codes

| Merchant | Eligible `combo_code` |
|---|---|
| BHD | `662613` |
| BHD | `662614` |
| Beta | `COMBO030158-09` |
| Beta | `COMBO030159-09` |

## 5. Relationship and aggregation rules

The two tables must not be joined directly before aggregation. A single booking transaction may correspond to multiple concession records, which can multiply ticket quantities if a row-level join is performed.

The safe reporting flow is:

1. Aggregate ticket usage from `CINEMA_FACT_BOOKING_GROUPSALE_V2` by month, merchant, and `groupsale_key`.
2. Aggregate combo usage from `CINEMA_FACT_CONCESSION_INAPP_V2` by month, merchant, and `combo_code`.
3. Normalize both outputs to a common reporting schema.
4. Combine the aggregated outputs with `UNION ALL`.

### 5.1 Normalized reporting schema

| Output field | BigQuery type | Derivation |
|---|---|---|
| `usage_month` | `DATE` | `DATE_TRUNC(booking_date, MONTH)` |
| `merchant` | `STRING` | Derived from `groupsale_key` for tickets or `merchant_name` for combos. |
| `usage_type` | `STRING` | Constant `TICKET` or `COMBO`. |
| `groupsale_key` | `STRING` | Original ticket key or generated combo key. |
| `trans` | `INT64` | `COUNT(DISTINCT core_tran_id)` |
| `qty_used` | `INT64` | Tickets: `SUM(tickets_groupsales)`; combos: `COUNT(*)`. |
| `debit_used` | `NUMERIC` | BHD ticket or combo monetary deduction; `NULL` for quantity-controlled merchants. |
| `cumulative_qty_used` | `INT64` | Running quantity by merchant, usage type, and key. |
| `cumulative_debit_used` | `NUMERIC` | Running BHD debit usage by usage type and key. |

## 6. Complete schema verification query

Run the following BigQuery query to retrieve the complete live schema for both tables, including columns not visible in the supplied screenshot:

```sql
SELECT
    table_name,
    ordinal_position,
    column_name,
    data_type,
    is_nullable,
    column_default,
    collation_name,
    policy_tags
FROM `project-5400504384186300846.MBI_DA.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN (
    'CINEMA_FACT_BOOKING_GROUPSALE_V2',
    'CINEMA_FACT_CONCESSION_INAPP_V2'
)
ORDER BY
    table_name,
    ordinal_position;
```

## 7. Data-quality checks

### 7.1 Unmapped ticket Group Sale keys

```sql
SELECT
    groupsale_key,
    COUNT(*) AS row_count,
    SUM(COALESCE(tickets_groupsales, 0)) AS qty_used
FROM `project-5400504384186300846.MBI_DA.CINEMA_FACT_BOOKING_GROUPSALE_V2`
WHERE groupsale_key IS NOT NULL
    AND NOT REGEXP_CONTAINS(
        UPPER(groupsale_key),
        r'LOTTE|BHD|BETA|GLX|CGV'
    )
GROUP BY groupsale_key
ORDER BY qty_used DESC;
```

### 7.2 Eligible combo-code availability

```sql
SELECT
    merchant_name,
    CAST(combo_code AS STRING) AS combo_code,
    combo_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT core_tran_id) AS trans
FROM `project-5400504384186300846.MBI_DA.CINEMA_FACT_CONCESSION_INAPP_V2`
WHERE CAST(combo_code AS STRING) IN (
    '662613',
    '662614',
    'COMBO030158-09',
    'COMBO030159-09'
)
GROUP BY
    merchant_name,
    combo_code,
    combo_name
ORDER BY row_count DESC;
```

## 8. Assumptions requiring confirmation

- One qualifying concession row represents one combo used. If a dedicated combo-quantity field exists, the usage query should sum that field instead of using `COUNT(*)`.
- `COMBO_BASE_PRICE` is the stored customer selling price used as the basis for the BHD 80% debit calculation.
- Failed, cancelled, refunded, or reversed transactions are either excluded upstream or require an additional approved filter.
- `CORE_TRAN_ID` is stored as `FLOAT64` in the concession table and `INT64` in the booking Group Sale table. Cast both to a common exact representation before cross-table reconciliation.
- The operational descriptions in this document are analytical interpretations; they are not source-system metadata unless explicitly stated.
