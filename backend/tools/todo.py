"""Stateful Todo / task-management tool.

This is the key tool for cross-session continuation.  The LLM can create,
update, and query tasks across conversation rounds because the task list
is persisted in the session's ``tool_state``.
"""

import itertools
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


from .base import BaseTool

# ---------- data model ----------

@dataclass
class Task:
    """A single task in the todo list."""

    id: str
    title: str
    description: str = ""
    status: str = "pending"  # pending | in_progress | done | cancelled
    parent_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(**d)


# ---------- tool ----------

class TodoTool(BaseTool):
    """Persistent task manager with create / update / list / get operations.

    State is stored on the instance and serialised via ``get_state()`` /
    ``set_state()`` so that every session can resume where it left off.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._id_counter = itertools.count(1)

    # -- BaseTool interface ------------------------------------------------

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return (
            "Manage a persistent task list that survives across conversation "
            "rounds. Use this to plan, track progress, and help the user "
            "stay organised. You MUST use this tool when the user asks you "
            "to create a plan, break down a goal into sub-tasks, or track "
            "progress on a multi-step project. "
            "Operations:\n"
            "- create: add one or more tasks (optionally with a parent for "
            "sub-tasks).\n"
            "- update: change a task's status (pending→in_progress→done) "
            "or edit its title/description.\n"
            "- list: get all tasks, optionally filtered by status.\n"
            "- get: get full details of a single task by id."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["create", "update", "list", "get"],
                    "description": "Which operation to perform.",
                },
                "tasks": {
                    "type": "array",
                    "description": (
                        "For 'create': a list of {title, description?, "
                        "parent_id?} objects."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "parent_id": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                },
                "task_id": {
                    "type": "string",
                    "description": "For 'update' or 'get': the task id.",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                    "description": "For 'update': new status.",
                },
                "new_title": {
                    "type": "string",
                    "description": "For 'update': new title (optional).",
                },
                "new_description": {
                    "type": "string",
                    "description": "For 'update': new description (optional).",
                },
                "filter_status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                    "description": "For 'list': only return tasks with this status.",
                },
            },
            "required": ["operation"],
        }

    # -- execute -----------------------------------------------------------

    def execute(self, operation: str = "", **kwargs: Any) -> str:
        if operation == "create":
            return self._create(kwargs.get("tasks", []))
        elif operation == "update":
            return self._update(
                kwargs.get("task_id", ""),
                kwargs.get("status"),
                kwargs.get("new_title"),
                kwargs.get("new_description"),
            )
        elif operation == "list":
            return self._list(kwargs.get("filter_status"))
        elif operation == "get":
            return self._get(kwargs.get("task_id", ""))
        else:
            return f"Error: unknown operation '{operation}'"

    # -- operation implementations -----------------------------------------

    def _create(self, tasks: list[dict]) -> str:
        if not tasks:
            return "Error: 'tasks' list is empty. Provide at least one {title, ...}."

        created: list[Task] = []
        for t in tasks:
            if not isinstance(t, dict) or not t.get("title"):
                continue
            task = Task(
                id=f"task_{next(self._id_counter):04d}",
                title=t["title"].strip(),
                description=t.get("description", "").strip(),
                parent_id=t.get("parent_id"),
            )
            self._tasks[task.id] = task
            created.append(task)

        if not created:
            return "Error: no valid tasks to create."

        lines = [f"Created {len(created)} task(s):"]
        for t in created:
            parent = f" (sub-task of {t.parent_id})" if t.parent_id else ""
            lines.append(f"  [{t.id}] {t.title}{parent}")
        return "\n".join(lines)

    def _update(
        self,
        task_id: str,
        status: str | None = None,
        new_title: str | None = None,
        new_description: str | None = None,
    ) -> str:
        if not task_id:
            return "Error: 'task_id' is required for update."
        task = self._tasks.get(task_id)
        if not task:
            return f"Error: task '{task_id}' not found. Use list to see all tasks."

        changes: list[str] = []
        if status:
            old = task.status
            task.status = status
            changes.append(f"status: {old} → {status}")
        if new_title:
            task.title = new_title.strip()
            changes.append(f"title updated")
        if new_description:
            task.description = new_description.strip()
            changes.append(f"description updated")

        task.updated_at = datetime.now(timezone.utc).isoformat()

        if not changes:
            return f"No changes for task '{task_id}'."
        return f"Updated [{task_id}] {task.title}: {', '.join(changes)}"

    def _list(self, filter_status: str | None = None) -> str:
        tasks = list(self._tasks.values())
        if filter_status:
            tasks = [t for t in tasks if t.status == filter_status]

        if not tasks:
            st = filter_status or "any"
            return f"No tasks found (filter: {st})."

        # Build a tree-like view: top-level first, then children
        top = [t for t in tasks if not t.parent_id]
        children: dict[str, list[Task]] = {}
        for t in tasks:
            if t.parent_id:
                children.setdefault(t.parent_id, []).append(t)

        status_icon = {
            "pending": "○",
            "in_progress": "◐",
            "done": "●",
            "cancelled": "✕",
        }

        lines = [f"Tasks ({len(tasks)} total):"]
        for t in top:
            icon = status_icon.get(t.status, "?")
            lines.append(f"  {icon} [{t.id}] {t.title} ({t.status})")
            for child in children.get(t.id, []):
                cicon = status_icon.get(child.status, "?")
                lines.append(f"     {cicon} [{child.id}] {child.title} ({child.status})")
        return "\n".join(lines)

    def _get(self, task_id: str) -> str:
        if not task_id:
            return "Error: 'task_id' is required."
        task = self._tasks.get(task_id)
        if not task:
            return f"Error: task '{task_id}' not found."
        return json.dumps(task.to_dict(), indent=2, ensure_ascii=False)

    # -- state persistence -------------------------------------------------

    def get_state(self) -> dict:
        return {
            "tasks": [t.to_dict() for t in self._tasks.values()],
            "id_counter": next(self._id_counter),
        }

    def set_state(self, state: dict) -> None:
        self._tasks = {
            t["id"]: Task.from_dict(t) for t in state.get("tasks", [])
        }
        start = state.get("id_counter", 0) + 1
        self._id_counter = itertools.count(start)
