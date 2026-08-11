"""BigQuery tools: run `.sql` templates and ad-hoc queries with named parameters.

Registered in `.claude/agents.json` as `bigquery_tools`. Driven by
`.claude/bq_query.py` from a shell, and usable directly by any agent:

    from claude.agents.tools.bigquery import BIGQUERY_TOOLS
    BIGQUERY_TOOLS["run_template"]("daily_counts", {"start_date": date(2026, 8, 1)})

See .claude/documents/BIGQUERY_INTEGRATION.md.
"""

from .templates import (
    TemplateError,
    describe_template,
    describe_templates,
    extract_param_names,
    get_template,
    is_valid_param_name,
    list_templates,
    template_dir,
    validate_params,
)
from .query_runner import (
    build_query_parameters,
    get_bigquery_client,
    get_table_schema,
    list_datasets,
    list_tables,
    run_sql,
    run_template,
)

# Tool registry for easy access
BIGQUERY_TOOLS = {
    "list_templates": describe_templates,
    "describe_template": describe_template,
    "run_template": run_template,
    "run_sql": run_sql,
    "list_datasets": list_datasets,
    "list_tables": list_tables,
    "get_table_schema": get_table_schema,
}

__all__ = [
    "BIGQUERY_TOOLS",
    "TemplateError",
    "build_query_parameters",
    "describe_template",
    "describe_templates",
    "extract_param_names",
    "get_bigquery_client",
    "get_table_schema",
    "get_template",
    "is_valid_param_name",
    "list_datasets",
    "list_tables",
    "list_templates",
    "run_sql",
    "run_template",
    "template_dir",
    "validate_params",
]
