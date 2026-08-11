#!/usr/bin/env python3
"""Run BigQuery `.sql` templates from a shell, outside a Claude Code session.

Usage:
    python .claude/bq_query.py --list
    python .claude/bq_query.py daily_counts --param start_date=2026-08-01 --param end_date=2026-08-07
    python .claude/bq_query.py daily_counts --param region:STRING=APAC --dry-run
    python .claude/bq_query.py daily_counts --param "statuses[]=paid,refunded" --format json

Adding a query needs no code: drop a `.sql` file into
.claude/agents/tools/bigquery/templates/ and it shows up in --list.

One-time setup (no local credentials needed) - see
.claude/documents/BIGQUERY_INTEGRATION.md:
    gcloud auth application-default login
"""

import argparse
import csv
import datetime
import decimal
import importlib.util
import json
import sys
from pathlib import Path

_CLAUDE_DIR = Path(__file__).resolve().parent

EXIT_OK = 0
EXIT_FAILED = 1
# argparse already exits 2 on a usage error; reuse it for our own input errors.
EXIT_USAGE = 2

# How wide a single cell may be in --format table before it is elided.
MAX_CELL_WIDTH = 60


def _load_claude_package():
    """Make this package importable as `claude`.

    The directory is named `.claude`, which is not a valid Python module name, so it
    can never be found on sys.path. Bind the existing package to the importable
    alias `claude` instead; submodules (`claude.agents`, `claude.clients`, ...) then
    resolve normally through submodule_search_locations.
    """
    if "claude" in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        "claude",
        _CLAUDE_DIR / "__init__.py",
        submodule_search_locations=[str(_CLAUDE_DIR)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"Could not load the agent package from {_CLAUDE_DIR}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so intra-package imports resolve during execution.
    sys.modules["claude"] = module
    spec.loader.exec_module(module)


_load_claude_package()

from claude.agents.tools import bigquery as bq_tools
from claude.agents.tools.bigquery import TemplateError
from claude.clients import config


# --- parameter parsing ---

# CLI values arrive as text, but BigQuery binds typed parameters: a STRING compared
# against a DATE column is an error, not a coercion. So a type is chosen per value,
# in this order: an explicit `name:TYPE=value`, then the template header's declared
# type, then inference from the literal.
_TYPE_CASTS = {
    "STRING": str,
    "BOOL": lambda v: _parse_bool(v),
    "BOOLEAN": lambda v: _parse_bool(v),
    "INT64": int,
    "INT": int,
    "INTEGER": int,
    "FLOAT64": float,
    "FLOAT": float,
    "NUMERIC": decimal.Decimal,
    "BIGNUMERIC": decimal.Decimal,
    "DECIMAL": decimal.Decimal,
    "DATE": lambda v: datetime.date.fromisoformat(v),
    "DATETIME": lambda v: datetime.datetime.fromisoformat(v),
    "TIMESTAMP": lambda v: _parse_timestamp(v),
    "TIME": lambda v: datetime.time.fromisoformat(v),
}


def _parse_bool(text: str) -> bool:
    """Parse a CLI boolean, rejecting anything ambiguous."""
    lowered = text.strip().lower()
    if lowered in ("true", "t", "yes", "y", "1"):
        return True
    if lowered in ("false", "f", "no", "n", "0"):
        return False
    raise ValueError(f"'{text}' is not a boolean (use true/false)")


def _parse_timestamp(text: str) -> datetime.datetime:
    """Parse an ISO timestamp, defaulting a missing zone to UTC.

    A TIMESTAMP is a point in time, so a naive value would be bound as DATETIME by
    type inference; attaching UTC keeps the declared type honest.
    """
    parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _infer_value(text: str):
    """Guess a Python type for a bare CLI value."""
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in ("null", "none", ""):
        return None
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        pass
    for parse in (datetime.date.fromisoformat, _parse_timestamp):
        try:
            return parse(stripped)
        except ValueError:
            continue
    return stripped


def _cast_value(text: str, declared_type):
    """Convert one CLI value, honouring a declared BigQuery type when there is one."""
    if declared_type:
        cast = _TYPE_CASTS.get(declared_type.upper())
        if cast is None:
            raise TemplateError(
                f"Unknown parameter type '{declared_type}'. Known types: "
                f"{', '.join(sorted(_TYPE_CASTS))}"
            )
        if text.strip().lower() in ("null", "none"):
            return None
        try:
            return cast(text)
        except (ValueError, decimal.InvalidOperation) as e:
            raise TemplateError(f"Value '{text}' is not a valid {declared_type}: {e}")
    return _infer_value(text)


def _declared_type(param_docs: dict, name: str):
    """The BigQuery type a template header declares for a parameter, if any.

    A header entry reads `name: DATE - first day`, so the type is the first token;
    anything unrecognised (prose, `ARRAY<STRING>`) is ignored and inference applies.
    """
    doc = param_docs.get(name)
    if not doc:
        return None
    token = doc.strip().split()[0].strip("-,").upper()
    return token if token in _TYPE_CASTS else None


def parse_params(raw_params, param_docs):
    """Parse `--param` arguments into a plain dict of Python values.

    Accepted forms:
        key=value           type inferred, or taken from the template header
        key:TYPE=value      explicit BigQuery type
        key[]=a,b,c         array of values (each parsed as above)

    Args:
        raw_params: The raw `key=value` strings from the command line
        param_docs: `param_docs` from the template description, may be empty

    Returns:
        Dict of parameter name to Python value
    """
    params = {}
    for item in raw_params or []:
        if "=" not in item:
            raise TemplateError(
                f"Bad --param '{item}'. Expected key=value (or key:TYPE=value)."
            )
        key, raw_value = item.split("=", 1)
        key = key.strip()

        declared = None
        if ":" in key:
            key, declared = (part.strip() for part in key.split(":", 1))

        is_array = key.endswith("[]")
        if is_array:
            key = key[:-2].strip()

        if not bq_tools.is_valid_param_name(key):
            raise TemplateError(
                f"Bad --param name '{key}'. Use the plain '@name' from the template."
            )
        if key in params:
            raise TemplateError(f"--param {key} was given more than once.")

        declared = declared or _declared_type(param_docs, key)
        if is_array:
            params[key] = [
                _cast_value(part, declared) for part in raw_value.split(",") if part != ""
            ]
        else:
            params[key] = _cast_value(raw_value, declared)
    return params


# --- output ---

def print_template_list() -> int:
    """List every available template with its description and required params."""
    described = bq_tools.describe_templates()
    directory = bq_tools.template_dir()

    print("\n" + "=" * 70)
    print(f"BIGQUERY TEMPLATES ({len(described)})")
    print("=" * 70)
    print(f"Directory: {directory}")

    if not described:
        print("\nNo templates yet.")
        print(f"Add one by dropping a .sql file into {directory} - for example:")
        print("    SELECT 1 AS n WHERE @flag IS NOT NULL")
        print("Every @name in the file becomes a required --param.")
        print("\n" + "=" * 70 + "\n")
        return EXIT_OK

    for info in described:
        print(f"\n{info['name']}")
        if info["description"]:
            print(f"   {info['description']}")
        if info["params"]:
            print("   Params:")
            for name in info["params"]:
                doc = info["param_docs"].get(name)
                print(f"     @{name}" + (f" - {doc}" if doc else ""))
        else:
            print("   Params: (none)")
        print(f"   Run: python .claude/bq_query.py {info['name']}" + "".join(
            f" --param {name}=..." for name in info["params"]
        ))

    print("\n" + "=" * 70 + "\n")
    return EXIT_OK


def _cell(value) -> str:
    """Render one cell as single-line text, elided if it is very long."""
    if value is None:
        text = "NULL"
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, default=str)
    else:
        text = str(value)
    text = text.replace("\n", " ").replace("\r", " ")
    if len(text) > MAX_CELL_WIDTH:
        text = text[: MAX_CELL_WIDTH - 3] + "..."
    return text


def print_table(result) -> None:
    """Print rows as a fixed-width table."""
    fields = result.get("fields") or []
    rows = result.get("rows") or []

    if not fields:
        print("(no columns returned)")
        return

    widths = {f: len(f) for f in fields}
    rendered = []
    for row in rows:
        cells = {f: _cell(row.get(f)) for f in fields}
        for f in fields:
            widths[f] = max(widths[f], len(cells[f]))
        rendered.append(cells)

    header = "  ".join(f.ljust(widths[f]) for f in fields)
    print(header)
    print("  ".join("-" * widths[f] for f in fields))
    for cells in rendered:
        print("  ".join(cells[f].ljust(widths[f]) for f in fields))
    if not rendered:
        print("(0 rows)")


def print_csv(result) -> None:
    """Print rows as CSV on stdout."""
    fields = result.get("fields") or []
    writer = csv.DictWriter(
        sys.stdout, fieldnames=fields, lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    for row in result.get("rows") or []:
        writer.writerow(
            {
                f: json.dumps(row.get(f), default=str)
                if isinstance(row.get(f), (dict, list))
                else row.get(f)
                for f in fields
            }
        )


def print_result(result, output_format: str) -> bool:
    """Print a query result; return True when the query succeeded."""
    if not result.get("ok"):
        print("\n" + "=" * 70)
        print("QUERY FAILED")
        print("=" * 70)
        print(f"\n{result.get('error', 'Unknown error')}")
        if result.get("template"):
            print(f"\nTemplate: {result['template']}")
        print("\nSee .claude/documents/BIGQUERY_INTEGRATION.md for setup and "
              "troubleshooting.")
        print("\n" + "=" * 70 + "\n")
        return False

    if output_format == "json":
        print(json.dumps(result, indent=2, default=str))
        return True

    if result.get("dry_run"):
        print("\n" + "=" * 70)
        print("DRY RUN - nothing was executed")
        print("=" * 70)
        if result.get("template"):
            print(f"Template:        {result['template']}")
        print(f"Bytes to scan:   {result['bytes_processed']:,}")
        print(f"                 {result['gigabytes_processed']} GiB")
        print(f"Estimated cost:  USD {result['estimated_cost_usd']} "
              "(on-demand pricing, indicative only)")
        cap = result.get("max_bytes_billed")
        if cap:
            print(f"Cost guard:      {cap:,} bytes ({cap / 1024 ** 3:.2f} GiB)")
        else:
            print("Cost guard:      off")
        if not result.get("within_max_bytes_billed", True):
            print("\nThis query would be REFUSED by the cost guard. Narrow it, or "
                  "raise BIGQUERY_MAX_BYTES_BILLED.")
        if result.get("fields"):
            print(f"Columns:         {', '.join(result['fields'])}")
        print("\n" + "=" * 70 + "\n")
        return True

    if output_format == "csv":
        print_csv(result)
        return True

    print("")
    print_table(result)
    print("")
    print(f"Rows: {result['row_count']} of {result['total_rows']}"
          f"   Scanned: {result['gigabytes_processed']} GiB"
          f"   Cached: {'yes' if result.get('cache_hit') else 'no'}")
    if result.get("truncated"):
        print(f"TRUNCATED at the {result['row_limit']} row cap. Raise it with --limit "
              "(up to BIGQUERY_MAX_ROWS) or narrow the query.")
    print("")
    return True


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252, which cannot encode non-ASCII results."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - non-reconfigurable stream
            pass


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="python .claude/bq_query.py",
        description="Run a BigQuery .sql template with named parameters.",
        epilog=(
            "Add a query by dropping a .sql file into "
            f"{config.BIGQUERY_TEMPLATE_DIR} - no code change needed. "
            "See .claude/documents/BIGQUERY_INTEGRATION.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "template",
        nargs="?",
        help="Template name (the .sql file name, without the extension)",
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List the available templates and the params each one needs",
    )
    parser.add_argument(
        "-p", "--param",
        action="append",
        default=[],
        metavar="key=value",
        help="Bind a named parameter. Repeatable. Forms: key=value, "
             "key:TYPE=value, key[]=a,b,c",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the bytes the query would scan, without running it",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help=f"Row cap for this run (default and maximum: {config.BIGQUERY_MAX_ROWS})",
    )
    parser.add_argument(
        "--show-sql",
        action="store_true",
        help="Print the template SQL and exit, without running it",
    )
    return parser


def main():
    """Main entry point."""
    _force_utf8_stdout()

    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        sys.exit(print_template_list())

    if not args.template:
        parser.print_help()
        print("\nNo template given. Run with --list to see what is available.")
        sys.exit(EXIT_USAGE)

    try:
        described = bq_tools.describe_template(args.template)

        if args.show_sql:
            print(described["sql"])
            sys.exit(EXIT_OK)

        params = parse_params(args.param, described["param_docs"])
        # Validate before touching BigQuery, so a typo is a local error.
        bq_tools.validate_params(args.template, params)
    except TemplateError as e:
        print(f"\nError: {e}\n")
        sys.exit(EXIT_USAGE)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(EXIT_FAILED)

    try:
        result = bq_tools.run_template(
            args.template,
            params,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        succeeded = print_result(result, args.format)
        # Non-zero on failure so callers (slash commands, scripts) can branch on it.
        sys.exit(EXIT_OK if succeeded else EXIT_FAILED)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(EXIT_FAILED)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(EXIT_FAILED)


if __name__ == "__main__":
    main()
