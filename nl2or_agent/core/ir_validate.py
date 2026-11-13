"""Problem IR validation: entity dimensions and the model skeleton.

Reads a normalized IR and reports errors/warnings; normalization itself lives in
``core/ir_normalize.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .block_model import READ_BLOCK_KEYS, readable_keys
from .ir_catalog import load_block_catalog, load_model_bank
from .ir_normalize import normalize_with_context
from .problem_ir import ProblemIR


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_problem_ir(
    ir: dict[str, Any],
    *,
    blocks_path: Path | None = None,
    models_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and normalize IR; return report dict for tools / tests.

    The report carries verdicts only (errors, warnings, skeleton). Template
    identification is the retrieval tools' job, so no block catalog or block
    math is echoed back into the context.
    """
    catalog = load_block_catalog(blocks_path)
    model_bank = load_model_bank(models_path)
    normalized, errors, warnings = normalize_with_context(ir, catalog, model_bank)
    for bid, bdef in catalog["by_id"].items():
        required_params = [p["name"] for p in bdef.get("parameters", []) if p.get("required")]
        if not required_params:
            continue
        for entry in normalized.get("constraint_blocks", []):
            if entry["block_id"] != bid:
                continue
            declared = set(entry.get("parameters") or {}) | set(normalized.get("parameters") or {})
            for pname in required_params:
                if pname not in declared:
                    errors.append(f"块 {bid} 缺少必填参数 '{pname}'")

    skeleton = _check_skeleton(normalized, catalog, model_bank, errors, warnings)

    declared = {
        key
        for key, value in (normalized.get("parameters") or {}).items()
        if not isinstance(value, str)
    }
    unread = sorted(declared - readable_keys(normalized))
    if unread:
        _report_unread_parameters(unread, normalized, skeleton, errors, warnings)

    return {
        "valid": len(errors) == 0,
        "normalized_ir": normalized,
        "errors": errors,
        "warnings": warnings,
        "skeleton": skeleton,
    }


def _report_unread_parameters(
    unread: list[str],
    normalized: dict[str, Any],
    skeleton: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Unread numeric data is an error on the solve_ir path.

    库内可执行的模型以块读取的键为准：多出的参数会让符号说明出现悬空符号，
    what_if 覆盖也会被拒绝，所以要求删除或换用读取它的块。没有可执行块的
    库外模型（run_solver 路径）保留提示，数据仍归手写脚本使用。
    """
    executable = bool(normalized.get("constraint_blocks")) and bool(
        skeleton.get("objective_in_catalog")
    )
    for key in unread:
        readers = sorted(block for block, keys in READ_BLOCK_KEYS.items() if key in keys)
        hint = f"读取它的块有 {'、'.join(readers)}" if readers else "库中没有块读取它"
        message = f"参数 {key} 未被任何已启用块读取（{hint}）；请删除该参数，或启用一个读取它的块"
        if executable:
            errors.append(message)
        else:
            warnings.append(message)


# ---------------------------------------------------------------------------


# Validation helpers


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
    family_id = model.get("inherits") or model.get("family")
    if family_id and family_id in model_bank["by_id"]:
        optional += list(model_bank["by_id"][family_id].get("optional_blocks") or [])
    return required, optional


def _substitute_candidates(
    bid: str,
    optional: list[str],
    by_block: dict[str, Any],
    declared: set[str],
) -> list[str]:
    """Optional blocks that could stand in for the missing required block *bid*."""
    category = (by_block.get(bid) or {}).get("category")
    candidates: list[str] = []
    for block_id in dict.fromkeys(optional):
        if block_id == bid or (by_block.get(block_id) or {}).get("category") != category:
            continue
        typical = set((by_block.get(block_id) or {}).get("typical_models") or [])
        if not typical or typical & declared:
            candidates.append(block_id)
    return candidates


def _check_entities(normalized_ir: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    """Check that the declared index sets agree with the declared data.

    核对的是内容维度：p 与 |J|、各参数长度与 |I| / |J|、矩阵维度、强制设施是否落在 J 内。
    """
    entities = normalized_ir.get("entities") or {}
    n_i = (entities.get("I") or {}).get("size") or None
    n_j = (entities.get("J") or {}).get("size") or None
    j_ids = [str(x) for x in (entities.get("J") or {}).get("ids") or []]
    params = ProblemIR(normalized_ir).parameters
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
    for key in ("distance", "service_cost", "coverage_matrix", "availability"):
        values = params.get(key)
        if n_i and n_j and isinstance(values, list) and values and isinstance(values[0], list):
            shape = (len(values), len(values[0]))
            if shape != (n_i, n_j):
                report(f"参数 {key} 的维度 {shape[0]}x{shape[1]} 与 |I|x|J|={n_i}x{n_j} 不符")

    values = params.get("facility_distance")
    if n_j and isinstance(values, list) and values and isinstance(values[0], list):
        shape = (len(values), len(values[0]))
        if shape != (n_j, n_j):
            report(
                f"参数 facility_distance 的维度 {shape[0]}x{shape[1]} 与 |J|x|J|={n_j}x{n_j} 不符"
            )

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
        parts = [f"骨架缺少模板要求的约束块 {', '.join(missing)}（来自族/模型 {', '.join(known)}）"]
        for bid in missing:
            candidates = _substitute_candidates(bid, optional, by_block, set(known))
            if candidates:
                parts.append(f"{bid} 可用同类别可选块 {'、'.join(candidates)} 替代")
        errors.append("；".join(parts))

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
