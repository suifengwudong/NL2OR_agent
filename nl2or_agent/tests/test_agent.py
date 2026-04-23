"""Tests for agents/nl2or_agent.py build_nl2or_agent and helpers."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.nl2or_agent import _load_system_prompt, build_nl2or_agent
from hamlet.core import CodeAgent


# ---------------------------------------------------------------------------
# _load_system_prompt tests
# ---------------------------------------------------------------------------

class TestLoadSystemPrompt:
    def test_returns_content_when_file_exists(self, tmp_path: Path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "system_prompt.md"
        prompt_file.write_text("You are an OR agent.", encoding="utf-8")

        with patch("agents.nl2or_agent._PROMPTS_DIR", prompts_dir):
            result = _load_system_prompt()

        assert result == "You are an OR agent."

    def test_returns_empty_string_when_file_missing(self, tmp_path: Path):
        empty_dir = tmp_path / "no_prompts"
        empty_dir.mkdir()

        with patch("agents.nl2or_agent._PROMPTS_DIR", empty_dir):
            result = _load_system_prompt()

        assert result == ""


# ---------------------------------------------------------------------------
# build_nl2or_agent tests
# ---------------------------------------------------------------------------

class TestBuildNl2orAgent:
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

    def test_custom_workspace_dir(self, tmp_path: Path):
        workspace = tmp_path / "custom_ws"
        agent = build_nl2or_agent(workspace_dir=workspace, verbosity_level=0)
        assert isinstance(agent, CodeAgent)
        assert workspace.exists()

    def test_model_id_from_env(self, monkeypatch):
        monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o-mini")
        agent = build_nl2or_agent(verbosity_level=0)
        assert isinstance(agent, CodeAgent)

    def test_explicit_model_id_overrides_env(self, monkeypatch):
        monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o")
        agent = build_nl2or_agent(model_id="openai/gpt-4o-mini", verbosity_level=0)
        assert isinstance(agent, CodeAgent)

    def test_default_model_id_used_when_no_env(self, monkeypatch):
        monkeypatch.delenv("HAMLET_MODEL_ID", raising=False)
        agent = build_nl2or_agent(verbosity_level=0)
        assert isinstance(agent, CodeAgent)

    def test_authorized_imports_include_required_libs(self):
        agent = build_nl2or_agent(verbosity_level=0)
        imports = agent.python_executor.authorized_imports
        assert "numpy" in imports
        assert "scipy.optimize" in imports
        assert "pulp" in imports
        assert "pandas" in imports

    def test_workspace_created_if_not_exists(self, tmp_path: Path):
        workspace = tmp_path / "new_dir" / "nested"
        assert not workspace.exists()
        build_nl2or_agent(workspace_dir=workspace, verbosity_level=0)
        assert workspace.exists()

    def test_no_prompt_templates_when_prompt_file_missing(self, tmp_path: Path):
        """When system_prompt.md is missing, agent still builds without error."""
        empty_dir = tmp_path / "empty_prompts"
        empty_dir.mkdir()
        with patch("agents.nl2or_agent._PROMPTS_DIR", empty_dir):
            agent = build_nl2or_agent(verbosity_level=0)
        assert isinstance(agent, CodeAgent)
