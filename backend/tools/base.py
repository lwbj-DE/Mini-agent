"""Base class for all Agent tools."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolExecResult:
    """Result of a tool execution."""

    success: bool
    content: str
    error: str | None = None


class BaseTool(ABC):
    """Abstract base for all tools.

    Tools can be stateless (calculator, search) or stateful (todo).
    Stateful tools implement get_state() / set_state() for session persistence.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier used in function calling."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description shown to the LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for the tool's arguments."""
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Execute the tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments matching the schema.

        Returns:
            String result to feed back to the LLM.
        """
        ...

    @property
    def source(self) -> str:
        """Human-readable origin label. Override in MCPTool."""
        return "local"

    def schema(self) -> dict:
        """Return the OpenAI function-calling schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def get_state(self) -> dict:
        """Return serializable tool state for session persistence.

        Override in stateful tools.
        """
        return {}

    def set_state(self, state: dict) -> None:
        """Restore tool state from a previously saved session.

        Override in stateful tools.
        """
        pass
