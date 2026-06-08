"""Dynamic tool loader — reads tools.yaml and instantiates tools.

Supports two sources:
- Local tools: Python classes (module + class in YAML)
- MCP tools:   remote tools discovered from MCP servers

Hot-reload via POST /api/tools/reload re-reads the YAML and refreshes both.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from .tools.base import BaseTool
from .tool_registry import ToolRegistry
from .mcp_client import create_mcp_clients
from .mcp_tool import MCPTool

# Default config path (relative to project root)
CONFIG_PATH = Path(__file__).resolve().parent.parent / "tools.yaml"


# ------------------------------------------------------------------
# YAML helpers
# ------------------------------------------------------------------

def _read_config(path: str | None = None) -> dict:
    config_path = Path(path) if path else CONFIG_PATH
    if not config_path.exists():
        logger.warning(f"工具配置文件不存在: {config_path}")
        return {"tools": [], "mcp_servers": []}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ------------------------------------------------------------------
# local tools
# ------------------------------------------------------------------

def load_tools_from_yaml(path: str | None = None) -> list[BaseTool]:
    """Parse the 'tools' section and return instantiated local tool objects."""
    config = _read_config(path)
    tools: list[BaseTool] = []
    for entry in config.get("tools", []):
        if not entry.get("enabled", True):
            logger.info(f"工具已禁用: {entry.get('name', '?')}")
            continue
        try:
            tool = _instantiate_tool(entry)
            tools.append(tool)
            logger.info(f"本地工具已加载: {tool.name} ← {entry['module']}.{entry['class']}")
        except Exception as exc:
            logger.error(f"本地工具加载失败 {entry.get('name', '?')}: {exc}")
    return tools


# ------------------------------------------------------------------
# MCP tools
# ------------------------------------------------------------------

# Keep-alive reference for disconnect on reload
_mcp_clients: list = []


def load_mcp_tools(path: str | None = None) -> list[MCPTool]:
    """Connect to MCP servers and return MCPTool proxies for each remote tool."""
    global _mcp_clients
    _disconnect_mcp()

    config = _read_config(path)
    servers = config.get("mcp_servers", [])
    if not servers:
        return []

    clients = create_mcp_clients(servers)
    _mcp_clients = clients

    tools: list[MCPTool] = []
    for client in clients:
        for td in client.tools:
            proxy = MCPTool(client, td)
            tools.append(proxy)
            logger.info(f"MCP 工具已注册: {proxy.name} ← [{client.server_name}]")
    return tools


def _disconnect_mcp() -> None:
    global _mcp_clients
    for client in _mcp_clients:
        try:
            client.disconnect()
        except Exception as exc:
            logger.warning(f"MCP 断开异常: {exc}")
    _mcp_clients = []


# ------------------------------------------------------------------
# reload
# ------------------------------------------------------------------

def reload_registry(registry: ToolRegistry, path: str | None = None) -> dict:
    """Hot-reload: refresh local + MCP tools into the given registry."""
    config = _read_config(path)
    new_local = load_tools_from_yaml(path)
    new_mcp = load_mcp_tools(path)
    new_tools = new_local + list(new_mcp)

    new_names = {t.name for t in new_tools}
    old_names = set(registry.list_tools())

    removed = []
    for name in old_names - new_names:
        registry.unregister(name)
        removed.append(name)
        logger.info(f"工具已移除: {name}")

    added = []
    kept = []
    for tool in new_tools:
        if tool.name in old_names:
            kept.append(tool.name)
        else:
            registry.register(tool)
            added.append(tool.name)

    total = len(new_local)
    mcp_count = len(new_mcp)
    logger.info(
        f"工具重载完成: 本地 {total} + MCP {mcp_count} | "
        f"+{len(added)} -{len(removed)} ={len(kept)}"
    )
    return {"added": added, "removed": removed, "kept": kept}


# ------------------------------------------------------------------
# internal
# ------------------------------------------------------------------

def _instantiate_tool(entry: dict) -> BaseTool:
    module_name = entry["module"]
    class_name = entry["class"]
    module = importlib.import_module(module_name)
    tool_class = getattr(module, class_name)
    tool_config = entry.get("config", {})
    if tool_config:
        return tool_class(**tool_config)
    return tool_class()
