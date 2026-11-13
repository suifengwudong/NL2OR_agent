"""Shared per-turn runtime for the CLI and the web UI.

The two interfaces differ only in how they present a turn. Session binding,
agent mode, conversation logging, output cleaning and artifact collection live
here so the same input produces the same session state in both places.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.output_format import format_agent_output
from utils.session import get_session, resolve_session

from .nl2or_agent import apply_agent_mode


@dataclass(frozen=True)
class TurnResult:
    """The outcome of one user turn, independent of the interface."""

    session_id: str
    answer: str
    error: str
    workspace: Path
    model_ready: bool
    code_files: tuple[Path, ...]


def run_turn(
    message: str,
    *,
    session_id: str | None,
    mode: str,
    agent: Any | None = None,
    agent_factory: Callable[[], Any] | None = None,
    get_agent: Callable[[str], Any] | None = None,
) -> TurnResult:
    """Run one turn against the session identified by *session_id*.

    Exactly one of *agent*, *agent_factory* and *get_agent* is expected.
    ``get_agent`` is used by the web UI to reuse its per-session cache; the CLI
    passes its single agent.
    """
    if agent is None and agent_factory is None and get_agent is None:
        raise ValueError("run_turn needs an agent, an agent_factory or get_agent")
    session = resolve_session(session_id)
    sid = session.session_id
    try:
        get_session(sid)
        if get_agent is not None:
            active_agent = get_agent(sid)
        elif agent is not None:
            active_agent = agent
        elif agent_factory is not None:
            active_agent = agent_factory()

        apply_agent_mode(active_agent, mode)
        session.save_conversation_entry(role="user", content=message.strip())
        raw = active_agent.run(message.strip(), reset=False)
        answer = format_agent_output(raw)
        session.save_conversation_entry(role="assistant", content=answer)
        return TurnResult(
            session_id=sid,
            answer=answer,
            error="",
            workspace=session.workspace,
            model_ready=session.model_file.is_file(),
            code_files=tuple(session.list_code_files()),
        )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            session.save_conversation_entry(role="assistant", content=f"[ERROR] {error}")
        except Exception:  # noqa: BLE001
            # The conversation log must not hide the original failure.
            pass
        return TurnResult(
            session_id=sid,
            answer="",
            error=error,
            workspace=session.workspace,
            model_ready=session.model_file.is_file(),
            code_files=tuple(session.list_code_files()),
        )


__all__ = ["TurnResult", "run_turn"]
