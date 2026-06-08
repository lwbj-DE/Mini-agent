#!/usr/bin/env python3
"""Demo MCP server — stdio JSON-RPC.

Exposes three mock tools: weather, time, echo

Usage:
    python mcp_servers/demo_server.py
"""

import json
import sys
from datetime import datetime, timezone
from typing import Any

# Force UTF-8 for stdio on Windows
sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")


def handle_request(request: dict) -> dict:
    rid = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    try:
        if method == "initialize":
            return ok(rid, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "demo-server", "version": "1.0.0"},
            })

        if method == "tools/list":
            return ok(rid, {"tools": [
                {
                    "name": "weather",
                    "description": "查询指定城市的天气（mock）。参数: city — 城市名称。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "城市名称，例如 'Beijing', 'Tokyo'",
                            }
                        },
                        "required": ["city"],
                    },
                },
                {
                    "name": "get_current_time",
                    "description": "获取当前 UTC 时间。无需参数。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                    },
                },
                {
                    "name": "echo",
                    "description": "回显输入文本，用于测试连通性。参数: text — 要回显的文本。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "要回显的文本",
                            }
                        },
                        "required": ["text"],
                    },
                },
            ]})

        if method == "tools/call":
            tool_name = params.get("name", "")
            args = params.get("arguments", {})

            if tool_name == "weather":
                city = args.get("city", "未知")
                # Mock weather data
                weather_data = {
                    "beijing": "北京: 晴 25°C, 湿度 45%, 风力 3 级",
                    "tokyo": "东京: 多云 22°C, 湿度 60%, 风力 2 级",
                    "london": "伦敦: 小雨 15°C, 湿度 80%, 风力 4 级",
                    "new york": "纽约: 晴 28°C, 湿度 50%, 风力 3 级",
                }
                key = city.lower().strip()
                text = weather_data.get(key, f"{city}: 晴 20°C（mock 数据）")
                return ok(rid, {"content": [{"type": "text", "text": text}]})

            if tool_name == "get_current_time":
                now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                return ok(rid, {"content": [{"type": "text", "text": f"当前 UTC 时间: {now}"}]})

            if tool_name == "echo":
                text = args.get("text", "")
                return ok(rid, {"content": [{"type": "text", "text": "[Echo] " + text}]})

            return err(rid, -32601, f"未知工具: {tool_name}")

        return err(rid, -32601, f"未知方法: {method}")

    except Exception as exc:
        return err(rid, -32603, str(exc))


def ok(rid: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def err(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def main() -> None:
    """Read JSON-RPC requests line-by-line from stdin, write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_request(request)
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
