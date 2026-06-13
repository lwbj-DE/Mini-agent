"""ReactMode — standard ReAct (Reasoning + Acting) loop.

Think → Act → Observe → repeat until done or max steps.

Extracted from agent_runtime.py for composability with other modes.
"""

from __future__ import annotations

import json
import time as _time
import traceback
from dataclasses import dataclass, field
from typing import AsyncGenerator

from loguru import logger

from ..config import get_config
from ..llm_client import LLMClient
from ..tool_registry import ToolRegistry
from ..session_manager import SessionManager, Session
from ..events import (
    StepStartEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    MessageEvent,
    ErrorEvent,
    DoneEvent,
    estimate_tokens,
)


class ReactMode:
    """Standard ReAct agent loop with streaming + compression.

    Parameters:
        isolate_state: If True, skip restoring/saving tool_state from session.
            Used by PlanExecuteMode sub-loops to avoid polluting session state.
        verbose_feedback: If False, max-steps feedback is a short truncation
            marker instead of verbose guidance. Used by sub-loops.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        session_manager: SessionManager,
        max_steps_override: int | None = None,
        isolate_state: bool = False,
        verbose_feedback: bool = True,
        exclude_tools: set[str] | None = None,
    ) -> None:
        self.llm = llm_client
        self.tools = tool_registry
        self.sessions = session_manager
        self._cfg = get_config()
        self._max_steps_override = max_steps_override
        self._isolate_state = isolate_state
        self._verbose_feedback = verbose_feedback
        self._exclude_tools: set[str] = exclude_tools or set()

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    async def run(
        self, session_id: str, user_input: str
    ) -> AsyncGenerator:
        """Execute the ReAct loop for a single user turn."""
        session = self.sessions.load(session_id)
        session.messages.append({"role": "user", "content": user_input})
        if not self._isolate_state:
            self.tools.set_state(session.tool_state)

        if session.name == "New Chat":
            session.name = self._quick_name(user_input)

        logger.info(
            f"[{session_id}] React 新消息 "
            f"({len(session.messages)} 条历史): "
            f"{user_input[:80]}{'...' if len(user_input) > 80 else ''}"
        )

        steps = 0
        max_steps = self._max_steps_override or self._cfg.max_steps

        while steps < max_steps:
            steps += 1
            self._maybe_compress(session, session_id, steps)
            yield StepStartEvent(step=steps, max_steps=max_steps)

            content_acc = ""
            reasoning_acc = ""
            content_streamed = False
            final_tool_calls: list[dict] | None = None

            try:
                for se in self.llm.chat_stream(
                    session.messages, self._filtered_schemas()
                ):
                    if se["type"] == "reasoning":
                        reasoning_acc += se["content"]
                        yield ReasoningEvent(content=se["content"])
                    elif se["type"] == "content":
                        content_acc += se["content"]
                        content_streamed = True
                        yield MessageEvent(content=se["content"], final=False)
                    elif se["type"] == "finished":
                        final_tool_calls = se.get("tool_calls")
                        # reasoning-first models (e.g. MiMo v2.5-pro) may
                        # output all text in reasoning_content with empty
                        # content — fall back to reasoning in that case
                        if not content_acc and reasoning_acc:
                            content_acc = reasoning_acc
            except Exception as exc:
                traceback.print_exc()
                logger.error(f"[{session_id}] LLM 调用失败 (步骤{steps}): {exc}")
                yield ErrorEvent(message=f"LLM 调用失败: {exc}")
                content_acc = "抱歉，连接语言模型时出现了错误，请稍后重试。"
                break

            if final_tool_calls:
                session.messages.append(
                    self._assistant_msg_with_tool_calls(
                        content_acc, final_tool_calls
                    )
                )
                for tc in final_tool_calls:
                    func_name = tc["function"]["name"]
                    try:
                        func_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        func_args = {}

                    logger.info(
                        f"[{session_id}] 步骤{steps} 调用 {func_name} "
                        f"{json.dumps(func_args, ensure_ascii=False)}"
                    )
                    yield ToolCallEvent(name=func_name, args=func_args, step=steps)

                    _t0 = _time.perf_counter()
                    try:
                        result = self.tools.execute(func_name, **func_args)
                        success = not result.startswith("Error")
                    except Exception as exc:
                        result = f"Error: {exc}"
                        success = False
                    _elapsed = (_time.perf_counter() - _t0) * 1000

                    logger.info(
                        f"[{session_id}] 步骤{steps} {func_name} "
                        f"→ {'✓' if success else '✗'} ({_elapsed:.1f}ms) "
                        f"{result[:100]}{'...' if len(result) > 100 else ''}"
                    )
                    yield ToolResultEvent(
                        name=func_name, result=result, step=steps, success=success
                    )
                    session.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
            else:
                session.messages.append({
                    "role": "assistant", "content": content_acc,
                })
                # If the model only produced reasoning tokens, the frontend
                # never received any content events to accumulate. Send the
                # full text as a single event so it gets rendered.
                if not content_streamed and content_acc:
                    yield MessageEvent(content=content_acc, final=False)
                yield MessageEvent(content="", final=True)
                break
        else:
            feedback = self._build_max_steps_feedback(session, steps, max_steps)
            session.messages.append({"role": "assistant", "content": feedback})
            logger.warning(f"[{session_id}] 达到最大步数 ({max_steps})")
            yield MessageEvent(content=feedback, final=True)
            yield ErrorEvent(message=f"达到最大步数 ({max_steps})")

        if not self._isolate_state:
            session.tool_state = self.tools.get_state()
            self.sessions.save(session)
        logger.info(
            f"[{session_id}] React 结束 — {steps} 步, "
            f"{len(session.messages)} 条消息"
        )
        yield DoneEvent(session_id=session.id)

    # ------------------------------------------------------------------
    # context compression
    # ------------------------------------------------------------------

    # -- system-message prefixes for two-tier compression -----------------
    _FACT_PREFIX = "📋 已记录事实"
    _SUMMARY_PREFIX = "📝 对话摘要"

    # ------------------------------------------------------------------
    # context compression (two-tier)
    # ------------------------------------------------------------------

    def _maybe_compress(self, session, session_id, step):
        if not self._cfg.compression_enabled:
            return
        if len(session.messages) <= self._cfg.compression_keep_messages:
            return
        est = estimate_tokens(session.messages)
        if est < self._cfg.compression_trigger_tokens:
            return

        keep = self._cfg.compression_keep_messages
        to_compress = session.messages[:-keep]
        recent = session.messages[-keep:]

        logger.info(
            f"[{session_id}] 步骤{step} 触发压缩: "
            f"{len(to_compress)} 条 → 摘要 "
            f"(估算 {est}/{self._cfg.model_max_input_tokens} tokens)"
        )
        try:
            # Extract existing memory layers from previous compressions
            existing_facts, existing_summary = self._extract_existing_memory(to_compress)

            # Tier 1: Extract and merge background facts (cumulative, never overwritten)
            fact_memory = self._extract_and_merge_facts(to_compress, existing_facts)

            # Tier 2: Generate rolling conversation summary
            rolling_summary = self._generate_rolling_summary(to_compress, existing_summary)

            # Build new message list: fact_memory → summary → recent
            new_messages: list[dict] = []
            if fact_memory:
                new_messages.append({"role": "system", "content": fact_memory})
            if rolling_summary:
                new_messages.append({"role": "system", "content": rolling_summary})
            session.messages = new_messages + recent

            logger.info(
                f"[{session_id}] 压缩完成: {len(to_compress)} 条 → "
                f"事实 {len(fact_memory)} 字符 + 摘要 {len(rolling_summary)} 字符"
            )
        except Exception as exc:
            logger.warning(f"[{session_id}] 压缩失败，跳过: {exc}")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _extract_existing_memory(self, messages: list[dict]) -> tuple[str, str]:
        """Scan system messages for previously persisted fact memory and summary."""
        facts = ""
        summary = ""
        for m in messages:
            if m.get("role") != "system":
                continue
            content = m.get("content", "")
            if content.startswith(self._FACT_PREFIX):
                facts = content
            elif content.startswith(self._SUMMARY_PREFIX) or content.startswith("[对话摘要]"):
                summary = content
        return facts, summary

    def _extract_and_merge_facts(self, messages: list[dict], existing_facts: str) -> str:
        """Extract background facts from messages and merge with existing fact memory.

        Facts include: names, project names, tech stack choices, metrics/numbers,
        personal preferences, org structure, business context — anything the user
        shared that is NOT a task or to-do.
        """
        prompt = (
            "从以下对话中提取用户分享过的所有背景事实信息，"
            "包括但不限于：人名、项目名称、技术选型、数字指标、"
            "个人偏好、组织架构、业务背景。\n\n"
            "要求：\n"
            "1. 保留原话中的具体名称和数字，不要泛化（如「张明远」不要写成「某同事」）\n"
            "2. 只记录事实，不要记录任务进度或对话流程\n"
            "3. 用简洁的要点形式输出，每行一个事实\n"
            "4. 如果信息在对话中被否定或更新过，记录最新状态"
        )
        if existing_facts:
            # Strip prefix for cleaner context
            clean = existing_facts
            if clean.startswith(self._FACT_PREFIX):
                clean = clean[len(self._FACT_PREFIX):].lstrip("：:\n ")
            prompt += (
                f"\n\n以下是之前已记录的事实，请合并："
                f"新增的事实补充进去，不变的事实保留原文，"
                f"有冲突的以新信息为准。\n\n{clean}"
            )

        user_content = json.dumps(
            [{"role": m.get("role", "?"), "content": m.get("content", "")[:500]}
             for m in messages if m.get("role") in ("user", "assistant")],
            ensure_ascii=False,
        )
        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            facts = response.choices[0].message.content.strip()
            return f"{self._FACT_PREFIX}：\n{facts}"
        except Exception:
            logger.warning("事实提取失败，保留已有事实")
            return existing_facts

    def _generate_rolling_summary(self, messages: list[dict], existing_summary: str) -> str:
        """Generate a rolling conversation summary focusing on task progress.

        Background facts are handled separately by _extract_and_merge_facts,
        so this summary only needs to cover task flow.
        """
        max_chars = self._cfg.compression_summary_max_chars
        prompt = (
            f"将以下对话历史浓缩为一段中文摘要（不超过{max_chars}字）。\n"
            "保留：用户的需求、任务进展、待办事项、重要决策和结论。\n"
            "注意：用户的背景事实（人名、项目名、技术选型等）已单独记录，"
            "摘要中不需要重复。"
        )
        if existing_summary:
            clean = existing_summary
            for pfx in (self._SUMMARY_PREFIX + "：", self._SUMMARY_PREFIX + ":", "[对话摘要] "):
                clean = clean.replace(pfx, "")
            prompt += f"\n\n之前的对话摘要（请合并）：{clean}"

        user_content = json.dumps(
            [{"role": m.get("role", "?"), "content": m.get("content", "")[:300]}
             for m in messages if m.get("role") in ("user", "assistant")][-30:],
            ensure_ascii=False,
        )
        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            summary = response.choices[0].message.content.strip()[: max_chars + 100]
            return f"{self._SUMMARY_PREFIX}：{summary}"
        except Exception:
            logger.warning("摘要生成失败，保留已有摘要")
            return existing_summary or f"{self._SUMMARY_PREFIX}：（压缩失败）"

    # ------------------------------------------------------------------
    # max-steps feedback
    # ------------------------------------------------------------------

    def _build_max_steps_feedback(self, session, steps, max_steps):
        """Generate a structured progress report with actionable suggestions."""
        if not self._verbose_feedback:
            return f"[TRUNCATED at step {steps}/{max_steps}]"

        todo_state = self.tools.get_state().get("todo", {})
        tasks = todo_state.get("tasks", [])

        if not tasks:
            return (
                f"⚠️ 已达到最大步数限制（{max_steps} 步），且未创建任何任务。\n\n"
                f"🔍 可能原因：search 工具未能找到相关信息，导致步数消耗在无效搜索上。\n\n"
                f"💡 建议：\n"
                f'  • 切换到 "⚡ 快速对话" 模式重试 — Agent 会直接用自身知识回答\n'
                f"  • 简化需求，将复杂问题拆成多个简短提问\n"
                f'  • 直接提问具体知识点，如 "C++ 指针是什么" 而非 "制定学习计划"'
            )

        done = [t for t in tasks if t.get("status") == "done"]
        in_prog = [t for t in tasks if t.get("status") == "in_progress"]
        pending = [t for t in tasks if t.get("status") == "pending"]

        lines = [
            f"⚠️ 已达到最大步数限制（{max_steps} 步），以下是当前进度：\n",
            "📊 **任务状态**",
        ]
        if done:
            titles = "、".join(t["title"][:20] for t in done[:5])
            lines.append(f"  ● 已完成 ({len(done)}): {titles}")
        if in_prog:
            titles = "、".join(t["title"][:20] for t in in_prog)
            lines.append(f"  ◐ 进行中 ({len(in_prog)}): {titles}")
        if pending:
            titles = "、".join(t["title"][:20] for t in pending[:5])
            lines.append(f"  ○ 未开始 ({len(pending)}): {titles}")

        lines.extend([
            "",
            "💡 **建议下一步输入**：",
            '  • "继续" — 从上次中断处继续执行',
            '  • "查看进度" — 查看详细任务状态',
            '  • "跳过当前步骤" — 进入下一个任务',
            '  • "重新开始" — 简化计划后重新执行',
        ])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _filtered_schemas(self) -> list[dict]:
        """Return tool schemas excluding tools in ``_exclude_tools``."""
        if not self._exclude_tools:
            return self.tools.schemas()
        return [
            s for s in self.tools.schemas()
            if s["function"]["name"] not in self._exclude_tools
        ]

    @staticmethod
    def _assistant_msg_with_tool_calls(content, tool_calls):
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {"id": tc["id"], "type": tc.get("type", "function"),
                 "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}
                for tc in tool_calls
            ],
        }

    @staticmethod
    def _quick_name(user_input):
        cleaned = user_input.strip().replace("\n", " ")
        return cleaned[:27] + "..." if len(cleaned) > 30 else cleaned
