"""Tests for agents/nl2or_agent.py build_nl2or_agent and helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.nl2or_agent import apply_agent_mode, build_nl2or_agent
from core.ir_catalog import load_block_catalog
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

        # 没有提示词文件时返回空串；目录与 what_if 附录不再拼进提示词
        assert result == ""

    def test_each_mode_selects_its_own_workflow(self):
        interactive = load_system_prompt("interactive")
        automatic = load_system_prompt("automatic")

        assert "one step per user turn" in interactive
        assert "complete the whole pipeline in one turn" in automatic
        assert "one step per user turn" not in automatic
        assert "complete the whole pipeline in one turn" not in interactive

    def test_modes_share_core_and_ir_appendix_without_the_catalog(self):
        for mode in AGENT_MODES:
            prompt = load_system_prompt(mode)
            assert prompt.startswith("You are NL2OR")
            assert "## Compositional modeling" in prompt
            assert "Appendix: problem_ir_format" in prompt
            # 模型库不再静态展开进提示词：块定义只能来自检索工具
            assert "Canonical block_id catalog" not in prompt
            assert "需求唯一分配" not in prompt
            assert "典型模型" not in prompt
            assert "search_model_library" in prompt
            assert "describe_model" in prompt

    def test_prompt_size_is_independent_of_the_block_catalog(self, tmp_path: Path):
        """把积木块目录换成上百个条目，提示词长度必须不变。"""
        import json as _json

        big = tmp_path / "constraint_blocks.json"
        blocks = [
            {
                "id": f"synthetic_block_{i}",
                "category": "synthetic",
                "name": f"块{i}",
                "description": "x" * 80,
                "math": "\\sum x",
                "parameters": [],
            }
            for i in range(150)
        ]
        big.write_text(
            _json.dumps({"schema_version": 2, "blocks": blocks}, ensure_ascii=False),
            encoding="utf-8",
        )

        plain = load_system_prompt("automatic")
        with patch("core.ir_catalog._BLOCKS_PATH", big):
            loaded = load_block_catalog(big)
            assert len(loaded["blocks"]) == 150
        assert load_system_prompt("automatic") == plain

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
        # 六个项目工具（检索、描述、校验、文档、执行、求解）+ HAMLET 自带 final_answer
        assert sorted(tool_names) == [
            "describe_model",
            "final_answer",
            "model_math",
            "run_solver",
            "search_model_library",
            "solve_ir",
            "validate_problem_ir",
        ]

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
        interactive_prompt = agent.prompt_templates["system_prompt"]

        # 同模式的回合不再重建提示词
        apply_agent_mode(agent, "interactive")
        assert agent.prompt_templates["system_prompt"] == interactive_prompt

        apply_agent_mode(agent, "automatic")
        assert "complete the whole pipeline in one turn" in agent.prompt_templates["system_prompt"]

        apply_agent_mode(agent, "interactive")
        assert "one step per user turn" in agent.prompt_templates["system_prompt"]

    def test_build_and_prompt_evaluation_are_silent(self, capsys):
        """HAMLET 在 initialize_system_prompt 里残留 print，补丁必须把它静音。"""
        agent = build_nl2or_agent(verbosity_level=0)

        assert agent.system_prompt  # 求值仍然成功
        assert capsys.readouterr().out == ""

    def test_startup_banner_follows_verbosity(self, capsys):
        build_nl2or_agent(verbosity_level=0)
        assert capsys.readouterr().out == ""

        build_nl2or_agent(verbosity_level=1)
        assert "Using model" in capsys.readouterr().out

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="interactive"):
            build_nl2or_agent(mode="nonsense", verbosity_level=0)
