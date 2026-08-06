"""Custom tools registry and management."""

from typing import Dict, List, Optional
from .base_tool import BaseTool


class ToolRegistry:
    """Centralized registry for custom tools."""

    def __init__(self):
        """Initialize empty tool registry."""
        self.tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        Register a custom tool.

        Args:
            tool: Tool instance to register
        """
        self.tools[tool.name] = tool

    def unregister(self, tool_name: str) -> bool:
        """
        Unregister a tool.

        Args:
            tool_name: Name of tool to unregister

        Returns:
            True if tool was registered and removed
        """
        if tool_name in self.tools:
            del self.tools[tool_name]
            return True
        return False

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """
        Get a tool by name.

        Args:
            tool_name: Name of tool to retrieve

        Returns:
            Tool instance or None if not found
        """
        return self.tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """
        List all registered tool names.

        Returns:
            List of tool names
        """
        return list(self.tools.keys())

    def get_tool_spec(self, tool_name: str) -> Optional[Dict]:
        """
        Get tool specification by name.

        Args:
            tool_name: Name of tool

        Returns:
            Tool spec dictionary or None
        """
        tool = self.get_tool(tool_name)
        return tool.get_spec() if tool else None

    def list_tool_specs(self) -> Dict[str, Dict]:
        """
        Get specifications for all registered tools.

        Returns:
            Dict mapping tool names to specs
        """
        return {name: tool.get_spec() for name, tool in self.tools.items()}


# Global registry instance
_global_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Get the global tool registry."""
    return _global_registry


def register_tool(tool: BaseTool) -> None:
    """Register a tool globally."""
    _global_registry.register(tool)


def get_tool(tool_name: str) -> Optional[BaseTool]:
    """Get a tool from global registry."""
    return _global_registry.get_tool(tool_name)


def list_tools() -> List[str]:
    """List all tools in global registry."""
    return _global_registry.list_tools()


__all__ = [
    "BaseTool",
    "ToolRegistry",
    "get_registry",
    "register_tool",
    "get_tool",
    "list_tools",
]
