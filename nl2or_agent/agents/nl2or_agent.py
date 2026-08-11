"""NL2OR Agent — built on HAMLET's CodeAgent.

Usage
-----
from agents import build_nl2or_agent
agent = build_nl2or_agent()
result = agent.run("我有一个背包问题……")
"""

from __future__ import annotations

import ast
import os
import importlib.resources
from typing import Any

import yaml
from hamlet.core import CodeAgent, LiteLLMModel

from core.prompt_loader import load_system_prompt
from tools import (
    ListBlockCatalogTool,
    QueryModelLibraryTool,
    RunSolverTool,
    ValidateProblemIrTool,
)

# Use markdown code fences instead of HAMLET's default ``<code>`` XML tags.
# deepseek-chat (and most open models) are trained to emit ```python ... ```
# blocks, not ``<code>...</code>``, so this dramatically reduces parse failures.
_CODE_BLOCK_TAGS: str | tuple[str, str] = "markdown"

_PATCHED_ATTR = "_nl2or_parse_patched"


def _patch_hamlet_code_parsing() -> None:
    """Harden HAMLET's code parsing against models that omit code tags.

    HAMLET's ``parse_several_code_blobs`` requires the LLM output to be wrapped
    in ``<code>...</code>`` (or markdown) tags.  Some models (e.g. deepseek-chat)
    occasionally emit a bare ``final_answer(...)`` call with no tags at all;
    HAMLET then auto-appends the closing tag and parsing fails.

    This patch adds a fallback: strip the trailing closing tag and, when the
    remainder parses as valid Python, treat it as a single code action.  The
    original error is preserved when the fallback also fails.
    """
    import hamlet.core.agents as hamlet_agents

    if getattr(hamlet_agents, _PATCHED_ATTR, False):
        return

    _original = hamlet_agents.parse_several_code_blobs

    def _robust_parse_several_code_blobs(
        text: str, code_block_tags: tuple[str, str]
    ) -> tuple[list[str], Any, Any]:
        try:
            return _original(text, code_block_tags)
        except Exception as exc:
            cleaned = str(text).rstrip()
            closing = code_block_tags[1]
            if closing and cleaned.endswith(closing):
                cleaned = cleaned[: -len(closing)].rstrip()
            try:
                ast.parse(cleaned)
            except SyntaxError:
                raise exc from None
            return [cleaned], None, None

    hamlet_agents.parse_several_code_blobs = _robust_parse_several_code_blobs
    setattr(hamlet_agents, _PATCHED_ATTR, True)


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
    _patch_hamlet_code_parsing()

    resolved_model_id = os.getenv("HAMLET_MODEL_ID")
    if not resolved_model_id:
        raise ValueError(
            "HAMLET_MODEL_ID environment variable must be set. "
            "Example: HAMLET_MODEL_ID=openai/gpt-4o-mini"
        )
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
        code_block_tags=_CODE_BLOCK_TAGS,
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
