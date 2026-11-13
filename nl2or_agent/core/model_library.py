"""Model-library retrieval: bounded, on-demand views over the bank.

The system prompt stays constant in size; identification happens through these
two views instead:

- ``search_entries(keywords)`` — compact index of candidate models and blocks.
- ``describe_model(model_id)`` — the chosen template's required skeleton.

Neither view carries LaTeX: ``model_math`` is the single source of formulas, so
block math is never duplicated into the identification step.
"""

from __future__ import annotations

import re
from typing import Any

from .ir_catalog import load_block_catalog, load_model_bank

_TOKEN_SPLIT = re.compile(r"[\s,，、;；/|]+")


def _tokens(keywords: str | None) -> list[str]:
    if not keywords:
        return []
    return [t for t in (tok.strip().lower() for tok in _TOKEN_SPLIT.split(keywords)) if t]


def _hits(tokens: list[str], *fields: Any) -> int:
    """How many tokens appear in any field; 0 means no match."""
    haystack = " ".join(str(field or "").lower() for field in fields)
    return sum(1 for token in tokens if token in haystack)


def _param_line(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", ""))
    required = "必填" if parameter.get("required") else "可选"
    description = str(parameter.get("description") or parameter.get("type") or "")
    suffix = f"：{description}" if description else ""
    return f"  - `{name}`（{required}）{suffix}"


def _block_summary(block_id: str, catalog: dict[str, Any]) -> str:
    entry = catalog["by_id"].get(block_id) or {}
    params = [p for p in entry.get("parameters", []) if p.get("required")]
    req = ", ".join(f"`{p['name']}`" for p in params) if params else "无"
    return (
        f"  - `{block_id}`（{entry.get('name', '')}，参数：{req}）：{entry.get('description', '')}"
    )


def search_entries(keywords: str | None = None) -> str:
    """Return a bounded candidate list: models first, then composable blocks.

    Tokens are matched against ids, names, descriptions and categories. Without
    keywords the whole model table is returned (blocks stay hidden — they are
    an implementation detail until a keyword asks for them).
    """
    bank = load_model_bank()
    catalog = load_block_catalog()
    tokens = _tokens(keywords)

    model_rows: list[tuple[int, dict[str, Any]]] = []
    for model in bank.get("models", []):
        required, _ = _required_and_optional(bank, model["id"])
        score = (
            _hits(
                tokens,
                model.get("id"),
                model.get("name"),
                model.get("description"),
                model.get("class"),
                *[catalog["by_id"].get(b, {}).get("name", "") for b in required],
            )
            if tokens
            else 1
        )
        if score:
            model_rows.append((score, model))

    model_rows.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    # 无关键词时给全表（当前 19 个模型）；有关键词时只给前 8 个
    shown_models = [m for _, m in model_rows] if not tokens else [m for _, m in model_rows[:8]]

    lines = ["### 模型库候选（模型）", "", "| id | 名称 | 说明 |"]
    lines.append("|----|------|------|")
    for model in shown_models:
        lines.append(
            f"| `{model['id']}` | {model.get('name', '')} | {model.get('description', '')} |"
        )
    if not shown_models:
        lines.append("|（无匹配；换关键词，或省略关键词列出全部模型） | | |")
    lines.append("")
    lines.append("选中后用 `describe_model(id)` 取该模板的必需块、参数与目标。")

    if tokens:
        block_rows: list[tuple[int, dict[str, Any]]] = []
        for block in catalog["blocks"]:
            score = _hits(
                tokens,
                block.get("id"),
                block.get("name"),
                block.get("category"),
                block.get("description"),
                *block.get("aliases", []),
            )
            if score:
                block_rows.append((score, block))
        block_rows.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        blocks = [b for _, b in block_rows[:10]]
        if blocks:
            lines.extend(
                [
                    "",
                    "### 模型库候选（可组合的积木块）",
                    "",
                    "| block_id | 名称 | 类别 | 说明 |",
                    "|----------|------|------|------|",
                ]
            )
            for block in blocks:
                lines.append(
                    f"| `{block['id']}` | {block.get('name', '')} "
                    f"| {block.get('category', '')} | {block.get('description', '')} |"
                )
            lines.extend(
                [
                    "",
                    "积木块只在题面明确要求对应限制时启用，作为 constraint_blocks 的额外块。",
                ]
            )
    return "\n".join(lines)


def _required_and_optional(bank: dict[str, Any], model_id: str) -> tuple[list[str], list[str]]:
    model = bank["by_id"].get(model_id)
    if model is None:
        return [], []
    if model.get("is_family"):
        return list(model.get("base_blocks") or []), list(model.get("optional_blocks") or [])
    required = list(bank.get("effective_blocks", {}).get(model_id, []))
    optional = list(model.get("optional_blocks") or [])
    family_id = model.get("inherits") or model.get("family")
    if family_id and family_id in bank["by_id"]:
        optional += list(bank["by_id"][family_id].get("optional_blocks") or [])
    return required, list(dict.fromkeys(optional))


def describe_model(model_id: str) -> str:
    """Return the template's required skeleton: blocks, data, objective, variables.

    Only required blocks are listed. Optional substitutes appear in
    ``validate_problem_ir`` errors when a required block is missing, and extra
    blocks can be found with ``search_model_library`` keywords.
    """
    bank = load_model_bank()
    catalog = load_block_catalog()
    model = bank["by_id"].get(model_id)
    if model is None:
        known = ", ".join(f"`{m['id']}`" for m in bank.get("models", []) if not m.get("is_family"))
        return f"模型库中没有 '{model_id}'。先用 search_model_library 检索；现有模型：{known}"

    required, _ = _required_and_optional(bank, model_id)
    lines = [f"### 模板 `{model_id}`（{model.get('name', '')}）", ""]
    lines.append(str(model.get("description", "")))
    lines.append("")

    if required:
        lines.append("**必需约束块**（都要出现在 constraint_blocks 里）")
        lines.append("")
        lines.extend(_block_summary(bid, catalog) for bid in required)
        lines.append("")

    objective_id = str(model.get("objective_block") or "")
    if objective_id:
        entry = catalog["by_id"].get(objective_id) or {}
        sense = entry.get("sense", "")
        lines.append(f"**目标块**：`{objective_id}`（{entry.get('name', '')}，方向 {sense}）")
        for parameter in entry.get("parameters", []):
            if parameter.get("required"):
                lines.append(_param_line(parameter))
        lines.append("")

    parameters = model.get("parameters") or []
    if parameters:
        lines.append("**数据参数**（放在顶层 parameters 或所属块的 parameters 里）")
        lines.append("")
        lines.extend(_param_line(parameter) for parameter in parameters)
        lines.append("")

    family_id = (
        model.get("inherits") or model.get("family") or (model_id if model.get("is_family") else "")
    )
    variables = (
        (bank["by_id"].get(family_id) or {}).get("variables") or model.get("variables") or []
    )
    if variables:
        lines.append("**决策变量**")
        lines.append("")
        for variable in variables:
            lines.append(
                f"  - ${variable['symbol']}$（{variable.get('type', '')}）：{variable.get('meaning', '')}"
            )
        lines.append("")

    lines.append("据此构建 Problem IR 并调用 `validate_problem_ir`；公式由 `model_math` 渲染。")
    return "\n".join(lines)


__all__ = ["describe_model", "search_entries"]
