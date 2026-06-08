"""LLM client wrapper around the OpenAI-compatible API.

Supports both non-streaming (used internally) and streaming with
progressive token delivery (used by the agent runtime for real-time UX).
"""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from openai import OpenAI

from .config import get_config


class LLMClient:
    """Thin wrapper around the OpenAI-compatible chat-completion API."""

    def __init__(self) -> None:
        cfg = get_config()
        self._client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        self._model = cfg.model
        self._temperature = cfg.temperature
        self._max_tokens = cfg.max_tokens
        self._max_retries = 3

    # ------------------------------------------------------------------
    # non-streaming (used by tests / internal logic)
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Any:
        """Send a non-streaming chat-completion request.

        Returns the full ``ChatCompletion`` response object.
        """
        kwargs = self._build_kwargs(messages, tools, stream=False)
        return self._call_with_retry(**kwargs)

    # ------------------------------------------------------------------
    # streaming — yields progressive token events
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Stream a chat-completion request, yielding token-level events.

        Yields dicts of the form:

            {"type": "reasoning", "content": "..."}
            {"type": "content",   "content": "..."}
            {"type": "tool_delta","index": 0, "name": "...", "args": "..."}
            {"type": "finished",  "content": "...", "reasoning": "...",
             "tool_calls": [...] | None}

        The final ``finished`` event contains the complete accumulated
        response so the agent loop can inspect tool_calls and continue.
        """
        kwargs = self._build_kwargs(messages, tools, stream=True)

        # Per-chunk accumulators
        acc_content = ""
        acc_reasoning = ""
        tool_calls_map: dict[int, dict[str, Any]] = {}

        for attempt in range(self._max_retries):
            try:
                stream = self._client.chat.completions.create(**kwargs)

                for chunk in stream:
                    delta = (
                        chunk.choices[0].delta
                        if chunk.choices
                        else None
                    )
                    if delta is None:
                        continue

                    # --- reasoning tokens ---
                    rc = getattr(delta, "reasoning_content", None) or ""
                    if rc:
                        acc_reasoning += rc
                        yield {"type": "reasoning", "content": rc}

                    # --- text content tokens ---
                    if delta.content:
                        acc_content += delta.content
                        yield {"type": "content", "content": delta.content}

                    # --- tool-call deltas ---
                    if delta.tool_calls:
                        for td in delta.tool_calls:
                            idx = td.index
                            if idx not in tool_calls_map:
                                tool_calls_map[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            tc = tool_calls_map[idx]
                            if td.id:
                                tc["id"] = td.id
                            if td.function:
                                if td.function.name:
                                    tc["function"]["name"] += td.function.name
                                    yield {
                                        "type": "tool_delta",
                                        "index": idx,
                                        "name": td.function.name,
                                        "args": "",
                                    }
                                if td.function.arguments:
                                    tc["function"]["arguments"] += td.function.arguments
                                    yield {
                                        "type": "tool_delta",
                                        "index": idx,
                                        "name": "",
                                        "args": td.function.arguments,
                                    }

                # --- stream completed successfully ---
                tool_calls = (
                    [tool_calls_map[i] for i in sorted(tool_calls_map.keys())]
                    if tool_calls_map
                    else None
                )
                yield {
                    "type": "finished",
                    "content": acc_content,
                    "reasoning": acc_reasoning,
                    "tool_calls": tool_calls,
                }
                return

            except Exception as exc:
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise RuntimeError(
                    f"LLM streaming failed after {self._max_retries} retries: {exc}"
                ) from exc

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _build_kwargs(
        self, messages: list[dict], tools: list[dict] | None, stream: bool
    ) -> dict:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": stream,
        }
        if tools:
            kwargs["tools"] = tools
        # Disable stream_options (not supported by all providers)
        if stream:
            kwargs["stream_options"] = {"include_usage": True}
        return kwargs

    def _call_with_retry(self, **kwargs: Any) -> Any:
        """Call the API with exponential-backoff retry (non-streaming)."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)
        raise RuntimeError(
            f"LLM API call failed after {self._max_retries} retries: {last_exc}"
        ) from last_exc
