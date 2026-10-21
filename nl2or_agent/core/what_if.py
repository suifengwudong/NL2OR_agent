"""The what-if skill: the procedure document plus the capability table.

No solving logic lives here. ``solve_ir`` in ``core/block_model.py`` solves exactly
one scenario; the loop, the comparison table and the deltas belong to the agent,
guided by the manual rendered below as the system prompt's ``what_if`` appendix.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._defaults import WHAT_IF_MANUAL_PATH
from .block_model import CONSTRAINT_BUILDERS, OBJECTIVE_BUILDERS
from .ir_catalog import load_model_bank
from .problem_ir import READABLE_DATA_KEYS

_SUPPORTED_SCHEMA_VERSION = 1

_SECTIONS = (
    ("何时使用", "when_to_use"),
    ("做法", "procedure"),
    ("规则", "rules"),
    ("边界", "limits"),
)


def load_manual(manual_path: Path | None = None) -> dict[str, Any]:
    """Load the local what-if manual (data/model_bank/what_if_manual.json)."""
    path = manual_path or WHAT_IF_MANUAL_PATH
    with open(path, encoding="utf-8") as f:
        manual = json.load(f)
    version = manual.get("schema_version", 0)
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"{path.name} schema_version={version}, expected {_SUPPORTED_SCHEMA_VERSION}."
        )
    return manual


def supported_models() -> list[dict[str, Any]]:
    """Models whose blocks all have executable semantics (driven by the library)."""
    bank = load_model_bank()
    out: list[dict[str, Any]] = []
    for model_id, model in sorted(bank["by_id"].items()):
        if model.get("is_family"):
            continue
        blocks = list(bank.get("effective_blocks", {}).get(model_id, []))
        objective = model.get("objective_block")
        if any(b not in CONSTRAINT_BUILDERS for b in blocks):
            continue
        if objective not in OBJECTIVE_BUILDERS:
            continue
        out.append({"id": model_id, "blocks": blocks, "objective": objective})
    return out


def manual_markdown(manual_path: Path | None = None) -> str:
    """Render the manual: hand-written procedure plus tables derived from the library."""
    manual = load_manual(manual_path)
    lines: list[str] = [f"### {manual['name']}（参数情景对比）", "", manual["summary"], ""]

    for heading, key in _SECTIONS:
        lines.append(f"**{heading}**")
        lines.append("")
        lines.extend(f"- {item}" for item in manual[key])
        lines.append("")

    lines.append(
        f"**可覆盖的键（须由该模型启用的块读取）**："
        f"{'、'.join(f'`{k}`' for k in sorted(READABLE_DATA_KEYS))}"
    )
    lines.append("")

    lines.append(
        "**可算的模型**："
        + "、".join(f"`{entry['id']}`" for entry in supported_models())
        + "（各模型需要的约束块与目标块见 `models.json`）"
    )
    lines.append("")

    lines.append("**示例**")
    for example in manual["examples"]:
        lines.append("")
        lines.append(f"{example['title']}：")
        lines.append("")
        lines.append("```python")
        lines.extend(example["calls"])
        lines.append("```")
    return "\n".join(lines)


__all__ = ["load_manual", "manual_markdown", "supported_models"]
