"""Agent output rendering for the CLI and the web UI.

The agent's content of record is the Problem IR (constraint set and objective),
so this module no longer imposes a prose schema on the reply: it strips harness
noise and passes the model's own text through.
"""

from __future__ import annotations

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
    clean = [line for line in lines if not line.lstrip().startswith(_NOISE_PREFIXES) and "```" not in line]
    return "\n".join(clean).strip() or text
