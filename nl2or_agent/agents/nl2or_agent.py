"""NL2OR Agent — built on HAMLET's CodeAgent.

Usage
-----
from agents import build_nl2or_agent
agent = build_nl2or_agent()
result = agent.run("我有一个背包问题……")
"""

from __future__ import annotations

import ast
import contextlib
import importlib.resources
import io
import os
import re
from pathlib import Path
from typing import Any

import yaml

# litellm 在 import 时向 raw.githubusercontent.com 拉取价格表，当前网络环境下
# SSL 握手超时；本地备份已足够（本项目不消费价格与上下文窗口数据）。
# 必须在第一次导入 hamlet/litellm 之前设置。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")

from hamlet.core import CodeAgent, LiteLLMModel

from core.prompt_loader import load_system_prompt
from tools import (
    DescribeModelTool,
    ModelMathTool,
    RunSolverTool,
    SearchModelLibraryTool,
    SolveIrTool,
    ValidateProblemIrTool,
)

# Use markdown code fences instead of HAMLET's default ``<code>`` XML tags.
# deepseek-chat (and most open models) are trained to emit ```python ... ```
# blocks, not ``<code>...</code>``, so this dramatically reduces parse failures.
_CODE_BLOCK_TAGS: str | tuple[str, str] = "markdown"

_PATCHED_ATTR = "_nl2or_parse_patched"
_QUIET_PROMPT_ATTR = "_nl2or_prompt_quiet"

# DeepSeek 原生工具调用标记：<｜DSML｜ parameter name="code" ...>...</｜DSML｜ parameter>
_DSML_CODE_RE = re.compile(
    r'<[｜|]DSML[｜|]\s*parameter\s+name="code"[^>]*>(.*?)</[｜|]DSML[｜|]\s*parameter>',
    re.DOTALL,
)
_EARLY_STOP_MARKER = "Early Stop Strategy:"


def _silence_system_prompt_print() -> None:
    """Suppress the stray ``print(system_prompt)`` in HAMLET's CodeAgent.

    ``CodeAgent.initialize_system_prompt()`` ends with an unconditional
    ``print(system_prompt)`` (hamlet/core/agents.py:1486).  Both ``__init__``
    and every ``run()`` evaluate ``self.system_prompt``, so the whole prompt is
    dumped to stdout twice per turn even at ``verbosity_level=0``.  Only the
    prompt build is silenced here; tool output and logging are untouched.
    """
    import hamlet.core.agents as hamlet_agents

    cls = hamlet_agents.CodeAgent
    if getattr(cls, _QUIET_PROMPT_ATTR, False):
        return

    original = cls.initialize_system_prompt

    def _quiet(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return original(self)

    cls.initialize_system_prompt = _quiet
    setattr(cls, _QUIET_PROMPT_ATTR, True)


def _fenced_blocks(text: str, tags: tuple[str, str]) -> list[str]:
    """Extract fenced code blocks with the same patterns HAMLET uses."""
    blocks = re.findall(rf"{tags[0]}\s*\n(.*?)\n{tags[1]}", text, re.DOTALL)
    if not blocks:
        blocks = re.findall(r"```(?:python|py)\s*\n(.*?)\n```", text, re.DOTALL)
    return blocks


def _repair_code_output(text: str, tags: tuple[str, str]) -> list[str]:
    """Recover the actions a model intended, from known malformed shapes.

    Three shapes are handled, all with an unambiguous intent:

    - several fenced blocks without the early-stop section: concatenate them in
      order, which is exactly the "put all tool calls in one block" contract;
    - one fenced block plus a stray/empty ``Early Stop Strategy`` section: drop
      the section and keep the block;
    - DeepSeek's native ``<｜DSML｜ parameter name="code">`` tool call: unwrap its
      payload.

    A plain-prose reply is not repaired here: the system prompt requires every
    message to be one ``python`` block ending in ``final_answer(...)``, and
    turning arbitrary prose into a final answer would accept intermediate
    thoughts as results.

    Valid output never reaches this function (the original parser succeeds).
    """
    dsml = _DSML_CODE_RE.search(text)
    if dsml:
        return [dsml.group(1).strip()]

    actions_part = text.split(_EARLY_STOP_MARKER, 1)[0]
    blocks = [block for block in _fenced_blocks(actions_part, tags) if block.strip()]
    if len(blocks) == 1:
        return blocks
    if len(blocks) > 1:
        return ["\n\n".join(blocks)]
    return []


def _patch_hamlet_code_parsing() -> None:
    """Harden HAMLET's code parsing against malformed model output.

    HAMLET's ``parse_several_code_blobs`` accepts exactly two shapes: one fenced
    block, or several blocks plus an ``Early Stop Strategy`` section.  Models
    regularly break that contract in three ways: one block per tool call, a
    single block plus an empty early-stop section, and DeepSeek's native
    ``<｜DSML｜ invoke ...>`` tool markup.  None of those should cost a step.

    The repair ladder runs only after the original parser raises: unwrap DSML,
    drop a stray early-stop section, merge several blocks in order, and finally
    fall back to treating a bare (unfenced) program as one action.  The original
    error is re-raised when nothing parses.
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
            repaired = _repair_code_output(str(text), code_block_tags)
            if repaired:
                return repaired, None, None

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


def apply_agent_mode(agent: CodeAgent, mode: str) -> None:
    """Switch *agent* to *mode* (``interactive`` or ``automatic``).

    Only the workflow section of the system prompt changes.  HAMLET re-reads
    ``prompt_templates["system_prompt"]`` at the start of every ``run()``, so the
    accumulated conversation memory survives the switch.  A turn in the mode the
    agent already carries skips the rebuild.
    """
    if getattr(agent, "_nl2or_mode", None) == mode:
        return
    system_prompt = load_system_prompt(mode)
    if system_prompt:
        agent.prompt_templates["system_prompt"] = system_prompt
    agent._nl2or_mode = mode


def _reasoning_kwargs() -> dict:
    """Reasons budget for the model call.

    Reasoning tokens are about 80% of the completion on this model and dominate
    the per-step wall time.  litellm does not recognise the model id, so
    ``reasoning_effort=`` is dropped before it reaches the request; only
    ``extra_body`` is forwarded verbatim.  The provider honours the on/off
    switch only (``effort`` and ``max_tokens`` were measured to have no effect).
    """
    if os.getenv("HAMLET_REASONING", "").strip().lower() not in {"off", "none", "false"}:
        return {}
    return {"extra_body": {"reasoning": {"enabled": False}}}


def build_nl2or_agent(
    *,
    mode: str = "interactive",
    verbosity_level: int = 1,
    workspace_dir: str | Path | None = None,
) -> CodeAgent:
    """Create and return a configured NL2OR CodeAgent.

    Parameters
    ----------
    mode:
        ``interactive`` advances one workflow step per user turn (parse, confirm,
        look up, solve); ``automatic`` runs the whole pipeline in a single turn.
    verbosity_level:
        0 = silent, 1 = normal, 2 = verbose / debug.
    workspace_dir:
        Where ``run_solver`` writes the generated scripts; defaults to the
        session directory. Used by the benchmark to isolate each run.

    Returns
    -------
    CodeAgent
        A fully configured agent ready to receive natural-language OR problems.
    """
    _patch_hamlet_code_parsing()
    _silence_system_prompt_print()

    resolved_model_id = os.getenv("HAMLET_MODEL_ID")
    if not resolved_model_id:
        raise ValueError(
            "HAMLET_MODEL_ID environment variable must be set. "
            "Example: HAMLET_MODEL_ID=openai/gpt-4o-mini"
        )
    _or_key = os.getenv("OPENROUTER_API_KEY")

    if verbosity_level >= 1:
        print(
            f"Using model: {resolved_model_id}, "
            f"with OPENROUTER_API_KEY: {'set' if _or_key else 'not set'}"
        )

    model = LiteLLMModel(model_id=resolved_model_id, api_key=_or_key, **_reasoning_kwargs())

    tools = [
        SearchModelLibraryTool(),
        DescribeModelTool(),
        ValidateProblemIrTool(workspace_dir=workspace_dir),
        ModelMathTool(),
        RunSolverTool(workspace_dir=workspace_dir),
        SolveIrTool(workspace_dir=workspace_dir),
    ]

    system_prompt = load_system_prompt(mode)

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
    agent._nl2or_mode = mode

    return agent
