"""Group Sale Management Agent - Manages group sales operations."""

import re
from ..base_agent import BaseAgent


class GroupSaleManagerAgent(BaseAgent):
    """Agent for managing group sales with BigQuery access."""

    def __init__(self):
        super().__init__(
            "group_sale_manager",
            "sales_manager",
            "read-write",
            ["thought", "schema_reader", "query_builder", "query_executor", "data_fetcher"],
        )
        self.identifier_pattern = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

    def _validate_identifier(self, name: str, field_type: str = "identifier") -> bool:
        """Validate identifier to prevent SQL injection."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Invalid {field_type}: empty or not a string")
        if not self.identifier_pattern.match(name):
            raise ValueError(f"Invalid {field_type} '{name}': must match pattern ^[A-Za-z_][A-Za-z0-9_]*$")
        return True

    def execute(self, task: str, run_id: str = "default", context: dict = None) -> dict:
        """
        Execute group sales management task.

        Args:
            task: Task description
            run_id: Unique run ID for tracking
            context: Optional context (filters, parameters)

        Returns:
            Execution result
        """
        context = context or {}

        # Analyze task using thought tool
        analysis = self.thought_tool.plan(task)

        return self._agent_result(
            success=True,
            task=task,
            response=f"Group Sale Manager: {task}",
            thinking=analysis,
            tools_used=self.tools,
            status="ready",
        )

    def query_sales(self, dataset: str, table: str, query_spec: dict) -> dict:
        """
        Query sales data from BigQuery using specialized tools.

        Args:
            dataset: Dataset name
            table: Table name
            query_spec: Query specification with columns, filters, etc
        """
        # Read schema
        schema_result = self.schema_reader.get_table_columns(dataset, table)
        if not schema_result["success"]:
            return {
                "success": False,
                "agent": "group_sale_manager",
                "operation": "query_sales",
                "error": schema_result.get("error"),
                "status": "failed"
            }

        # Build query
        columns = query_spec.get("columns")
        where_conditions = query_spec.get("where_conditions")
        group_by = query_spec.get("group_by")
        order_by = query_spec.get("order_by")
        limit = query_spec.get("limit", 1000)

        query_result = self.query_builder.build_select_query(
            dataset, table,
            columns=columns,
            where_conditions=where_conditions,
            group_by=group_by,
            order_by=order_by,
            limit=limit
        )

        # Execute query
        sql = query_result["sql"]
        execute_result = self.query_executor.execute_and_fetch(sql)
        job_id = execute_result.get("job_id")

        # Fetch results
        fetch_result = self.data_fetcher.fetch_results(job_id, max_results=limit)

        return {
            "success": True,
            "agent": "group_sale_manager",
            "operation": "query_sales",
            "dataset": dataset,
            "table": table,
            "schema": schema_result.get("columns", []),
            "sql": sql,
            "job_id": job_id,
            "rows": fetch_result.get("rows", []),
            "total_rows": fetch_result.get("total_rows", 0),
            "status": "completed"
        }

    def get_sales_summary(self, dataset: str, table: str, group_by: list = None) -> dict:
        """
        Get sales summary by group using BigQuery aggregation.

        Args:
            dataset: Dataset name
            table: Table name
            group_by: Columns to group by
        """
        group_by = group_by or ["group_id", "region"]
        aggregations = {
            "total_sales": "SUM",
            "average_sale": "AVG",
            "sale_count": "COUNT"
        }

        # Read schema
        schema_result = self.schema_reader.get_table_columns(dataset, table)

        # Build aggregation query
        query_result = self.query_builder.build_aggregate_query(
            dataset, table,
            aggregations=aggregations,
            group_by=group_by
        )

        # Execute query
        sql = query_result["sql"]
        execute_result = self.query_executor.execute_and_fetch(sql)
        job_id = execute_result.get("job_id")

        # Fetch results
        fetch_result = self.data_fetcher.fetch_results(job_id)

        return {
            "success": True,
            "agent": "group_sale_manager",
            "operation": "get_sales_summary",
            "dataset": dataset,
            "table": table,
            "group_by": group_by,
            "aggregations": aggregations,
            "sql": sql,
            "job_id": job_id,
            "rows": fetch_result.get("rows", []),
            "total_rows": fetch_result.get("total_rows", 0),
            "status": "completed"
        }

    def identify_top_groups(self, dataset: str, table: str, metric: str = "total_sales", limit: int = 10) -> dict:
        """
        Identify top performing groups.

        Args:
            dataset: Dataset name
            table: Table name
            metric: Metric to sort by (must be a valid column name)
            limit: Number of top groups to return (must be positive integer)
        """
        try:
            self._validate_identifier(metric, "metric column")
            if not isinstance(limit, int) or limit <= 0:
                raise ValueError(f"Invalid limit: must be a positive integer, got {limit}")
        except ValueError as e:
            return {
                "success": False,
                "agent": "group_sale_manager",
                "error": str(e),
                "status": "failed"
            }

        # Build query to get top groups
        aggregations = {metric: "SUM"}
        group_by = ["group_id"]

        query_result = self.query_builder.build_aggregate_query(
            dataset, table,
            aggregations=aggregations,
            group_by=group_by
        )

        # Append ORDER BY DESC and LIMIT (with validated values)
        sql = query_result["sql"] + f" ORDER BY {metric} DESC LIMIT {limit}"

        # Execute query
        execute_result = self.query_executor.execute_and_fetch(sql)
        job_id = execute_result.get("job_id")

        # Fetch results
        fetch_result = self.data_fetcher.fetch_results(job_id, max_results=limit)

        return {
            "success": True,
            "agent": "group_sale_manager",
            "operation": "identify_top_groups",
            "dataset": dataset,
            "table": table,
            "metric": metric,
            "limit": limit,
            "sql": sql,
            "job_id": job_id,
            "rows": fetch_result.get("rows", []),
            "status": "completed"
        }

    def evaluate_group_performance(self, dataset: str, table: str, group_id: str) -> dict:
        """
        Evaluate performance of a specific group.

        Args:
            dataset: Dataset name
            table: Table name
            group_id: Group ID to evaluate
        """
        # Build query for group performance
        query_result = self.query_builder.build_select_query(
            dataset, table,
            where_conditions={"group_id": group_id},
            limit=1000
        )

        # Execute query
        sql = query_result["sql"]
        execute_result = self.query_executor.execute_and_fetch(sql)
        job_id = execute_result.get("job_id")

        # Fetch results
        fetch_result = self.data_fetcher.fetch_results(job_id)
        rows = fetch_result.get("rows", [])

        # Get statistics on results
        stats_result = self.data_fetcher.get_statistics(rows)

        return {
            "success": True,
            "agent": "group_sale_manager",
            "operation": "evaluate_group_performance",
            "dataset": dataset,
            "table": table,
            "group_id": group_id,
            "sql": sql,
            "job_id": job_id,
            "total_records": fetch_result.get("total_rows", 0),
            "statistics": stats_result.get("statistics", {}),
            "status": "completed"
        }

    def export_sales_data(self, job_id: str, format: str, output_path: str) -> dict:
        """
        Export sales query results to file.

        Args:
            job_id: BigQuery job ID
            format: Export format (csv, json, parquet, avro)
            output_path: Path to save file
        """
        export_result = self.data_fetcher.export_results(
            job_id,
            export_format=format,
            output_path=output_path
        )

        return {
            "success": True,
            "agent": "group_sale_manager",
            "operation": "export_sales_data",
            "job_id": job_id,
            "format": format,
            "output_path": output_path,
            "file_size_bytes": export_result.get("file_size_bytes"),
            "rows_exported": export_result.get("rows_exported"),
            "status": "completed"
        }

    def join_sales_tables(self, dataset: str, left_table: str, right_table: str, on_conditions: dict) -> dict:
        """
        Join two sales tables.

        Args:
            dataset: Dataset name
            left_table: Left table name
            right_table: Right table name
            on_conditions: Join conditions
        """
        query_result = self.query_builder.build_join_query(
            dataset, left_table, right_table,
            join_type="INNER",
            on_conditions=on_conditions
        )

        sql = query_result["sql"]
        execute_result = self.query_executor.execute_and_fetch(sql)
        job_id = execute_result.get("job_id")

        fetch_result = self.data_fetcher.fetch_results(job_id)

        return {
            "success": True,
            "agent": "group_sale_manager",
            "operation": "join_sales_tables",
            "dataset": dataset,
            "left_table": left_table,
            "right_table": right_table,
            "sql": sql,
            "job_id": job_id,
            "rows": fetch_result.get("rows", []),
            "status": "completed"
        }
