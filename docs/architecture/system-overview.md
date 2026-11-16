# System Overview

The authoritative description of the workspace's structure, folder ownership, dependency
direction and conventions. Every agent reads this before working on the system
(`docs/architecture/system-overview.md`).

Related: [agent orchestration and safety contract](../../CLAUDE.md),
[trusted Merchant execution](trusted-execution.md),
[Merchant project lifecycle](../merchant/project-lifecycle.md).

## 1. What the system is

A multi-agent workspace built on Claude Code:

- The **team lead** is the main session running the `/solve` command. It validates the injected
  intent envelope, plans, dispatches specialist teammates in visible tmux/psmux panes, and
  reports.
- **Specialist subagents** (`.claude/agents/*.md`) handle code review, security, bug fixing,
  implementation, diagnostics, sales data, Merchant operations and scheduling.
- **Hooks** (`.claude/hooks/`) enforce the intent gate, tool/dispatch policy, teammate backend,
  result delivery and the trusted Merchant execution pipeline.
- **Tools** (`.claude/agents/tools/`) and **clients** (`.claude/clients/`) provide capabilities
  and external integrations (Google Calendar, BigQuery, PostgreSQL, the local RAG API).
- **System** (`.claude/system/`) holds the intent parser, shared schemas and the controlled
  in-process Merchant runtime handoff.

Everything runs inside a Claude Code session, with two standalone exceptions: the scheduler
(`python .claude/schedule.py`) and the Merchant alert worker (`.claude/workers/merchant_alert.py`).

## 2. Directory structure

```text
README.md, CLAUDE.md          Repository overview; project instructions (loaded every session)
docs/                         Current documentation (index: docs/README.md)
archive/checkpoints/          Historical checkpoint reports, kept byte-for-byte as evidence
tests/                        pytest suite (unit, hook, PostgreSQL test-database integration)
rag-server/                   Local RAG API (own tests; docker-compose.rag.yml)
.claude/
├── agents.json               Human-readable roster index (must agree with frontmatter)
├── settings.json             Harness configuration: hooks, Agent Teams flag, teammateMode tmux
├── agents/
│   ├── *.md                  The eight subagent definitions (the only form Claude Code dispatches)
│   ├── base_agent.py, system_init.py, team/scheduler.py
│   │                         Python scheduler agent for the standalone path
│   └── tools/
│       ├── merchant/         Merchant domain engines, previews, CLI
│       │   └── agent_cli.py  Credential-safe operational agent adapter
│       ├── bigquery/         Group Sale query templates and runner
│       ├── rag/              RAG search tool
│       └── scheduler/        Calendar helpers
├── clients/
│   ├── calendar_client.py, bigquery_client.py, rag_client.py, config.py
│   └── merchant/             PostgreSQL repositories, migrations/, migrate.py,
│                             attempt evidence, runtime readiness and verification
├── commands/                 /solve (team lead), /schedule-agent
├── hooks/                    Intent gate, policy gate, teammate identity/backend gates,
│                             Merchant preview capture, pending confirmations, Direct EXECUTE
│                             handoff, team result contract, run state
├── system/
│   ├── intent_parser.py      Classifies a request into the intent envelope
│   ├── schemas.py            TaskResult for the scheduler path
│   └── merchant_runtime_handoff.py
│                             One-use in-process user-scoped Merchant Direct EXECUTE bridge
├── workers/                  Merchant alert worker (one-shot, standalone)
├── scripts/                  merchant_activation_preflight.py (read-only)
├── examples/                 scheduler_example.py
├── schedule.py, bq_query.py, bq_test.py, rag_search.py, system_test.py
└── runtime/                  Generated session state (git-ignored)
```

## 3. Two kinds of agent

| | Subagent (`.md`) | Python agent (`.py`) |
|---|---|---|
| Lives in | `.claude/agents/{name}.md` | `.claude/agents/team/{name}.py` |
| Runs | Inside a Claude Code session | As a standalone process |
| Dispatched by | `/solve` as an Agent Team teammate | A script (`schedule.py`) |
| Use when | Always, by default | Only when it must run with no session |

The only Python agent is the scheduler. Claude Code never loads or dispatches Python classes.

## 4. Team hierarchy

```text
Team Lead (/solve command in the main session — not an agent)
├── Diagnostician         (root cause from logs, metrics, traces)  read-only
├── Red Team              (security and edge cases)                read-only
├── Reviewer              (code validation)                        read-only
├── Coder                 (features and refactors)                 writes
├── Bug Fixer             (issue resolution)                       writes
├── Group Sales Manager   (sales data, allocation analysis)        read-only
├── Merchant Manager      (Merchant reads; trusted Direct EXECUTE) controlled
└── Scheduler             (calendar & task management)             calendar only
```

- Only the main session dispatches; teammates cannot create nested teams.
- A teammate's report reaches the lead only as a `SendMessage`; pane text, a completed task
  or an idle notification is not a result. Every definition grants `SendMessage` and
  `TaskUpdate` and ends with the delivery contract.
- Never run two writing agents on overlapping paths concurrently.

Merchant operations are owned by `merchant-manager.md`, whose only executable surface is
`agent_cli.py`. See [trusted execution](trusted-execution.md).

## 5. Folder rules and dependency direction

- **One-way dependencies:** agents → tools → clients. `system/` must not import from agents,
  tools or clients (except the explicit Merchant handoff modules). Never import from `agents/`
  into `tools/`.
- **agents/**: subagent definitions and the standalone scheduler only. No credentials or
  hard-coded environment paths. Grant each subagent only the tools its role needs; omit
  `Edit`/`Write` for read-only roles; always grant `SendMessage` and `TaskUpdate`.
- **tools/**: one capability per subdirectory; agent-agnostic.
- **clients/**: one module per external service; credentials resolved through `config.py`
  and the repository-root `.env` (never committed). Do not create component-specific `.env`
  files.
- **hooks/**: trusted enforcement. A broken import in a hook that `policy_gate` loads blocks
  every tool, so `py_compile` and import-smoke any hook immediately after editing it.
- **clients/merchant/migrations/**: append-only. Applied migrations (001–011) are never edited;
  their bytes and line endings are pinned by `.gitattributes`.

## 6. Documentation rules

| Markdown | Location | Why |
|---|---|---|
| Project instructions | `CLAUDE.md` | Loaded into every session and teammate |
| Repository overview | `README.md` | Entry point |
| Subagent definitions | `.claude/agents/*.md` | Load-bearing: the harness discovers agents only here |
| Slash commands | `.claude/commands/*.md` | Load-bearing: the harness discovers commands only here |
| Agent reference data | `.claude/agents/tools/bigquery/{schemas,templates}/*.md` | Read by `group-sales-manager` |
| Current documentation | `docs/` | One canonical document per subject; indexed in `docs/README.md` |
| Historical reports | `archive/checkpoints/` | Evidence only; never edited, never authoritative |

When adding documentation: put it in the matching `docs/` subfolder, add it to
`docs/README.md`, and link to the canonical document instead of repeating its content. Moving an
agent definition or slash command out of its folder silently stops it from existing.
`python .claude/system_test.py` reports any `.md` in an invalid location.

## 7. Adding components

**A subagent:** create `.claude/agents/{name}.md` (kebab-case; `name`, `description`, `tools`,
`model` frontmatter; description says *when* to use it; body opens with the requirement to read
this document and closes with the result-delivery contract); register it in `agents.json`
with an identical id; add it to the team table in `.claude/commands/solve.md` and to the
`dispatches` list; run `python .claude/system_test.py`.

**A tool:** `.claude/agents/tools/{tool}/` with `__init__.py`; register it in `agents.json`.

**A client:** `.claude/clients/{service}_client.py` resolving credentials through `config.py`;
document setup in [local setup](../operations/local-setup.md).

## 8. Naming conventions

- `snake_case` for Python files and functions; `CamelCase` classes; `SCREAMING_SNAKE_CASE`
  constants.
- `kebab-case` for agent, command and documentation filenames.
- Agent filename, frontmatter `name` and `agents.json` id are identical.

## 9. Before building anything

1. Read this document and `CLAUDE.md`.
2. Check existing agents, tools and clients for similar functionality.
3. Keep the dependency direction and folder ownership.
4. Register new agents and tools in `agents.json`.
5. Run `python .claude/system_test.py`, the relevant tests, and `git diff --check`.
