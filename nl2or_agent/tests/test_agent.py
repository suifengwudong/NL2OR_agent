"""Tests for agents/nl2or_agent.py build_nl2or_agent and helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.nl2or_agent import apply_agent_mode, build_nl2or_agent
from core.prompt_loader import AGENT_MODES, load_system_prompt
from hamlet.core import CodeAgent


# ---------------------------------------------------------------------------
# load_system_prompt tests
# ---------------------------------------------------------------------------


class TestLoadSystemPrompt:
    def test_returns_content_when_file_exists(self, tmp_path: Path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "system.prompt.md"
        prompt_file.write_text("You are an OR agent.", encoding="utf-8")

        with patch("core.prompt_loader._PROMPTS_DIR", prompts_dir):
            result = load_system_prompt()

        assert result.startswith("You are an OR agent.")

    def test_returns_empty_string_when_file_missing(self, tmp_path: Path):
        empty_dir = tmp_path / "no_prompts"
        empty_dir.mkdir()

        with patch("core.prompt_loader._PROMPTS_DIR", empty_dir):
            result = load_system_prompt()

        # When system prompt file is missing, we still append appendix if
        # ir_format prompt exists.  Since both are in the same dir, both
        # will be missing — result is empty plus catalog markdown.
        assert "Canonical block_id catalog" in result

    def test_each_mode_selects_its_own_workflow(self):
        interactive = load_system_prompt("interactive")
        automatic = load_system_prompt("automatic")

        assert "one step per user turn" in interactive
        assert "complete the whole pipeline in one turn" in automatic
        assert "one step per user turn" not in automatic
        assert "complete the whole pipeline in one turn" not in interactive

    def test_modes_share_core_appendix_and_catalog(self):
        for mode in AGENT_MODES:
            prompt = load_system_prompt(mode)
            assert prompt.startswith("You are NL2OR")
            assert "## Compositional modeling" in prompt
            assert "Appendix: problem_ir_format" in prompt
            assert "Canonical block_id catalog" in prompt

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="interactive"):
            load_system_prompt("nonsense")

    def test_prompts_route_solving_through_solve_ir_first(self):
        """求解默认走确定性快路径，run_solver 只作为库外块的退路。"""
        for mode in AGENT_MODES:
            prompt = load_system_prompt(mode)
            assert "solve_ir" in prompt
            assert "solve_ir" in prompt.split("Fall back to `run_solver")[0]
            assert "without executable semantics" in prompt


# ---------------------------------------------------------------------------
# build_nl2or_agent tests
# ---------------------------------------------------------------------------


class TestBuildNl2orAgent:
    @pytest.fixture(autouse=True)
    def _ensure_model_env(self, monkeypatch) -> None:
        monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o-mini")

    def test_returns_code_agent(self):
        agent = build_nl2or_agent(verbosity_level=0)
        assert isinstance(agent, CodeAgent)

    def test_agent_name(self):
        agent = build_nl2or_agent(verbosity_level=0)
        assert agent.name == "NL2OR"

    def test_tools_loaded(self):
        agent = build_nl2or_agent(verbosity_level=0)
        tool_names = [t.name for t in agent.tools.values()]
        assert "query_model_library" in tool_names
        assert "run_solver" in tool_names

    def test_model_id_from_env(self, monkeypatch):
        monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o-mini")
        agent = build_nl2or_agent(verbosity_level=0)
        assert isinstance(agent, CodeAgent)

    def test_reasoning_off_goes_through_extra_body(self, monkeypatch):
        """思考 token 占 completion 的八成，HAMLET_REASONING=off 时关掉。

        litellm 不认识这个模型 id，reasoning_effort 会在过滤阶段被丢掉，
        所以只能走 extra_body。
        """
        monkeypatch.setenv("HAMLET_REASONING", "off")
        agent = build_nl2or_agent(verbosity_level=0)
        assert agent.model.kwargs["extra_body"] == {"reasoning": {"enabled": False}}

    def test_reasoning_left_to_the_provider_by_default(self, monkeypatch):
        monkeypatch.delenv("HAMLET_REASONING", raising=False)
        agent = build_nl2or_agent(verbosity_level=0)
        assert "extra_body" not in agent.model.kwargs

    def test_raises_when_no_env(self, monkeypatch):
        monkeypatch.delenv("HAMLET_MODEL_ID", raising=False)
        with pytest.raises(ValueError, match="HAMLET_MODEL_ID"):
            build_nl2or_agent(verbosity_level=0)

    @pytest.mark.parametrize("lib", ["numpy", "scipy.optimize", "pulp", "pandas"])
    def test_authorized_imports_include_required_libs(self, lib: str):
        agent = build_nl2or_agent(verbosity_level=0)
        assert lib in agent.additional_authorized_imports

    def test_no_prompt_templates_when_prompt_file_missing(self, tmp_path: Path):
        empty_dir = tmp_path / "empty_prompts"
        empty_dir.mkdir()
        with patch("core.prompt_loader._PROMPTS_DIR", empty_dir):
            agent = build_nl2or_agent(verbosity_level=0)
        assert isinstance(agent, CodeAgent)

    def test_uses_markdown_code_block_tags(self):
        """Agent must parse markdown ```python fences (deepseek-native), not
        HAMLET's default ``<code>`` XML tags."""
        agent = build_nl2or_agent(verbosity_level=0)
        assert agent.code_block_tags == ("```python", "```")

    def test_bare_code_fallback_parses(self):
        """Regression: deepseek sometimes emits a bare ``final_answer(...)``
        with no code fences; HAMLET appends the closing fence and fails to
        parse.  Our patch must fall back to treating the bare code as valid."""
        import ast

        import hamlet.core.agents as hamlet_agents

        build_nl2or_agent(verbosity_level=0)
        parse_fn = hamlet_agents.parse_several_code_blobs

        # Simulate the exact failure: model emits bare final_answer without
        # opening fence, and HAMLET auto-appends the closing fence.
        bare = 'final_answer("""请确认：\np-中位问题，p=2""")'
        raw = bare + "```"
        actions, strategy, _ = parse_fn(raw, ("```python", "```"))

        assert strategy is None
        assert len(actions) == 1
        # Recovered code must be syntactically valid Python and call final_answer.
        ast.parse(actions[0])
        assert "final_answer" in actions[0]

    def test_markdown_fenced_block_parses(self):
        """A well-formed markdown code fence must still parse via the fallback
        path (i.e. patch must not break normal HAMLET parsing)."""
        import hamlet.core.agents as hamlet_agents

        build_nl2or_agent(verbosity_level=0)
        parse_fn = hamlet_agents.parse_several_code_blobs

        raw = "```python\nprint(1 + 1)\n```"
        actions, strategy, _ = parse_fn(raw, ("```python", "```"))
        assert "print(1 + 1)" in actions[0]

    def test_default_mode_is_interactive(self):
        agent = build_nl2or_agent(verbosity_level=0)
        assert "one step per user turn" in agent.prompt_templates["system_prompt"]

    def test_automatic_mode_prompt(self):
        agent = build_nl2or_agent(mode="automatic", verbosity_level=0)
        assert "complete the whole pipeline in one turn" in agent.prompt_templates["system_prompt"]

    def test_apply_agent_mode_switches_workflow(self):
        agent = build_nl2or_agent(verbosity_level=0)

        apply_agent_mode(agent, "automatic")
        assert "complete the whole pipeline in one turn" in agent.prompt_templates["system_prompt"]

        apply_agent_mode(agent, "interactive")
        assert "one step per user turn" in agent.prompt_templates["system_prompt"]

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="interactive"):
            build_nl2or_agent(mode="nonsense", verbosity_level=0)
