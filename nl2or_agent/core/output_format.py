"""Agent output rendering for the CLI and the web UI.

The agent's content of record is the Problem IR (constraint set and objective),
so this module no longer imposes a prose schema on the reply: it strips harness
noise and passes the model's own text through.
"""

from __future__ import annotations

_NOISE_PREFIXES = ("Thought:", "Code:", "```", "import", "╭", "╰", "━━")


def format_agent_output(raw: str) -> str:
    """Clean agent output for display.

    Drops harness noise lines (thought/log prefixes, stray fences, imports) and
    keeps the tail of the reply, where the model's actual answer lives.
    """
    text = str(raw).strip()
    if not text:
        return ""

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    clean = [line for line in lines if not line.startswith(_NOISE_PREFIXES) and "```" not in line]
    return "\n".join(clean[-20:]) or text[-500:]
