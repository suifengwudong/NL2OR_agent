"""IR normalization: normalize Problem IR against block catalog and model bank.

Separated from ir_catalog.py to keep data-loading and normalization logic
in distinct modules.
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
    errors: list[str] = []
    warnings: list[str] = []

    model_bank = load_model_bank(models_path)
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

    params = ir.get("parameters")
    out["parameters"] = params if isinstance(params, dict) else {}

    out["decision_variables"] = (
        ir.get("decision_variables") if isinstance(ir.get("decision_variables"), list) else []
    )

    out["objective"] = _normalize_objective(ir.get("objective"), catalog)

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

    return out, errors, warnings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _canonical_block_id_fixed(raw: str, catalog: dict[str, Any]) -> str | None:
    key = raw.strip().lower()
    by_id = catalog["by_id"]
    if key in by_id:
        return key
    if key in catalog["alias_to_id"]:
        return catalog["alias_to_id"][key]
    return None


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


def _normalize_family(
    fam: Any, catalog: dict[str, Any], model_ids: set[str]
) -> dict[str, Any]:
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


def _normalize_objective(obj: Any, catalog: dict[str, Any]) -> dict[str, Any]:
    objective_ids = set(catalog["objective_block_ids"])
    if isinstance(obj, str):
        key = obj.strip().lower()
        block_id = OBJECTIVE_BLOCK_ALIASES.get(key, key)
        if block_id not in objective_ids:
            block_id = _canonical_block_id_fixed(block_id, catalog) or block_id
        return {
            "sense": "minimize",
            "block_id": (
                block_id
                if block_id in objective_ids
                else "weighted_service_distance_objective"
            ),
            "expression": obj,
            "natural_language": obj,
        }
    if isinstance(obj, dict):
        block_id = obj.get("block_id") or obj.get("id") or ""
        if block_id:
            canon = _canonical_block_id_fixed(str(block_id), catalog)
            if canon and canon in objective_ids:
                block_id = canon
            elif str(block_id).lower() in OBJECTIVE_BLOCK_ALIASES:
                block_id = OBJECTIVE_BLOCK_ALIASES[str(block_id).lower()]
        else:
            expr = str(obj.get("expression", "")).lower()
            block_id = OBJECTIVE_BLOCK_ALIASES.get(
                expr, "weighted_service_distance_objective"
            )
        return {
            "sense": obj.get("sense", "minimize"),
            "block_id": block_id,
            "expression": obj.get("expression", ""),
            "natural_language": obj.get("natural_language", ""),
            "parameters": obj.get("parameters") or {},
        }
    return {
        "sense": "minimize",
        "block_id": "weighted_service_distance_objective",
        "expression": "",
        "natural_language": "",
        "parameters": {},
    }


def _normalize_constraint_entry(
    entry: Any,
    catalog: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        errors.append(
            f"constraint_blocks 项必须是对象，收到: {type(entry).__name__}"
        )
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
    canon = _canonical_block_id_fixed(raw_id, catalog)
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
    if (
        canon == "force_facility_open"
        and "forced_open" not in params
        and "facility_ids" in params
    ):
        warnings.append(
            "参数 facility_ids 已映射为 forced_open（请使用设施名如 'B' 或索引）"
        )
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
