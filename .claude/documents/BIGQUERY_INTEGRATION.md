# BigQuery Integration

**Status:** Active
**Audience:** Anyone adding a query, and any agent that needs data

Run parameterized SQL against BigQuery from a shell, from an agent, or from `/solve`.
Queries live as plain `.sql` files, one per file. **Adding a query is a file drop, not a
code change.**

---

## What this is

| Piece | Path | Role |
|---|---|---|
| Client | `.claude/clients/bigquery_client.py` | `BigQueryClient` — auth, query execution, dry runs, schema discovery |
| Config | `.claude/clients/config.py` | `BIGQUERY_*` settings, resolved once from the environment |
| Tool | `.claude/agents/tools/bigquery/` | `BIGQUERY_TOOLS` — template loading, parameter binding, row caps |
| Templates | `.claude/agents/tools/bigquery/templates/*.sql` | **Your queries go here** |
| CLI | `.claude/bq_query.py` | `python .claude/bq_query.py <template> --param k=v` |

Data flow, following the one-way dependency rule in
[ARCHITECTURE.md](./ARCHITECTURE.md):

```
python .claude/bq_query.py daily_counts --param day=2026-08-01
    ↓
claude.agents.tools.bigquery  (templates.py + query_runner.py)
    ├─ loads templates/daily_counts.sql
    ├─ checks the @params in the SQL against what you passed
    └─ builds typed BigQuery query parameters from your values
    ↓
clients/bigquery_client.py  (gcloud ADC → bigquery.Client)
    ↓
BigQuery  → rows as plain dicts
```

**Values are never interpolated into SQL.** Every value is bound as a BigQuery named
query parameter (`@name`), so a template is not a format string and cannot be injected
into. There is deliberately no `{{table}}`-style identifier substitution: if you need a
different table, write a different template.

---

## Setup

### 1. Authenticate (one time)

```powershell
gcloud auth application-default login
```

That is the whole credential setup. Application Default Credentials already carry the
scope BigQuery needs, and no credential file is created in this repo. The exact
scoped form, if you prefer to be explicit:

```powershell
gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/cloud-platform
```

### 2. Point at a project

The client bills and runs queries against a project. It uses, in order:

1. `BIGQUERY_PROJECT` from the environment / `root .env`
2. the project gcloud ADC is configured with

So this is usually enough:

```powershell
gcloud config set project my-project-id
```

If the ADC project is not the one you want to query, set it explicitly instead — see
below.

### 3. Install the package

```powershell
pip install -r .claude/agents/requirements.txt
```

Everything imports fine without `google-cloud-bigquery`; you just get a clear
"package is not installed" message when you actually run a query. `--list` and
`--show-sql` work without it, since they only read files.

### Optional: service account

If ADC is unavailable (an unattended box, for example), drop a service-account key at
`.claude/clients/bigquery_service_account.json` or point `BIGQUERY_SERVICE_ACCOUNT` at
one. ADC is tried first; the file does **not** need to exist.

---

## Environment variables

All optional. Copy `root .env.example` to `root .env` and
uncomment what you need.

All variables are optional. Copy the root `.env.example` to `.env` and set
only what you need. The intent parser, RAG service, Calendar client,
BigQuery client, and Docker Compose all read the same root `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `BIGQUERY_PROJECT` | ADC's project | Project that queries run in and are billed to |
| `BIGQUERY_LOCATION` | `US` | Job location; must match where the datasets live (`EU`, `asia-southeast1`, …) |
| `BIGQUERY_SERVICE_ACCOUNT` | `bigquery_service_account.json` | Optional key file; relative paths resolve against `.claude/clients/` |
| `BIGQUERY_MAX_BYTES_BILLED` | `10737418240` (10 GiB) | Cost guard — BigQuery refuses a query that would scan more |
| `BIGQUERY_MAX_ROWS` | `1000` | Context guard — maximum rows returned to a caller |
| `BIGQUERY_TEMPLATE_DIR` | `.claude/agents/tools/bigquery/templates` | Where `.sql` templates are discovered |

For one shell session, in PowerShell:

```powershell
$env:BIGQUERY_PROJECT = "my-project-id"
$env:BIGQUERY_LOCATION = "asia-southeast1"
```

---

## How to add a query template

This is the whole workflow. There is no registration step and no code to touch.

### Step 1 — Create the file

Put a `.sql` file in `.claude/agents/tools/bigquery/templates/`. **The file name minus
`.sql` is the template name**, so `daily_orders.sql` becomes the template
`daily_orders`. Use `snake_case`.

### Step 2 — Write the SQL, with `@params` for every value

```sql
SELECT
  DATE(created_at) AS day,
  COUNT(*)         AS orders,
  SUM(amount)      AS revenue
FROM `my-project.group_sales.orders`
WHERE DATE(created_at) BETWEEN @start_date AND @end_date
  AND region = @region
GROUP BY day
ORDER BY day
```

Every `@name` in the file becomes a **required** parameter. Names are discovered
automatically; `@words` inside `--` comments, `/* */` blocks, and string literals are
ignored, as are `@@system_variables`.

### Step 3 — Optionally describe it

A leading `--` comment block gives the template a description and declares parameter
types. It is entirely optional — a bare `.sql` file with no comments works exactly the
same — but the types make the CLI easier to use (see Step 5).

```sql
-- description: Daily order count and revenue for one region.
-- params:
--   start_date: DATE - first day, inclusive
--   end_date: DATE - last day, inclusive
--   region: STRING - region code, e.g. APAC
```

### Step 4 — Confirm it was picked up

```powershell
python .claude/bq_query.py --list
```

```
daily_orders
   Daily order count and revenue for one region.
   Params:
     @start_date - DATE - first day, inclusive
     @end_date - DATE - last day, inclusive
     @region - STRING - region code, e.g. APAC
   Run: python .claude/bq_query.py daily_orders --param start_date=... --param end_date=... --param region=...
```

### Step 5 — Run it

```powershell
python .claude/bq_query.py daily_orders --param start_date=2026-08-01 --param end_date=2026-08-07 --param region=APAC
```

Check the cost first if the table is large:

```powershell
python .claude/bq_query.py daily_orders --param start_date=2026-08-01 --param end_date=2026-08-07 --param region=APAC --dry-run
```

That is all. Delete `templates/example_daily_counts.sql` once you have a real one —
it is a placeholder that points at a table which does not exist.

---

## Running a template from the CLI

```powershell
# What is available, and what each template needs
python .claude/bq_query.py --list

# Run one
python .claude/bq_query.py daily_orders --param start_date=2026-08-01 --param region=APAC

# Estimate the scan instead of running it
python .claude/bq_query.py daily_orders --param start_date=2026-08-01 --dry-run

# Output formats
python .claude/bq_query.py daily_orders --param region=APAC --format json
python .claude/bq_query.py daily_orders --param region=APAC --format csv > out.csv

# Raise the row cap for this run (still bounded by BIGQUERY_MAX_ROWS)
python .claude/bq_query.py daily_orders --param region=APAC --limit 500

# Print the SQL without running anything
python .claude/bq_query.py daily_orders --show-sql
```

### Parameter forms

| Form | Example | Result |
|---|---|---|
| `key=value` | `--param region=APAC` | Type from the template header, else inferred from the literal |
| `key:TYPE=value` | `--param day:STRING=2026-08-01` | Bound as exactly that BigQuery type |
| `key[]=a,b,c` | `--param "statuses[]=paid,refunded"` | `ARRAY` — each element parsed as above |
| `key=null` | `--param note=null` | `NULL` |

Types accepted after `:` are `STRING`, `BOOL`, `INT64`, `FLOAT64`, `NUMERIC`,
`BIGNUMERIC`, `DATE`, `DATETIME`, `TIMESTAMP`, `TIME` (plus the aliases `INT`,
`INTEGER`, `FLOAT`, `BOOLEAN`, `DECIMAL`).

**When no type is declared, it is inferred from the text**: `2026-08-01` becomes a
`DATE`, `42` an `INT64`, `1.5` a `FLOAT64`, `true` a `BOOL`, anything else a `STRING`.
This matters because BigQuery does not coerce a `STRING` into a `DATE` — if a column is
a `STRING` that happens to look like a date, declare it: `--param day:STRING=2026-08-01`,
or add `day: STRING` to the template header so you never have to think about it again.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Query ran (or the dry run reported an estimate) |
| `1` | The query failed — auth, permissions, bad SQL, missing package |
| `2` | Input problem — no template given, unknown template, bad or missing `--param` |

---

## How an agent uses the tool

Inside a Claude Code session, an agent normally just runs the CLI with `Bash`:

```powershell
python .claude/bq_query.py daily_orders --param start_date=2026-08-01 --format json
```

From Python (the standalone path), import the tool package — never the client
directly, and never `agents/` from `tools/`:

```python
from datetime import date
from claude.agents.tools.bigquery import BIGQUERY_TOOLS

BIGQUERY_TOOLS["list_templates"]()          # names, descriptions, required @params
BIGQUERY_TOOLS["describe_template"]("daily_orders")

result = BIGQUERY_TOOLS["run_template"](
    "daily_orders",
    {"start_date": date(2026, 8, 1), "end_date": date(2026, 8, 7), "region": "APAC"},
    limit=200,
)
if result["ok"]:
    print(result["row_count"], "of", result["total_rows"], "rows")
    for row in result["rows"]:
        ...
else:
    print(result["error"])       # already a human-readable message
```

Every tool returns a dict rather than raising, so an agent can report a failure instead
of crashing. A successful `run_template` / `run_sql` result carries:

| Key | Meaning |
|---|---|
| `ok` | `True` on success; on failure, `error` holds the message |
| `rows` | List of JSON-serializable dicts (dates → ISO strings, `NUMERIC` → float, `BYTES` → base64) |
| `row_count` / `total_rows` | Rows returned / rows the query actually produced |
| `truncated` / `row_limit` | Whether the row cap cut the result, and what the cap was |
| `fields` / `schema` | Column names / full column types |
| `bytes_processed` / `gigabytes_processed` | What the query scanned |
| `template` / `params` | What was run, for the audit trail |
| `cache_hit` / `job_id` | BigQuery job details |

Other tools: `run_sql(sql, params)` for ad-hoc SQL (same `@param` rules),
`list_datasets()`, `list_tables(dataset)`, `get_table_schema(dataset, table)` for
discovery.

---

## Safety caps

Two guards apply to every query, and both are deliberately conservative.

### Bytes billed — `BIGQUERY_MAX_BYTES_BILLED`

Default **10 GiB** (`10737418240` bytes, roughly USD 0.05 at on-demand pricing).
BigQuery refuses the job *before running it* if it would scan more, so a `SELECT *`
over a huge table fails fast instead of arriving on the bill. To change it:

```powershell
# .env
BIGQUERY_MAX_BYTES_BILLED=53687091200   # 50 GiB
```

A dry run deliberately ignores the cap so you always get a real estimate back; the
output tells you whether that estimate would clear the guard.

### Rows returned — `BIGQUERY_MAX_ROWS`

Default **1000 rows**. This stops a wide result set from flooding an agent's context.
Results are cut at the cap, and `truncated: true` plus a visible CLI warning say so —
truncation is never silent. `--limit N` lowers the cap for one run; it cannot raise it
above `BIGQUERY_MAX_ROWS`.

```powershell
# .env
BIGQUERY_MAX_ROWS=5000
```

Prefer aggregating in SQL over raising this. A template that returns 5000 rows is
usually a template that should have a `GROUP BY`.

---

## Troubleshooting

### `The google-cloud-bigquery package is not installed.`

```powershell
pip install -r .claude/agents/requirements.txt
```

Nothing here fails at import time on a missing SDK, so `--list` still works — only the
query itself is blocked.

### `No BigQuery credentials found.`

ADC is not set up:

```powershell
gcloud auth application-default login
```

If `gcloud` itself is missing, install the Google Cloud SDK
(<https://cloud.google.com/sdk/docs/install>), or use a service-account key via
`BIGQUERY_SERVICE_ACCOUNT`.

### `No BigQuery project id.`

Credentials resolved but no project did. Either:

```powershell
gcloud config set project my-project-id
```

or set `BIGQUERY_PROJECT=my-project-id` in `root .env`.

### `Permission denied on project '…' (403).`

The signed-in account needs `roles/bigquery.jobUser` on the project (to run a job) and
`roles/bigquery.dataViewer` on the dataset (to read it). Check who you actually are:

```powershell
gcloud auth list
gcloud config get-value project
```

Then re-authenticate as the right account with the command the error prints.

### `Not found … (404).`

Wrong dataset/table name, wrong project, or the wrong **location**: a job in `US`
cannot read an `EU` dataset. Confirm with

```powershell
python .claude/bq_query.py --list          # then check the SQL with --show-sql
```

and set `BIGQUERY_LOCATION` to match the data.

### `Query cancelled by the cost guard`

The query would scan more than `BIGQUERY_MAX_BYTES_BILLED`. Filter on the partition
column, select fewer columns, or raise the cap. Use `--dry-run` to see the number.

### `BigQuery rejected the query (400)`

A SQL error; BigQuery's own message follows and names the position. `--show-sql` prints
exactly what was sent. Remember that `@params` are values, never identifiers — you
cannot parameterize a table or column name.

### `Template '…' not found`

The error lists what *is* available. Check the file is in
`.claude/agents/tools/bigquery/templates/`, ends in `.sql`, and that you passed the
name without the extension. Template names are file names: no slashes, no `..`.

### `Parameter mismatch for template '…'`

The message lists exactly which parameters are missing or unused, and what the template
requires. This check runs locally, before BigQuery is contacted.

### A `DATE` column rejects your value

You passed a `STRING` where BigQuery wanted a temporal type, or the reverse. Declare
the type: `--param day:DATE=2026-08-01`, or add `day: DATE` to the template's `params:`
header.

### `Parameter '…' is an empty list`

An empty array has no element type to infer. Pass at least one value, or write a
template variant without that filter.

---

## Related documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — folder rules and the agents → tools → clients dependency direction
- [SETUP.md](./SETUP.md) — the Google Calendar side of `clients/config.py`
- [SCHEDULE_CLI.md](./SCHEDULE_CLI.md) — the other standalone CLI, same package-loading pattern

---

**Last Updated:** August 11, 2026
