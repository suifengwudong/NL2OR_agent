"""Shared per-turn runtime for the CLI and the web UI.

The two interfaces differ only in how they present a turn. Session binding,
agent mode, conversation logging, output cleaning and artifact collection live
here so the same input produces the same session state in both places.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.answer_manifest import AnswerManifest
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


def _model_ready(session) -> bool:
    """True when the session has a model/patch artifact or a legacy model.json."""
    return ArtifactStore(session).has_models()


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
    providers = [
        name
        for name, value in (
            ("agent", agent),
            ("agent_factory", agent_factory),
            ("get_agent", get_agent),
        )
        if value is not None
    ]
    if len(providers) != 1:
        raise ValueError(
            "run_turn needs exactly one of agent, agent_factory, get_agent; "
            f"got {providers or 'none'}"
        )
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
        raw = active_agent.run(message.strip(), reset=False)
        manifest = AnswerManifest(session_id=sid)
        answer = expand_placeholders(format_agent_output(raw), session, manifest=manifest)
        session.save_conversation_entry(
            role="assistant", content=answer, extra=manifest.entry_extra()
        )
        return TurnResult(
            session_id=sid,
            answer=answer,
            error="",
            workspace=session.workspace,
            model_ready=_model_ready(session),
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
            model_ready=_model_ready(session),
            code_files=tuple(session.list_code_files()),
        )


__all__ = ["TurnResult", "hydrate_agent_history", "run_turn"]
