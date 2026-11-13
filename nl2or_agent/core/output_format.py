"""Agent output rendering for the CLI and the web UI.

The agent's content of record is the Problem IR (constraint set and objective),
so this module no longer imposes a prose schema on the reply: it strips harness
noise and expands the placeholders that carry the authoritative sections.

``[MODEL_MATH]`` and ``[SOLVE_RESULT]`` are filled from the session's model
of record and the saved baseline solve, never from the LLM's own copy: the
math document and the result tables in every answer are byte-identical to what
the tools produced.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from core.model_document import render_model_document
from core.problem_ir import fingerprint

if TYPE_CHECKING:
    from utils.session import Session

MODEL_MATH_PLACEHOLDER = "[MODEL_MATH]"
SOLVE_RESULT_PLACEHOLDER = "[SOLVE_RESULT]"

_NOISE_PREFIXES = ("Thought:", "Code:", "```", "import", "╭", "╰", "━━")


def format_agent_output(raw: str) -> str:
    """Clean agent output for display.

    Drops harness noise lines while preserving the complete answer and its
    Markdown spacing (especially display math and lists).
    """
    text = str(raw).strip()
    if not text:
        return ""

    lines = text.splitlines()
    clean = [
        line
        for line in lines
        if not line.lstrip().startswith(_NOISE_PREFIXES) and "```" not in line
    ]
    return "\n".join(clean).strip() or text


def expand_placeholders(text: str, session: "Session") -> str:
    """Replace the authoritative-section placeholders from session artifacts.

    The prompts use ``[MODEL_MATH]`` and ``[SOLVE_RESULT]`` (Jinja-plain, since
    HAMLET renders the system prompt through Jinja). An unresolved placeholder
    fails loudly: leaving it as a literal, or filling it with a stale result
    from an earlier IR, would silently put a wrong model in front of the user.
    """
    if MODEL_MATH_PLACEHOLDER in text:
        model = session.load_model()
        if model is None:
            raise ValueError(
                f"{MODEL_MATH_PLACEHOLDER} 没有对应的已校验模型：请先调用 validate_problem_ir"
            )
        document = render_model_document(model["report"]["normalized_ir"])
        text = text.replace(MODEL_MATH_PLACEHOLDER, document)
        # 占位符自带 ## 数学模型 标题；agent 若又写了一个，相邻的重复标题去掉一个
        text = re.sub(r"(?m)^## 数学模型\s*\n## 数学模型\s*$", "## 数学模型", text)

    if SOLVE_RESULT_PLACEHOLDER in text:
        model = session.load_model()
        if model is None:
            raise ValueError(
                f"{SOLVE_RESULT_PLACEHOLDER} 没有对应的已校验模型：请先调用 validate_problem_ir"
            )
        path = session.solve_result_file
        if not path.is_file():
            raise ValueError(
                f"{SOLVE_RESULT_PLACEHOLDER} 没有已保存的基准求解结果：请先调用 solve_ir"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        current = fingerprint(model["report"]["normalized_ir"])
        if payload.get("ir_fingerprint") != current:
            raise ValueError(
                f"{SOLVE_RESULT_PLACEHOLDER} 对应的模型已变更：请对当前模型重新调用 solve_ir"
            )
        text = text.replace(SOLVE_RESULT_PLACEHOLDER, str(payload["text"]))
    return text
