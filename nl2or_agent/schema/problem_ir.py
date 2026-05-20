"""Canonical Problem IR alignment with constraint_blocks.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BLOCKS_PATH = Path(__file__).parent.parent / "data" / "model_bank" / "constraint_blocks.json"
_MODELS_PATH = Path(__file__).parent.parent / "data" / "model_bank" / "models.json"

# LLM 常见缩写 / 误用 id → 库中标准 block_id
BLOCK_ID_ALIASES: dict[str, str] = {
    "assignment": "assign_each_demand_once",
    "demand_assignment": "assign_each_demand_once",
    "unique_assignment": "assign_each_demand_once",
    "linking": "link_assignment_to_open",
    "capacity_link": "link_assignment_to_open",
    "cardinality": "cardinality_open_p_facilities",
    "p_facility": "cardinality_open_p_facilities",
    "select_p": "cardinality_open_p_facilities",
    "forcing": "force_facility_open",
    "forcing_open": "force_facility_open",
    "must_open": "force_facility_open",
    "prohibiting": "force_facility_closed",
    "forcing_closed": "force_facility_closed",
    "must_close": "force_facility_closed",
    "force_closed": "force_facility_closed",
    "weighted_distance": "weighted_service_distance_objective",
    "minimize_weighted_distance": "weighted_service_distance_objective",
    "service_distance": "weighted_service_distance_objective",
    "knapsack": "knapsack_capacity",
}

OBJECTIVE_BLOCK_ALIASES: dict[str, str] = {
    "minimize_total_weighted_distance": "weighted_service_distance_objective",
    "weighted_distance": "weighted_service_distance_objective",
    "min_sum_weighted_distance": "weighted_service_distance_objective",
}

FAMILY_ID_ALIASES: dict[str, str] = {
    "p-median": "p_median",
    "p median": "p_median",
    "facility location": "facility_location",
    "facility_location_problem": "facility_location",
}

FORBIDDEN_AS_BLOCK = frozenset({"custom_constraints", "custom", "objective"})

VALID_STATUS = frozenset({"required", "optional", "user_specified"})


def load_block_catalog(blocks_path: Path | None = None) -> dict[str, Any]:
    path = blocks_path or _BLOCKS_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    blocks = data.get("blocks", [])
    by_id = {b["id"]: b for b in blocks}
    alias_to_id: dict[str, str] = dict(BLOCK_ID_ALIASES)
    for block in blocks:
        for alias in block.get("aliases", []):
            alias_to_id[str(alias).strip().lower()] = block["id"]
    return {
        "blocks": blocks,
        "by_id": by_id,
        "alias_to_id": alias_to_id,
        "block_ids": sorted(by_id.keys()),
        "objective_block_ids": sorted(
            b["id"] for b in blocks if b.get("category") == "objective"
        ),
    }


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


def _normalize_family(fam: Any, catalog: dict[str, Any], model_ids: set[str]) -> dict[str, Any]:
    if not isinstance(fam, dict):
        return {"id": "unknown", "name": str(fam), "confidence": "medium", "notes": ""}
    raw_id = (fam.get("id") or fam.get("name") or "unknown").strip().lower()
    fam_id = FAMILY_ID_ALIASES.get(raw_id, raw_id.replace(" ", "_").replace("-", "_"))
    if fam_id not in model_ids and raw_id in model_ids:
        fam_id = raw_id
    out = {
        "id": fam_id,
        "name": fam.get("name") or fam_id,
        "confidence": _normalize_confidence(fam.get("confidence", "medium")),
        "notes": fam.get("notes") or "",
    }
    return out


def _normalize_objective(obj: Any, catalog: dict[str, Any]) -> dict[str, Any]:
    objective_ids = set(catalog["objective_block_ids"])
    if isinstance(obj, str):
        key = obj.strip().lower()
        block_id = OBJECTIVE_BLOCK_ALIASES.get(key, key)
        if block_id not in objective_ids:
            block_id = _canonical_block_id_fixed(block_id, catalog) or block_id
        return {
            "sense": "minimize",
            "block_id": block_id if block_id in objective_ids else "weighted_service_distance_objective",
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
            block_id = OBJECTIVE_BLOCK_ALIASES.get(expr, "weighted_service_distance_objective")
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
    if canon == "force_facility_open" and "forced_open" not in params and "facility_ids" in params:
        warnings.append("参数 facility_ids 已映射为 forced_open（请使用设施名如 'B' 或索引）")
        params["forced_open"] = params.pop("facility_ids")
    if canon == "force_facility_closed" and "forced_closed" not in params and "facility_ids" in params:
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
        "natural_language": entry.get("natural_language") or block_def.get("description", ""),
    }


def normalize_problem_ir(
    ir: dict[str, Any],
    *,
    blocks_path: Path | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Return (normalized_ir, errors, warnings)."""
    catalog = load_block_catalog(blocks_path)
    errors: list[str] = []
    warnings: list[str] = []

    with open(_MODELS_PATH, encoding="utf-8") as f:
        models_bank = json.load(f)
    model_ids = {m["id"] for m in models_bank.get("models", [])}

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
                warnings.append(f"目标块 {nb['block_id']} 应放在 objective，不应在 constraint_blocks")
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


def validate_problem_ir(
    ir: dict[str, Any],
    *,
    blocks_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and normalize IR; return report dict for tools / tests."""
    normalized, errors, warnings = normalize_problem_ir(ir, blocks_path=blocks_path)
    catalog = load_block_catalog(blocks_path)
    for bid, bdef in catalog["by_id"].items():
        required_params = [p["name"] for p in bdef.get("parameters", []) if p.get("required")]
        if not required_params:
            continue
        for entry in normalized.get("constraint_blocks", []):
            if entry["block_id"] != bid:
                continue
            for pname in required_params:
                if pname not in entry.get("parameters", {}):
                    errors.append(f"块 {bid} 缺少必填参数 '{pname}'")

    return {
        "valid": len(errors) == 0,
        "normalized_ir": normalized,
        "errors": errors,
        "warnings": warnings,
        "catalog_block_ids": catalog["block_ids"],
    }


def catalog_markdown(blocks_path: Path | None = None) -> str:
    """Compact block id list for prompts."""
    catalog = load_block_catalog(blocks_path)
    lines = ["| block_id | category | 必填参数 |", "|----------|----------|----------|"]
    for bid in catalog["block_ids"]:
        b = catalog["by_id"][bid]
        req = ", ".join(
            p["name"] for p in b.get("parameters", []) if p.get("required")
        ) or "—"
        lines.append(f"| `{bid}` | {b.get('category', '')} | {req} |")
    return "\n".join(lines)
