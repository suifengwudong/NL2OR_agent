"""What-if analysis over the model of record: 参数情景对比。

给定一个归一化 Problem IR 与若干参数情景，逐个求解并对比目标值与决策。

依赖说明：可执行的块语义目前实现在 ``benchmarks/references/block_model.py``，
这里直接复用，避免出现第二份建模实现。若将来把该模块提升到 ``core/``，只需改这一处 import。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from benchmarks.references.block_model import (
    CONSTRAINT_BUILDERS,
    OBJECTIVE_BUILDERS,
    READABLE_DATA_KEYS,
    constraint_block_ids,
    objective_block_id,
    solve_ir,
)

from ._defaults import WHAT_IF_MANUAL_PATH
from .ir_catalog import load_model_bank

BASELINE_ID = "(基准)"
_SUPPORTED_SCHEMA_VERSION = 1

_STATUS_TEXT = {
    "Optimal": "最优",
    "Not Solved": "未求解",
    "Infeasible": "不可行",
    "Unbounded": "无界",
    "Undefined": "未定义",
}

_SENSE_TEXT = {"minimize": "最小化", "maximize": "最大化"}

_VARIABLE_LABELS = {"y": "开设", "z": "覆盖需求", "x2": "分配", "x1": "选中"}


# ---------------------------------------------------------------------------
# 情景
# ---------------------------------------------------------------------------


def apply_overrides(
    ir: dict[str, Any], overrides: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Return a copy of *ir* with the scenario's parameter overrides applied.

    Only top-level ``parameters.<key>`` assignments are supported; anything else is
    rejected instead of being silently ignored.
    """
    out = copy.deepcopy(ir)
    for override in overrides or []:
        path = str(override.get("path") or "").strip()
        if not path:
            raise ValueError("覆盖项缺少 path")
        parts = path.split(".")
        if len(parts) != 2 or parts[0] != "parameters":
            raise ValueError(f"不支持的覆盖路径 {path!r}：只支持 parameters.<键>")
        key = parts[1]
        if key not in READABLE_DATA_KEYS:
            allowed = "、".join(sorted(READABLE_DATA_KEYS))
            raise ValueError(f"不支持的参数 {key!r}；可覆盖的键为 {allowed}")
        if "value" not in override:
            raise ValueError(f"{path} 缺少 value")
        out.setdefault("parameters", {})[key] = override["value"]
    return out


def run_scenarios(
    ir: dict[str, Any], scenarios: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Solve the baseline and every scenario; return the comparison rows."""
    try:
        baseline = solve_ir(copy.deepcopy(ir))
    except ValueError as exc:
        raise ValueError(f"基准模型无法求解：{exc}") from exc

    rows = [_build_row(BASELINE_ID, baseline, baseline, False)]
    for index, scenario in enumerate(scenarios or [], start=1):
        scenario_id = str(scenario.get("id") or f"scenario{index}")
        try:
            variant = apply_overrides(ir, scenario.get("overrides"))
            result = solve_ir(variant)
        except ValueError as exc:
            rows.append(
                {
                    "id": scenario_id,
                    "status": "覆盖无效",
                    "objective": None,
                    "delta": None,
                    "decisions": "",
                    "note": str(exc),
                    "optimal": False,
                }
            )
            continue
        rows.append(_build_row(scenario_id, result, baseline, True))

    return {
        "sense": str((ir.get("objective") or {}).get("sense") or ""),
        "baseline_objective": baseline.objective if baseline.status == "Optimal" else None,
        "rows": rows,
    }


def _build_row(scenario_id: str, result: Any, baseline: Any, is_scenario: bool) -> dict[str, Any]:
    optimal = result.status == "Optimal" and result.objective is not None
    delta: float | None = None
    if optimal and baseline.status == "Optimal" and baseline.objective is not None:
        delta = result.objective - baseline.objective
    return {
        "id": scenario_id,
        "status": _STATUS_TEXT.get(result.status, result.status),
        "objective": result.objective if optimal else None,
        "delta": delta,
        "decisions": _summarize(result.variables) if optimal else "",
        "note": "",
        "optimal": optimal,
        "is_scenario": is_scenario,
    }


def _summarize(variables: dict[str, float]) -> str:
    """Compact decision summary, grouped by variable name (no per-family branches)."""
    scalars: list[str] = []
    groups: dict[str, list[str]] = {}
    for key, value in variables.items():
        if "[" not in key:
            scalars.append(f"{key}={_fmt_number(value)}")
            continue
        name, rest = key.split("[", 1)
        groups.setdefault(name, []).append(rest.rstrip("]"))

    parts = list(scalars)
    for name, entries in sorted(groups.items()):
        label = _VARIABLE_LABELS.get(name, name)
        points = [e for e in entries if "," not in e]
        edges = [e for e in entries if "," in e]
        if points:
            parts.append(f"{label} [{', '.join(points)}]")
        if edges:
            parts.append(f"{label} {len(edges)} 条")
    return "；".join(parts) if parts else "—"


def _fmt_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def render_comparison(comparison: dict[str, Any]) -> str:
    """Markdown table for the agent to relay."""
    sense = _SENSE_TEXT.get(comparison["sense"], comparison["sense"] or "未声明方向")
    baseline = comparison["baseline_objective"]
    head = f"目标方向：{sense}；基准目标值：{_fmt_number(baseline) if baseline is not None else '未求得'}"

    lines = [head, "", "| 场景 | 状态 | 目标值 | 与基准之差 | 决策 |", "|---|---|---|---|---|"]
    for row in comparison["rows"]:
        objective = _fmt_number(row["objective"]) if row["objective"] is not None else "—"
        if row["delta"] is None:
            delta = "—"
        elif row["delta"] == 0:
            delta = "0"
        else:
            delta = f"{'+' if row['delta'] > 0 else ''}{_fmt_number(row['delta'])}"
        lines.append(
            f"| {row['id']} | {row['status']} | {objective} | {delta} | {row['decisions'] or '—'} |"
        )

    notes = [row for row in comparison["rows"] if row["note"]]
    if notes:
        lines.append("")
        for row in notes:
            lines.append(f"- {row['id']}：{row['note']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 本地 manual
# ---------------------------------------------------------------------------


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
    """Render the manual: hand-written prose plus tables derived from the library."""
    manual = load_manual(manual_path)
    lines: list[str] = [f"### {manual['name']}（参数情景对比）", "", manual["summary"], ""]

    lines.append("**何时使用**")
    lines.append("")
    for item in manual["when_to_use"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("**场景结构**")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(manual["scenario"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    lines.append("**规则**")
    lines.append("")
    for item in manual["rules"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("**边界**")
    lines.append("")
    for item in manual["limits"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append(f"**可覆盖的键**：{'、'.join(f'`{k}`' for k in sorted(READABLE_DATA_KEYS))}")
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
        lines.append("```json")
        lines.append(json.dumps(example["scenarios"], ensure_ascii=False))
        lines.append("```")
    return "\n".join(lines)


def describe_model(ir: dict[str, Any]) -> str:
    """One-line description of the model of record, used in the tool's answer."""
    families = [str(f.get("id")) for f in ir.get("problem_families") or [] if f.get("id")]
    blocks = constraint_block_ids(ir)
    objective = objective_block_id(ir)
    return (
        f"基准模型：{'、'.join(families) or '未声明族'}；"
        f"约束块 {len(blocks)} 个；目标块 {objective or '未声明'}"
    )


__all__ = [
    "BASELINE_ID",
    "apply_overrides",
    "describe_model",
    "load_manual",
    "manual_markdown",
    "render_comparison",
    "run_scenarios",
    "supported_models",
]
