# Refactoring Plan: Stub Implementations
**coding-agent-workspace** - Migration path for incomplete features

**Date:** 2026-07-28  
**Status:** Planning phase

---

## Overview

This document outlines the strategy for handling stub implementations in the codebase. Four BigQuery tools and GroupSaleManagerAgent currently return mock data and are not production-ready.

**Options:**
1. **Complete Implementation** - Add real BigQuery connectivity
2. **Mark as Experimental** - Document as mock/example code
3. **Remove Entirely** - Delete if not in roadmap

---

## Component Status

### Stub Components

| Component | Purpose | Status | Current | Recommendation |
|-----------|---------|--------|---------|-----------------|
| schema_reader.py | Read BigQuery table schemas | Mock only | Returns hardcoded schema | Complete ⭐ or Remove ❌ |
| query_builder.py | Build SQL queries | Mock only | Returns sample queries | Complete ⭐ or Remove ❌ |
| query_executor.py | Execute BigQuery queries | Mock only | Returns fake job IDs | Complete ⭐ or Remove ❌ |
| data_fetcher.py | Fetch query results | Mock only | Returns empty results | Complete ⭐ or Remove ❌ |
| group_sale_manager.py | Sales operations agent | Partial | Uses stub tools | Complete ⭐ or Remove ❌ |

---

## Option 1: Complete Implementation (If BigQuery is Needed)

### Requirements
1. Google Cloud SDK authentication
2. `google-cloud-bigquery` Python library
3. BigQuery project credentials
4. Actual dataset and table access

### Implementation Steps

#### Phase 1: Add Dependencies

Update `pyproject.toml`:
```python
[project]
dependencies = [
    # ... existing ...
    "google-cloud-bigquery>=3.0.0",
    "google-auth>=2.0.0",
]
```

#### Phase 2: Implement Authentication

Create `.claude/tools/bigquery_auth.py`:
```python
"""BigQuery Authentication Handler"""

from google.cloud import bigquery
from google.oauth2 import service_account
import os

class BigQueryAuthenticator:
    """Handles BigQuery authentication and client management."""
    
    def __init__(self):
        self.client = None
        self.project_id = None
        
    def authenticate(self, credentials_path: str = None, project_id: str = None):
        """
        Authenticate with BigQuery.
        
        Args:
            credentials_path: Path to service account JSON (or use ADC)
            project_id: GCP project ID
            
        Returns:
            BigQuery client instance
        """
        if credentials_path:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path
            )
            self.client = bigquery.Client(
                credentials=credentials,
                project=project_id
            )
        else:
            # Use Application Default Credentials
            self.client = bigquery.Client(project=project_id)
        
        self.project_id = project_id or self.client.project
        return self.client
    
    def get_client(self):
        """Get authenticated BigQuery client."""
        if not self.client:
            self.authenticate()
        return self.client
```

#### Phase 3: Implement SchemaReaderTool

```python
"""Schema Reader - Real Implementation"""

from google.cloud import bigquery
from typing import Dict, Any, List, Optional

class SchemaReaderTool:
    """Read BigQuery table schemas directly from database."""
    
    def __init__(self, bigquery_client: bigquery.Client = None):
        self.name = "schema_reader"
        self.client = bigquery_client or bigquery.Client()
    
    def get_table_columns(self, dataset: str, table: str) -> Dict[str, Any]:
        """
        Get columns for a BigQuery table.
        
        Args:
            dataset: Dataset name
            table: Table name
            
        Returns:
            Schema information
        """
        try:
            table_ref = self.client.get_table(f"{dataset}.{table}")
            
            columns = []
            for field in table_ref.schema:
                columns.append({
                    "name": field.name,
                    "type": field.field_type,
                    "mode": field.mode,
                    "description": field.description or ""
                })
            
            return {
                "success": True,
                "columns": columns,
                "total_columns": len(columns),
                "status": "completed"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "status": "failed"
            }
```

#### Phase 4: Implement QueryExecutorTool

```python
"""Query Executor - Real Implementation"""

from google.cloud import bigquery
from typing import Dict, Any, Optional

class QueryExecutorTool:
    """Execute real BigQuery queries."""
    
    def __init__(self, bigquery_client: bigquery.Client = None):
        self.name = "query_executor"
        self.client = bigquery_client or bigquery.Client()
    
    def execute_query(
        self,
        sql: str,
        project_id: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Execute a BigQuery query."""
        try:
            config = bigquery.QueryJobConfig(
                dry_run=dry_run,
                use_query_cache=True
            )
            
            job = self.client.query(sql, job_config=config)
            
            return {
                "success": True,
                "job_id": job.job_id,
                "state": job.state(),
                "status": "queued" if not dry_run else "validated"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "status": "failed"
            }
```

#### Phase 5: Update GroupSaleManagerAgent

Remove mock implementation, use real BigQuery tools:
```python
"""Group Sale Manager - Real Implementation"""

from google.cloud import bigquery

class GroupSaleManagerAgent:
    """Real sales operations agent with BigQuery access."""
    
    def __init__(self, bigquery_client: bigquery.Client = None):
        self.client = bigquery_client or bigquery.Client()
        self.tools = [
            "schema_reader", "query_builder", 
            "query_executor", "data_fetcher"
        ]
    
    def get_sales_summary(self, dataset: str, table: str) -> Dict[str, Any]:
        """Get sales summary from BigQuery."""
        # Use real tools to query BigQuery
        query = f"""
            SELECT 
                COUNT(*) as total_sales,
                SUM(amount) as total_revenue,
                AVG(amount) as avg_sale
            FROM `{dataset}.{table}`
        """
        # Execute and return real results
        ...
```

#### Phase 6: Update Configuration

In `agents.json`, update BigQuery settings:
```json
{
  "bigquery_config": {
    "project_id": "${GCP_PROJECT_ID}",
    "credentials_path": "${GCP_CREDENTIALS_PATH}",
    "datasets": {
      "group_sales": {
        "tables": ["sales", "group_metadata", "transactions"]
      },
      "sales_metrics": {
        "tables": ["daily_summary", "trends"]
      }
    }
  }
}
```

#### Phase 7: Add Tests

Create `.claude/tests/test_bigquery_tools.py`:
```python
"""Tests for real BigQuery tools"""

import unittest
from unittest.mock import Mock, patch
from tools.schema_reader import SchemaReaderTool
from tools.query_executor import QueryExecutorTool

class TestBigQueryTools(unittest.TestCase):
    """Test BigQuery tool implementations."""
    
    @patch('google.cloud.bigquery.Client')
    def test_schema_reader(self, mock_client):
        """Test schema reading from real BigQuery."""
        tool = SchemaReaderTool(mock_client)
        # Test implementation...
```

---

## Option 2: Mark as Experimental (Keep as Mocks)

### For Each Stub Tool

Add docstring clearly marking as experimental:
```python
"""Schema Reader Tool - EXPERIMENTAL/MOCK IMPLEMENTATION"""

class SchemaReaderTool:
    """
    Tool for reading BigQuery table schemas.
    
    ⚠️ EXPERIMENTAL: Current implementation returns mock data.
    For production use, implement real BigQuery API integration.
    See REFACTORING_PLAN.md for completion guide.
    """
```

### Update agents.json

Add deprecation notice:
```json
{
  "id": "schema_reader",
  "deprecated": true,
  "status": "experimental",
  "warning": "Mock implementation - returns sample data only",
  "completion_guide": "See REFACTORING_PLAN.md"
}
```

### Add to Documentation

Update `CODEBASE_DOCUMENTATION.md`:
```markdown
## Experimental Features

### BigQuery Tools (Mocks)
- schema_reader.py - EXPERIMENTAL
- query_builder.py - EXPERIMENTAL  
- query_executor.py - EXPERIMENTAL
- data_fetcher.py - EXPERIMENTAL

These tools currently return mock data for demonstration purposes.
For production BigQuery integration, see REFACTORING_PLAN.md.
```

---

## Option 3: Remove Entirely

### If Not in Roadmap

Simply delete:
```bash
rm .claude/tools/schema_reader.py
rm .claude/tools/query_builder.py
rm .claude/tools/query_executor.py
rm .claude/tools/data_fetcher.py
rm .claude/agents/business/group_sale_manager.py
```

### Clean Up Imports

In `.claude/tools/__init__.py`:
```python
# REMOVE:
from .schema_reader import SchemaReaderTool
from .query_builder import QueryBuilderTool
from .query_executor import QueryExecutorTool
from .data_fetcher import DataFetcherTool

# REMOVE from TOOLS dict and __all__
```

In `.claude/agents/technical/team_leader.py`:
```python
# REMOVE from TASK_PATTERNS:
"data_operations": [...]

# REMOVE from _determine_agents():
elif task_type == "data_operations":
    agents = ["group_sale_manager"]

# REMOVE from _build_workflow_steps():
if "group_sale_manager" in agents:
    ...
```

---

## Recommendation Matrix

| Use Case | Choose | Effort | Timeline |
|----------|--------|--------|----------|
| **BigQuery integration planned** | Option 1 (Complete) | High | 2-3 weeks |
| **Learning/demo project** | Option 2 (Mark Experimental) | Low | 1 day |
| **Not in roadmap** | Option 3 (Remove) | Low | 1 day |
| **Unsure/Future consideration** | Option 2 (Mark Experimental) | Low | 1 day |

---

## Current Recommendation

Based on codebase analysis:

### ✅ **Recommended: Option 2 (Mark as Experimental)**

**Reasons:**
1. **Lowest risk** - keeps door open for future implementation
2. **Clear documentation** - prevents confusion
3. **Minimal effort** - 1 day of work
4. **Non-blocking** - doesn't impede current functionality
5. **Team learning** - keeps example code for reference

**Steps:**
1. Add deprecation docstrings to all 4 BigQuery tools
2. Add deprecation notice to GroupSaleManagerAgent
3. Update agents.json with "deprecated": true
4. Add section to CODEBASE_DOCUMENTATION.md
5. Link to this REFACTORING_PLAN.md from docs

---

## Implementation Timeline

If choosing **Option 2** (Recommended):

**Day 1:**
- [ ] Add deprecation notices to all stub files
- [ ] Update agents.json
- [ ] Update CODEBASE_DOCUMENTATION.md
- [ ] Commit with message: "Mark BigQuery tools as experimental/mock"

**If choosing Option 1** (Complete Implementation):
- Week 1: Setup BigQuery auth, add dependencies
- Week 2: Implement each tool with real BigQuery API
- Week 3: Add tests, documentation, handle edge cases

**If choosing Option 3** (Remove):
- 1 hour: Delete files
- 1 hour: Clean up imports
- 30 min: Update documentation

---

## Questions to Answer

1. **Is BigQuery integration part of the roadmap?**
   - Yes → Choose Option 1
   - No → Choose Option 3
   - Maybe → Choose Option 2

2. **Do you want to keep example code for reference?**
   - Yes → Choose Option 2
   - No → Choose Option 3

3. **Is this for production use?**
   - Yes → Choose Option 1 or 3
   - No → Choose Option 2

---

## Files Affected by Refactoring

- `.claude/tools/schema_reader.py`
- `.claude/tools/query_builder.py`
- `.claude/tools/query_executor.py`
- `.claude/tools/data_fetcher.py`
- `.claude/agents/business/group_sale_manager.py`
- `.claude/agents/technical/team_leader.py`
- `.claude/agents/business/__init__.py`
- `.claude/tools/__init__.py`
- `agents.json`
- `CODEBASE_DOCUMENTATION.md`

---

## Next Steps

1. **Decision**: Choose Option 1, 2, or 3
2. **Planning**: If Option 1, create detailed implementation spec
3. **Execution**: Follow the steps in chosen option
4. **Testing**: Verify no breaking changes to other agents
5. **Documentation**: Update all guides

---

## Related Documents

- See: `CODEBASE_ANALYSIS.md` - Detailed code analysis
- See: `CODEBASE_DOCUMENTATION.md` - System architecture
