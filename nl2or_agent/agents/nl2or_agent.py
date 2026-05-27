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

from core.ir_processor import catalog_markdown
from tools import (
    ListBlockCatalogTool,
    QueryModelLibraryTool,
    RunSolverTool,
    ValidateProblemIrTool,
)
from utils.session import get_session


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


# NOTE: 这里需要考量到未来可能会有多个 prompt 文件的情况，因此单独写一个函数来加载所有 prompt，并且在系统 prompt 中附加上 IR 格式说明和 catalog。之后可以试试分开成不同层级的 prompt。

def _load_prompt(prompt_path: str | Path) -> str:
    """Load a prompt template from a file."""
    p = prompt_path if isinstance(prompt_path, Path) else Path(prompt_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""

def _load_all_prompts() -> dict[str, str]:
    """Load all prompt templates from the prompts directory."""
    prompts = {}
    system_prompt_path = _PROMPTS_DIR / "system.prompt.md"
    problem_ir_prompt_path = _PROMPTS_DIR / "problem_ir_format.prompt.md"
    if system_prompt_path.exists():
        prompts["system_prompt"] = system_prompt_path.read_text(encoding="utf-8")
    if problem_ir_prompt_path.exists():
        prompts["problem_ir_format"] = problem_ir_prompt_path.read_text(encoding="utf-8")
    return prompts


def _load_system_prompt() -> str:
    """Load system prompt and compositional IR appendix."""
    parts: list[str] = []
    # 首先加载系统 prompt 的主体内容
    prompt_file = _PROMPTS_DIR / "system.prompt.md"
    parts.append(_load_prompt(prompt_file))

    # 然后附加上 IR 格式说明和 catalog
    ir_file = _PROMPTS_DIR / "problem_ir_format.prompt.md"
    parts.append("\n\n---\n\n## Appendix: problem_ir_format\n\n")
    parts.append(_load_prompt(ir_file))
    parts.append("\n\n### Canonical block_id catalog\n\n")
    parts.append(catalog_markdown())
    return "\n".join(parts)


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

    system_prompt = _load_system_prompt()

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
