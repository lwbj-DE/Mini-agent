"""FastAPI application — REST API + SSE streaming + static file serving."""

from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from .agent_runtime import AgentRuntime
from .config import get_config
from .llm_client import LLMClient
from .session_manager import SessionManager
from .tool_registry import ToolRegistry
from .tool_loader import load_tools_from_yaml, load_mcp_tools, reload_registry

# ---------------------------------------------------------------------------
# request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    mode: str = "react"  # "react" | "plan_execute"


class RenameRequest(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None
_tool_registry: ToolRegistry | None = None
_session_manager: SessionManager | None = None
_agent_runtime: AgentRuntime | None = None


def _build_app() -> FastAPI:
    global _llm_client, _tool_registry, _session_manager, _agent_runtime

    _llm_client = LLMClient()

    # Load tools from YAML config (local + MCP)
    _tool_registry = ToolRegistry()
    local_tools = load_tools_from_yaml()
    mcp_tools = load_mcp_tools()
    for tool in local_tools + list(mcp_tools):
        _tool_registry.register(tool)
    logger.info(
        f"已注册 {len(local_tools)} 个本地工具 + "
        f"{len(mcp_tools)} 个 MCP 工具: {_tool_registry.list_tools()}"
    )

    _session_manager = SessionManager()
    _agent_runtime = AgentRuntime(_llm_client, _tool_registry, _session_manager)

    app = FastAPI(title="Mini Agent", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # REST endpoints
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "tools": _tool_registry.list_tools()}

    @app.post("/api/sessions")
    async def create_session():
        session = _session_manager.create()
        return session.summary

    @app.get("/api/sessions")
    async def list_sessions():
        return _session_manager.list_sessions()

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        session = _session_manager.load(session_id)
        return {
            "id": session.id,
            "name": session.name,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "messages": session.messages,
            "tool_state": session.tool_state,
        }

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        ok = _session_manager.delete(session_id)
        if not ok:
            raise HTTPException(404, "Session not found")
        return {"deleted": True}

    @app.patch("/api/sessions/{session_id}/rename")
    async def rename_session(session_id: str, body: RenameRequest):
        _session_manager.rename(session_id, body.name)
        return {"ok": True}

    @app.post("/api/sessions/{session_id}/chat")
    async def chat(session_id: str, body: ChatRequest):
        """SSE streaming endpoint — supports mode selection."""

        async def event_stream() -> AsyncGenerator[str, None]:
            async for event in _agent_runtime.run(
                session_id, body.message, mode=body.mode
            ):
                data = _serialize_event(event)
                yield f"event: {event.type}\ndata: {data}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --- Tool management ---

    @app.get("/api/tools")
    async def list_tools():
        """List all registered tools with schemas and source info."""
        return {
            "tools": [
                {
                    "name": name,
                    "source": getattr(_tool_registry._tools[name], "source", "local"),
                    "schema": _tool_registry._tools[name].schema(),
                }
                for name in _tool_registry.list_tools()
            ]
        }

    @app.post("/api/tools/reload")
    async def reload_tools():
        """Hot-reload tools from tools.yaml without restarting."""
        try:
            result = reload_registry(_tool_registry)
            return {"ok": True, **result}
        except Exception as exc:
            logger.error(f"工具重载失败: {exc}")
            raise HTTPException(500, f"Reload failed: {exc}")

    # Serve frontend static files (must be last)
    import os as _os

    _frontend_dir = str(_os.path.join(_os.path.dirname(__file__), "..", "frontend"))
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")

    return app


def _serialize_event(event) -> str:
    """Convert an event to a JSON string, using dataclass/object fields."""
    if hasattr(event, "__dict__"):
        data = {k: v for k, v in event.__dict__.items() if not k.startswith("_")}
    else:
        data = {}
        for k in dir(event):
            if not k.startswith("_") and not callable(getattr(event, k, None)):
                data[k] = getattr(event, k)
    data.setdefault("type", getattr(event, "type", "unknown"))
    return json.dumps(data, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# module-level app instance
# ---------------------------------------------------------------------------

app = _build_app()
