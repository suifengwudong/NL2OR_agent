"""Problem IR normalization: aliases, entities, objective, constraint blocks.

Turns whatever the model produced into one canonical shape. Validation lives in
``core/ir_validate.py``; the executable parameter view lives on ``ProblemIR``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from schema.problem_ir import (
    FAMILY_ID_ALIASES,
    FORBIDDEN_AS_BLOCK,
    OBJECTIVE_BLOCK_ALIASES,
    VALID_STATUS,
)

from .ir_catalog import load_block_catalog, load_model_bank

_SENSE_ALIASES: dict[str, str] = {
    "min": "minimize",
    "minimise": "minimize",
    "minimize": "minimize",
    "minimum": "minimize",
    "max": "maximize",
    "maximise": "maximize",
    "maximize": "maximize",
    "maximum": "maximize",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_problem_ir(
    ir: dict[str, Any],
    *,
    blocks_path: Path | None = None,
    models_path: Path | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Return (normalized_ir, errors, warnings)."""
    catalog = load_block_catalog(blocks_path)
    model_bank = load_model_bank(models_path)
    return normalize_with_context(ir, catalog, model_bank)


# ---------------------------------------------------------------------------


# Normalization helpers


# ---------------------------------------------------------------------------


def normalize_with_context(
    ir: dict[str, Any],
    catalog: dict[str, Any],
    model_bank: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Normalize IR using a pre-loaded catalog and model bank (shared loading)."""
    errors: list[str] = []
    warnings: list[str] = []

    model_ids = set(model_bank["by_id"].keys())

    out: dict[str, Any] = {}

    families = ir.get("problem_families") or []
    if not isinstance(families, list):
        errors.append("problem_families 必须是列表")
        families = []
    out["problem_families"] = [_normalize_family(f, catalog, model_ids) for f in families]

    out["is_hybrid"] = bool(
        ir.get("is_hybrid", len(out["problem_families"]) > 1 or ir.get("custom_constraints"))
    )
    out["hybrid_notes"] = ir.get("hybrid_notes") or (
        "组合多个问题族或含自定义约束" if out["is_hybrid"] else ""
    )

    out["entities"] = _normalize_entities(ir.get("entities"))

    params = ir.get("parameters")
    out["parameters"] = _normalize_parameters(params, out["entities"])

    out["decision_variables"] = (
        ir.get("decision_variables") if isinstance(ir.get("decision_variables"), list) else []
    )

    out["objective"] = _normalize_objective(ir.get("objective"), catalog, errors, warnings)

    raw_blocks = ir.get("constraint_blocks") or []
    if not isinstance(raw_blocks, list):
        errors.append("constraint_blocks 必须是列表")
        raw_blocks = []
    normalized_blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_blocks:
        nb = _normalize_constraint_entry(entry, catalog, errors, warnings)
        if nb:
            if nb["block_id"] in seen:
                warnings.append(f"重复块 {nb['block_id']}，已保留第一条")
                continue
            seen.add(nb["block_id"])
            if nb["category"] == "objective":
                warnings.append(
                    f"目标块 {nb['block_id']} 应放在 objective，不应在 constraint_blocks"
                )
                continue
            normalized_blocks.append(nb)
    out["constraint_blocks"] = normalized_blocks

    custom = ir.get("custom_constraints")
    if custom is None:
        custom = []
    if isinstance(custom, str):
        custom = [custom]
    if not isinstance(custom, list):
        errors.append("custom_constraints 必须是字符串列表")
        custom = []
    out["custom_constraints"] = [str(c) for c in custom if str(c).strip()]

    missing = ir.get("missing_data")
    out["missing_data"] = missing if isinstance(missing, list) else []

    report = ir.get("report")
    if report is None:
        out["report"] = {}
    elif isinstance(report, dict):
        out["report"] = report
    else:
        errors.append("report 必须是对象")
        out["report"] = {}

    return out, errors, warnings


def _canonical_block_id(raw: str, catalog: dict[str, Any]) -> str | None:
    key = raw.strip().lower()
    by_id = catalog["by_id"]
    if key in by_id:
        return key
    if key in catalog["alias_to_id"]:
        return catalog["alias_to_id"][key]
    return None


def _normalize_entities(value: Any) -> dict[str, Any]:
    """Normalize ``entities`` into ``{"I": {"size": n, "ids": [...]}, ...}``."""
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, entry in value.items():
        if isinstance(entry, int):
            out[str(key)] = {"size": int(entry), "ids": []}
            continue
        if not isinstance(entry, dict):
            continue
        size = entry.get("size")
        ids = entry.get("ids")
        out[str(key)] = {
            "size": int(size) if isinstance(size, (int, float)) else 0,
            "ids": [str(x) for x in ids] if isinstance(ids, list) else [],
        }
    return out


def _normalize_confidence(val: Any) -> str:
    if isinstance(val, (int, float)):
        if val >= 0.8:
            return "high"
        if val >= 0.5:
            return "medium"
        return "low"
    if isinstance(val, str):
        low = val.strip().lower()
        if low in {"high", "medium", "low"}:
            return low
        try:
            return _normalize_confidence(float(low))
        except ValueError:
            pass
    return "medium"


def _normalize_family(fam: Any, catalog: dict[str, Any], model_ids: set[str]) -> dict[str, Any]:
    if not isinstance(fam, dict):
        return {"id": "unknown", "name": str(fam), "confidence": "medium", "notes": ""}
    raw_id = (fam.get("id") or fam.get("name") or "unknown").strip().lower()
    fam_id = FAMILY_ID_ALIASES.get(raw_id, raw_id.replace(" ", "_").replace("-", "_"))
    if fam_id not in model_ids and raw_id in model_ids:
        fam_id = raw_id
    return {
        "id": fam_id,
        "name": fam.get("name") or fam_id,
        "confidence": _normalize_confidence(fam.get("confidence", "medium")),
        "notes": fam.get("notes") or "",
    }


def _normalize_objective(
    obj: Any,
    catalog: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Normalize ``objective`` into ``{sense, block_id, expression, ...}``.

    目标块只做归一与核对，不做替换：库中找不到就按库外目标记录并给出提示，
    未声明就留空，避免把未知目标静默改写成某个库内目标。
    """
    objective_ids = set(catalog["objective_block_ids"])
    sense_by_id: dict[str, str] = catalog.get("objective_sense", {})

    def _empty() -> dict[str, Any]:
        return {
            "sense": "",
            "block_id": "",
            "expression": "",
            "natural_language": "",
            "parameters": {},
        }

    if isinstance(obj, str):
        text = obj.strip()
        if not text:
            warnings.append("未声明目标函数：objective.block_id 为空")
            return _empty()
        key = text.lower()
        candidate = OBJECTIVE_BLOCK_ALIASES.get(key) or key
        block_id = _canonical_block_id(candidate, catalog) or ""
        if block_id not in objective_ids:
            warnings.append(f"目标 '{text}' 未匹配到库中目标块，按库外目标处理")
            block_id = ""
        return {
            "sense": _normalize_sense(None, sense_by_id.get(block_id), block_id, warnings),
            "block_id": block_id,
            "expression": text,
            "natural_language": text,
            "parameters": {},
        }

    if isinstance(obj, dict):
        raw = str(obj.get("block_id") or obj.get("id") or "").strip()
        block_id = ""
        if raw:
            canon = _canonical_block_id(raw, catalog)
            if canon is None:
                block_id = raw
                warnings.append(f"目标块 '{raw}' 不在库中，按库外目标处理")
            elif canon in objective_ids:
                block_id = canon
            else:
                errors.append(
                    f"'{raw}' 不是目标块（category={catalog['by_id'][canon].get('category', '')}），"
                    "请放入 constraint_blocks"
                )
                block_id = canon
        else:
            expr = str(obj.get("expression", "")).strip()
            if expr:
                candidate = OBJECTIVE_BLOCK_ALIASES.get(expr.lower()) or _canonical_block_id(
                    expr, catalog
                )
                if candidate in objective_ids:
                    block_id = candidate or ""

        catalog_sense = sense_by_id.get(block_id)
        sense = _normalize_sense(obj.get("sense"), catalog_sense, block_id, warnings)
        if sense and catalog_sense and sense != catalog_sense:
            errors.append(f"目标块 {block_id} 的优化方向为 {catalog_sense}，IR 声明为 {sense}")

        params = obj.get("parameters") or {}
        if not isinstance(params, dict):
            warnings.append("objective.parameters 必须是对象，已忽略")
            params = {}
        return {
            "sense": sense,
            "block_id": block_id,
            "expression": str(obj.get("expression", "")),
            "natural_language": str(obj.get("natural_language", "")),
            "parameters": params,
        }

    if obj is None:
        warnings.append("未声明目标函数：objective 缺失")
        return _empty()

    errors.append(f"objective 必须是对象或字符串，收到 {type(obj).__name__}")
    return _empty()


def _normalize_sense(
    value: Any,
    catalog_sense: str | None,
    block_id: str,
    warnings: list[str],
) -> str:
    """Resolve the optimization direction, falling back to the catalog sense."""
    if value is None or str(value).strip() == "":
        if catalog_sense:
            return catalog_sense
        warnings.append(f"目标块 {block_id or '(未声明)'} 缺少优化方向 sense")
        return ""
    sense = _SENSE_ALIASES.get(str(value).strip().lower(), "")
    if not sense:
        warnings.append(f"无法识别的 sense '{value}'，已按未声明处理")
    return sense


def _normalize_constraint_entry(
    entry: Any,
    catalog: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        errors.append(f"constraint_blocks 项必须是对象，收到: {type(entry).__name__}")
        return None
    raw_id = str(entry.get("block_id") or entry.get("id") or "").strip()
    if not raw_id:
        errors.append("constraint_blocks 某项缺少 block_id")
        return None
    low = raw_id.lower()
    if low in FORBIDDEN_AS_BLOCK:
        errors.append(
            f"'{raw_id}' 不能放在 constraint_blocks 中；请写入顶层 custom_constraints 列表"
        )
        return None
    canon = _canonical_block_id(raw_id, catalog)
    if not canon:
        errors.append(f"未知 block_id: '{raw_id}'；请使用库中标准 id")
        return None
    if canon != raw_id:
        warnings.append(f"block_id '{raw_id}' 已规范为 '{canon}'")
    block_def = catalog["by_id"][canon]
    params = entry.get("parameters")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        errors.append(f"块 {canon} 的 parameters 必须是对象")
        params = {}
    if canon == "force_facility_open" and "forced_open" not in params and "facility_ids" in params:
        warnings.append("参数 facility_ids 已映射为 forced_open（请使用设施名如 'B' 或索引）")
        params["forced_open"] = params.pop("facility_ids")
    if (
        canon == "force_facility_closed"
        and "forced_closed" not in params
        and "facility_ids" in params
    ):
        warnings.append("参数 facility_ids 已映射为 forced_closed")
        params["forced_closed"] = params.pop("facility_ids")
    status = str(entry.get("status", "required")).lower()
    if status not in VALID_STATUS:
        warnings.append(f"块 {canon} 的 status '{status}' 已改为 required")
        status = "required"
    return {
        "block_id": canon,
        "category": block_def.get("category", ""),
        "name": block_def.get("name", ""),
        "parameters": params,
        "status": status,
        "natural_language": str(entry.get("natural_language", "")),
    }


def _normalize_parameters(params: Any, entities: dict[str, Any]) -> dict[str, Any]:
    """Normalize named matrix data to the list-of-lists solver representation."""
    if not isinstance(params, dict):
        return {}

    out = dict(params)
    index_sets = {
        key: [str(item) for item in (entities.get(key) or {}).get("ids") or []]
        for key in ("I", "J")
    }
    row_ids = index_sets["I"]
    col_ids = index_sets["J"]
    if not row_ids or not col_ids:
        return out

    for key in ("distance", "service_cost", "coverage_matrix", "availability"):
        value = out.get(key)
        if not isinstance(value, dict):
            continue
        try:
            out[key] = [[value[row_id][col_id] for col_id in col_ids] for row_id in row_ids]
        except (KeyError, TypeError):
            # Leave malformed input unchanged so validation can report it.
            continue

    value = out.get("facility_distance")
    if isinstance(value, dict) and col_ids:
        try:
            out["facility_distance"] = [
                [value[row_id][col_id] for col_id in col_ids] for row_id in col_ids
            ]
        except (KeyError, TypeError):
            pass
    return out
