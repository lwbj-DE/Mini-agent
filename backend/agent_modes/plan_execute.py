"""PlanExecuteMode — Plan → Execute → Replan workflow.

For complex multi-step tasks the agent first creates a structured plan,
then executes each step with a ReAct sub-loop, re-assessing after each step.
"""

from __future__ import annotations

import json
import time as _time
from typing import AsyncGenerator

from loguru import logger

from ..config import get_config
from ..llm_client import LLMClient
from ..tool_registry import ToolRegistry
from ..session_manager import SessionManager
from ..events import (
    StepStartEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    MessageEvent,
    ErrorEvent,
    DoneEvent,
)
from .react_mode import ReactMode

# ---------------------------------------------------------------------------
# plan-specific event
# ---------------------------------------------------------------------------


class PlanCreatedEvent:
    """Emitted after the planning phase completes."""

    def __init__(self, steps: list[dict]) -> None:
        self.steps = steps  # [{"step":1, "title":"...", "description":"..."}, ...]
        self.type = "plan_created"


class PlanStepUpdateEvent:
    """Emitted when a plan step's status changes."""

    def __init__(self, index: int, status: str) -> None:
        self.index = index  # 0-based
        self.status = status  # "pending" | "in_progress" | "done" | "failed"
        self.type = "plan_step_update"


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

MAX_PLAN_STEPS = 8
MAX_REPLAN_ROUNDS = 5   # no replanning after this many total steps
MAX_STEPS_PER_PLAN_ITEM = 8  # each plan step gets at most 8 tool calls
MAX_TOTAL_PLAN_STEPS = 15    # absolute cap for the whole plan

_PLANNER_PROMPT = """你是一个任务规划专家。分析用户的需求，将其分解为可执行的具体步骤。

要求：
1. 每个步骤必须清晰、包含具体的交付物和完成标准，不能只写一个抽象名称
2. 步骤间应有逻辑递进关系
3. 步骤数控制在 2-6 个
4. 如果任务本身很简单（如简单计算、闲聊），则只需 1 个步骤
5. 每个步骤的 description 必须包含：
   - 该步骤要产出的具体交付物
   - 完成标准（怎样算做完）
   - 可以参考哪些知识或方向

示例格式：
[{"step": 1, "title": "需求分析", "description": "梳理用户群体的核心需求和使用场景，产出需求清单文档（包含功能需求、非功能需求、优先级排序）。完成标准：所有需求项都有明确描述和优先级。"}]

请用 JSON 数组格式输出，不要包含其他内容：
[{"step": 1, "title": "步骤标题", "description": "详细描述该步骤的交付物和完成标准"}]"""

_REPLANNER_PROMPT = """评估当前计划执行情况，判断下一步行动。

当前已完成步骤：
{completed}

当前步骤结果：
{current_result}

计划剩余步骤：
{pending}

请用以下三个选项之一回答（只输出单词）：
- continue: 计划合理，继续执行下一步
- replan: 情况有变，需要重新制定后续计划
- respond: 任务已基本完成，可以给出最终回答"""


# ---------------------------------------------------------------------------
# PlanExecuteMode
# ---------------------------------------------------------------------------


class PlanExecuteMode:
    """Plan-Execute-Replan workflow for complex multi-step tasks."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        session_manager: SessionManager,
    ) -> None:
        self.llm = llm_client
        self.tools = tool_registry
        self.sessions = session_manager
        self._cfg = get_config()
        # ReAct sub-loop for executing individual steps
        self._react = ReactMode(llm_client, tool_registry, session_manager)

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    async def run(
        self, session_id: str, user_input: str
    ) -> AsyncGenerator:
        logger.info(f"[{session_id}] PlanExecute 启动: {user_input[:80]}")

        # --- Phase 1: Planning ---
        yield MessageEvent(content="正在制定执行计划…\n\n", final=False)

        plan = await self._plan(user_input)
        if not plan:
            # Fallback: use ReAct for simple tasks
            yield MessageEvent(content="任务较为简单，直接执行。\n\n", final=False)
            async for event in self._react.run(session_id, user_input):
                yield event
            return

        yield PlanCreatedEvent(steps=plan)
        yield MessageEvent(
            content=f"已制定 {len(plan)} 步执行计划：\n\n"
            + "\n".join(f"{s['step']}. {s['title']}" for s in plan)
            + "\n\n开始执行…\n\n",
            final=False,
        )

        # --- Phase 2-3: Execute + Replan ---
        total_steps = 0
        step_idx = 0

        while step_idx < len(plan) and total_steps < MAX_TOTAL_PLAN_STEPS:
            step = plan[step_idx]
            yield PlanStepUpdateEvent(index=step_idx, status="in_progress")

            step_prompt = (
                f"执行计划第 {step['step']} 步：{step['title']}\n\n"
                f"详细说明：{step['description']}\n\n"
                f"规则：\n"
                f"- 你最多可以调用 {MAX_STEPS_PER_PLAN_ITEM} 次工具\n"
                f"- 优先用你自己的知识直接回答，search 仅作参考且最多搜索一次\n"
                f"- 如果 search 无结果，不要继续搜索，直接用自身知识回答\n"
                f"- 禁止使用 todo 工具（创建/更新/查询任务），本步骤的进度由外部系统自动追踪\n"
                f"- 完成后给出清晰的结论，不要继续扩展或额外创建子任务"
            )

            # Execute this step with limited ReAct sub-loop
            limited_react = ReactMode(
                self.llm, self.tools, self.sessions,
                max_steps_override=MAX_STEPS_PER_PLAN_ITEM,
                isolate_state=True,
                verbose_feedback=False,
            )
            step_steps = 0
            step_truncated = False
            async for event in limited_react.run(session_id, step_prompt):
                if isinstance(event, DoneEvent):
                    continue
                if isinstance(event, StepStartEvent):
                    step_steps = event.step
                if isinstance(event, ErrorEvent) and "达到最大步数" in event.message:
                    step_truncated = True
                yield event
            total_steps += step_steps

            step_status = "failed" if step_truncated else "done"
            yield PlanStepUpdateEvent(index=step_idx, status=step_status)

            # --- Replan ---
            if step_idx + 1 < len(plan):
                decision = await self._replan(
                    plan, step_idx, session_id, step_truncated
                )
                if decision == "replan":
                    logger.info(f"[{session_id}] 重新规划 (步骤{total_steps})")
                    plan = await self._plan(
                        f"根据当前执行结果，重新规划剩余步骤。已完成：{step['title']}"
                    )
                    if plan:
                        yield PlanCreatedEvent(steps=plan)
                    step_idx = 0
                    continue
                elif decision == "respond":
                    logger.info(f"[{session_id}] 提前结束 (步骤{total_steps})")
                    break

            step_idx += 1

        # --- Final ---
        session = self.sessions.load(session_id)
        session.tool_state = self.tools.get_state()
        self.sessions.save(session)

        yield MessageEvent(
            content=f"\n\n计划执行完毕，共完成 {step_idx + 1} 个步骤。",
            final=True,
        )
        yield DoneEvent(session_id=session_id)

    # ------------------------------------------------------------------
    # planner
    # ------------------------------------------------------------------

    async def _plan(self, user_input: str) -> list[dict] | None:
        """Generate a structured plan from the user input."""
        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": _PLANNER_PROMPT},
                    {"role": "user", "content": user_input},
                ],
            )
            text = response.choices[0].message.content.strip()
            # Extract JSON from possible markdown wrappers
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            plan = json.loads(text)
            if isinstance(plan, list) and len(plan) > 0:
                # Ensure required fields
                for i, s in enumerate(plan):
                    if "step" not in s:
                        s["step"] = i + 1
                    if "title" not in s:
                        s["title"] = s.get("description", f"步骤{i+1}")[:30]
                    if "description" not in s:
                        s["description"] = s.get("title", "")
                logger.info(f"计划生成: {len(plan)} 步 — {[s['title'] for s in plan]}")
                return plan
        except Exception as exc:
            logger.warning(f"计划生成失败，降级到 ReAct: {exc}")
        return None

    # ------------------------------------------------------------------
    # replanner
    # ------------------------------------------------------------------

    async def _replan(
        self, plan: list[dict], step_idx: int, session_id: str,
        step_truncated: bool = False,
    ) -> str:
        """Decide: continue | replan | respond."""
        completed = plan[: step_idx + 1]
        pending = plan[step_idx + 1 :]

        status_note = "已完成" if not step_truncated else "被截断（达到步数上限），可能未充分完成"
        current_result = f"第{step_idx+1}步 '{completed[-1]['title']}' {status_note}"

        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": _REPLANNER_PROMPT.format(
                        completed=json.dumps(completed, ensure_ascii=False),
                        current_result=current_result,
                        pending=json.dumps(pending, ensure_ascii=False) if pending else "无",
                    )},
                ],
            )
            decision = response.choices[0].message.content.strip().lower()
            if "replan" in decision:
                return "replan"
            elif "respond" in decision:
                return "respond"
            return "continue"
        except Exception:
            return "continue"
