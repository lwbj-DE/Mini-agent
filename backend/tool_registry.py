"""Tool registry — register, discover, and execute tools."""

from typing import Any

from .tools.base import BaseTool


class ToolRegistry:
    """Holds all available tools and provides schema/execution access.

    Tools can be stateless (calculator, search) or stateful (todo).
    Stateful tools have their state saved/restored via get_state() / set_state().
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if it was registered."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def schemas(self) -> list[dict]:
        """Return OpenAI function-calling schemas for all registered tools."""
        return [t.schema() for t in self._tools.values()]

    def execute(self, name: str, **kwargs: Any) -> str:
        """Execute a tool by name.

        Args:
            name: Tool name.
            **kwargs: Arguments matching the tool's parameter schema.

        Returns:
            String result to feed back to the LLM.

        Raises:
            KeyError: If the tool is not registered.
        """
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tools.keys()))
            return (
                f"Error: tool '{name}' is not registered. "
                f"Available tools: {available}"
            )
        try:
            return tool.execute(**kwargs)
        except Exception as exc:
            return f"Error executing '{name}': {exc}"

    def get_state(self) -> dict:
        """Collect serializable state from all stateful tools."""
        return {
            name: tool.get_state()
            for name, tool in self._tools.items()
        }

    def set_state(self, state: dict) -> None:
        """Restore state to all tools that have saved state."""
        for name, tool_state in state.items():
            tool = self._tools.get(name)
            if tool is not None:
                tool.set_state(tool_state)

    def list_tools(self) -> list[str]:
        """Return names of all registered tools."""
        return sorted(self._tools.keys())
