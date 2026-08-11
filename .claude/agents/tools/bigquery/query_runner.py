"""Tool implementations for running BigQuery queries and templates.

Values never reach SQL as text. A caller passes a plain Python dict, this module
turns it into typed BigQuery query parameters (`@name` placeholders in the SQL), and
BigQuery binds them - so a template is not a format string and cannot be injected
into.

Two guards apply to everything here:
- `config.BIGQUERY_MAX_BYTES_BILLED` - BigQuery refuses the job if it would scan more
- `config.BIGQUERY_MAX_ROWS` - rows returned are capped, and `truncated` says so
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any, Dict, List, Mapping, Optional

from ....clients import config
from ....clients.bigquery_client import (
    BigQueryClient,
    BigQueryClientError,
    require_bigquery,
)
from . import templates
from .templates import TemplateError

# Global client instance; the connection itself is built lazily inside the client.
_bigquery_client: Optional[BigQueryClient] = None


def get_bigquery_client(
    project: Optional[str] = None,
    location: Optional[str] = None,
) -> BigQueryClient:
    """Get or create the global BigQuery client.

    Passing None defers to the client's config/env defaults.
    """
    global _bigquery_client
    if _bigquery_client is None:
        _bigquery_client = BigQueryClient(project=project, location=location)
    return _bigquery_client


# Python type -> BigQuery scalar type. bool is checked before int because
# `isinstance(True, int)` is true and BOOL is virtually never what an INT64 means.
def _scalar_type(value: Any) -> str:
    """The BigQuery scalar type to bind a Python value as."""
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT64"
    if isinstance(value, float):
        return "FLOAT64"
    if isinstance(value, decimal.Decimal):
        return "NUMERIC"
    if isinstance(value, datetime.datetime):
        # An aware datetime is a point in time (TIMESTAMP); a naive one is a
        # wall-clock reading (DATETIME).
        return "TIMESTAMP" if value.tzinfo is not None else "DATETIME"
    if isinstance(value, datetime.date):
        return "DATE"
    if isinstance(value, datetime.time):
        return "TIME"
    if isinstance(value, (bytes, bytearray)):
        return "BYTES"
    if isinstance(value, str):
        return "STRING"
    raise TemplateError(
        f"Cannot bind a value of type {type(value).__name__} as a query parameter. "
        "Supported: str, int, float, bool, Decimal, date, datetime, time, bytes, "
        "and lists of those."
    )


def build_query_parameters(params: Optional[Mapping[str, Any]] = None) -> List[Any]:
    """Turn a plain dict into typed BigQuery query parameters.

    Args:
        params: Mapping of parameter name to Python value. A list or tuple becomes
            an ArrayQueryParameter; None becomes a typed NULL.

    Returns:
        List of ScalarQueryParameter / ArrayQueryParameter objects
    """
    bigquery = require_bigquery()
    built: List[Any] = []

    for name, value in (params or {}).items():
        if not templates.is_valid_param_name(name):
            raise TemplateError(
                f"Invalid parameter name '{name}'. Names must be a plain identifier, "
                "matching the '@name' placeholder in the SQL."
            )

        if isinstance(value, (list, tuple, set)):
            items = [v for v in value]
            element_values = [v for v in items if v is not None]
            if not element_values:
                # An empty array has no type to infer, and guessing wrong produces a
                # confusing BigQuery type error further downstream.
                raise TemplateError(
                    f"Parameter '{name}' is an empty list, so its element type cannot "
                    "be inferred. Pass at least one value, or drop the parameter."
                )
            built.append(
                bigquery.ArrayQueryParameter(
                    name, _scalar_type(element_values[0]), items
                )
            )
            continue

        if value is None:
            # A NULL still needs a declared type; STRING is the safe default and
            # works for `@p IS NULL` style predicates.
            built.append(bigquery.ScalarQueryParameter(name, "STRING", None))
            continue

        built.append(bigquery.ScalarQueryParameter(name, _scalar_type(value), value))

    return built


def _row_limit(limit: Optional[int]) -> int:
    """The effective row cap: the caller's, bounded by the configured maximum."""
    configured = config.BIGQUERY_MAX_ROWS
    if limit is None:
        return configured
    limit = int(limit)
    if limit <= 0:
        raise TemplateError("limit must be a positive number of rows.")
    return min(limit, configured)


def run_sql(
    sql: str,
    params: Optional[Mapping[str, Any]] = None,
    *,
    limit: Optional[int] = None,
    dry_run: bool = False,
    timeout: Optional[float] = None,
    template: Optional[str] = None,
) -> Dict[str, Any]:
    """Run SQL with named parameters and return a structured result.

    Args:
        sql: Standard SQL using `@name` placeholders for every value
        params: Mapping of parameter name to Python value
        limit: Row cap for this call (bounded by config.BIGQUERY_MAX_ROWS)
        dry_run: Estimate bytes scanned instead of running the query
        timeout: Seconds to wait for the job
        template: Template name to record in the result, when there was one

    Returns:
        On success: dict with `ok`, `rows`, `row_count`, `total_rows`, `fields`,
        `schema`, `bytes_processed`, `truncated`, `row_limit`, `template`, `params`.
        On failure: dict with `ok` False and a human-readable `error`.
    """
    given = dict(params or {})
    result: Dict[str, Any] = {
        "ok": False,
        "template": template,
        "params": given,
        "dry_run": bool(dry_run),
    }

    try:
        query_parameters = build_query_parameters(given)
        client = get_bigquery_client()

        if dry_run:
            estimate = client.dry_run(sql, query_parameters)
            result.update(estimate)
            result["fields"] = [field["name"] for field in estimate.get("schema", [])]
            result["rows"] = []
            result["row_count"] = 0
            result["ok"] = True
            return result

        cap = _row_limit(limit)
        stats = client.run_query_with_stats(
            sql, query_parameters, timeout=timeout, max_results=cap
        )
        rows = stats["rows"]
        result.update(
            {
                "ok": True,
                "rows": rows,
                "row_count": len(rows),
                "total_rows": stats["total_rows"],
                "fields": [field["name"] for field in stats["schema"]],
                "schema": stats["schema"],
                "bytes_processed": stats["bytes_processed"],
                "gigabytes_processed": round(stats["bytes_processed"] / 1024**3, 4),
                "truncated": stats["total_rows"] > len(rows),
                "row_limit": cap,
                "cache_hit": stats["cache_hit"],
                "job_id": stats["job_id"],
            }
        )
        return result
    except (BigQueryClientError, TemplateError) as e:
        result["error"] = str(e)
        return result


def run_template(
    name: str,
    params: Optional[Mapping[str, Any]] = None,
    *,
    limit: Optional[int] = None,
    dry_run: bool = False,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Run a named `.sql` template with named parameters.

    Args:
        name: Template name (the file name in the templates directory, without `.sql`)
        params: Mapping of parameter name to Python value; must match the template's
            `@placeholders` exactly
        limit: Row cap for this call (bounded by config.BIGQUERY_MAX_ROWS)
        dry_run: Estimate bytes scanned instead of running the query
        timeout: Seconds to wait for the job

    Returns:
        Same structured result as `run_sql`, with `template` set
    """
    try:
        sql = templates.get_template(name)
        checked = templates.validate_params(name, params)
    except TemplateError as e:
        return {
            "ok": False,
            "template": name,
            "params": dict(params or {}),
            "dry_run": bool(dry_run),
            "error": str(e),
        }

    return run_sql(
        sql,
        checked,
        limit=limit,
        dry_run=dry_run,
        timeout=timeout,
        template=name,
    )


def list_datasets() -> Dict[str, Any]:
    """List the datasets visible in the configured project.

    Returns:
        Dict with `ok` and `datasets`, or `ok` False and an `error`
    """
    try:
        return {"ok": True, "datasets": get_bigquery_client().list_datasets()}
    except BigQueryClientError as e:
        return {"ok": False, "error": str(e)}


def list_tables(dataset: str) -> Dict[str, Any]:
    """List the tables and views in a dataset.

    Args:
        dataset: Dataset id, optionally qualified as `project.dataset`

    Returns:
        Dict with `ok`, `dataset`, and `tables`, or `ok` False and an `error`
    """
    try:
        return {
            "ok": True,
            "dataset": dataset,
            "tables": get_bigquery_client().list_tables(dataset),
        }
    except BigQueryClientError as e:
        return {"ok": False, "dataset": dataset, "error": str(e)}


def get_table_schema(dataset: str, table: str) -> Dict[str, Any]:
    """Describe the columns of a table or view.

    Args:
        dataset: Dataset id, optionally qualified as `project.dataset`
        table: Table or view name

    Returns:
        Dict with `ok` and `table` (name, counts, and fields), or `ok` False and an
        `error`
    """
    try:
        return {
            "ok": True,
            "table": get_bigquery_client().get_table_schema(dataset, table),
        }
    except BigQueryClientError as e:
        return {"ok": False, "error": str(e)}
