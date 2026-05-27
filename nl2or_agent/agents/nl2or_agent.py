"""NL2OR Agent — built on HAMLET's CodeAgent.

Usage
-----
from agents import build_nl2or_agent
agent = build_nl2or_agent()
result = agent.run("我有一个背包问题……")
"""

from __future__ import annotations

import os
import importlib.resources

import yaml
from hamlet.core import CodeAgent, LiteLLMModel

from core.prompt_loader import load_system_prompt
from tools import (
    ListBlockCatalogTool,
    QueryModelLibraryTool,
    RunSolverTool,
    ValidateProblemIrTool,
)


def build_nl2or_agent(
    *,
    model_id: str | None = None,
    verbosity_level: int = 1,
) -> CodeAgent:
    """Create and return a configured NL2OR CodeAgent.

    Parameters
    ----------
    model_id:
        LiteLLM model identifier, defaults to the ``HAMLET_MODEL_ID``.
    verbosity_level:
        0 = silent, 1 = normal, 2 = verbose / debug.

    Returns
    -------
    CodeAgent
        A fully configured agent ready to receive natural-language OR problems.
    """
    _or_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if _or_key:
        os.environ["OPENROUTER_API_KEY"] = _or_key

    resolved_model_id = (
        model_id
        or os.getenv("HAMLET_MODEL_ID")
    )

    model = LiteLLMModel(model_id=resolved_model_id, api_key=_or_key)

    tools = [
        ListBlockCatalogTool(),
        ValidateProblemIrTool(),
        QueryModelLibraryTool(),
        RunSolverTool(),
    ]

    system_prompt = load_system_prompt()

    # Load default hamlet prompt templates and override the system prompt
    default_prompts_file = importlib.resources.files("hamlet.core.prompts").joinpath("code_agent.yaml")
    #################
    # NOTE: 此处原先是 file.exists():
    #################
    if default_prompts_file.is_file():
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
