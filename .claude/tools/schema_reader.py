"""Schema Reader Tool - Reads BigQuery table schemas from markdown files."""

import os
import json
from typing import Dict, Any, List, Optional


class SchemaReaderTool:
    """Tool for reading and parsing BigQuery table schemas from .md files."""

    def __init__(self):
        self.name = "schema_reader"
        self.description = "Read and parse BigQuery table schemas from markdown files"
        self.type = "schema_access"
        self.schema_dir = ".schemas"

    def read_schema_from_file(self, schema_file: str) -> Dict[str, Any]:
        """
        Read table schema from a markdown file.

        Args:
            schema_file: Path to the .md schema file

        Returns:
            Parsed schema information
        """
        if not os.path.exists(schema_file):
            return {
                "success": False,
                "tool": "schema_reader",
                "operation": "read_schema_from_file",
                "file": schema_file,
                "error": f"Schema file not found: {schema_file}",
                "status": "failed"
            }

        try:
            with open(schema_file, 'r', encoding='utf-8') as f:
                content = f.read()

            schema = self._parse_schema_markdown(content)
            return {
                "success": True,
                "tool": "schema_reader",
                "operation": "read_schema_from_file",
                "file": schema_file,
                "schema": schema,
                "status": "completed"
            }
        except Exception as e:
            return {
                "success": False,
                "tool": "schema_reader",
                "operation": "read_schema_from_file",
                "file": schema_file,
                "error": str(e),
                "status": "failed"
            }

    def _parse_schema_markdown(self, content: str) -> Dict[str, Any]:
        """Parse markdown schema file into structured format."""
        lines = content.split('\n')
        schema = {
            "tables": [],
            "columns": {},
            "metadata": {}
        }

        current_table = None
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith('## '):
                current_section = line[3:].strip()
            elif line.startswith('### '):
                current_table = line[4:].strip()
                schema["tables"].append(current_table)
                schema["columns"][current_table] = []
            elif line.startswith('- ') and current_table:
                col_info = self._parse_column_line(line[2:].strip())
                if col_info:
                    schema["columns"][current_table].append(col_info)
            elif ':' in line and current_section == 'Metadata':
                key, value = line.split(':', 1)
                schema["metadata"][key.strip()] = value.strip()

        return schema

    def _parse_column_line(self, line: str) -> Optional[Dict[str, str]]:
        """Parse a single column definition line."""
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 2:
            return {
                "name": parts[0],
                "type": parts[1] if len(parts) > 1 else "STRING",
                "description": parts[2] if len(parts) > 2 else ""
            }
        return None

    def get_table_columns(self, dataset: str, table: str) -> Dict[str, Any]:
        """
        Get columns for a specific table.

        Args:
            dataset: Dataset name
            table: Table name

        Returns:
            Column information
        """
        schema_file = f"{self.schema_dir}/{dataset}_{table}.md"
        result = self.read_schema_from_file(schema_file)

        if result["success"]:
            schema = result.get("schema", {})
            columns = schema.get("columns", {}).get(table, [])
            return {
                "success": True,
                "tool": "schema_reader",
                "operation": "get_table_columns",
                "dataset": dataset,
                "table": table,
                "columns": columns,
                "column_count": len(columns),
                "status": "completed"
            }

        return {
            "success": False,
            "tool": "schema_reader",
            "operation": "get_table_columns",
            "dataset": dataset,
            "table": table,
            "error": result.get("error"),
            "status": "failed"
        }

    def list_available_schemas(self) -> Dict[str, Any]:
        """
        List all available schema files in the schemas directory.

        Returns:
            List of available schemas
        """
        schemas = []
        if os.path.exists(self.schema_dir):
            for file in os.listdir(self.schema_dir):
                if file.endswith('.md'):
                    schemas.append(file)

        return {
            "success": True,
            "tool": "schema_reader",
            "operation": "list_available_schemas",
            "schemas": schemas,
            "count": len(schemas),
            "status": "completed"
        }

    def validate_schema_compatibility(self, schema: Dict[str, Any], required_columns: List[str]) -> Dict[str, Any]:
        """
        Validate that a schema contains all required columns.

        Args:
            schema: Schema dictionary
            required_columns: List of required column names

        Returns:
            Validation result
        """
        schema_columns = []
        for table_columns in schema.get("columns", {}).values():
            schema_columns.extend([col["name"] for col in table_columns])

        missing = [col for col in required_columns if col not in schema_columns]

        return {
            "success": len(missing) == 0,
            "tool": "schema_reader",
            "operation": "validate_schema_compatibility",
            "required_columns": required_columns,
            "available_columns": schema_columns,
            "missing_columns": missing,
            "status": "completed"
        }
