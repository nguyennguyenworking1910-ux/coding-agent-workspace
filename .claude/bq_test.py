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

BY_MERCHANT = "groupsale_by_merchant"
UNMATCHED = "groupsale_unmatched_keys"

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


# --- reading the templates as text ---

# The merchant patterns and labels are written twice on purpose: the CASE in
# groupsale_by_merchant.sql assigns labels in priority order, and the exclusion in
# groupsale_unmatched_keys.sql has to mirror it. These regexes exist so the duplication
# is checked rather than trusted.
_CASE_BRANCH = re.compile(
    r"WHEN\s+REGEXP_CONTAINS\(\s*UPPER\(\s*groupsale_key\s*\)\s*,\s*r'([^']+)'\s*\)\s*"
    r"THEN\s*'([^']+)'",
    re.IGNORECASE,
)
_MAP_MERCHANT = re.compile(r"STRUCT\(\s*'([^']+)'\s+AS\s+merchant\b", re.IGNORECASE)
# `[^\[\]]` rather than `[^\]]`: the alias arrays sit inside the outer `UNNEST([...])`
# bracket, and allowing `[` in the class lets a match start at that outer bracket and
# swallow the merchant label with it.
_MAP_ALIASES = re.compile(r"\[([^\[\]]*)\]\s+AS\s+aliases", re.IGNORECASE)
_EXCLUSION = re.compile(
    r"NOT\s+REGEXP_CONTAINS\(\s*UPPER\(\s*groupsale_key\s*\)\s*,\s*r'([^']+)'\s*\)",
    re.IGNORECASE,
)
_TABLE = re.compile(r"FROM\s+`([^`]+)`", re.IGNORECASE)
_DEFAULT_DATE = re.compile(r"DATE\s+'(\d{4}-\d{2}-\d{2})'")


def template_sql(name):
    """The raw text of a template, read through the tool layer."""
    return bq.get_template(name)


def case_branches(sql):
    """[(pattern, label), ...] from the CASE, in the order they are evaluated."""
    return _CASE_BRANCH.findall(sql)


def map_merchants(sql):
    """The merchant labels the alias map can select."""
    return _MAP_MERCHANT.findall(sql)


def map_aliases(sql):
    """Every alias string in the map, lower-cased."""
    aliases = []
    for group in _MAP_ALIASES.findall(sql):
        aliases.extend(re.findall(r"'([^']*)'", group))
    return [a.lower() for a in aliases]


# --- level 0: offline ---

def run_offline_checks(results):
    """Checks that read the .sql files and the tool layer. No BigQuery, no credentials."""
    print_header("LEVEL 0: OFFLINE (no BigQuery)")

    available = bq.list_templates()

    for name in (BY_MERCHANT, UNMATCHED):
        if not results.check(f"Template discovered: {name}", name in available,
                             f"available: {', '.join(available) or '(none)'}"):
            return  # nothing below can work without the files

    merchant_sql = template_sql(BY_MERCHANT)
    unmatched_sql = template_sql(UNMATCHED)

    # -- parameters --

    results.check(
        f"{BY_MERCHANT} takes exactly merchant, start_date, end_date",
        set(bq.extract_param_names(merchant_sql)) == {"merchant", "start_date", "end_date"},
        f"found: {bq.extract_param_names(merchant_sql)}",
    )
    results.check(
        f"{UNMATCHED} takes exactly start_date, end_date",
        set(bq.extract_param_names(unmatched_sql)) == {"start_date", "end_date"},
        f"found: {bq.extract_param_names(unmatched_sql)}",
    )

    # A missing or misspelled parameter must fail locally, before a job is created.
    try:
        bq.validate_params(BY_MERCHANT, {"merchant": "cgv", "start_date": None})
        results.fail("Missing parameter is rejected locally", "validate_params accepted it")
    except bq.TemplateError as e:
        results.ok("Missing parameter is rejected locally", str(e).splitlines()[0])

    try:
        bq.validate_params(
            BY_MERCHANT,
            {"merchant": "cgv", "start_date": None, "end_date": None, "typo": 1},
        )
        results.fail("Unknown parameter is rejected locally", "validate_params accepted it")
    except bq.TemplateError:
        results.ok("Unknown parameter is rejected locally")

    # -- the duplication between the two templates --

    branches = case_branches(merchant_sql)
    case_patterns = [p.upper() for p, _ in branches]
    case_labels = [label for _, label in branches]

    results.check(
        "CASE labels every merchant exactly once",
        len(case_labels) == len(set(case_labels)) and len(case_labels) == 5,
        f"labels: {case_labels}",
    )

    excluded = _EXCLUSION.findall(unmatched_sql)
    if not excluded:
        results.fail(f"{UNMATCHED} has a merchant exclusion", "no NOT REGEXP_CONTAINS found")
    else:
        unmatched_patterns = [p.upper() for p in excluded[0].split("|")]
        results.check(
            "Both templates use the same merchant patterns",
            set(case_patterns) == set(unmatched_patterns),
            f"only in {BY_MERCHANT}: {sorted(set(case_patterns) - set(unmatched_patterns))}; "
            f"only in {UNMATCHED}: {sorted(set(unmatched_patterns) - set(case_patterns))}",
        )

    # A label in the map that the CASE never produces selects nothing and returns zero
    # rows - the exact silent-empty-result failure the templates are built to avoid.
    mapped = map_merchants(merchant_sql)
    results.check(
        "Every alias-map merchant is produced by the CASE",
        set(mapped) == set(case_labels),
        f"map: {sorted(set(mapped))} vs CASE: {sorted(set(case_labels))}",
    )

    aliases = map_aliases(merchant_sql)
    results.check(
        "Aliases are lower case, single-spaced, and unique",
        aliases == [a.strip() for a in aliases]
        and all("  " not in a for a in aliases)
        and len(aliases) == len(set(aliases)),
        f"{len(aliases)} aliases",
    )
    results.check(
        "Every merchant has its own name as an alias",
        all(label.lower() in aliases for label in case_labels),
        f"missing: {[l for l in case_labels if l.lower() not in aliases]}",
    )

    # -- shared constants --

    tables = {t for t in _TABLE.findall(merchant_sql)} | {t for t in _TABLE.findall(unmatched_sql)}
    results.check(
        "Both templates read the same table",
        len(tables) == 1,
        f"tables: {sorted(tables)}",
    )

    floors = set(_DEFAULT_DATE.findall(merchant_sql)) | set(_DEFAULT_DATE.findall(unmatched_sql))
    results.check(
        "Both templates default to the same start date",
        len(floors) == 1,
        f"defaults: {sorted(floors)}",
    )


# --- level 1: dry run ---

# Each shape compiles a different branch of the SQL: an explicit window, the defaulted
# window, and the alias path. A dry run type-checks all of it without executing.
DRY_RUN_SHAPES = [
    ("explicit merchant and window",
     {"merchant": "cgv", "start_date": "2026-07-01", "end_date": "2026-07-31"}),
    ("all defaults (no merchant, no dates)",
     {"merchant": None, "start_date": None, "end_date": None}),
    ("multi-word alias",
     {"merchant": "beta cinemas", "start_date": None, "end_date": None}),
    ("code used as an alias (glx)",
     {"merchant": "glx", "start_date": None, "end_date": None}),
    ("open-ended window (start only)",
     {"merchant": None, "start_date": "2026-07-01", "end_date": None}),
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
    Note that ERROR() does not fire here - nothing is executed - so the unknown-merchant
    guard is a live check, not a dry-run one.
    """
    print_header("LEVEL 1: DRY RUN (BigQuery compiles, nothing executes)")

    blocked = None
    for label, params in DRY_RUN_SHAPES:
        name = f"Compiles: {label}"
        if blocked:
            results.skip(name, blocked)
            continue

        result = bq.run_template(BY_MERCHANT, params, dry_run=True)
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

    name = f"Compiles: {UNMATCHED}"
    if blocked:
        results.skip(name, blocked)
    else:
        result = bq.run_template(
            UNMATCHED, {"start_date": None, "end_date": None}, dry_run=True
        )
        if result["ok"]:
            results.ok(name, f"{result['gigabytes_processed']} GiB would be scanned")
        elif _unavailable(result.get("error", "")):
            results.skip(name, result["error"].strip().splitlines()[0])
        else:
            results.fail(name, result.get("error", ""))

    return blocked


# --- level 2: live ---

def _rowset(result):
    """A comparable, order-independent view of a result's rows."""
    return {tuple(sorted(row.items())) for row in result["rows"]}


def _run(params, limit=None):
    """Run the merchant template, returning the result dict unchanged."""
    return bq.run_template(BY_MERCHANT, params, limit=limit)


def run_live_checks(results, start_date, end_date):
    """Real queries. These test behaviour the SQL cannot be trusted on until it runs."""
    print_header("LEVEL 2: LIVE (real queries)")

    window = {"start_date": start_date, "end_date": end_date}
    print(f"Window: start_date={start_date or 'null (template default)'}, "
          f"end_date={end_date or 'null (no upper bound)'}\n")

    # -- a named merchant only ever returns its own label --

    named = _run({"merchant": "lotte", **window})
    if not named["ok"]:
        if _unavailable(named.get("error", "")):
            results.skip("Live checks", named["error"].strip().splitlines()[0])
            return
        results.fail("Query runs for a named merchant", named["error"])
        return

    labels = {row["merchant"] for row in named["rows"]}
    if not named["rows"]:
        # Passing an assertion over zero rows would be vacuous, so say so instead.
        results.skip("A named merchant returns only its own rows", "no rows in this window")
    else:
        results.check(
            "A named merchant returns only its own rows",
            labels == {"Lotte"},
            f"labels present: {sorted(labels)}",
        )

    # -- the all-merchants default --

    every = _run({"merchant": None, **window})
    if not every["ok"]:
        results.fail("Query runs with merchant=null", every["error"])
        return

    all_labels = {row["merchant"] for row in every["rows"]}
    results.check(
        "merchant=null covers more than one merchant",
        len(all_labels) > 1,
        f"merchants present: {sorted(all_labels)}",
    )
    results.check(
        "merchant=null never returns an unclassified row",
        "Unknown" not in all_labels,
        "an 'Unknown' row means the merchant filter is not applied",
    )

    # -- the date default --

    merchant_sql = template_sql(BY_MERCHANT)
    floors = _DEFAULT_DATE.findall(merchant_sql)
    if start_date is not None:
        results.skip("start_date=null equals the documented default", "--start was given")
    elif not floors:
        results.skip("start_date=null equals the documented default", "no default date in the SQL")
    else:
        explicit = _run({"merchant": None, "start_date": floors[0], "end_date": end_date})
        if not explicit["ok"]:
            results.fail("start_date=null equals the documented default", explicit["error"])
        else:
            results.check(
                "start_date=null equals the documented default",
                _rowset(explicit) == _rowset(every),
                f"null: {every['row_count']} rows vs {floors[0]}: {explicit['row_count']} rows",
            )

    # -- aliases resolve to the same merchant --

    galaxy = _run({"merchant": "galaxy", **window})
    glx = _run({"merchant": "glx", **window})
    if galaxy["ok"] and glx["ok"]:
        results.check(
            "Aliases 'galaxy' and 'glx' return identical rows",
            _rowset(galaxy) == _rowset(glx),
            f"galaxy: {galaxy['row_count']} rows, glx: {glx['row_count']} rows",
        )
    else:
        results.fail(
            "Aliases 'galaxy' and 'glx' return identical rows",
            galaxy.get("error") or glx.get("error"),
        )

    # -- the guard: an unknown merchant must fail loudly --

    unknown = _run({"merchant": "cinestar", **window})
    if unknown["ok"]:
        results.fail(
            "An unknown merchant fails instead of returning nothing",
            f"the query succeeded with {unknown['row_count']} rows - a typo would be "
            "reported as 'no sales'",
        )
    elif "unknown merchant" in unknown.get("error", "").lower():
        results.ok("An unknown merchant fails instead of returning nothing",
                   "ERROR() names the merchant")
    else:
        results.fail(
            "An unknown merchant fails instead of returning nothing",
            f"failed, but not with the guard message: {unknown.get('error', '')}",
        )

    run_reconciliation(results, every, window, merchant_sql)


def run_reconciliation(results, matched, window, merchant_sql):
    """Matched rows + unmatched rows must account for the whole table in this window.

    This is the check that catches a wrong merchant pattern. If a chain's code is not in
    the CASE, its rows do not vanish - they land in `groupsale_unmatched_keys`, and the
    two totals still have to add up to the table's own total.
    """
    name = "Matched + unmatched = every Group Sale row in the window"

    unmatched = bq.run_template(UNMATCHED, window)
    if not unmatched["ok"]:
        results.fail(name, unmatched["error"])
        return

    # Both sides are aggregated per groupsale_key, so a truncated result set means the
    # sums below are partial and the comparison would be meaningless.
    if matched.get("truncated") or unmatched.get("truncated"):
        results.skip(
            name,
            f"result truncated at the {matched['row_limit']} row cap - narrow the window "
            "with --start/--end, or raise BIGQUERY_MAX_ROWS",
        )
        return

    tables = _TABLE.findall(merchant_sql)
    floors = _DEFAULT_DATE.findall(merchant_sql)
    if not tables or not floors:
        results.skip(name, "could not read the table or default date out of the template")
        return

    # The table name and the default date are interpolated because BigQuery cannot
    # parameterize an identifier. Both are read out of a repo file, never from a request,
    # and the two date values below are still bound as real query parameters.
    total_sql = f"""
    SELECT
      COUNT(*)                                  AS transaction_count,
      SUM(COALESCE(total_amount_groupsale, 0))  AS total_amount
    FROM `{tables[0]}`
    WHERE groupsale_key IS NOT NULL
      AND booking_date >= IFNULL(PARSE_DATE('%Y-%m-%d', @start_date), DATE '{floors[0]}')
      AND (@end_date IS NULL OR booking_date <= PARSE_DATE('%Y-%m-%d', @end_date))
    """
    whole = bq.run_sql(total_sql, window)
    if not whole["ok"]:
        results.fail(name, whole["error"])
        return

    expected = whole["rows"][0]
    matched_count = sum(row["transaction_count"] for row in matched["rows"])
    unmatched_count = sum(row["transaction_count"] for row in unmatched["rows"])
    matched_amount = sum(row["total_amount"] for row in matched["rows"])
    unmatched_amount = sum(row["total_amount"] for row in unmatched["rows"])

    results.check(
        name,
        matched_count + unmatched_count == expected["transaction_count"]
        and matched_amount + unmatched_amount == expected["total_amount"],
        f"matched {matched_count} + unmatched {unmatched_count} = "
        f"{matched_count + unmatched_count}, table has {expected['transaction_count']}",
    )

    # Not a pass/fail - unmatched rows are legitimate, but they are excluded from every
    # per-merchant figure, so their size is the number to know.
    if unmatched["rows"]:
        share = (
            100.0 * unmatched_count / expected["transaction_count"]
            if expected["transaction_count"] else 0.0
        )
        print(f"{Colors.YELLOW}  note: {len(unmatched['rows'])} groupsale_keys "
              f"({unmatched_count} rows, {share:.1f}%) match no merchant and are excluded "
              f"from every figure above.{Colors.END}")
        print(f"        run: python .claude/bq_query.py {UNMATCHED} "
              f"--param start_date=null --param end_date=null")
    else:
        print(f"{Colors.GREEN}  note: every groupsale_key in this window matched a "
              f"merchant.{Colors.END}")


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
