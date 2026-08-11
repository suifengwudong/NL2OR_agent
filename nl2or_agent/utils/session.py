"""Session-scoped workspace management for solver artifacts.

Each conversation gets a unique session directory under
``data/workspace/sessions/``.  Solvers, logs, and conversation history are
isolated per session.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_WORKSPACE_ROOT = Path(
    os.getenv("NL2OR_WORKSPACE_DIR") or Path(__file__).parent.parent / "data" / "workspace"
)
_SESSIONS_ROOT = _WORKSPACE_ROOT / "sessions"
_write_lock = threading.Lock()


class Session:
    """A single conversation session with its own workspace directory."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.created_at = datetime.now(timezone.utc)
        self.workspace = _SESSIONS_ROOT / self.session_id
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------
    # Directory properties
    # ----------------------------------------------------------------

    @property
    def code_dir(self) -> Path:
        """Directory for solver code files."""
        d = self.workspace / "code"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def conversation_file(self) -> Path:
        """Path to the conversation log (JSON Lines)."""
        return self.workspace / "conversation.jsonl"

    # ----------------------------------------------------------------
    # Code / output persistence
    # ----------------------------------------------------------------

    def save_code(self, code: str, filename: str | None = None) -> Path:
        """Write solver code to the session code directory."""
        fname = filename or f"solver_{uuid.uuid4().hex[:8]}.py"
        path = self.code_dir / fname
        with _write_lock:
            path.write_text(code, encoding="utf-8")
        return path

    # ----------------------------------------------------------------
    # Conversation history persistence
    # ----------------------------------------------------------------

    def save_conversation_entry(self, role: str, content: str) -> None:
        """Append one conversation turn to the session's JSONL log file."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "content": content,
        }
        with _write_lock:
            with open(self.conversation_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ----------------------------------------------------------------
    # File listing
    # ----------------------------------------------------------------

    def list_code_files(self) -> list[Path]:
        """Return all solver files in this session."""
        return sorted(self.code_dir.glob("*.py")) if self.code_dir.exists() else []

    # ----------------------------------------------------------------
    # Class methods for session discovery
    # ----------------------------------------------------------------

    @classmethod
    def list_all(cls) -> list[str]:
        """Return all session IDs on disk."""
        if not _SESSIONS_ROOT.exists():
            return []
        return sorted(d.name for d in _SESSIONS_ROOT.iterdir() if d.is_dir())

    @classmethod
    def load(cls, session_id: str) -> Session | None:
        """Load an existing session by ID, or None if it doesn't exist."""
        ws = _SESSIONS_ROOT / session_id
        if not ws.is_dir():
            return None
        s = cls(session_id=session_id)
        return s

    @classmethod
    def prune(cls, max_age_days: int = 30) -> int:
        """Remove sessions older than *max_age_days*. Returns count removed."""
        if not _SESSIONS_ROOT.exists():
            return 0
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
        removed = 0
        with _write_lock:
            for d in _SESSIONS_ROOT.iterdir():
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d)
                    removed += 1
        return removed


# ---------------------------------------------------------------------------
# Thread-safe per-thread session storage (replaces module-level singleton)
# ---------------------------------------------------------------------------

_tls = threading.local()


def get_session(session_id: str | None = None) -> Session:
    """Get or create the **current thread's** session.

    Thread-safe: each thread / Gradio request gets its own Session instance
    via ``threading.local``, avoiding cross-user contamination.
    """
    current: Session | None = getattr(_tls, "session", None)
    if current is None or (session_id and current.session_id != session_id):
        _tls.session = Session(session_id=session_id)
    return _tls.session


def reset_session() -> None:
    """Reset the current thread's session (create a new one next call)."""
    _tls.session = None


def prune_old_sessions(max_age_days: int = 30) -> int:
    """Convenience wrapper for periodic cleanup (called on app startup)."""
    return Session.prune(max_age_days=max_age_days)
