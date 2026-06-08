"""Session persistence layer — JSON-file-based storage.

Each session is a single ``.json`` file under ``data/sessions/``.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_config


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """A conversation session with full message history and tool state."""

    id: str
    name: str = "New Chat"
    created_at: str = ""
    updated_at: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
            "tool_state": self.tool_state,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Session:
        # tolerate missing keys from older session files
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            name=d.get("name", "New Chat"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            messages=d.get("messages", []),
            tool_state=d.get("tool_state", {}),
        )

    @property
    def summary(self) -> dict:
        """Lightweight summary for the session list (no messages)."""
        tasks = self.tool_state.get("todo", {}).get("tasks", [])
        total = len(tasks)
        done = sum(1 for t in tasks if t.get("status") == "done")
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "task_total": total,
            "task_done": done,
        }


# ---------------------------------------------------------------------------
# manager
# ---------------------------------------------------------------------------

class SessionManager:
    """CRUD operations for Session objects backed by JSON files."""

    def __init__(self) -> None:
        cfg = get_config()
        self._dir = Path(cfg.sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # -- path helpers -------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    # -- CRUD ---------------------------------------------------------------

    def create(self, name: str = "New Chat") -> Session:
        """Create a brand-new session and persist it immediately."""
        session = Session(id=str(uuid.uuid4())[:8], name=name)
        self.save(session)
        return session

    def load(self, session_id: str) -> Session:
        """Load a session from disk.

        Returns a *new* empty session if the file does not exist (so the
        caller doesn't have to branch on None).
        """
        path = self._path(session_id)
        if not path.exists():
            return Session(id=session_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        return Session.from_dict(data)

    def save(self, session: Session) -> None:
        """Persist a session to disk."""
        session.updated_at = datetime.now(timezone.utc).isoformat()
        data = session.to_dict()
        self._path(session.id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def delete(self, session_id: str) -> bool:
        """Delete a session file. Returns True if it existed."""
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_sessions(self) -> list[dict]:
        """Return summaries for all sessions, newest first."""
        results: list[dict] = []
        for path in sorted(
            self._dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sess = Session.from_dict(data)
                results.append(sess.summary)
            except (json.JSONDecodeError, KeyError):
                # Skip corrupted files silently
                continue
        return results

    def rename(self, session_id: str, name: str) -> None:
        """Rename a session."""
        session = self.load(session_id)
        session.name = name
        self.save(session)
