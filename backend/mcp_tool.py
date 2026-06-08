"""MCPTool — wraps a remote MCP tool as a local BaseTool.

The Agent sees no difference between local and MCP tools.
"""

from __future__ import annotations

from typing import Any

from .mcp_client import MCPClient
from .tools.base import BaseTool


class MCPTool(BaseTool):
    """Proxy that forwards execute() to a remote MCP server."""

    def __init__(self, client: MCPClient, tool_def) -> None:
        self._client = client
        self._name = tool_def.name
        self._description = tool_def.description
        self._parameters = tool_def.inputSchema
        self._server_name = client.server_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return self._parameters

    @property
    def source(self) -> str:
        """Human-readable origin label."""
        return f"mcp:{self._server_name}"

    def execute(self, **kwargs: Any) -> str:
        return self._client.call_tool(self._name, kwargs)
