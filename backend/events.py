"""Shared event types — used by agent_runtime and all agent modes."""

from dataclasses import dataclass


@dataclass
class StepStartEvent:
    step: int
    max_steps: int
    type: str = "step_start"


@dataclass
class ReasoningEvent:
    content: str
    type: str = "reasoning"


@dataclass
class ToolCallEvent:
    name: str
    args: dict
    step: int
    type: str = "tool_call"


@dataclass
class ToolResultEvent:
    name: str
    result: str
    step: int
    success: bool = True
    type: str = "tool_result"


@dataclass
class MessageEvent:
    content: str
    final: bool = False
    type: str = "message"


@dataclass
class ErrorEvent:
    message: str
    type: str = "error"


@dataclass
class DoneEvent:
    session_id: str = ""
    type: str = "done"


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token count (1 token ≈ 3 chars English, ≈ 1.5 CJK)."""
    total = 0
    for m in messages:
        text = m.get("content", "") or ""
        cjk = sum(1 for c in text if "一" <= c <= "鿿")
        other = len(text) - cjk
        total += int(cjk / 1.5 + other / 3.5)
    return max(total, 1)
