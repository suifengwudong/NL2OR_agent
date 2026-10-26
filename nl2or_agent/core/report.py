"""Strict mapping from the model structure to the result tables.

The block set decides which tables a model can produce. ``resolve_report_profile``
names the profile, ``validate_report_spec`` rejects a spec that asks for another
profile's tables, and ``render_report`` renders the declared tables from one
solve result.
"""

from __future__ import annotations

from typing import Any, Callable

from .block_model import (
    SolveResult,
    constraint_block_ids,
    format_number,
    model_sizes,
    objective_block_id,
)
from .ir_catalog import load_block_catalog
from .problem_ir import ProblemIR

PROFILES: dict[str, tuple[str, ...]] = {
    "location": ("opened_facilities", "assignments", "objective_breakdown"),
    "set_covering": ("opened_facilities", "objective_breakdown"),
    "covering": ("opened_facilities", "coverage", "objective_breakdown"),
    "knapsack": ("selected_items", "objective_breakdown"),
    "dispersion": ("opened_facilities", "pairwise_distance", "objective_breakdown"),
    "capacity": (
        "opened_facilities",
        "assignments",
        "facility_load",
        "objective_breakdown",
    ),
    "covering_capacity": (
        "opened_facilities",
        "coverage",
        "facility_load",
        "objective_breakdown",
    ),
    "general": ("objective_breakdown",),
}

TABLE_TITLES = {
    "opened_facilities": "开设设施",
    "assignments": "分配关系",
    "coverage": "覆盖状态",
    "facility_load": "设施负荷",
    "selected_items": "选中物品",
    "pairwise_distance": "最小设施间距",
    "objective_breakdown": "目标项",
}

AUDIENCES = frozenset({"learner", "engineer"})
MAX_ROWS = 40
_SENSE_TEXT = {"minimize": "最小化", "maximize": "最大化"}


def resolve_report_profile(ir: dict[str, Any]) -> str:
    """Pick the report profile from the active blocks."""
    active = set(constraint_block_ids(ir)) | {objective_block_id(ir)}
    if active & {"knapsack_capacity", "total_value_objective"}:
        return "knapsack"
    if active & {
        "min_pairwise_distance_bound",
        "maximize_min_pairwise_distance_objective",
    }:
        return "dispersion"

    has_coverage = bool(
        active
        & {
            "demand_coverage_activation",
            "assignment_coverage_activation",
            "covered_demand_objective",
        }
    )
    if "cover_each_demand_at_least_once" in active and not has_coverage:
        return "set_covering"

    has_capacity = "facility_capacity" in active
    if has_coverage and has_capacity:
        return "covering_capacity"
    if has_coverage:
        return "covering"
    if has_capacity:
        return "capacity"
    if active & {
        "assign_each_demand_once",
        "link_assignment_to_open",
        "opening_budget",
        "cardinality_open_p_facilities",
    }:
        return "location"
    return "general"


def default_report_spec(ir: dict[str, Any]) -> dict[str, Any]:
    profile = resolve_report_profile(ir)
    return {"profile": profile, "tables": list(PROFILES[profile]), "audience": "learner"}


def validate_report_spec(
    ir: dict[str, Any], spec: Any = None
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Validate a report spec; return (normalized spec, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    derived = resolve_report_profile(ir)
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        return default_report_spec(ir), ["report 必须是对象"], warnings

    profile = str(spec.get("profile") or derived)
    if profile not in PROFILES:
        errors.append(f"未知报表类型 '{profile}'；可选 {', '.join(sorted(PROFILES))}")
        profile = derived
    elif profile != derived:
        errors.append(f"报表类型 {profile} 与模型结构推导出的 {derived} 不一致")

    required = list(PROFILES[derived])
    allowed = set(required)
    requested = spec.get("tables")
    if requested is None:
        tables = required
    elif not isinstance(requested, list):
        errors.append("report.tables 必须是字符串列表")
        tables = required
    else:
        tables = [str(item) for item in requested]
        unknown = [item for item in tables if item not in allowed]
        if unknown:
            errors.append(f"报表 {derived} 不允许的表: {', '.join(unknown)}")
        missing = [item for item in required if item not in tables]
        if missing:
            warnings.append(f"报表 {derived} 自动补齐必需表: {', '.join(missing)}")
        tables = list(dict.fromkeys([*required, *tables]))

    audience = str(spec.get("audience") or "learner")
    if audience not in AUDIENCES:
        warnings.append(f"未知报表读者 '{audience}'，已改为 learner")
        audience = "learner"

    return {"profile": derived, "tables": tables, "audience": audience}, errors, warnings


def render_report(
    ir: dict[str, Any],
    result: SolveResult,
    *,
    spec: dict[str, Any] | None = None,
) -> str:
    """Render the declared report tables for one solve result."""
    if spec is None:
        spec, _, _ = validate_report_spec(ir, ir.get("report"))
    lines = ["## 结果报表"]
    tables = list(spec["tables"])
    if result.status != "Optimal":
        lines.append("")
        lines.append("该情景没有最优解，以下只保留目标项。")
        tables = [table for table in tables if table == "objective_breakdown"]
    for table in tables:
        rendered = _TABLE_RENDERERS[table](ir, result)
        if rendered:
            lines.append("")
            lines.append(rendered)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Table renderers
# ---------------------------------------------------------------------------


def _ids(ir: dict[str, Any], key: str, size: int) -> list[str]:
    ids = (ir.get("entities") or {}).get(key, {}).get("ids") or []
    if ids:
        return [str(item) for item in ids]
    return [str(index + 1) for index in range(size)]


def _value(result: SolveResult, name: str) -> float:
    return result.variables.get(name, 0.0)


def _parameters(ir: dict[str, Any]) -> dict[str, Any]:
    return ProblemIR(ir).parameters


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _opened_facilities(ir: dict[str, Any], result: SolveResult) -> str:
    n_i, n_j = model_sizes(ir)
    if not any(key.startswith("y[") for key in result.variables) and n_j == 0:
        return ""
    names = _ids(ir, "J", n_j)
    fixed = _parameters(ir).get("fixed_cost")
    rows: list[list[Any]] = []
    for j, name in enumerate(names):
        opened = _value(result, f"y[{j}]") > 0.5
        cost = fixed[j] if isinstance(fixed, list) and j < len(fixed) else "—"
        rows.append([name, "是" if opened else "否", cost])
    return f"**{TABLE_TITLES['opened_facilities']}**\n\n" + _table(
        ["设施", "开设", "固定成本"], rows
    )


def _assignments(ir: dict[str, Any], result: SolveResult) -> str:
    n_i, n_j = model_sizes(ir)
    names_i = _ids(ir, "I", n_i)
    names_j = _ids(ir, "J", n_j)
    params = _parameters(ir)
    cost = params.get("distance") or params.get("service_cost")
    rows: list[list[Any]] = []
    for i in range(n_i):
        for j in range(n_j):
            if _value(result, f"x2[{i},{j}]") <= 0.5:
                continue
            shown = "—"
            if isinstance(cost, list) and i < len(cost) and j < len(cost[i]):
                shown = cost[i][j]
            rows.append([names_i[i], names_j[j], shown])
            if len(rows) >= MAX_ROWS:
                break
        if len(rows) >= MAX_ROWS:
            break
    if not rows:
        return ""
    text = f"**{TABLE_TITLES['assignments']}**\n\n" + _table(["需求点", "设施", "距离或成本"], rows)
    if len(rows) >= MAX_ROWS:
        text += f"\n\n仅显示前 {MAX_ROWS} 条分配。"
    return text


def _coverage(ir: dict[str, Any], result: SolveResult) -> str:
    n_i, _ = model_sizes(ir)
    names = _ids(ir, "I", n_i)
    demand = _parameters(ir).get("demand")
    rows: list[list[Any]] = []
    for i, name in enumerate(names):
        covered = _value(result, f"z[{i}]") > 0.5
        weight = demand[i] if isinstance(demand, list) and i < len(demand) else "—"
        rows.append([name, "是" if covered else "否", weight])
    return f"**{TABLE_TITLES['coverage']}**\n\n" + _table(["需求点", "覆盖", "权重"], rows)


def _facility_load(ir: dict[str, Any], result: SolveResult) -> str:
    n_i, n_j = model_sizes(ir)
    params = _parameters(ir)
    demand = params.get("demand")
    capacity = params.get("facility_capacity")
    if not isinstance(demand, list) or not isinstance(capacity, list):
        return ""
    names = _ids(ir, "J", n_j)
    rows: list[list[Any]] = []
    for j, name in enumerate(names):
        load = sum(float(demand[i]) * _value(result, f"x2[{i},{j}]") for i in range(n_i))
        cap = capacity[j] if j < len(capacity) else 0
        used = f"{load / cap:.1%}" if cap else "—"
        rows.append([name, format_number(load), cap, used])
    return f"**{TABLE_TITLES['facility_load']}**\n\n" + _table(
        ["设施", "负荷", "容量", "利用率"], rows
    )


def _selected_items(ir: dict[str, Any], result: SolveResult) -> str:
    n_i, _ = model_sizes(ir)
    names = _ids(ir, "I", n_i)
    params = _parameters(ir)
    value = params.get("value")
    weight = params.get("weight")
    rows: list[list[Any]] = []
    for i, name in enumerate(names):
        selected = _value(result, f"x1[{i}]") > 0.5
        shown_value = value[i] if isinstance(value, list) and i < len(value) else "—"
        shown_weight = weight[i] if isinstance(weight, list) and i < len(weight) else "—"
        rows.append([name, "是" if selected else "否", shown_value, shown_weight])
    return f"**{TABLE_TITLES['selected_items']}**\n\n" + _table(
        ["物品", "选中", "价值", "重量"], rows
    )


def _pairwise_distance(ir: dict[str, Any], result: SolveResult) -> str:
    n_i, n_j = model_sizes(ir)
    names = _ids(ir, "J", n_j)
    distance = _parameters(ir).get("facility_distance")
    if not isinstance(distance, list):
        return ""
    opened = [j for j in range(n_j) if _value(result, f"y[{j}]") > 0.5]
    if len(opened) < 2:
        return f"**{TABLE_TITLES['pairwise_distance']}**\n\n已开设设施少于 2 个。"
    rows = [
        [f"{names[j]} - {names[k]}", distance[j][k]]
        for index, j in enumerate(opened)
        for k in opened[index + 1 :]
    ]
    rows.sort(key=lambda row: row[1])
    return f"**{TABLE_TITLES['pairwise_distance']}**\n\n" + _table(["设施对", "距离"], rows)


def _objective_breakdown(ir: dict[str, Any], result: SolveResult) -> str:
    objective = ir.get("objective") or {}
    block_id = str(objective.get("block_id") or "")
    entry = load_block_catalog()["by_id"].get(block_id) or {}
    name = entry.get("name") or "库外目标"
    sense = str(objective.get("sense") or entry.get("sense") or "")
    sense = _SENSE_TEXT.get(sense, sense or "—")
    shown = (
        format_number(result.objective)
        if result.status == "Optimal" and result.objective is not None
        else "—"
    )
    return f"**{TABLE_TITLES['objective_breakdown']}**\n\n" + _table(
        ["目标块", "方向", "目标值"], [[f"{name}（`{block_id or '未声明'}`）", sense, shown]]
    )


_TABLE_RENDERERS: dict[str, Callable[[dict[str, Any], SolveResult], str]] = {
    "opened_facilities": _opened_facilities,
    "assignments": _assignments,
    "coverage": _coverage,
    "facility_load": _facility_load,
    "selected_items": _selected_items,
    "pairwise_distance": _pairwise_distance,
    "objective_breakdown": _objective_breakdown,
}


__all__ = [
    "PROFILES",
    "TABLE_TITLES",
    "default_report_spec",
    "render_report",
    "resolve_report_profile",
    "validate_report_spec",
]
