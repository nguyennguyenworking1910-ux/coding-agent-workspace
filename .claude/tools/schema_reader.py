"""Schema Reader Tool - Reads BigQuery table schemas from markdown files."""

import os
import re
import json
from typing import Dict, Any, List, Optional

from .tool_result import ToolResult


class SchemaReaderTool:
    """Tool for reading and parsing BigQuery table schemas from .md files."""

    def __init__(self):
        self.name = "schema_reader"
        self.description = "Read and parse BigQuery table schemas from markdown files"
        self.type = "schema_access"
        self.schema_dir = ".schemas"
        self.identifier_pattern = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

    def _validate_identifier(self, name: str, field_type: str = "identifier") -> bool:
        """Validate identifier to prevent path traversal.

        Args:
            name: The identifier to validate
            field_type: Type for error messages

        Returns:
            True if valid, raises ValueError if invalid
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Invalid {field_type}: empty or not a string")
        if not self.identifier_pattern.match(name):
            raise ValueError(f"Invalid {field_type} '{name}': must match pattern ^[A-Za-z_][A-Za-z0-9_]*$")
        return True

    def read_schema_from_file(self, schema_file: str) -> Dict[str, Any]:
        """
        Read table schema from a markdown file.

        Args:
            schema_file: Path to the .md schema file

        Returns:
            Parsed schema information
        """
        if not os.path.exists(schema_file):
            return ToolResult.fail(
                "schema_reader",
                "read_schema_from_file",
                f"Schema file not found: {schema_file}",
                file=schema_file,
            )

        try:
            with open(schema_file, 'r', encoding='utf-8') as f:
                content = f.read()

            schema = self._parse_schema_markdown(content)
            return ToolResult.ok(
                "schema_reader",
                "read_schema_from_file",
                file=schema_file,
                schema=schema,
            )
        except Exception as e:
            return ToolResult.fail(
                "schema_reader",
                "read_schema_from_file",
                str(e),
                file=schema_file,
            )

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
        try:
            self._validate_identifier(dataset, "dataset")
            self._validate_identifier(table, "table")
        except ValueError as e:
            return ToolResult.fail(
                "schema_reader",
                "get_table_columns",
                str(e),
            )

        schema_file = f"{self.schema_dir}/{dataset}_{table}.md"
        result = self.read_schema_from_file(schema_file)

        if result["success"]:
            schema = result.get("schema", {})
            columns = schema.get("columns", {}).get(table, [])
            return ToolResult.ok(
                "schema_reader",
                "get_table_columns",
                dataset=dataset,
                table=table,
                columns=columns,
                column_count=len(columns),
            )

        return ToolResult.fail(
            "schema_reader",
            "get_table_columns",
            result.get("error"),
            dataset=dataset,
            table=table,
        )

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

        return ToolResult.ok(
            "schema_reader",
            "list_available_schemas",
            schemas=schemas,
            count=len(schemas),
        )

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

        return ToolResult.ok(
            "schema_reader",
            "validate_schema_compatibility",
            success=len(missing) == 0,
            required_columns=required_columns,
            available_columns=schema_columns,
            missing_columns=missing,
        )
