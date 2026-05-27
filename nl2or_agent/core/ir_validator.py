"""IR validation: validate Problem IR against block catalog and model bank.

Pulled out of ir_processor.py to separate normalization from validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .ir_processor import load_block_catalog, load_model_bank, normalize_problem_ir


def validate_problem_ir(
    ir: dict[str, Any],
    *,
    blocks_path: Path | None = None,
    models_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and normalize IR; return report dict for tools / tests."""
    normalized, errors, warnings = normalize_problem_ir(
        ir, blocks_path=blocks_path, models_path=models_path,
    )
    catalog = load_block_catalog(blocks_path)
    # Check required parameters for each constraint block
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
