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
    resolved_model_id = os.getenv("HAMLET_MODEL_ID")
    _or_key = os.getenv("OPENROUTER_API_KEY")

    print(
        f"Using model: {resolved_model_id}, with OPENROUTER_API_KEY: {'set' if _or_key else 'not set'}"
    )

    model = LiteLLMModel(model_id=resolved_model_id, api_key=_or_key)

    tools = [
        ListBlockCatalogTool(),
        ValidateProblemIrTool(),
        QueryModelLibraryTool(),
        RunSolverTool(),
    ]

    system_prompt = load_system_prompt()

    default_prompts_file = importlib.resources.files("hamlet.core.prompts").joinpath(
        "code_agent.yaml"
    )
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
            "scipy.optimize",
            "scipy",
            "gurobipy",
            "pulp",
            "numpy",
            "pandas",
            "json",
            "math",
            "os",
        ],
    )

    return agent
