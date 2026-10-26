"""Render the Problem IR as a human-readable mathematical model.

The catalog already carries the LaTeX for every block and objective. This
module assembles those pieces with the index sets, parameters and variable
definitions, so the final answer and the web model view show one document
instead of a list of block ids.
"""

from __future__ import annotations

from typing import Any

from .block_model import active_variable_names
from .ir_catalog import load_block_catalog, load_model_bank
from .problem_ir import ProblemIR

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
        lines.append(f"**问题类型**：{'、'.join(f'`{item}`' for item in family_ids)}")
        lines.append("")

    lines.extend(_render_entities(ir))
    lines.extend(_render_parameters(ir, entries))
    lines.extend(_render_variables(ir, entries))
    lines.extend(_render_objective(ir, catalog))
    lines.extend(_render_constraints(ir, catalog))
    lines.extend(_render_custom_constraints(ir))
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
    lines = ["**索引集合**", ""]
    for key, entry in entities.items():
        size = entry.get("size")
        ids = entry.get("ids") or []
        shown = ""
        if ids:
            shown = f"，${key} = \\{{{', '.join(str(item) for item in ids)}\\}}$"
        size_text = f"$|{key}| = {size}$" if size else f"${key}$"
        lines.append(f"- {size_text}{shown}")
    lines.append("")
    return lines


def _render_parameters(ir: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    definitions: dict[str, dict[str, Any]] = {}
    for model in entries:
        for parameter in model.get("parameters") or []:
            definitions.setdefault(str(parameter.get("name")), parameter)

    values = ProblemIR(ir).parameters
    names = list(dict.fromkeys([*definitions, *values]))
    if not names:
        return []

    lines = ["**参数**", "", "| 参数 | 含义 | 取值 |", "|------|------|------|"]
    for name in names:
        definition = definitions.get(name) or {}
        if name not in values and not definition.get("required"):
            continue
        meaning = definition.get("description") or "—"
        shown = _value_summary(values.get(name)) if name in values else "缺失"
        lines.append(f"| `{name}` | {meaning} | {shown} |")
    lines.append("")
    return lines


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


def _render_variables(ir: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    variables: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in entries:
        declared = model.get("variables") or model.get("decision_variables") or []
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

    if not variables:
        return ["**决策变量**：未声明", ""]

    lines = ["**决策变量**", ""]
    for variable in variables:
        symbol = _symbol_latex(str(variable.get("symbol") or ""))
        var_type = str(variable.get("type") or "")
        meaning = str(variable.get("meaning") or "")
        domain = _domain_latex(var_type)
        suffix = f" {domain}" if domain else ""
        lines.append(f"- ${symbol}{suffix}$：{meaning}")
    lines.append("")
    return lines


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


def _render_objective(ir: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    objective = ir.get("objective") or {}
    block_id = str(objective.get("block_id") or "")
    entry = catalog["by_id"].get(block_id) if block_id else None
    sense = str(objective.get("sense") or (entry or {}).get("sense") or "")
    name = (entry or {}).get("name") or "库外目标"

    sense_text = _SENSE_TEXT.get(sense, sense or "未声明方向")
    lines = [f"**目标函数**（{name}，`{block_id or '未声明'}`，{sense_text}）", ""]
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
        name = entry.get("name") or block.get("name") or block_id
        lines.append(f"{index}. **{name}**（`{block_id}`）")
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
