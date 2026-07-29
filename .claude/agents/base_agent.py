"""BaseAgent - Shared foundation for all agents."""

from tools import get_tool


class BaseAgent:
    """Base class providing common agent init, tool wiring, and I/O helpers."""

    def __init__(self, name, type, mode, tool_names):
        self.name = name
        self.type = type
        self.mode = mode
        self.tool_names = tool_names
        self.tools = tool_names
        self._init_tools()

    def _init_tools(self):
        """Instantiate registered tools as named attributes."""
        for name in self.tool_names:
            tool_cls = get_tool(name)
            if tool_cls is None:
                continue
            attr = "thought_tool" if name == "thought" else name
            setattr(self, attr, tool_cls())

    def _print_header(self, task, run_id):
        """Print the standard run header banner."""
        print(f"\n{'='*70}")
        print(f"AGENT: {self.name.upper()}")
        print(f"RUN ID: {run_id}")
        print(f"TASK: {task}")
        print(f"{'='*70}\n")

    def _print_footer(self, status="COMPLETED"):
        """Print the standard run completion footer."""
        print(f"\n{'='*70}")
        print(f"STATUS: {status}")
        print(f"{'='*70}\n")

    def _agent_result(self, success=True, **kwargs):
        """Build a result dict tagged with success flag and agent name."""
        return {"success": success, "agent": self.name, **kwargs}
