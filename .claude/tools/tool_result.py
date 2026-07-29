"""ToolResult factory - consistent return-value envelopes for all tools."""

from typing import Any, Dict, Optional


class ToolResult:
    """Factory for the shared tool return envelope.

    Every result orders its keys the same way: ``success`` and ``tool``
    first, an optional ``operation``, then tool-specific payload fields,
    with ``status`` always last. Payload field names are passed through
    unchanged so callers that read them keep working.
    """

    @staticmethod
    def ok(
        tool_name: str,
        operation: Optional[str] = None,
        *,
        success: bool = True,
        status: str = "completed",
        **fields: Any,
    ) -> Dict[str, Any]:
        """Build a success envelope.

        ``success`` defaults to True but may be overridden for
        validation-style results whose outcome is data-dependent while
        the operation itself still completed.
        """
        return ToolResult._build(success, tool_name, operation, status, fields)

    @staticmethod
    def fail(
        tool_name: str,
        operation: Optional[str] = None,
        error: str = "",
        *,
        status: str = "failed",
        **fields: Any,
    ) -> Dict[str, Any]:
        """Build a failure envelope carrying an ``error`` message."""
        return ToolResult._build(
            False, tool_name, operation, status, fields, error=error
        )

    @staticmethod
    def _build(
        success: bool,
        tool_name: str,
        operation: Optional[str],
        status: str,
        fields: Dict[str, Any],
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {"success": success, "tool": tool_name}
        if operation is not None:
            result["operation"] = operation
        if error is not None:
            result["error"] = error
        result.update(fields)
        result["status"] = status
        return result
