"""MCP JSON-RPC 2.0 client — stdio + streamable-http transports."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"  # "stdio" | "streamable-http"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    enabled: bool = True


@dataclass
class MCPToolDef:
    name: str
    description: str = ""
    inputSchema: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# transport base
# ---------------------------------------------------------------------------


class Transport:
    """Abstract transport — send a JSON-RPC dict, return the response dict."""

    def send(self, request: dict) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        pass


class StdioTransport(Transport):
    """Launch a subprocess, communicate via stdin/stdout JSON lines."""

    def __init__(self, command: str, args: list[str]) -> None:
        # Resolve 'python' → sys.executable for reliability on Windows
        cmd = sys.executable if command in ("python", "python3") else command
        # Resolve relative paths to absolute
        resolved_args = []
        for a in args:
            if a.endswith(".py") and not a.startswith(("/", "\\", "C:")):
                a = str(Path(a).resolve())
            resolved_args.append(a)

        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            self._proc = subprocess.Popen(
                [cmd] + resolved_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"MCP 无法启动进程: {cmd} — {exc}") from exc

        logger.info(
            f"MCP stdio 进程已启动: {cmd} {' '.join(resolved_args)} "
            f"(pid={self._proc.pid})"
        )

    def send(self, request: dict) -> dict:
        line = json.dumps(request, ensure_ascii=False) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"MCP 子进程通信失败 (进程可能已崩溃): {exc}") from exc

        try:
            resp_line = self._proc.stdout.readline()
        except Exception as exc:
            raise RuntimeError(f"MCP 子进程读取失败: {exc}") from exc

        if not resp_line:
            raise RuntimeError("MCP 子进程无响应（stdout 已关闭）")
        return json.loads(resp_line)

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            logger.info(f"MCP stdio 进程已关闭 (pid={self._proc.pid})")


class HttpTransport(Transport):
    """HTTP POST transport for streamable-http MCP servers."""

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        # Lazy import to avoid hard dependency at module level
        import httpx

        self._client = httpx.Client(timeout=30.0)
        logger.info(f"MCP HTTP 客户端就绪: {self._url}")

    def send(self, request: dict) -> dict:
        import httpx

        try:
            resp = self._client.post(self._url, json=request)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MCP HTTP 请求失败 [{self._url}]: {exc}") from exc

    def close(self) -> None:
        self._client.close()
        logger.info(f"MCP HTTP 客户端已关闭: {self._url}")


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


class MCPClient:
    """JSON-RPC 2.0 client that discovers and calls tools on one MCP server."""

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._next_id = 1
        self._transport: Transport | None = None
        self._tools: list[MCPToolDef] = []
        self._connected = False

    # -- connect / disconnect ----------------------------------------------

    def connect(self) -> None:
        if self._connected:
            return
        cfg = self._config

        if cfg.transport == "stdio":
            if not cfg.command:
                raise ValueError(f"MCP [{cfg.name}]: stdio 模式需要 command")
            self._transport = StdioTransport(cfg.command, cfg.args)
        elif cfg.transport == "streamable-http":
            if not cfg.url:
                raise ValueError(f"MCP [{cfg.name}]: HTTP 模式需要 url")
            self._transport = HttpTransport(cfg.url)
        else:
            raise ValueError(f"MCP [{cfg.name}]: 不支持的 transport '{cfg.transport}'")

        # Initialize handshake
        try:
            init_resp = self._rpc_call("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mini-agent", "version": "1.0"},
            })
        except Exception as exc:
            self._transport.close()
            raise RuntimeError(
                f"MCP [{cfg.name}] initialize 失败: {exc}"
            ) from exc

        logger.info(
            f"MCP [{cfg.name}] 已连接 "
            f"(protocol={init_resp.get('protocolVersion', '?')})"
        )
        self._connected = True

    def disconnect(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
        self._connected = False

    # -- tool discovery ----------------------------------------------------

    def discover_tools(self) -> list[MCPToolDef]:
        """Fetch the tool list from the server."""
        if not self._connected:
            raise RuntimeError(f"MCP [{self._config.name}] 未连接，请先调用 connect()")

        try:
            resp = self._rpc_call("tools/list", {})
        except Exception as exc:
            logger.error(f"MCP [{self._config.name}] tools/list 失败: {exc}")
            return []

        raw = resp.get("tools", [])
        tools = [
            MCPToolDef(
                name=t.get("name", "unknown"),
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {}),
            )
            for t in raw
        ]
        self._tools = tools
        names = [t.name for t in tools]
        logger.info(f"MCP [{self._config.name}] 发现 {len(tools)} 个工具: {names}")
        return tools

    # -- tool execution ----------------------------------------------------

    def call_tool(self, name: str, arguments: dict) -> str:
        """Invoke a remote tool by name, return its text content."""
        if not self._connected:
            raise RuntimeError(f"MCP [{self._config.name}] 未连接")

        try:
            resp = self._rpc_call("tools/call", {
                "name": name,
                "arguments": arguments,
            })
        except Exception as exc:
            return f"Error: MCP 工具 '{name}' 调用失败: {exc}"

        # Extract text from response content
        contents = resp.get("content", [])
        texts = []
        for item in contents:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts) if texts else json.dumps(resp, ensure_ascii=False)

    # -- helpers -----------------------------------------------------------

    def _rpc_call(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and return the result."""
        rid = self._next_id
        self._next_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params,
        }
        assert self._transport is not None
        response = self._transport.send(request)

        if "error" in response:
            err = response["error"]
            raise RuntimeError(
                f"JSON-RPC error [{method}]: code={err.get('code')} {err.get('message','')}"
            )
        return response.get("result", {})

    # -- properties --------------------------------------------------------

    @property
    def server_name(self) -> str:
        return self._config.name

    @property
    def tools(self) -> list[MCPToolDef]:
        return list(self._tools)


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------


def create_mcp_clients(servers: list[dict]) -> list[MCPClient]:
    """Instantiate MCPClient objects from raw config dicts."""
    clients: list[MCPClient] = []
    for srv in servers:
        if not srv.get("enabled", True):
            logger.info(f"MCP 已禁用: {srv.get('name', '?')}")
            continue
        config = MCPServerConfig(
            name=srv.get("name", "unnamed"),
            transport=srv.get("transport", "stdio"),
            command=srv.get("command", ""),
            args=srv.get("args", []),
            url=srv.get("url", ""),
            enabled=True,
        )
        try:
            client = MCPClient(config)
            client.connect()
            client.discover_tools()
            clients.append(client)
        except Exception as exc:
            logger.error(f"MCP [{config.name}] 初始化失败: {exc}")
    return clients
