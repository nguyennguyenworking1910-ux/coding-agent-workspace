"""BigQuery client for the query tools and the standalone `.claude/bq_query.py` path.

Credential resolution order:
1. gcloud ADC (Application Default Credentials) - the primary path
2. bigquery_service_account.json (only if the file happens to exist)

Step 1 is what lets this run with no credential files at all: one
`gcloud auth application-default login` and the client works. See
`config.BIGQUERY_ADC_LOGIN_COMMAND`. Unlike Calendar, plain ADC already carries the
scope BigQuery needs, so the usual failure is a missing project id or a missing IAM
role rather than a missing scope - both of which are translated into an actionable
message instead of surfacing raw.

The SDK is imported defensively: every module here must import cleanly with
`google-cloud-bigquery` absent, and complain only when a query is actually run.
"""

from __future__ import annotations

import base64
import datetime
import decimal
from typing import Any, Dict, List, Optional, Sequence

from . import config

try:
    from google.cloud import bigquery
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    from google.api_core import exceptions as api_exceptions
    BIGQUERY_AVAILABLE = True
except ImportError:
    BIGQUERY_AVAILABLE = False


MISSING_PACKAGE_MESSAGE = (
    "The google-cloud-bigquery package is not installed.\n"
    "Run: pip install -r .claude/agents/requirements.txt"
)

# On-demand analysis pricing, used only to turn a byte estimate into a number a
# human can react to. Not authoritative - flat-rate/editions billing differs.
USD_PER_TEBIBYTE = 5.0


class BigQueryClientError(RuntimeError):
    """A BigQuery call failed, with a message intended for a human or an agent."""


def require_bigquery():
    """Return the `google.cloud.bigquery` module, or raise with install guidance.

    Tools that need to build SDK objects (query parameters, for instance) go
    through this so a missing dependency is one clear error at call time rather
    than an ImportError at import time.
    """
    if not BIGQUERY_AVAILABLE:
        raise BigQueryClientError(MISSING_PACKAGE_MESSAGE)
    return bigquery


def _coerce_value(value: Any) -> Any:
    """Make a BigQuery cell JSON-serializable.

    Rows are destined for JSON, a terminal, or an agent's context, so exactness
    matters less than being printable: temporal types become ISO 8601 strings,
    NUMERIC becomes a float, and BYTES becomes base64 text.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, dict):
        return {k: _coerce_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_value(v) for v in value]
    # STRUCT rows and anything else the SDK invents: fall back to text.
    if hasattr(value, "items"):
        return {k: _coerce_value(v) for k, v in value.items()}
    return str(value)


def _schema_field(field) -> Dict[str, Any]:
    """Flatten one SchemaField into a plain dict, recursing into STRUCT fields."""
    described: Dict[str, Any] = {
        "name": field.name,
        "type": field.field_type,
        "mode": field.mode,
    }
    if field.description:
        described["description"] = field.description
    if getattr(field, "fields", None):
        described["fields"] = [_schema_field(f) for f in field.fields]
    return described


class BigQueryClient:
    """Client for BigQuery query and metadata operations.

    Credential resolution - tries in order:
    1. gcloud ADC (Application Default Credentials)
    2. bigquery_service_account.json, if present

    The underlying `bigquery.Client` is built lazily on first use, so constructing
    this class never touches the network and never fails on missing credentials.
    """

    SCOPES = config.BIGQUERY_SCOPES

    def __init__(
        self,
        project: Optional[str] = None,
        location: Optional[str] = None,
        max_bytes_billed: Optional[int] = None,
    ):
        """Initialize the BigQuery client.

        Args:
            project: Billing/query project (defaults to config.BIGQUERY_PROJECT / env,
                then to the project gcloud ADC is configured with)
            location: Job location (defaults to config.BIGQUERY_LOCATION / env)
            max_bytes_billed: Per-query scan cap in bytes (defaults to
                config.BIGQUERY_MAX_BYTES_BILLED)
        """
        self.project = project or config.BIGQUERY_PROJECT
        self.location = location or config.BIGQUERY_LOCATION
        self.max_bytes_billed = (
            max_bytes_billed
            if max_bytes_billed is not None
            else config.BIGQUERY_MAX_BYTES_BILLED
        )
        self._client = None
        # Which source produced credentials; used to tailor guidance when a call
        # is later rejected for permissions.
        self.auth_source: Optional[str] = None

    # --- credentials & connection ---

    def _get_credentials(self):
        """Get credentials and the project they imply, using ADC first."""
        if not BIGQUERY_AVAILABLE:
            raise BigQueryClientError(MISSING_PACKAGE_MESSAGE)

        # 1. gcloud ADC. The "no credential files needed" path; it also hands back
        # the quota project, which is what we use when BIGQUERY_PROJECT is unset.
        try:
            credentials, adc_project = google.auth.default(scopes=self.SCOPES)
            self.auth_source = "adc"
            return credentials, adc_project
        except DefaultCredentialsError:
            pass

        # 2. Service account key, for unattended runs where ADC is not set up.
        if config.BIGQUERY_SERVICE_ACCOUNT.exists():
            try:
                credentials = ServiceAccountCredentials.from_service_account_file(
                    str(config.BIGQUERY_SERVICE_ACCOUNT),
                    scopes=self.SCOPES,
                )
                self.auth_source = "service_account"
                return credentials, getattr(credentials, "project_id", None)
            except Exception as e:
                raise BigQueryClientError(
                    f"{config.BIGQUERY_SERVICE_ACCOUNT.name} could not be loaded: {e}"
                )

        raise BigQueryClientError(
            "No BigQuery credentials found.\n\n"
            "Credential resolution order (tried in this order):\n"
            "1. gcloud ADC - Application Default Credentials\n"
            f"2. {config.BIGQUERY_SERVICE_ACCOUNT} - Service account key (optional)\n\n"
            "Fix (no credential files needed):\n"
            f"  {config.BIGQUERY_ADC_LOGIN_COMMAND}\n\n"
            "See .claude/documents/BIGQUERY_INTEGRATION.md for details."
        )

    @property
    def client(self):
        """The underlying `bigquery.Client`, built on first use."""
        if self._client is None:
            credentials, adc_project = self._get_credentials()
            project = self.project or adc_project
            if not project:
                raise BigQueryClientError(
                    "No BigQuery project id.\n\n"
                    "The credentials resolved, but no project was found to bill and "
                    "run the query against. Set one:\n"
                    "  - BIGQUERY_PROJECT=my-project-id in the repository root .env\n"
                    "  - or: gcloud config set project my-project-id, then\n"
                    f"    {config.BIGQUERY_ADC_LOGIN_COMMAND}"
                )
            self.project = project
            try:
                self._client = bigquery.Client(
                    project=project,
                    credentials=credentials,
                    location=self.location,
                )
            except Exception as e:
                raise BigQueryClientError(f"BigQuery client initialization failed: {e}")
        return self._client

    # --- error rendering ---

    def _describe_error(self, exc: Exception) -> str:
        """Render an API error, expanding the common failures into a fix."""
        if isinstance(exc, BigQueryClientError):
            return str(exc)

        if BIGQUERY_AVAILABLE:
            if isinstance(exc, api_exceptions.Forbidden):
                return (
                    f"Permission denied on project '{self.project}' (403).\n"
                    f"{exc}\n"
                    "The account needs roles/bigquery.jobUser on the project and "
                    "roles/bigquery.dataViewer on the dataset.\n"
                    f"Signed in as: {self.auth_source or 'unknown'}. Re-authorize with:\n"
                    f"  {config.BIGQUERY_ADC_LOGIN_COMMAND}"
                )
            if isinstance(exc, api_exceptions.NotFound):
                return (
                    f"Not found in project '{self.project}' (404). Check the dataset "
                    f"and table names, and that BIGQUERY_LOCATION ('{self.location}') "
                    f"matches where the data lives.\n{exc}"
                )
            if isinstance(exc, api_exceptions.BadRequest):
                text = str(exc)
                if "maximum bytes billed" in text.lower():
                    return (
                        "Query cancelled by the cost guard: it would scan more than "
                        f"the {self.max_bytes_billed} byte cap "
                        f"({self.max_bytes_billed / 1024**3:.2f} GiB).\n"
                        "Narrow the query (filter on the partition column), or raise "
                        "BIGQUERY_MAX_BYTES_BILLED in the repository root .env.\n"
                        f"{text}"
                    )
                return f"BigQuery rejected the query (400):\n{text}"
        return str(exc)

    def _fail(self, exc: Exception) -> BigQueryClientError:
        """Wrap any exception as a BigQueryClientError with readable guidance."""
        return BigQueryClientError(self._describe_error(exc))

    # --- queries ---

    def _query_job_config(
        self,
        params: Optional[Sequence[Any]],
        *,
        dry_run: bool,
        max_bytes_billed: Optional[int],
    ):
        """Build a QueryJobConfig with parameters and the cost guard attached."""
        cap = self.max_bytes_billed if max_bytes_billed is None else max_bytes_billed
        job_config = bigquery.QueryJobConfig(
            query_parameters=list(params or []),
            dry_run=dry_run,
            use_query_cache=True,
        )
        # A dry run bills nothing, and setting the cap there would turn an estimate
        # into an error - which defeats the point of asking for the estimate.
        if not dry_run and cap:
            job_config.maximum_bytes_billed = int(cap)
        return job_config

    def run_query(
        self,
        sql: str,
        params: Optional[Sequence[Any]] = None,
        *,
        dry_run: bool = False,
        max_bytes_billed: Optional[int] = None,
        timeout: Optional[float] = None,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Run a query and return the rows as plain dicts.

        Args:
            sql: Standard SQL, using `@name` placeholders for any values
            params: Already-built query parameters (ScalarQueryParameter, ...)
            dry_run: Validate and estimate only; returns an empty list
            max_bytes_billed: Override the per-query scan cap
            timeout: Seconds to wait for the job
            max_results: Stop fetching after this many rows

        Returns:
            List of JSON-serializable row dicts (empty for a dry run)
        """
        return self.run_query_with_stats(
            sql,
            params,
            dry_run=dry_run,
            max_bytes_billed=max_bytes_billed,
            timeout=timeout,
            max_results=max_results,
        )["rows"]

    def run_query_with_stats(
        self,
        sql: str,
        params: Optional[Sequence[Any]] = None,
        *,
        dry_run: bool = False,
        max_bytes_billed: Optional[int] = None,
        timeout: Optional[float] = None,
        max_results: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run a query and return the rows plus the job statistics.

        Same arguments as `run_query`. Callers that need to report cost or detect a
        truncated result use this; `run_query` is the shorthand for "just the rows".

        Returns:
            Dict with `rows`, `total_rows` (the full result size, before any
            `max_results` cut), `schema`, `bytes_processed`, `cache_hit`, and `job_id`
        """
        if not sql or not sql.strip():
            raise BigQueryClientError("No SQL to run (the query text is empty).")

        try:
            client = self.client
            job_config = self._query_job_config(
                params, dry_run=dry_run, max_bytes_billed=max_bytes_billed
            )
            job = client.query(sql, job_config=job_config, location=self.location)

            if dry_run:
                # A dry-run job never executes, so there is no result set to fetch;
                # the statistics are populated on the job itself.
                return {
                    "rows": [],
                    "total_rows": 0,
                    "schema": [_schema_field(f) for f in (job.schema or [])],
                    "bytes_processed": int(job.total_bytes_processed or 0),
                    "cache_hit": False,
                    "job_id": job.job_id,
                }

            iterator = job.result(timeout=timeout, max_results=max_results)
            rows = [
                {key: _coerce_value(value) for key, value in dict(row).items()}
                for row in iterator
            ]
            total_rows = iterator.total_rows
            return {
                "rows": rows,
                "total_rows": int(total_rows) if total_rows is not None else len(rows),
                "schema": [_schema_field(f) for f in (iterator.schema or [])],
                "bytes_processed": int(job.total_bytes_processed or 0),
                "cache_hit": bool(job.cache_hit),
                "job_id": job.job_id,
            }
        except Exception as e:
            raise self._fail(e)

    def dry_run(
        self,
        sql: str,
        params: Optional[Sequence[Any]] = None,
    ) -> Dict[str, Any]:
        """Estimate what a query would cost, without executing it.

        Args:
            sql: Standard SQL, using `@name` placeholders for any values
            params: Already-built query parameters

        Returns:
            Dict with `bytes_processed`, `gigabytes_processed`, `estimated_cost_usd`,
            the `max_bytes_billed` cap, and `within_max_bytes_billed`
        """
        stats = self.run_query_with_stats(sql, params, dry_run=True)
        processed = stats["bytes_processed"]
        cap = self.max_bytes_billed
        return {
            "bytes_processed": processed,
            "gigabytes_processed": round(processed / 1024**3, 4),
            "estimated_cost_usd": round(processed / 1024**4 * USD_PER_TEBIBYTE, 4),
            "max_bytes_billed": cap,
            "within_max_bytes_billed": (not cap) or processed <= cap,
            "schema": stats["schema"],
        }

    # --- discovery ---

    def list_datasets(self) -> List[Dict[str, Any]]:
        """List the datasets visible in the project.

        Returns:
            List of dicts with `dataset_id`, `project`, and `location`
        """
        try:
            return [
                {
                    "dataset_id": dataset.dataset_id,
                    "project": dataset.project,
                    "location": getattr(dataset, "location", None),
                }
                for dataset in self.client.list_datasets()
            ]
        except Exception as e:
            raise self._fail(e)

    def list_tables(self, dataset: str) -> List[Dict[str, Any]]:
        """List the tables and views in a dataset.

        Args:
            dataset: Dataset id, optionally qualified as `project.dataset`

        Returns:
            List of dicts with `table_id`, `dataset_id`, and `type`
        """
        try:
            return [
                {
                    "table_id": table.table_id,
                    "dataset_id": table.dataset_id,
                    "type": table.table_type,
                }
                for table in self.client.list_tables(self._dataset_ref(dataset))
            ]
        except Exception as e:
            raise self._fail(e)

    def get_table_schema(self, dataset: str, table: str) -> Dict[str, Any]:
        """Describe a table's columns.

        Args:
            dataset: Dataset id, optionally qualified as `project.dataset`
            table: Table or view name

        Returns:
            Dict with the fully-qualified name, row/byte counts, and `fields`
        """
        try:
            reference = self.client.get_table(f"{self._dataset_ref(dataset)}.{table}")
            return {
                "project": reference.project,
                "dataset_id": reference.dataset_id,
                "table_id": reference.table_id,
                "full_name": f"{reference.project}.{reference.dataset_id}.{reference.table_id}",
                "type": reference.table_type,
                "num_rows": reference.num_rows,
                "num_bytes": reference.num_bytes,
                "description": reference.description,
                "fields": [_schema_field(f) for f in (reference.schema or [])],
            }
        except Exception as e:
            raise self._fail(e)

    def _dataset_ref(self, dataset: str) -> str:
        """Qualify a bare dataset id with the resolved project."""
        if not dataset or not dataset.strip():
            raise BigQueryClientError("No dataset given.")
        dataset = dataset.strip()
        # `client` resolves the project as a side effect, so read it afterwards.
        project = self.client.project
        return dataset if "." in dataset else f"{project}.{dataset}"
