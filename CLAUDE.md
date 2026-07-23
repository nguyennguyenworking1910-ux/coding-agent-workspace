# Coding Agent Workspace

Agent system for code analysis, quality assurance, and sales operations management.

## Subagents

### team_leader
**Purpose**: Orchestrates the agent team to coordinate code analysis and fixes

**Capabilities**:
- Plan and coordinate code analysis workflows
- Spawn diagnostician to scan for bugs and issues
- Spawn bug_fixer to implement solutions
- Spawn reviewer to validate changes
- Spawn group_sale_manager for BigQuery operations
- Synthesize results from all agents

**How to use**:
```
Analyze my code for bugs and issues (will spawn diagnostician)
Fix the bugs in my code (will spawn diagnostician then bug_fixer)
Review my code changes (will spawn reviewer)
Query sales data from BigQuery (will spawn group_sale_manager)
```

**Tools available**:
- Thought tool for reasoning and planning
- Can spawn: diagnostician, bug_fixer, reviewer, group_sale_manager

**Agent Spawning Methods**:
- `spawn_diagnostician(task)` - Spawn bug analysis specialist
- `spawn_bug_fixer(issues)` - Spawn fix implementer
- `spawn_reviewer(changes)` - Spawn validation specialist
- `spawn_group_sale_manager(task)` - Spawn BigQuery operations agent
- `coordinate_analysis_workflow()` - Full analysis pipeline

**Spawn conditions**:
- User asks for code analysis
- User requests bug fixes
- User wants code review
- User needs BigQuery queries

---

### group_sale_manager
**Purpose**: Manages group sales operations with BigQuery data access

**Capabilities**:
- Query sales data with automatic schema reading
- Create and execute complex SQL queries (SELECT, INSERT, JOIN, aggregations)
- Get aggregated sales summaries by group and region
- Identify top performing groups by various metrics
- Evaluate group performance with statistics
- Export query results to multiple formats (CSV, JSON, Parquet, Avro)
- Join multiple sales tables for analysis
- Filter and aggregate results in-memory

**How to use**:
```
Query sales data from group_sales dataset
Get sales summary by group and region
Find top 10 performing groups
Evaluate performance of group ID X
Export sales results to CSV
```

**Tools available**:
- Thought tool for strategic analysis
- Schema Reader - Read table definitions from .md files
- Query Builder - Build parameterized SQL queries
- Query Executor - Execute queries in BigQuery
- Data Fetcher - Fetch, process, and export results

**Methods**:
- `query_sales(dataset, table, query_spec)` - Query with custom specifications
- `get_sales_summary(dataset, table, group_by)` - Get aggregated summaries
- `identify_top_groups(dataset, table, metric, limit)` - Find top performers
- `evaluate_group_performance(dataset, table, group_id)` - Detailed analysis
- `export_sales_data(job_id, format, output_path)` - Export results
- `join_sales_tables(dataset, left_table, right_table, on_conditions)` - Multi-table queries

**Spawn conditions**:
- User asks for sales data analysis
- User requests BigQuery queries
- User wants to aggregate sales data
- User needs to export BigQuery results
- User wants to analyze group performance

**Schema Files**:
Store BigQuery table schemas in `.schemas/{dataset}_{table}.md` format.
Example: `.schemas/group_sales_sales_data.md`

See `.claude/BIGQUERY_TOOLS.md` for detailed BigQuery tools documentation.

---

## Project Structure

```
.claude/
├── agents/                           # Agent implementations
│   ├── team_leader.py               # Code analysis coordinator
│   ├── diagnostician.py             # Bug finder
│   ├── bug_fixer.py                 # Fix implementer
│   ├── reviewer.py                  # Validator
│   ├── group_sale_manager.py        # Sales operations with BigQuery
│   └── __init__.py
│
├── tools/                            # Tool implementations
│   ├── thought.py                   # Reasoning tool
│   ├── bigquery.py                  # Legacy BigQuery tool (deprecated)
│   ├── schema_reader.py             # Read table schemas from .md files
│   ├── query_builder.py             # Build SQL queries
│   ├── query_executor.py            # Execute queries in BigQuery
│   ├── data_fetcher.py              # Fetch and process results
│   └── __init__.py
│
├── agents.json                       # Agent and tool configuration
├── BIGQUERY_TOOLS.md                # BigQuery tools architecture documentation
├── AGENTS.md                        # Detailed agent documentation
└── settings.json                    # Settings configuration

.schemas/
└── {dataset}_{table}.md             # BigQuery table schema files
```

## Agent Team Workflow

1. **Team Leader** receives task
2. **Thought Tool** plans analysis
3. **Diagnostician** scans for issues
4. **Bug Fixer** (if needed) implements fixes
5. **Reviewer** validates changes

## Available Agents

- **team_leader**: Orchestrates analysis and coordinates other agents (code analysis only)
- **diagnostician**: Finds bugs and code issues
- **bug_fixer**: Implements code fixes
- **reviewer**: Validates and approves changes
- **group_sale_manager**: Manages sales operations with BigQuery data access

## Available Tools

### Code Analysis
- **thought**: Reasoning and analysis tool for planning and evaluation

### BigQuery Data Access (Modular Architecture)
- **schema_reader**: Read table schemas from markdown files
- **query_builder**: Build SQL queries programmatically
- **query_executor**: Execute queries in BigQuery
- **data_fetcher**: Fetch, process, and export results

### Legacy (Deprecated)
- **bigquery**: Legacy monolithic BigQuery tool - use modular tools instead

## Tool Responsibilities

Each BigQuery tool has a specific responsibility:

1. **Schema Reader** - Know what columns exist in tables
2. **Query Builder** - Create SQL queries based on requirements
3. **Query Executor** - Send queries to BigQuery and manage jobs
4. **Data Fetcher** - Get results and process them

See `.claude/BIGQUERY_TOOLS.md` for complete BigQuery tools documentation.

## Settings

Claude Code configuration is in `.claude/settings.json` and `.claude/settings.local.json`.

See `.claude/AGENTS.md` for detailed agent documentation.
