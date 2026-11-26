"""Shared per-turn runtime for the CLI and the web UI.

The two interfaces differ only in how they present a turn. Session binding,
agent mode, conversation logging, output cleaning and artifact collection live
here so the same input produces the same session state in both places.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.answer_manifest import latest_answer_manifest
from core.output_format import expand_placeholders, format_agent_output
from utils.artifact_store import ArtifactStore
from utils.session import get_session, resolve_session

from .nl2or_agent import apply_agent_mode

AgentFactory = Callable[[str], Any]
AgentGetter = Callable[[str, str], Any]


def hydrate_agent_history(agent: Any, messages: list[dict[str, str]]) -> None:
    """Seed an empty agent memory with the visible user/assistant turns.

    The web UI restores the chat from ``conversation.jsonl``; a fresh agent in
    that session must see the same dialogue. Tool observations are not replayed,
    because replaying them would execute tools again.
    """
    from hamlet.core.memory import ActionStep, TaskStep
    from hamlet.core.monitoring import Timing

    memory = getattr(agent, "memory", None)
    steps = getattr(memory, "steps", None)
    if not isinstance(steps, list) or steps or not messages:
        return

    for entry in messages:
        role = entry.get("role")
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            steps.append(TaskStep(task=content))
        elif role == "assistant":
            steps.append(
                ActionStep(
                    step_number=len(steps) + 1,
                    timing=Timing(start_time=0.0, end_time=0.0),
                    model_output=content,
                    action_output=content,
                    is_final_answer=True,
                )
            )


@dataclass(frozen=True)
class TurnResult:
    """The outcome of one user turn, independent of the interface."""

    session_id: str
    answer: str
    error: str
    workspace: Path
    model_ready: bool
    code_files: tuple[Path, ...]


def _answer_id_of(session, started_at: datetime) -> str | None:
    """Link this turn to the AnswerManifest saved while rendering the answer."""
    try:
        manifest = latest_answer_manifest(ArtifactStore(session))
    except Exception:  # noqa: BLE001
        return None
    if manifest is None or not manifest.created_at:
        return None
    try:
        created = datetime.fromisoformat(manifest.created_at)
    except ValueError:
        return None
    return manifest.answer_id if created > started_at else None


def run_turn(
    message: str,
    *,
    session_id: str | None,
    mode: str,
    agent: Any | None = None,
    agent_factory: AgentFactory | None = None,
    get_agent: AgentGetter | None = None,
) -> TurnResult:
    """Run one turn against the session identified by *session_id*.

    Exactly one of *agent*, *agent_factory* and *get_agent* is expected.
    ``get_agent`` is used by the web UI to reuse its per-session cache and
    receives ``(session_id, mode)`` so a lazily built agent starts in the
    mode the user actually selected; the CLI passes its single agent.
    """
    if agent is None and agent_factory is None and get_agent is None:
        raise ValueError("run_turn needs an agent, an agent_factory or get_agent")
    session = resolve_session(session_id)
    sid = session.session_id
    try:
        get_session(sid)
        if get_agent is not None:
            active_agent = get_agent(sid, mode)
        elif agent is not None:
            active_agent = agent
        elif agent_factory is not None:
            active_agent = agent_factory(mode)

        hydrate_agent_history(active_agent, session.load_conversation())
        apply_agent_mode(active_agent, mode)
        session.save_conversation_entry(role="user", content=message.strip())
        started_at = datetime.now(timezone.utc)
        raw = active_agent.run(message.strip(), reset=False)
        answer = expand_placeholders(format_agent_output(raw), session)
        session.save_conversation_entry(
            role="assistant", content=answer, answer_id=_answer_id_of(session, started_at)
        )
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


__all__ = ["TurnResult", "hydrate_agent_history", "run_turn"]
