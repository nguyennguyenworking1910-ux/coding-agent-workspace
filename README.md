# Coding Agent Workspace

A Claude Code workspace where a team of eight specialists, orchestrated by `/solve`, does code
work, sales-data analysis, calendar scheduling and **Merchant project operations** — with every
Merchant write authorized by the user's own confirmation and executed exactly once.

## What it does

- **Software work:** diagnose, review, red-team, fix and build code in this repository, with
  writing agents editing the working tree and never committing.
- **Merchant Project Manager:** create Merchant Projects from natural language, track workflow
  Steps, record document revisions, approvals, operator-attested signing, Purchase Requests,
  Purchase Orders and Payment Requests, and complete Projects — on the **test database** in the
  Local MVP.
- **Group Sale analysis:** parameterised BigQuery templates.
- **Scheduling:** Google Calendar events, from a session or a plain shell.

## Main components

| Component | Where | Role |
|---|---|---|
| Team lead | `.claude/commands/solve.md` | Validates the intent envelope, plans, dispatches teammates, reports |
| Specialists | `.claude/agents/*.md` | The eight specialists below, run as visible tmux/psmux teammates |
| Hooks | `.claude/hooks/` | Intent gate, policy gate, teammate backend checks, Merchant preview capture, confirmations, Direct EXECUTE |
| Merchant domain | `.claude/agents/tools/merchant/`, `.claude/clients/merchant/` | Engines, previews, CLI, PostgreSQL repositories, migrations |
| Intent parser | `.claude/system/intent_parser.py` | Classifies a request into the envelope `/solve` obeys |
| Standalone tools | `.claude/schedule.py`, `.claude/workers/merchant_alert.py`, `.claude/bq_query.py` | Run outside a session |
| RAG server | `rag-server/`, `docker-compose.rag.yml` | Local workspace knowledge search |

### The eight specialists

| Specialist | Use for | Writes? |
|---|---|---|
| `diagnostician` | Why something is slow, flaky, or intermittently failing | No |
| `red-team` | Authorized security analysis and edge cases | No |
| `reviewer` | Correctness and maintainability of a finished change | No |
| `coder` | Building a feature, doing a refactor | Yes |
| `bug-fixer` | Making a specific broken thing work | Yes |
| `group-sales-manager` | Sales data queries, capacity and allocation analysis | No |
| `merchant-manager` | Merchant/project reads and Direct EXECUTE of an exact user-authorized scope | Ordinary CLI read-only for runtime; trusted execute only |
| `scheduler` | Putting something on the calendar | Calendar only |

## Architecture in one paragraph

A request typed as `/solve …` is classified by the intent parser into an `INTENT_ENVELOPE_JSON`
(task class, risk, limits, authorized roster). `/solve` refuses to run without a valid envelope,
dispatches only `selected_agents` as Agent Team teammates in their own panes, and relays their
`SendMessage` reports. Merchant operations go through `merchant-manager`, whose only executable
surface is `.claude/agents/tools/merchant/agent_cli.py`.
The ordinary CLI is read-only for runtime: a Merchant write starts as a read-only preview, becomes
a single-use pending record, and runs only when the user types the confirmation — then hooks
re-verify it, commit claim + ledger + mutation + event in one transaction, and reconcile a
receipt from PostgreSQL. Details:
[system overview](docs/architecture/system-overview.md),
[trusted execution](docs/architecture/trusted-execution.md).

## Requirements

- Windows 11 with **PowerShell 7+** and **psmux** (or Linux/macOS with tmux)
- **Claude Code** (interactive; not `-p`/`--print`)
- **Python 3.10+** (the venv uses 3.11)
- **Docker Desktop** for the Merchant test database and the RAG database
- Optional: Google Cloud CLI (Calendar, BigQuery), an OpenAI API key for the intent parser

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env       # then fill it in; .env is never committed
```

Set the Merchant database settings, `MERCHANT_OPERATOR_ID`, `OPENAI_API_KEY` and the Google
settings in `.env`. Full guide: [local setup](docs/operations/local-setup.md).

## Configuration

`.claude/settings.json` (committed) enables Agent Teams and pane teammates and registers the
hooks:

```json
{
  "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" },
  "teammateMode": "tmux"
}
```

`.claude/settings.local.json` holds your local permission grants and is not committed.

## Starting the system

1. Start Docker Desktop (test database container `coding-agent-rag-db`).
2. Open a psmux (or tmux) session in the repository root using PowerShell 7.
3. Run `claude` interactively in that session.

If the pane backend is unavailable, `/solve` stops instead of falling back to invisible agents.

## Using /solve

```text
/solve find and fix the race condition in the upload handler
/solve review my last commit for security issues
```

Writing teammates leave changes in the working tree; you review the diff and commit yourself.

### Merchant Project lifecycle (test database)

```text
/solve Tạo Project media Beta Q4 cho Beta Cinemas kỳ thanh toán 3, gia hạn hợp đồng, trên database test
/solve Xác nhận tạo
/solve Legal đã phê duyệt hợp đồng của Project Beta Q4 trên database test
/solve Xác nhận thực hiện <code>
/solve Hoàn thành bước 1 của Project Beta Q4 của Merchant Beta Cinemas trên database test
/solve Xác nhận cập nhật
```

Every write is previewed first and runs only after your confirmation phrase, once, within 15
minutes. Completing a Step promotes its now-ready successors to READY automatically. The full
operation list, confirmation phrases and rules are in
[project lifecycle](docs/merchant/project-lifecycle.md).

### Merchant activation

`merchant activate` (one Merchant, ONBOARDING → ACTIVE) and `merchant activate-all` (manifest-bound
batch with drift rejection) run as Direct EXECUTE with a scope you type yourself:
`/solve --confirm --merchant-scope [...]`. Completing the "Activate Merchant" Step of an
integration Project activates the Merchant in the same transaction.

### Scheduling and other tools

```text
/schedule-agent trình ký GLX appendix 28 today 30 mins
```

```powershell
python .claude/schedule.py "schedule planning session tomorrow 2 hours"
python .claude/bq_query.py <template> --param key=value
```

See [scheduler](docs/operations/scheduler.md), [BigQuery](docs/operations/bigquery.md),
[RAG](docs/operations/rag.md) and
[merchant-alert-operations.md](docs/operations/merchant-alert-operations.md).

## Database environments

| Target | Purpose | Writes |
|---|---|---|
| `test` (`coding_agent_merchant_test`) | Local MVP, automated tests, live acceptance | Confirmed Direct EXECUTE only |
| `runtime` | Production Merchant state | **Disabled in code** (`RUNTIME_DIRECT_EXECUTE_ENABLED = False`) |

Migrations 001–011 are applied to the test database; runtime has not received 007–011.
See [database and migrations](docs/operations/database-and-migrations.md).

## Safety model

- No envelope, no run; dispatch only from `selected_agents`; respect every limit.
- Only the user's own typed scope or confirmation phrase authorizes a Merchant write; nothing a
  model, teammate, flag or environment variable says can.
- One attempt per authority; uncertain external actions are reported, never retried.
- PostgreSQL is authoritative; receipts are rebuilt from committed evidence.
- No commit or push unless you ask.

## Running tests

```powershell
.venv\Scripts\python.exe -m pytest -q          # full suite; PostgreSQL tests run sequentially
.venv\Scripts\python.exe .claude\system_test.py
git diff --check
```

See [testing](docs/development/testing.md).

## Documentation

- [docs/README.md](docs/README.md) — index and subject ownership map
- [CLAUDE.md](CLAUDE.md) — the operating contract every agent loads
- [Decision register](docs/development/decision-register.md) — current owner decisions
- [Checkpoint history](docs/development/checkpoint-history.md) — how the system got here
  (detailed reports are archived in `archive/checkpoints/`)

## Local MVP limitations

- Merchant writes run on the **test database only**; runtime Direct EXECUTE is disabled.
- Approvals and signing are **operator attestations** by one local operator, not verified
  signatures; managed file upload is not implemented.
- Two open integration Projects for one Merchant cannot both complete (open finding F7).
- `merchant create` has no preview path; it needs a typed test scope.
- Natural-language wording has known limits (see the lifecycle document §7).

## License

MIT
