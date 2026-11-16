# Testing

## 1. Commands

Use the virtual-environment interpreter (it has `psycopg`, `google-cloud-bigquery`, …):

```bash
.venv/Scripts/python.exe -m pytest -q                 # full suite (tests/)
.venv/Scripts/python.exe .claude/system_test.py       # structure, registry, frontmatter, doc index
git diff --check                                      # whitespace / conflict markers
```

`rag-server/` has its own suite: run `pytest` from inside `rag-server/` with its environment.
The Group Sale query templates have a tiered checker: `python .claude/bq_test.py --offline`
(no credentials), plain (dry runs), `--live` (real queries).

## 2. PostgreSQL tests

- PostgreSQL tests use the **test database only** (`coding_agent_merchant_test`); start Docker
  Desktop first. When `MERCHANT_TEST_*` is not configured they skip or defer.
- **Never run two pytest processes against the test database.** `tests/merchant/conftest.py`
  takes a PostgreSQL advisory lock per process; a second process exits.
- Tests create their own `PYTEST_*`-prefixed Merchants, Projects and claim keys, clean them up,
  and must scope every assertion to those fixtures. The database also holds accepted
  live-acceptance records that must never be modified or counted.
- Runtime and live-service suites are opt-in only: `MERCHANT_RUN_LIVE_TESTS`,
  `MERCHANT_RUN_RUNTIME_VERIFICATION`, `MERCHANT_RUN_RUNTIME_READINESS`,
  `MERCHANT_RUN_RUNTIME_CATALOG_PREFLIGHT`, `MERCHANT_RUN_RUNTIME_TEMPLATE_PREFLIGHT`. Leave them
  unset; they account for the skipped tests in a normal run.

**No-database run** (e.g. without Docker): blank `MERCHANT_*_PASSWORD` and
`MERCHANT_TEST_DB_NAME`, `MERCHANT_DB_HOST=127.0.0.1`, `MERCHANT_DB_PORT=1`
(`python-dotenv` does not override variables already set).

## 3. What to run after a change

| Changed | Run |
|---|---|
| Agent definitions, commands, `agents.json`, hooks, docs layout | `system_test.py`, full suite, `git diff --check`; start a **fresh Claude Code session** before live use (definitions are fingerprinted) |
| A hook | `python -m py_compile <hook>` and an import smoke test immediately — a broken hook import blocks every tool |
| Merchant domain / repositories | full suite (PostgreSQL tests sequentially) and a read-only database snapshot before/after |
| A migration | RED/GREEN tests, dry run, `migrate.py --plan` on the test database; never edit applied files |

## 4. Writing tests

- Prefer one runnable check that fails when the logic breaks over broad suites.
- Hook byte-boundary behaviour (stdin encoding) must be tested in a real subprocess
  (`PYTHONIOENCODING=cp1252`); in-process tests feed decoded strings.
- Unit tests must never fence or spend real claim keys (guarded in `tests/merchant/conftest.py`).
- Write patch scripts with an editor, not shell heredocs, when they contain backslashes
  (heredocs turned a regex `\b` into a backspace byte once).

## 5. Live acceptance

Live `/solve` acceptance on the test database is user-driven, one confirmed operation at a time:
[live acceptance runbook](../operations/live-acceptance.md).
