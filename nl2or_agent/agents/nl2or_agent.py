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
import yaml
import importlib.resources

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
        or "openrouter/deepseek/deepseek-chat"
    )
    resolved_workspace = Path(workspace_dir) if workspace_dir else _DEFAULT_WORKSPACE
    resolved_workspace.mkdir(parents=True, exist_ok=True)

    model = LiteLLMModel(model_id=resolved_model_id)

    tools = [
        QueryModelLibraryTool(),
        RunSolverTool(workspace_dir=resolved_workspace),
    ]

    system_prompt = _load_system_prompt()

    # Load default hamlet prompt templates and override the system prompt
    default_prompts_file = importlib.resources.files("hamlet.core.prompts").joinpath("code_agent.yaml")
    if default_prompts_file.exists():
        with default_prompts_file.open("r", encoding="utf-8") as f:
            prompt_templates = yaml.safe_load(f)
    else:
        prompt_templates = None

    if prompt_templates and system_prompt:
        prompt_templates["system_prompt"] = system_prompt

    agent = CodeAgent(
        model=model,
        tools=tools,
        name="NL2OR",
        description=(
            "An intelligent agent that converts natural language Operations Research "
            "problems into mathematical models and solves them automatically."
        ),
        prompt_templates=prompt_templates,
        verbosity_level=verbosity_level,
        additional_authorized_imports=[
            "scipy.optimize", "scipy", "gurobipy", "pulp", 
            "numpy", "pandas", "json", "math", "os"
        ],
    )

    return agent
