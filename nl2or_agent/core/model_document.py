"""Render the Problem IR as a human-readable mathematical model.

The catalog already carries the LaTeX for every block and objective. This
module assembles those pieces with the index sets, parameters and variable
definitions, so the final answer and the web model view show one document
instead of a list of block ids.
"""

from __future__ import annotations

import re
from typing import Any

from .block_model import (
    active_variable_names,
    constraint_block_ids,
    objective_block_id,
    readable_keys,
)
from .ir_catalog import load_block_catalog, load_model_bank
from .problem_ir import ProblemIR

# 直接进入数学模式的实体名：ASCII 字母数字、下划线与短横线
_PLAIN_ID = re.compile(r"[A-Za-z0-9_\-]+")

_ROLE_DEFS: dict[str, tuple[str, str, str]] = {
    "y": ("y_j", "binary", "是否在候选设施 j 开设设施"),
    "x2": ("x_ij", "binary", "需求点 i 是否分配给设施 j"),
    "z": ("z_i", "binary", "需求点 i 是否被覆盖"),
    "w": ("w", "continuous", "所有需求点到其服务设施距离的最大值"),
    "dmin": ("D", "continuous", "任意两个已开设设施之间的最小距离"),
    "x1": ("x_i", "binary", "是否选择物品 i"),
}

_SENSE_TEXT = {"minimize": "最小化", "maximize": "最大化"}


def render_model_document(
    ir: dict[str, Any],
    *,
    catalog: dict[str, Any] | None = None,
    model_bank: dict[str, Any] | None = None,
) -> str:
    """Return the mathematical model as Markdown with LaTeX formulas."""
    catalog = catalog or load_block_catalog()
    model_bank = model_bank or load_model_bank()
    entries = _model_entries(ir, model_bank)

    lines: list[str] = ["## 数学模型", ""]

    family_ids = [str(f.get("id")) for f in ir.get("problem_families") or [] if f.get("id")]
    if family_ids:
        names = [
            str(model_bank["by_id"].get(item, {}).get("name") or "其他模型") for item in family_ids
        ]
        lines.append(f"**问题类型**：{'、'.join(names)}")
        lines.append("")

    lines.append("**符号说明**")
    lines.append("")
    symbols = model_bank.get("symbols") or {}
    variables = _collect_variables(ir, entries)
    lines.extend(_render_entities(ir))
    lines.extend(_render_parameters(ir, entries, symbols))
    lines.extend(_render_variables(variables))
    lines.extend(_render_objective(ir, catalog))
    lines.extend(_render_constraints(ir, catalog))
    lines.extend(_render_custom_constraints(ir))
    lines.extend(_render_domains(variables))
    return "\n".join(lines).rstrip() + "\n"


def _model_entries(ir: dict[str, Any], model_bank: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for family in ir.get("problem_families") or []:
        model = model_bank["by_id"].get(str(family.get("id")))
        if model is not None:
            entries.append(model)
    return entries


def _render_entities(ir: dict[str, Any]) -> list[str]:
    entities = ir.get("entities") or {}
    if not entities:
        return []
    lines = []
    for key, entry in entities.items():
        size = entry.get("size")
        ids = entry.get("ids") or []
        shown = ""
        if ids:
            # 纯 ASCII 短名直接排版；含空格或非 ASCII 的名字包进 \text，
            # 避免被数学模式拆成多个符号或渲染失败
            members = ", ".join(
                f"\\text{{{item}}}" if not _PLAIN_ID.fullmatch(str(item)) else str(item)
                for item in ids
            )
            shown = f"，${key} = \\{{{members}\\}}$"
        size_text = f"$|{key}| = {size}$" if size else f"${key}$"
        meaning = {"I": "需求点集合", "J": "候选设施集合"}.get(key, "索引集合")
        lines.append(f"- {size_text}：{meaning}{shown}")
    lines.append("")
    return lines


def _render_parameters(
    ir: dict[str, Any],
    entries: list[dict[str, Any]],
    symbols: dict[str, str],
) -> list[str]:
    definitions: dict[str, dict[str, Any]] = {}
    for model in entries:
        for parameter in model.get("parameters") or []:
            definitions.setdefault(str(parameter.get("name")), parameter)

    values = ProblemIR(ir).parameters
    # 只列被启用块读取的参数：符号说明中的每个符号都必须出现在某条公式里
    readable = readable_keys(ir)
    names = [name for name in dict.fromkeys([*definitions, *values]) if name in readable]
    if not names:
        return []

    weight_demand, capacity_demand = _demand_usage(ir)
    lines = []
    for name in names:
        definition = definitions.get(name) or {}
        is_demand = name == "demand"
        default_demand = is_demand and weight_demand
        if name not in values and not definition.get("required") and not default_demand:
            continue
        meaning = definition.get("description") or "模型参数"
        symbol = _parameter_symbol(name, ir, symbols)
        if is_demand and weight_demand and capacity_demand:
            meaning = "需求点 i 的需求量，同时作为覆盖权重"
        elif is_demand and weight_demand:
            meaning = "需求点 i 的需求量或权重；未给出时按模型约定取 1"
        if meaning.startswith(symbol + "，"):
            meaning = meaning[len(symbol) + 1 :]
        shown = (
            _value_summary(values.get(name))
            if name in values
            else ("默认 1" if default_demand else "缺失")
        )
        lines.append(f"- ${_symbol_latex(symbol)}$：{meaning}（取值：{shown}）")
        if is_demand and weight_demand and capacity_demand:
            lines.append("- $h_i = d_i$：覆盖权重与容量需求使用同一数据")
    lines.append("")
    return lines


def _demand_usage(ir: dict[str, Any]) -> tuple[bool, bool]:
    active = set(constraint_block_ids(ir)) | {objective_block_id(ir)}
    weight = bool(active & {"weighted_service_distance_objective", "covered_demand_objective"})
    capacity = "facility_capacity" in active
    return weight, capacity


def _parameter_symbol(name: str, ir: dict[str, Any], symbols: dict[str, str]) -> str:
    if name == "demand":
        weight_demand, capacity_demand = _demand_usage(ir)
        if weight_demand and not capacity_demand:
            return "h_i"
    return symbols.get(name, name)


def _value_summary(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            rows = len(value)
            cols = len(value[0]) if value[0] else 0
            return f"{rows} x {cols} 矩阵"
        if len(value) <= 8 and all(isinstance(item, (int, float)) for item in value):
            return "[" + ", ".join(str(item) for item in value) + "]"
        return f"长度 {len(value)}"
    if isinstance(value, dict):
        return f"{len(value)} 项"
    return str(value)


def _collect_variables(ir: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decision variables of the model: template variables, else active roles."""
    variables: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in entries:
        declared = model.get("variables") or []
        for variable in declared:
            symbol = str(variable.get("symbol") or "")
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            variables.append(variable)

    if not variables:
        for role in active_variable_names(ir):
            symbol, var_type, meaning = _ROLE_DEFS[role]
            variables.append({"symbol": symbol, "type": var_type, "meaning": meaning})
    return variables


def _render_variables(variables: list[dict[str, Any]]) -> list[str]:
    if not variables:
        return ["- 决策变量：未声明", ""]

    lines = []
    for variable in variables:
        symbol = _symbol_latex(str(variable.get("symbol") or ""))
        var_type = str(variable.get("type") or "")
        meaning = str(variable.get("meaning") or "")
        domain = _domain_latex(var_type)
        suffix = f" {domain}" if domain else ""
        lines.append(f"- ${symbol}{suffix}$：{meaning}")
    lines.append("")
    return lines


def _quantifier_latex(symbol: str) -> str:
    """Turn the subscript of ``x_ij`` into ``\\forall i \\in I,\\ j \\in J``."""
    if "_" not in symbol:
        return ""
    subscript = symbol.split("_", 1)[1]
    indices = [char for char in subscript if char.isalpha()]
    if not indices:
        return ""
    return "\\forall " + ",\\ ".join(f"{char} \\in {char.upper()}" for char in indices)


def _render_domains(variables: list[dict[str, Any]]) -> list[str]:
    """The s.t. tail: every decision variable's domain as an explicit constraint.

    数域属于模型的约束部分，不能只写在符号说明里；目标与结构约束之后列出，
    与 ``min/max objective; s.t. constraints; x >= 0, y in {0,1}`` 的惯例一致。
    """
    pieces: list[str] = []
    for variable in variables:
        symbol = str(variable.get("symbol") or "")
        domain = _domain_latex(str(variable.get("type") or ""))
        if not symbol or not domain:
            continue
        piece = f"{_symbol_latex(symbol)} {domain}"
        quantifier = _quantifier_latex(symbol)
        if quantifier:
            piece += f", \\quad {quantifier}"
        pieces.append(piece)

    if not pieces:
        return []
    return ["**变量取值范围**", "", "$$", ",\\qquad ".join(pieces), "$$", ""]


def _symbol_latex(symbol: str) -> str:
    if "_" not in symbol:
        return symbol
    base, subscript = symbol.split("_", 1)
    return f"{base}_{{{subscript}}}" if len(subscript) > 1 else f"{base}_{subscript}"


def _domain_latex(var_type: str) -> str:
    if var_type == "binary":
        return "\\in \\{0,1\\}"
    if var_type == "integer":
        return "\\in \\mathbb{Z}_{\\ge 0}"
    if var_type == "continuous":
        return "\\ge 0"
    return ""


def _objective_display_name(name: str) -> str:
    text = str(name)
    for prefix in ("最小化", "最大化"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.removesuffix("目标").replace("目标（", "（")
    return text or str(name)


def _render_objective(ir: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    objective = ir.get("objective") or {}
    block_id = str(objective.get("block_id") or "")
    entry = catalog["by_id"].get(block_id) if block_id else None
    sense = str(objective.get("sense") or (entry or {}).get("sense") or "")
    name = (entry or {}).get("name") or "库外目标"

    sense_text = _SENSE_TEXT.get(sense, sense or "未声明方向")
    display_name = _objective_display_name(name) if entry else str(name)
    lines = [f"**目标函数：{sense_text}{display_name}**", ""]
    math = (entry or {}).get("math")
    if math:
        lines.append("$$")
        lines.append(str(math))
        lines.append("$$")
    else:
        expression = str(objective.get("expression") or objective.get("natural_language") or "")
        if expression:
            lines.append(expression)
        else:
            lines.append("未声明目标函数。")
    lines.append("")
    return lines


def _render_constraints(ir: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    blocks = ir.get("constraint_blocks") or []
    if not blocks:
        return ["**约束条件**：未声明", ""]

    lines = ["**约束条件**", ""]
    for index, block in enumerate(blocks, 1):
        block_id = str(block.get("block_id") or "")
        entry = catalog["by_id"].get(block_id) or {}
        name = entry.get("name") or block.get("name") or "其他约束"
        lines.append(f"{index}. **{name}**")
        natural = str(block.get("natural_language") or entry.get("description") or "").strip()
        if natural and natural != name:
            lines.append("")
            lines.append(natural)
        math = entry.get("math")
        if math:
            lines.append("")
            lines.append("$$")
            lines.append(str(math))
            lines.append("$$")
        else:
            text = block.get("natural_language") or entry.get("description")
            if text:
                lines.append("")
                lines.append(str(text))
        lines.append("")
    return lines


def _render_custom_constraints(ir: dict[str, Any]) -> list[str]:
    custom = ir.get("custom_constraints") or []
    if not custom:
        return []
    lines = ["**库外规则**", ""]
    lines.extend(f"- {item}" for item in custom)
    lines.append("")
    return lines


__all__ = ["render_model_document"]
