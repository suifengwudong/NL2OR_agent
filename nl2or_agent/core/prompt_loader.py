"""Prompt loading: load and assemble prompt templates for the NL2OR agent.

Pulled out of agents/nl2or_agent.py to separate prompt assembly from agent construction.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(prompt_path: str | Path) -> str:
    """Load a prompt template from a file."""
    p = prompt_path if isinstance(prompt_path, Path) else Path(prompt_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def load_system_prompt() -> str:
    """Load system prompt with compositional IR appendix and block catalog."""
    from .ir_catalog import catalog_markdown

    parts: list[str] = []

    # 主体：系统 prompt
    prompt_file = _PROMPTS_DIR / "system.prompt.md"
    parts.append(_load_prompt(prompt_file))

    # 附录：IR 格式说明
    ir_file = _PROMPTS_DIR / "problem_ir_format.prompt.md"
    if ir_file.exists():
        parts.append("\n\n---\n\n## Appendix: problem_ir_format\n\n")
        parts.append(_load_prompt(ir_file))

    # 附录：积木块目录
    parts.append("\n\n### Canonical block_id catalog\n\n")
    parts.append(catalog_markdown())

    return "\n".join(parts)
