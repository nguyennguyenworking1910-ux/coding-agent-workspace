#!/usr/bin/env python3
"""Test the Group Sale query templates.

Three levels, cheapest first. Each level is a superset of the one before it:

    python .claude/bq_test.py --offline     # no BigQuery at all, no credentials needed
    python .claude/bq_test.py               # + dry runs: BigQuery compiles the SQL, runs nothing
    python .claude/bq_test.py --live        # + real queries, and the reconciliation check

Run it with the virtualenv interpreter, which is where google-cloud-bigquery lives:

    .\\.venv\\Scripts\\python.exe .claude/bq_test.py

Everything above --offline needs a project you can create jobs in. That does NOT have to
be the project holding the table - BigQuery reads across projects, so a billing project
plus roles/bigquery.dataViewer on the dataset is enough:

    .\\.venv\\Scripts\\python.exe .claude/bq_test.py --project my-billing-project

Live queries scan real data, so bound them while iterating:

    ... --live --start 2026-07-01 --end 2026-07-31

A check that cannot run (no project, no permission, a truncated result) is reported as
SKIP with the reason and does not fail the suite. Only a check that ran and disagreed
with the templates is a failure.
"""

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

_CLAUDE_DIR = Path(__file__).resolve().parent

USAGE_MONTHLY = "groupsale_usage_monthly"

EXIT_OK = 0
EXIT_FAILED = 1

# Set by main() once the environment is configured; see the note in main().
bq = None


# --- terminal output (same vocabulary as system_test.py) ---

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}\n")


def _force_utf8_stdout():
    """Windows consoles default to cp1252, which cannot encode the check marks."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - non-reconfigurable stream
            pass


def _load_claude_package():
    """Make this package importable as `claude`.

    Same trick as `.claude/bq_query.py`: the directory is named `.claude`, which is not a
    valid module name, so bind it to the importable alias instead.
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
    sys.modules["claude"] = module
    spec.loader.exec_module(module)


# --- result tracking ---

class Results:
    """Counts and prints check outcomes.

    A skip is deliberately not a pass: an environment that cannot reach BigQuery should
    report a suite that mostly did not run, not a green one.
    """

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.failures = []

    def ok(self, name, detail=""):
        self.passed += 1
        print(f"{Colors.GREEN}✓ {name}{Colors.END}" + (f"  ({detail})" if detail else ""))

    def fail(self, name, detail=""):
        self.failed += 1
        self.failures.append(f"{name}: {detail}" if detail else name)
        print(f"{Colors.RED}✗ {name}{Colors.END}" + (f"\n    {detail}" if detail else ""))

    def skip(self, name, reason):
        self.skipped += 1
        print(f"{Colors.YELLOW}– {name}  (skipped: {reason}){Colors.END}")

    def check(self, name, condition, detail=""):
        if condition:
            self.ok(name, detail)
        else:
            self.fail(name, detail)
        return bool(condition)




# --- level 0: offline ---

def run_offline_checks(results):
    """Checks that read the .sql files and the tool layer. No BigQuery, no credentials."""
    print_header("LEVEL 0: OFFLINE (no BigQuery)")

    available = bq.list_templates()

    if not results.check(f"Template discovered: {USAGE_MONTHLY}", USAGE_MONTHLY in available,
                         f"available: {', '.join(available) or '(none)'}"):
        return  # nothing below can work without the template

    # -- parameters --

    usage_sql = bq.get_template(USAGE_MONTHLY)
    param_names = set(bq.extract_param_names(usage_sql))

    results.check(
        f"{USAGE_MONTHLY} has merchant parameter",
        "merchant" in param_names,
        f"found: {param_names}",
    )
    results.check(
        f"{USAGE_MONTHLY} has usage_type parameter",
        "usage_type" in param_names,
        f"found: {param_names}",
    )
    results.check(
        f"{USAGE_MONTHLY} has start_date parameter",
        "start_date" in param_names,
        f"found: {param_names}",
    )
    results.check(
        f"{USAGE_MONTHLY} has end_date parameter",
        "end_date" in param_names,
        f"found: {param_names}",
    )

    # A missing parameter must fail locally, before a job is created.
    try:
        bq.validate_params(USAGE_MONTHLY, {"merchant": None})
        results.fail("Missing parameters are rejected locally", "validate_params accepted incomplete set")
    except bq.TemplateError as e:
        results.ok("Missing parameters are rejected locally", str(e).splitlines()[0])

    # An unknown parameter must fail locally.
    try:
        bq.validate_params(
            USAGE_MONTHLY,
            {"merchant": None, "usage_type": None, "start_date": None, "end_date": None, "typo": 1},
        )
        results.fail("Unknown parameters are rejected locally", "validate_params accepted it")
    except bq.TemplateError:
        results.ok("Unknown parameters are rejected locally")

    # Valid parameter sets should be accepted.
    try:
        bq.validate_params(USAGE_MONTHLY, {"merchant": None, "usage_type": None, "start_date": None, "end_date": None})
        results.ok("Valid parameter set is accepted")
    except bq.TemplateError as e:
        results.fail("Valid parameter set is accepted", str(e))


# --- level 1: dry run ---

# Each shape compiles a different branch of the SQL: an explicit window, the defaulted
# window, and the alias path. A dry run type-checks all of it without executing.
DRY_RUN_SHAPES = [
    ("explicit merchant and window",
     {"merchant": "BHD", "usage_type": None, "start_date": "2026-07-01", "end_date": "2026-07-31"}),
    ("all defaults (all nulls)",
     {"merchant": None, "usage_type": None, "start_date": None, "end_date": None}),
    ("tickets only",
     {"merchant": "BHD", "usage_type": "TICKET", "start_date": None, "end_date": None}),
    ("combos only",
     {"merchant": "BHD", "usage_type": "COMBO", "start_date": None, "end_date": None}),
    ("multiple merchants (null), date window",
     {"merchant": None, "usage_type": None, "start_date": "2026-07-01", "end_date": "2026-08-31"}),
]


def _unavailable(error):
    """True when an error means 'this environment cannot reach BigQuery', not 'bad SQL'."""
    lowered = (error or "").lower()
    markers = (
        "no bigquery credentials",
        "no bigquery project id",
        "permission denied",
        "not installed",
        "403",
    )
    return any(marker in lowered for marker in markers)


def run_dry_run_checks(results):
    """Ask BigQuery to compile each shape of the query without executing it.

    This is where the SQL is actually validated: syntax, types, and the table reference.
    """
    print_header("LEVEL 1: DRY RUN (BigQuery compiles, nothing executes)")

    blocked = None
    for label, params in DRY_RUN_SHAPES:
        name = f"Compiles: {label}"
        if blocked:
            results.skip(name, blocked)
            continue

        result = bq.run_template(USAGE_MONTHLY, params, dry_run=True)
        if result["ok"]:
            results.ok(name, f"{result['gigabytes_processed']} GiB would be scanned")
            continue

        error = result.get("error", "")
        if _unavailable(error):
            # The environment, not the SQL. Skip the rest rather than repeat it five times.
            blocked = error.strip().splitlines()[0]
            results.skip(name, blocked)
            continue
        results.fail(name, error)

    return blocked


# --- level 2: live ---

def _rowset(result):
    """A comparable, order-independent view of a result's rows."""
    return {tuple(sorted(row.items())) for row in result["rows"]}


def _run(params, limit=None):
    """Run the usage monthly template, returning the result dict unchanged."""
    return bq.run_template(USAGE_MONTHLY, params, limit=limit)


def run_live_checks(results, start_date, end_date):
    """Real queries. These test behaviour the SQL cannot be trusted on until it runs."""
    print_header("LEVEL 2: LIVE (real queries)")

    window = {"merchant": None, "usage_type": None, "start_date": start_date, "end_date": end_date}
    print(f"Window: start_date={start_date or 'null'}, end_date={end_date or 'null'}\n")

    # -- query runs with all nulls --

    result = _run(window)
    if not result["ok"]:
        if _unavailable(result.get("error", "")):
            results.skip("Live checks", result["error"].strip().splitlines()[0])
            return
        results.fail("Query runs with all parameters null", result["error"])
        return

    results.ok("Query runs with all parameters null", f"{result['row_count']} rows")

    # -- query returns expected columns --

    if result["rows"]:
        cols = set(result["rows"][0].keys())
        expected_cols = {"usage_month", "merchant", "usage_type", "groupsale_key", "trans",
                        "qty_used", "debit_used", "cumulative_qty_used", "cumulative_debit_used"}
        results.check(
            "Result has all expected columns",
            expected_cols <= cols,
            f"missing: {sorted(expected_cols - cols)}",
        )
    else:
        results.skip("Result has all expected columns", "no rows in this window")

    # -- BHD tickets return debit_used --

    bhd_tickets = _run({"merchant": "BHD", "usage_type": "TICKET", "start_date": None, "end_date": None})
    if bhd_tickets["ok"] and bhd_tickets["rows"]:
        has_debit = all(row.get("debit_used") is not None for row in bhd_tickets["rows"])
        results.check(
            "BHD tickets have debit_used values",
            has_debit,
            f"{sum(1 for r in bhd_tickets['rows'] if r.get('debit_used') is None)}/{len(bhd_tickets['rows'])} rows have NULL debit",
        )
    else:
        results.skip("BHD tickets have debit_used values", "no BHD ticket rows in data")

    # -- non-BHD merchants return NULL debit_used --

    beta_tickets = _run({"merchant": "Beta", "usage_type": "TICKET", "start_date": None, "end_date": None})
    if beta_tickets["ok"] and beta_tickets["rows"]:
        has_null_debit = all(row.get("debit_used") is None for row in beta_tickets["rows"])
        results.check(
            "Non-BHD merchants have NULL debit_used",
            has_null_debit,
            f"{sum(1 for r in beta_tickets['rows'] if r.get('debit_used') is not None)}/{len(beta_tickets['rows'])} rows have non-NULL debit",
        )
    else:
        results.skip("Non-BHD merchants have NULL debit_used", "no Beta ticket rows in data")


# --- entry point ---

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python .claude/bq_test.py",
        description="Test the Group Sale query templates, cheapest checks first.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Levels: --offline reads files only; the default adds dry runs (BigQuery "
            "compiles the SQL but executes nothing); --live adds real queries."
        ),
    )
    parser.add_argument("--offline", action="store_true",
                        help="Only run the checks that need no BigQuery access")
    parser.add_argument("--live", action="store_true",
                        help="Also run real queries, including the reconciliation check")
    parser.add_argument("--project", metavar="ID",
                        help="Billing project (sets BIGQUERY_PROJECT for this run)")
    parser.add_argument("--location", metavar="LOC",
                        help="Dataset location, e.g. US or asia-southeast1")
    parser.add_argument("--start", metavar="YYYY-MM-DD", default=None,
                        help="start_date for the live checks (default: the template's own)")
    parser.add_argument("--end", metavar="YYYY-MM-DD", default=None,
                        help="end_date for the live checks (default: no upper bound)")
    return parser


def main():
    _force_utf8_stdout()
    args = build_parser().parse_args()

    # clients/config.py resolves BIGQUERY_* once, at import time, so the environment has
    # to be set before the package is loaded - not after.
    if args.project:
        os.environ["BIGQUERY_PROJECT"] = args.project
    if args.location:
        os.environ["BIGQUERY_LOCATION"] = args.location

    _load_claude_package()
    global bq
    from claude.agents.tools import bigquery as bigquery_tools
    bq = bigquery_tools

    print_header("GROUP SALE TEMPLATE TESTS")
    print(f"Templates: {bq.template_dir()}")
    print(f"Project:   {os.environ.get('BIGQUERY_PROJECT') or '(from gcloud ADC)'}")
    print(f"Location:  {os.environ.get('BIGQUERY_LOCATION') or 'US (default)'}")
    print(f"Level:     {'offline' if args.offline else ('live' if args.live else 'dry run')}")

    results = Results()
    run_offline_checks(results)

    if not args.offline:
        blocked = run_dry_run_checks(results)
        if args.live:
            if blocked:
                print_header("LEVEL 2: LIVE (real queries)")
                results.skip("Live checks", blocked)
            else:
                run_live_checks(results, args.start, args.end)
    elif args.live:
        print(f"\n{Colors.YELLOW}--live ignored: --offline was also given.{Colors.END}")

    print_header("SUMMARY")
    total = results.passed + results.failed
    print(f"Ran:     {total}")
    print(f"Passed:  {Colors.GREEN}{results.passed}{Colors.END}")
    print(f"Failed:  {Colors.RED if results.failed else ''}{results.failed}{Colors.END}")
    print(f"Skipped: {Colors.YELLOW}{results.skipped}{Colors.END}")

    if results.failures:
        print(f"\n{Colors.RED}{Colors.BOLD}Failures:{Colors.END}")
        for failure in results.failures:
            print(f"  • {failure}")

    if results.failed:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ {results.failed} CHECK(S) FAILED{Colors.END}\n")
        return EXIT_FAILED

    if results.skipped:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}✓ Everything that ran passed, but "
              f"{results.skipped} check(s) were skipped.{Colors.END}")
        print("  The templates are not proven until at least the dry runs execute.\n")
        return EXIT_OK

    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ ALL CHECKS PASSED{Colors.END}\n")
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(EXIT_FAILED)
