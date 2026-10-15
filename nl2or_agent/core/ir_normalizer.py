"""IR normalization and validation.

Normalizes and validates Problem IR against block catalog and model bank.
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
    return _normalize_with_context(ir, catalog, model_bank)


def _normalize_with_context(
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
    out["parameters"] = params if isinstance(params, dict) else {}

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

    return out, errors, warnings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def validate_problem_ir(
    ir: dict[str, Any],
    *,
    blocks_path: Path | None = None,
    models_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and normalize IR; return report dict for tools / tests."""
    catalog = load_block_catalog(blocks_path)
    model_bank = load_model_bank(models_path)
    normalized, errors, warnings = _normalize_with_context(ir, catalog, model_bank)
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

    skeleton = _check_skeleton(normalized, catalog, model_bank, errors, warnings)

    return {
        "valid": len(errors) == 0,
        "normalized_ir": normalized,
        "errors": errors,
        "warnings": warnings,
        "catalog_block_ids": catalog["block_ids"],
        "catalog_objective_ids": catalog["objective_block_ids"],
        "skeleton": skeleton,
    }


# ---------------------------------------------------------------------------
# Skeleton checks: 约束集与目标函数是否构成完整的运筹模型
# ---------------------------------------------------------------------------


def _required_and_optional_blocks(
    model_bank: dict[str, Any], model_id: str
) -> tuple[list[str], list[str]]:
    """Return (必需块, 可替代块) for a declared family or concrete model."""
    model = model_bank["by_id"][model_id]
    if model.get("is_family"):
        return (
            list(model.get("base_blocks") or []),
            list(model.get("optional_blocks") or []),
        )
    required = list(model_bank.get("effective_blocks", {}).get(model_id, []))
    optional = list(model.get("optional_blocks") or [])
    family_id = model.get("family")
    if family_id and family_id in model_bank["by_id"]:
        optional += list(model_bank["by_id"][family_id].get("optional_blocks") or [])
    return required, optional


def collect_parameters(ir: dict[str, Any]) -> dict[str, Any]:
    """Merge the executable view of the IR's numeric data.

    Data may sit in the top-level ``parameters`` or inside a block's own
    ``parameters``; string values are treated as placeholders (e.g.
    "由距离矩阵给定") and ignored. Top-level values win.
    """
    data = {k: v for k, v in (ir.get("parameters") or {}).items() if not isinstance(v, str)}
    for entry in ir.get("constraint_blocks") or []:
        for key, value in (entry.get("parameters") or {}).items():
            if not isinstance(value, str):
                data.setdefault(key, value)
    for key, value in ((ir.get("objective") or {}).get("parameters") or {}).items():
        if not isinstance(value, str):
            data.setdefault(key, value)
    return data


def _check_entities(normalized_ir: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    """Check that the declared index sets agree with the declared data.

    核对的是内容维度：p 与 |J|、各参数长度与 |I| / |J|、矩阵维度、强制设施是否落在 J 内。
    """
    entities = normalized_ir.get("entities") or {}
    n_i = (entities.get("I") or {}).get("size") or None
    n_j = (entities.get("J") or {}).get("size") or None
    j_ids = [str(x) for x in (entities.get("J") or {}).get("ids") or []]
    params = collect_parameters(normalized_ir)
    problems: list[str] = []

    def report(message: str) -> None:
        errors.append(message)
        problems.append(message)

    if n_j is not None:
        p = params.get("p")
        if isinstance(p, int) and p > n_j:
            report(f"p={p} 超过候选设施数 |J|={n_j}")

    for key in ("demand", "value", "weight"):
        values = params.get(key)
        if n_i and isinstance(values, list) and len(values) != n_i:
            report(f"参数 {key} 的长度 {len(values)} 与 |I|={n_i} 不符")
    for key in ("fixed_cost", "facility_capacity"):
        values = params.get(key)
        if n_j and isinstance(values, list) and len(values) != n_j:
            report(f"参数 {key} 的长度 {len(values)} 与 |J|={n_j} 不符")
    for key in ("distance", "service_cost", "coverage_matrix"):
        values = params.get(key)
        if n_i and n_j and isinstance(values, list) and values and isinstance(values[0], list):
            shape = (len(values), len(values[0]))
            if shape != (n_i, n_j):
                report(f"参数 {key} 的维度 {shape[0]}x{shape[1]} 与 |I|x|J|={n_i}x{n_j} 不符")

    for key in ("forced_open", "forced_closed"):
        for item in params.get(key) or []:
            if j_ids:
                if str(item) not in j_ids:
                    report(f"参数 {key} 中的 {item!r} 不在设施集合 J 中")
            elif isinstance(item, int) and n_j is not None and not 0 <= item < n_j:
                report(f"参数 {key} 中的下标 {item} 超出 |J|={n_j}")

    return {"n_i": n_i, "n_j": n_j, "problems": problems}


def _check_skeleton(
    normalized_ir: dict[str, Any],
    catalog: dict[str, Any],
    model_bank: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Check that the constraint set and objective form a complete OR model.

    核对对象是模型的骨架（约束块与目标函数），与生成代码的写法无关。
    """
    by_block = catalog["by_id"]
    objective_ids = set(catalog["objective_block_ids"])
    present = [b["block_id"] for b in normalized_ir.get("constraint_blocks", [])]
    present_set = set(present)

    declared = [str(f.get("id")) for f in normalized_ir.get("problem_families", []) if f.get("id")]
    known = [mid for mid in declared if mid in model_bank["by_id"]]
    unknown = [mid for mid in declared if mid not in model_bank["by_id"]]

    required: list[str] = []
    optional: list[str] = []
    for mid in known:
        req, opt = _required_and_optional_blocks(model_bank, mid)
        required += req
        optional += opt
    required = list(dict.fromkeys(required))
    optional = list(dict.fromkeys(optional))

    missing: list[str] = []
    substituted: list[str] = []
    for bid in required:
        if bid in present_set:
            continue
        category = (by_block.get(bid) or {}).get("category")
        alternatives = [
            p
            for p in present
            if p in optional and (by_block.get(p) or {}).get("category") == category
        ]
        if alternatives:
            substituted.append(bid)
            warnings.append(f"模板要求 {bid}，实际使用了同类别可选块 {alternatives[0]}")
        else:
            missing.append(bid)
    if missing:
        errors.append(
            f"骨架缺少模板要求的约束块 {', '.join(missing)}（来自族/模型 {', '.join(known)}）"
        )

    for bid in present:
        one_of = list((by_block.get(bid) or {}).get("requires_one_of") or [])
        if one_of and not (present_set & set(one_of)):
            errors.append(f"块 {bid} 需要同时使用 {' 或 '.join(one_of)} 之一")

    inconsistent: list[str] = []
    for bid in present:
        if bid in required:
            # 模板要求的块必然与声明的族一致
            continue
        typical = list((by_block.get(bid) or {}).get("typical_models") or [])
        if typical and known and not (set(typical) & set(known)):
            inconsistent.append(bid)
            warnings.append(f"块 {bid} 通常用于 {'、'.join(typical)}，与声明的族/模型不一致")

    if unknown:
        warnings.append(f"族/模型 {'、'.join(unknown)} 不在模型库中，无法核对约束块骨架")

    objective = normalized_ir.get("objective") or {}
    objective_block = str(objective.get("block_id") or "")
    objective_sense = str(objective.get("sense") or "")
    if objective_block and known:
        expected = {
            str(model_bank["by_id"][mid].get("objective_block"))
            for mid in known
            if model_bank["by_id"][mid].get("objective_block")
        }
        if expected and objective_block not in expected:
            warnings.append(
                f"目标块 {objective_block} 与声明的族/模型不一致，模板期望 {' 或 '.join(sorted(expected))}"
            )

    unbound: list[str] = []
    if objective_block in by_block:
        required_params = [
            p["name"] for p in by_block[objective_block].get("parameters", []) if p.get("required")
        ]
        declared_data = set(objective.get("parameters") or {}) | set(
            normalized_ir.get("parameters") or {}
        )
        unbound = [name for name in required_params if name not in declared_data]
        if unbound:
            warnings.append(
                f"目标块 {objective_block} 的必填参数未在 objective.parameters 或顶层 parameters 中声明: "
                f"{', '.join(unbound)}"
            )

    return {
        "declared_models": known,
        "unknown_models": unknown,
        "required_blocks": required,
        "missing_required_blocks": missing,
        "substituted_blocks": substituted,
        "inconsistent_blocks": inconsistent,
        "objective_block": objective_block,
        "objective_sense": objective_sense,
        "objective_in_catalog": objective_block in objective_ids,
        "unbound_objective_params": unbound,
        "entities": _check_entities(normalized_ir, errors),
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
