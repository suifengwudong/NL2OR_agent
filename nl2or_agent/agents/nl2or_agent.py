"""NL2OR Agent — built on HAMLET's CodeAgent.

Usage
-----
from agents import build_nl2or_agent
agent = build_nl2or_agent()
result = agent.run("我有一个背包问题……")
"""

from __future__ import annotations

import os
from pathlib import Path

from hamlet.core import CodeAgent, LiteLLMModel

from tools import QueryModelLibraryTool, RunSolverTool


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_DEFAULT_WORKSPACE = Path(__file__).parent.parent / "data" / "workspace"


def _load_system_prompt() -> str:
    """Load system prompt from markdown file."""
    prompt_file = _PROMPTS_DIR / "system_prompt.md"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    return ""


def build_nl2or_agent(
    *,
    model_id: str | None = None,
    workspace_dir: str | Path | None = None,
    verbosity_level: int = 1,
) -> CodeAgent:
    """Create and return a configured NL2OR CodeAgent.

    Parameters
    ----------
    model_id:
        LiteLLM model identifier, e.g. ``"deepseek/deepseek-chat"`` or
        ``"openai/gpt-4o"``. Defaults to the ``HAMLET_MODEL_ID`` env var,
        falling back to ``"openai/gpt-4o-mini"``.
    workspace_dir:
        Directory where generated solver scripts are saved.
    verbosity_level:
        0 = silent, 1 = normal, 2 = verbose / debug.

    Returns
    -------
    CodeAgent
        A fully configured agent ready to receive natural-language OR problems.
    """
    resolved_model_id = (
        model_id
        or os.getenv("HAMLET_MODEL_ID")
        or "openai/gpt-4o-mini"
    )
    resolved_workspace = Path(workspace_dir) if workspace_dir else _DEFAULT_WORKSPACE
    resolved_workspace.mkdir(parents=True, exist_ok=True)

    model = LiteLLMModel(model_id=resolved_model_id)

    tools = [
        QueryModelLibraryTool(),
        RunSolverTool(workspace_dir=resolved_workspace),
    ]

    system_prompt = _load_system_prompt()

    agent = CodeAgent(
        model=model,
        tools=tools,
        name="NL2OR",
        description=(
            "An intelligent agent that converts natural language Operations Research "
            "problems into mathematical models and solves them automatically."
        ),
        system_prompt=system_prompt if system_prompt else None,
        verbosity_level=verbosity_level,
    )

    return agent
