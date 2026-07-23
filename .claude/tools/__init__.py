"""Tool implementations for agents."""

from .thought import ThoughtTool
from .schema_reader import SchemaReaderTool
from .query_builder import QueryBuilderTool
from .query_executor import QueryExecutorTool
from .data_fetcher import DataFetcherTool

__all__ = [
    "ThoughtTool",
    "SchemaReaderTool",
    "QueryBuilderTool",
    "QueryExecutorTool",
    "DataFetcherTool"
]

# Tool registry
TOOLS = {
    "thought": ThoughtTool,
    "schema_reader": SchemaReaderTool,
    "query_builder": QueryBuilderTool,
    "query_executor": QueryExecutorTool,
    "data_fetcher": DataFetcherTool,
}

def get_tool(name: str):
    """Get tool by name."""
    return TOOLS.get(name)

def list_tools():
    """List all available tools."""
    return list(TOOLS.keys())
