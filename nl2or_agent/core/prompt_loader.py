"""Prompt loading: load and assemble prompt templates for the NL2OR agent.

Pulled out of agents/nl2or_agent.py to separate prompt assembly from agent construction.

The system prompt is assembled from three sources:

- ``system.prompt.md`` — the mode-independent core (role, output rules, IR flow, solving).
- ``workflow.<mode>.prompt.md`` — the workflow for the selected agent mode.
- the ``problem_ir_format`` appendix and the canonical block_id catalog.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Agent modes select the workflow prompt.
AGENT_MODES: tuple[str, ...] = ("interactive", "automatic")


def _load_prompt(prompt_path: str | Path) -> str:
    """Load a prompt template from a file."""
    p = prompt_path if isinstance(prompt_path, Path) else Path(prompt_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def load_system_prompt(mode: str = "interactive") -> str:
    """Load the system prompt for *mode*, with the IR appendix and block catalog.

    ``interactive`` advances one workflow step per user turn (parse → confirm → look up → solve);
    ``automatic`` runs the whole pipeline within a single turn.
    """
    from .ir_catalog import catalog_markdown
    from .what_if import manual_markdown

    if mode not in AGENT_MODES:
        raise ValueError(f"Unknown agent mode {mode!r}. Expected one of: {', '.join(AGENT_MODES)}.")

    parts: list[str] = []

    # 主体：与模式无关的核心 prompt
    parts.append(_load_prompt(_PROMPTS_DIR / "system.prompt.md"))

    # 工作流：按模式选择
    parts.append(_load_prompt(_PROMPTS_DIR / f"workflow.{mode}.prompt.md"))

    # 附录：IR 格式说明
    ir_file = _PROMPTS_DIR / "problem_ir_format.prompt.md"
    if ir_file.exists():
        parts.append("\n\n---\n\n## Appendix: problem_ir_format\n\n")
        parts.append(_load_prompt(ir_file))

    # 附录：积木块目录
    parts.append("\n\n### Canonical block_id catalog\n\n")
    parts.append(catalog_markdown())

    # 附录：what_if 工具的 manual（与 catalog 同一机制，本地文件 + 库派生表）
    parts.append("\n\n---\n\n## Appendix: what_if\n\n")
    parts.append(manual_markdown())

    return "\n".join(parts)
