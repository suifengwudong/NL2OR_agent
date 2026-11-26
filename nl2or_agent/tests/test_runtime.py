"""Shared turn runtime: CLI and Web must produce the same session state."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.runtime import hydrate_agent_history, run_turn
from utils.session import Session, reset_session


class _Agent:
    def __init__(self, answer: str = "答案", error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[tuple[str, bool]] = []
        self.prompt_templates: dict[str, str] = {}

    def run(self, message: str, *, reset: bool) -> str:
        self.calls.append((message, reset))
        if self.error is not None:
            raise self.error
        return self.answer


@pytest.fixture(autouse=True)
def _isolate_sessions(tmp_path, monkeypatch):
    import utils.session as session_mod

    monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
    reset_session()


def _entries(session_id: str) -> list[dict]:
    path = Session.load(session_id).conversation_file
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_turn_logs_both_roles_and_returns_artifacts():
    agent = _Agent("最优目标值 220")

    with patch("agents.runtime.apply_agent_mode") as apply_mode:
        result = run_turn(
            "背包问题",
            session_id=None,
            mode="automatic",
            agent=agent,
        )

    apply_mode.assert_called_once_with(agent, "automatic")
    assert agent.calls == [("背包问题", False)]
    assert result.error == ""
    assert result.answer == "最优目标值 220"
    assert result.model_ready is False
    assert result.code_files == ()
    assert result.workspace.name == result.session_id
    assert [entry["role"] for entry in _entries(result.session_id)] == ["user", "assistant"]
    assert _entries(result.session_id)[1]["content"] == "最优目标值 220"


def test_turn_records_the_error_and_keeps_the_session():
    agent = _Agent(error=RuntimeError("模型不可用"))

    result = run_turn("问题", session_id=None, mode="interactive", agent=agent)

    assert result.error == "模型不可用"
    assert result.answer == ""
    assert [entry["role"] for entry in _entries(result.session_id)] == ["user", "assistant"]
    assert _entries(result.session_id)[1]["content"].startswith("[ERROR]")


def test_turn_links_the_answer_manifest_to_the_assistant_entry():
    from core.ir_validate import validate_problem_ir
    from utils.artifact_store import ArtifactStore

    session = Session(session_id="mf01")
    store = ArtifactStore(session)
    report = validate_problem_ir(
        {
            "problem_families": [{"id": "p_median"}],
            "entities": {"I": {"size": 2}, "J": {"size": 2}},
            "parameters": {"p": 1, "distance": [[1, 2], [2, 1]]},
            "constraint_blocks": [
                {"block_id": "assign_each_demand_once"},
                {"block_id": "link_assignment_to_open"},
                {"block_id": "cardinality_open_p_facilities"},
            ],
            "objective": {"block_id": "weighted_service_distance_objective"},
        }
    )
    store.save_model_artifact(report, name="baseline", kind="baseline")
    store.save_solve_artifact(
        report["normalized_ir"],
        status="Optimal",
        objective=10,
        text="状态：最优\n[RESULT] Objective: 10",
    )
    agent = _Agent("[MODEL_MATH]\n[SOLVE_RESULT]")

    result = run_turn("求解", session_id="mf01", mode="interactive", agent=agent)

    assert result.error == ""
    entries = _entries("mf01")
    assert entries[1].get("answer_id", "").startswith("answer_")


def test_turn_can_use_a_session_bound_agent_getter():
    agent = _Agent("来自缓存")
    seen: list[tuple[str, str]] = []

    def get_agent(session_id: str, mode: str) -> _Agent:
        seen.append((session_id, mode))
        return agent

    result = run_turn(
        "问题",
        session_id=None,
        mode="interactive",
        get_agent=get_agent,
    )

    assert seen == [(result.session_id, "interactive")]
    assert result.answer == "来自缓存"


def test_factory_receives_the_turn_mode():
    agent = _Agent("按模式构造")
    modes: list[str] = []

    def factory(mode: str) -> _Agent:
        modes.append(mode)
        return agent

    result = run_turn("问题", session_id=None, mode="automatic", agent_factory=factory)

    assert modes == ["automatic"]
    assert result.answer == "按模式构造"


def test_turn_requires_an_agent_source():
    with pytest.raises(ValueError, match="agent"):
        run_turn("问题", session_id=None, mode="interactive")


def test_hydrate_agent_history_seeds_empty_memory():
    from hamlet.core.memory import AgentMemory

    agent = _Agent()
    agent.memory = AgentMemory("system")
    hydrate_agent_history(
        agent,
        [
            {"role": "user", "content": "历史问题"},
            {"role": "assistant", "content": "历史回答"},
        ],
    )

    assert len(agent.memory.steps) == 2
    messages = [message for step in agent.memory.steps for message in step.to_messages()]
    assert any("历史问题" in str(message.content) for message in messages)
    assert any("历史回答" in str(message.content) for message in messages)

    hydrate_agent_history(agent, [{"role": "user", "content": "重复"}])
    assert len(agent.memory.steps) == 2


def test_run_turn_hydrates_a_fresh_agent_from_the_session():
    from hamlet.core.memory import AgentMemory

    session = Session()
    session.save_conversation_entry("user", "历史问题")
    session.save_conversation_entry("assistant", "历史回答")
    agent = _Agent("新回答")
    agent.memory = AgentMemory("system")

    result = run_turn("继续", session_id=session.session_id, mode="interactive", agent=agent)

    assert result.answer == "新回答"
    assert len(agent.memory.steps) == 2
    assert agent.calls == [("继续", False)]


def test_hydration_skips_an_agent_without_memory():
    hydrate_agent_history(_Agent(), [{"role": "user", "content": "问题"}])
