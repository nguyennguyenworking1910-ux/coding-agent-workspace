# Agent Team System

Unified agent system with code management and sales operations capabilities.

## Code Management Agents

### Team Leader (Coordinator)
- Orchestrates other agents
- Creates execution plans using **Thought Tool**
- Spawns workers as needed
- Synthesizes results
- **Mode**: Read-only
- **Tools**: Thought (planning)

### Diagnostician (Analyzer)
- Analyzes code using **Thought Tool**
- Finds bugs and issues
- Reports findings
- **Mode**: Read-only
- **Tools**: Thought (analysis)

### Bug Fixer (Implementer)
- Fixes bugs using **Thought Tool** for planning
- Implements changes
- Modifies files
- **Mode**: Write access
- **Tools**: Thought (planning)

### Reviewer (Validator)
- Reviews changes using **Thought Tool**
- Validates quality
- Approves or rejects
- **Mode**: Read-only
- **Tools**: Thought (evaluation)

## Sales Management Agent

### Group Sale Manager
- **Type**: Sales Manager
- **Mode**: Read-Write
- **Tools**: BigQuery + Thought Tool
- **Description**: Manages group sales operations and analytics

**Capabilities**:
- `query_sales(sql)` - Execute custom BigQuery queries
- `get_sales_summary(group_by)` - Get aggregated sales data
- `identify_top_groups(metric, limit)` - Find top performing groups
- `evaluate_group_performance(group_id)` - Analyze specific group performance

**BigQuery Access**:
- Datasets: `group_sales`, `sales_metrics`
- Operations: query, insert, update, aggregate
- Permissions: Read-Write

## Tools

### Thought Tool (Reasoning)
**Description**: Reasoning and thinking capability for agents

**Methods**:
- `execute(thought)` - Execute a thought/reasoning step
- `analyze(task, context)` - Analyze a task through reasoning
- `plan(goal, constraints)` - Create a plan through reasoning
- `evaluate(statement, criteria)` - Evaluate something through reasoning

**Used by**: All agents for decision-making and planning

### BigQuery Tool (Data Access)
**Description**: Query and manage BigQuery datasets for sales data

**Methods**:
- `query(sql, project_id)` - Execute SQL queries
- `list_tables(dataset_id)` - List tables in dataset
- `get_table_schema(dataset_id, table_id)` - Get table structure
- `insert_rows(dataset_id, table_id, rows)` - Insert data
- `get_group_sales_data(filters)` - Get sales data
- `aggregate_sales(group_by, metrics)` - Aggregate metrics

**Datasets**:
- `group_sales` - Main sales data
- `sales_metrics` - Aggregated metrics

## How to Use

### Code Management
```bash
# Spawn team leader for code tasks
/agents spawn team_leader "analyze this bug"

# Or specific agent
/agents spawn diagnostician "review this code"
```

### Sales Management
```bash
# Query sales data
Ask Claude to: "Query sales data for Q4"

# Show top performing groups
Ask Claude to: "Show top 10 performing groups"

# Evaluate group performance
Ask Claude to: "Evaluate performance of group XYZ"

# Get sales summary
Ask Claude to: "Get sales summary by region"
```

## Configuration

Edit `agents.json` to:
- Enable/disable agents
- Modify permissions
- Add/remove tools from agents
- Configure BigQuery dataset access
- Change operational capabilities

## File Structure

```
.claude/
├── agents.json         # Agent & tool definitions
├── AGENTS.md          # This file
├── settings.json      # Configuration
│
├── agents/            # Agent implementations
│   ├── __init__.py    (registry)
│   ├── team_leader.py
│   ├── diagnostician.py
│   ├── bug_fixer.py
│   ├── reviewer.py
│   └── group_sale_manager.py
│
└── tools/             # Tool implementations
    ├── __init__.py    (registry)
    ├── thought.py     (Thought Tool)
    └── bigquery.py    (BigQuery Tool)
```

## Tool Connection Flow

```
Agent created
    ↓
Agent._init_tools()
    ↓
get_tool("thought") or get_tool("bigquery")
    ↓
Tool instance created
    ↓
Agent can call tool methods
    ↓
Tool executes operation
    ↓
Result included in agent response
```
