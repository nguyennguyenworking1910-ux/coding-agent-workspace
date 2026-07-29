"""Query Builder Tool - Creates SQL queries for BigQuery."""

import re
from typing import Dict, Any, List, Optional

from .tool_result import ToolResult


class QueryBuilderTool:
    """Tool for building SQL queries based on schema and requirements."""

    def __init__(self):
        self.name = "query_builder"
        self.description = "Build SQL queries for BigQuery operations"
        self.type = "query_builder"
        self.identifier_pattern = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

    def _validate_identifier(self, name: str, field_type: str = "identifier") -> bool:
        """Validate that an identifier (table, column, etc.) is safe.

        Args:
            name: The identifier to validate
            field_type: Type of field for error messages

        Returns:
            True if valid, raises ValueError if invalid
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Invalid {field_type}: empty or not a string")
        if not self.identifier_pattern.match(name):
            raise ValueError(f"Invalid {field_type} '{name}': must match pattern ^[A-Za-z_][A-Za-z0-9_]*$")
        return True

    def build_select_query(
        self,
        dataset: str,
        table: str,
        columns: Optional[List[str]] = None,
        where_conditions: Optional[Dict[str, Any]] = None,
        group_by: Optional[List[str]] = None,
        order_by: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Build a SELECT query.

        Args:
            dataset: Dataset name
            table: Table name
            columns: Columns to select (None = all)
            where_conditions: WHERE clause conditions as dict (values use parameters)
            group_by: Columns to group by
            order_by: Columns to order by
            limit: Row limit

        Returns:
            Query object with SQL string and parameters
        """
        # Validate identifiers
        self._validate_identifier(dataset, "dataset")
        self._validate_identifier(table, "table")

        select_clause = self._build_select(columns)
        from_clause = f"FROM `{dataset}.{table}`"
        where_clause, params = self._build_where(where_conditions) if where_conditions else ("", {})
        group_by_clause = self._build_group_by(group_by) if group_by else ""
        order_by_clause = self._build_order_by(order_by) if order_by else ""
        limit_clause = f"LIMIT {limit}" if limit and isinstance(limit, int) and limit > 0 else ""

        sql = " ".join([
            select_clause,
            from_clause,
            where_clause,
            group_by_clause,
            order_by_clause,
            limit_clause
        ]).strip()

        return ToolResult.ok(
            "query_builder",
            "build_select_query",
            query_type="SELECT",
            dataset=dataset,
            table=table,
            sql=sql,
            parameters=params,
            parameter_schema={
                "columns": columns or ["*"],
                "group_by": group_by or [],
                "order_by": order_by or [],
                "limit": limit
            },
        )

    def build_aggregate_query(
        self,
        dataset: str,
        table: str,
        aggregations: Dict[str, str],
        group_by: Optional[List[str]] = None,
        where_conditions: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build an aggregate query (SUM, COUNT, AVG, etc).

        Args:
            dataset: Dataset name
            table: Table name
            aggregations: Dict of {column: aggregation_function}
            group_by: Columns to group by
            where_conditions: WHERE clause conditions

        Returns:
            Aggregation query object
        """
        agg_clauses = []
        for column, func in aggregations.items():
            agg_clauses.append(f"{func}({column}) as {func}_{column}")

        select_clause = "SELECT " + ", ".join(agg_clauses)
        if group_by:
            select_clause = "SELECT " + ", ".join(group_by) + ", " + ", ".join(agg_clauses)

        from_clause = f"FROM `{dataset}.{table}`"
        where_clause = self._build_where(where_conditions) if where_conditions else ""
        group_by_clause = self._build_group_by(group_by) if group_by else ""

        sql = " ".join([
            select_clause,
            from_clause,
            where_clause,
            group_by_clause
        ]).strip()

        return ToolResult.ok(
            "query_builder",
            "build_aggregate_query",
            query_type="AGGREGATE",
            dataset=dataset,
            table=table,
            sql=sql,
            parameters={
                "aggregations": aggregations,
                "group_by": group_by or [],
                "where_conditions": where_conditions or {}
            },
        )

    def build_insert_query(
        self,
        dataset: str,
        table: str,
        columns: List[str],
        values: List[List[Any]]
    ) -> Dict[str, Any]:
        """
        Build an INSERT query.

        Args:
            dataset: Dataset name
            table: Table name
            columns: Column names
            values: List of value lists

        Returns:
            Insert query object
        """
        col_str = ", ".join(columns)
        values_strs = []
        for row in values:
            formatted_vals = []
            for val in row:
                if isinstance(val, str):
                    formatted_vals.append(f"'{val}'")
                elif val is None:
                    formatted_vals.append("NULL")
                else:
                    formatted_vals.append(str(val))
            values_strs.append(f"({', '.join(formatted_vals)})")

        sql = f"INSERT INTO `{dataset}.{table}` ({col_str}) VALUES {', '.join(values_strs)}"

        return ToolResult.ok(
            "query_builder",
            "build_insert_query",
            query_type="INSERT",
            dataset=dataset,
            table=table,
            sql=sql,
            parameters={
                "columns": columns,
                "rows": len(values)
            },
        )

    def build_join_query(
        self,
        dataset: str,
        left_table: str,
        right_table: str,
        join_type: str = "INNER",
        on_conditions: Optional[Dict[str, str]] = None,
        columns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Build a JOIN query.

        Args:
            dataset: Dataset name
            left_table: Left table name
            right_table: Right table name
            join_type: JOIN type (INNER, LEFT, RIGHT, FULL)
            on_conditions: ON clause conditions
            columns: Columns to select

        Returns:
            Join query object
        """
        select_clause = self._build_select(columns)
        from_clause = f"FROM `{dataset}.{left_table}` {join_type} JOIN `{dataset}.{right_table}`"

        on_clause = ""
        if on_conditions:
            conditions = [f"{k} = {v}" for k, v in on_conditions.items()]
            on_clause = "ON " + " AND ".join(conditions)

        sql = " ".join([select_clause, from_clause, on_clause]).strip()

        return ToolResult.ok(
            "query_builder",
            "build_join_query",
            query_type="JOIN",
            dataset=dataset,
            tables=[left_table, right_table],
            join_type=join_type,
            sql=sql,
        )

    def _build_select(self, columns: Optional[List[str]] = None) -> str:
        """Build SELECT clause with validated column names."""
        if not columns or len(columns) == 0:
            return "SELECT *"
        validated = []
        for col in columns:
            self._validate_identifier(col, "column")
            validated.append(col)
        return f"SELECT {', '.join(validated)}"

    def _build_where(self, conditions: Dict[str, Any]) -> tuple:
        """Build WHERE clause with parameterized queries.

        Returns:
            Tuple of (where_clause_sql, parameters_dict)
        """
        if not conditions:
            return "", {}
        conditions_list = []
        params = {}
        param_idx = 0

        for key, value in conditions.items():
            self._validate_identifier(key, "column")
            param_key = f"@param_{param_idx}"
            param_idx += 1

            if isinstance(value, str):
                conditions_list.append(f"{key} = {param_key}")
                params[param_key] = value
            elif isinstance(value, (list, tuple)):
                if len(value) == 2 and value[0] in ['>', '<', '>=', '<=', '!=']:
                    param_key = f"@param_{param_idx}"
                    param_idx += 1
                    conditions_list.append(f"{key} {value[0]} {param_key}")
                    params[param_key] = value[1]
                else:
                    in_params = []
                    for v in value:
                        param_key = f"@param_{param_idx}"
                        param_idx += 1
                        in_params.append(param_key)
                        params[param_key] = v
                    conditions_list.append(f"{key} IN ({', '.join(in_params)})")
            else:
                conditions_list.append(f"{key} = {param_key}")
                params[param_key] = value

        return ("WHERE " + " AND ".join(conditions_list), params)

    def _build_group_by(self, columns: List[str]) -> str:
        """Build GROUP BY clause with validated column names."""
        if not columns:
            return ""
        validated = []
        for col in columns:
            self._validate_identifier(col, "column")
            validated.append(col)
        return f"GROUP BY {', '.join(validated)}"

    def _build_order_by(self, columns: List[str]) -> str:
        """Build ORDER BY clause with validated column names."""
        if not columns:
            return ""
        validated = []
        for col in columns:
            self._validate_identifier(col, "column")
            validated.append(col)
        return f"ORDER BY {', '.join(validated)}"
