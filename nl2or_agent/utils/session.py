"""Session-scoped workspace management for solver artifacts.

Each conversation gets a unique session directory under
``data/workspace/sessions/``.  Solvers, logs, and intermediate results are
isolated per session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

_SESSIONS_ROOT = Path(__file__).parent.parent / "data" / "workspace" / "sessions"


class Session:
    """A single conversation session with its own workspace directory."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.created_at = datetime.now(timezone.utc)
        self.workspace = _SESSIONS_ROOT / self.session_id
        self.workspace.mkdir(parents=True, exist_ok=True)

    @property
    def code_dir(self) -> Path:
        """Directory for solver code files."""
        d = self.workspace / "code"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def output_dir(self) -> Path:
        """Directory for solver output / logs."""
        d = self.workspace / "output"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_code(self, code: str, filename: str | None = None) -> Path:
        """Write solver code to the session code directory."""
        fname = filename or f"solver_{uuid.uuid4().hex[:8]}.py"
        path = self.code_dir / fname
        path.write_text(code, encoding="utf-8")
        return path

    def save_output(self, filename: str, content: str) -> Path:
        """Write solver output to the session output directory."""
        path = self.output_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def list_code_files(self) -> list[Path]:
        """Return all solver files in this session."""
        return sorted(self.code_dir.glob("*.py")) if self.code_dir.exists() else []

    def list_output_files(self) -> list[Path]:
        """Return all output files in this session."""
        return sorted(self.output_dir.glob("*")) if self.output_dir.exists() else []

    # ------------------------------------------------------------------
    # Class methods for session discovery
    # ------------------------------------------------------------------

    @classmethod
    def list_all(cls) -> list[str]:
        """Return all session IDs on disk."""
        if not _SESSIONS_ROOT.exists():
            return []
        return sorted(
            d.name for d in _SESSIONS_ROOT.iterdir() if d.is_dir()
        )

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
        for d in _SESSIONS_ROOT.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                import shutil
                shutil.rmtree(d)
                removed += 1
        return removed


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_current_session: Session | None = None


def get_session(session_id: str | None = None) -> Session:
    """Get or create the current session."""
    global _current_session
    if _current_session is None or (session_id and _current_session.session_id != session_id):
        _current_session = Session(session_id=session_id)
    return _current_session


def reset_session() -> None:
    """Reset the current session (create a new one next call)."""
    global _current_session
    _current_session = None
