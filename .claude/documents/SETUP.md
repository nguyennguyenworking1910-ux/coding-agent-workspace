# Setup

**Status:** Active
**Audience:** Anyone installing this workspace on a new machine

Nothing here is needed for the subagents or slash commands — those are configuration, not
code, and Claude Code picks them up as soon as you open the repository. This guide covers the
Python environment behind the standalone scheduler (`.claude/schedule.py`), the intent parser
(`.claude/system/intent_parser.py`), and the BigQuery CLI (`.claude/bq_query.py`).

---

## 1. Python 3.10+

`pyproject.toml` declares `requires-python = ">=3.10"`. The code uses PEP 604 unions
(`str | None`) and `from __future__ import annotations`, so 3.9 fails at import, not at
runtime. Check what you have:

```powershell
python --version
```

If that reports 3.9 or older, install 3.10+ from <https://www.python.org/downloads/> and use
that interpreter explicitly (`py -3.12 -m venv .venv` on Windows).

---

## 2. Virtual environment (Windows)

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script with an execution-policy error, allow signed local
scripts for your user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Alternatives that need no policy change: `.venv\Scripts\activate.bat` from `cmd.exe`, or
Git Bash with `source .venv/Scripts/activate`. On macOS/Linux it is
`source .venv/bin/activate`.

`.venv/` is git-ignored. Confirm the environment is the active one before installing:

```powershell
(Get-Command python).Source     # should be ...\coding-agent-workspace\.venv\Scripts\python.exe
```

---

## 3. Install the package

```powershell
pip install -e .
```

Editable install matters here. The source directory is `.claude`, whose leading dot is not a
valid module name, so `pyproject.toml` remaps it to the importable package `claude`
(`package-dir = {"claude" = ".claude"}`). Without the install, `from claude.agents import
get_agent` cannot resolve, and the entry points fall back to their own path-loading shim.

This pulls in the Google API client libraries, `openai`, `pydantic`, `python-dotenv`,
`google-cloud-bigquery`, and `filelock`. One optional extra exists:

```powershell
pip install -e ".[scheduler-extras]"      # adds python-dateutil
```

---

## 4. `OPENAI_API_KEY`

The intent parser calls OpenAI to classify a request before `/solve` runs, and it
**fails closed** — no key means no envelope, and no envelope means no run. It reads the key
from the process environment or a root `.env` file, and raises
`IntentParserConfigError: OPENAI_API_KEY is missing.` when neither has it.

For one shell session:

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

Persistently for your user:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")
```

Or in a `.env` file at the repository root (git-ignored — never commit a key):

```
OPENAI_API_KEY=sk-...
```

The model and effort used are set in `.claude/agents.json` under
`orchestration.intent_parser`, not in the environment.

---

## 5. Google Cloud CLI and Application Default Credentials

Needed only for the standalone scheduler and for BigQuery. Install the Google Cloud SDK from
<https://cloud.google.com/sdk/docs/install>, then confirm:

```powershell
gcloud --version
```

### Calendar scope (for `.claude/schedule.py`)

Plain `gcloud auth application-default login` only carries cloud-platform scopes, which the
Calendar API rejects with a 403 "insufficient authentication scopes". Grant the Calendar
scope explicitly — this is `config.ADC_LOGIN_COMMAND`, the exact command the client prints
when authentication fails:

```powershell
gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/calendar
```

### BigQuery scope (for `.claude/bq_query.py`)

Plain ADC already covers BigQuery:

```powershell
gcloud auth application-default login
gcloud config set project my-project-id
```

Details, environment variables, and safety caps are in
[BIGQUERY_INTEGRATION.md](./BIGQUERY_INTEGRATION.md).

### Calendar credential resolution order

`.claude/clients/calendar_client.py` tries four sources in this order and uses the first that
works. Paths come from `.claude/clients/config.py` and are anchored at `.claude/clients/`, not
the working directory:

| Order | Source | Path / override |
|---|---|---|
| 1 | Cached OAuth token (auto-refreshed) | `.claude/clients/token.json` — `GOOGLE_CALENDAR_TOKEN` |
| 2 | Desktop OAuth app consent flow | `.claude/clients/credentials.json` — `GOOGLE_CALENDAR_CREDENTIALS` |
| 3 | Service account with the calendar shared to it | `.claude/clients/service_account.json` — `GOOGLE_CALENDAR_SERVICE_ACCOUNT` |
| 4 | gcloud ADC | the login command above |

ADC is last, so a stale `token.json` wins over a fresh `gcloud` login — delete it if you
switch accounts. None of these files need to exist if ADC is set up. Other calendar settings:
`GOOGLE_CALENDAR_ID` (default `primary`) and `CALENDAR_TIMEZONE` (default
`Asia/Ho_Chi_Minh`).

Credential troubleshooting for the scheduler specifically is in
[SCHEDULE_CLI.md](./SCHEDULE_CLI.md).

---

## 6. Verify the install

### Unit tests

```powershell
python -m pytest tests -q
```

`pytest` is not a declared dependency, so install it if it is missing (`pip install pytest`).
The suite covers the intent parser and stubs the OpenAI call — it makes no network requests
and needs no `OPENAI_API_KEY`. A single test:

```powershell
python -m pytest tests/test_intent_parser.py -q
```

### System test

```powershell
python .claude/system_test.py
```

This is the structural check, not a unit-test runner: folder layout, every `.md` in a location
the harness actually reads, `agents.json` parsing, subagent frontmatter matching the registry,
the documentation index, and the critical documents. It exits non-zero when a check fails, so
CI and pre-commit hooks can gate on it. Run it after adding an agent, a document, or a tool.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'claude'`** — the editable install did not happen, or
you are in a different interpreter than the one you installed into. Re-activate `.venv` and
re-run `pip install -e .`.

**`OPENAI_API_KEY is missing`** — see section 4. `/solve` will refuse to run rather than guess
a task class.

**Output is garbled on Windows** — the console defaults to cp1252, which cannot encode the
status glyphs. The entry points force UTF-8 themselves; for anything else set
`$env:PYTHONIOENCODING = "utf-8"`.

**`gcloud` not recognized after installing the SDK** — the installer edits `PATH`; open a new
shell.

---

## Related documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — folder ownership and the rules for adding anything
- [SCHEDULE_CLI.md](./SCHEDULE_CLI.md) — scheduling from a session or a shell
- [BIGQUERY_INTEGRATION.md](./BIGQUERY_INTEGRATION.md) — the BigQuery side of `clients/config.py`
- [AGENT_INITIALIZATION.md](./AGENT_INITIALIZATION.md) — what every agent reads before executing

---

**Last Updated:** August 13, 2026
