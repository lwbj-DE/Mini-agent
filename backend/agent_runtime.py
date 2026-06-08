"""Agent runtime — mode dispatcher.

Routes user input to the selected agent mode:
- react  (default): standard Think → Act → Observe loop
- plan_execute:     Plan → Execute → Replan workflow
"""

from __future__ import annotations

from typing import AsyncGenerator

from loguru import logger

from .config import get_config
from .llm_client import LLMClient
from .tool_registry import ToolRegistry
from .session_manager import SessionManager
from .agent_modes import ReactMode, PlanExecuteMode

# Re-export for backward compatibility
from .events import (
    StepStartEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    MessageEvent,
    ErrorEvent,
    DoneEvent,
    estimate_tokens,
)


class AgentRuntime:
    """Holds all agent modes and dispatches user input to the selected one."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        session_manager: SessionManager,
    ) -> None:
        self.react = ReactMode(llm_client, tool_registry, session_manager)
        self.plan_execute = PlanExecuteMode(llm_client, tool_registry, session_manager)
        self._cfg = get_config()

    async def run(
        self, session_id: str, user_input: str, mode: str = "react"
    ) -> AsyncGenerator:
        """Dispatch to the selected agent mode.

        Args:
            session_id: Session identifier.
            user_input: User's message.
            mode: "react" (default) or "plan_execute".
        """
        logger.info(f"[{session_id}] 模式: {mode}")

        if mode == "plan_execute":
            async for event in self.plan_execute.run(session_id, user_input):
                yield event
        else:
            async for event in self.react.run(session_id, user_input):
                yield event
