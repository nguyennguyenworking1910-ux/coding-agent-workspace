"""Abstract base class for tools."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, List


@dataclass
class ToolInput:
    """Represents tool input schema."""
    name: str
    type: str
    description: str
    required: bool = True


@dataclass
class ToolOutput:
    """Represents tool output schema."""
    name: str
    type: str
    description: str


class BaseTool(ABC):
    """Abstract base class for all tools."""

    def __init__(self, name: str, description: str):
        """Initialize tool with name and description."""
        self.name = name
        self.description = description

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """
        Execute the tool with given inputs.

        Returns:
            Tool output result
        """
        pass

    @abstractmethod
    def get_input_schema(self) -> List[ToolInput]:
        """Return the input schema for this tool."""
        pass

    @abstractmethod
    def get_output_schema(self) -> ToolOutput:
        """Return the output schema for this tool."""
        pass

    def get_spec(self) -> Dict[str, Any]:
        """Return tool specification."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": [
                {
                    "name": inp.name,
                    "type": inp.type,
                    "description": inp.description,
                    "required": inp.required,
                }
                for inp in self.get_input_schema()
            ],
            "output_schema": {
                "name": self.get_output_schema().name,
                "type": self.get_output_schema().type,
                "description": self.get_output_schema().description,
            },
        }
