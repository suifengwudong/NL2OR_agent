"""Executable-model census for the bank: which models solve_ir can run.

No solving logic and no prompt appendix live here. The what-if procedure
(baseline once, one call per override set, tabulate the `[RESULT]` lines) is
stated in the system prompt; key and shape rules are enforced by ``solve_ir``
itself and reported in its errors. ``supported_models`` stays as the
library-derived census used by tests and benchmarks.
"""

from __future__ import annotations

from typing import Any

from .block_model import CONSTRAINT_BUILDERS, OBJECTIVE_BUILDERS
from .ir_catalog import load_model_bank


def supported_models() -> list[dict[str, Any]]:
    """Models whose blocks all have executable semantics (driven by the library)."""
    bank = load_model_bank()
    out: list[dict[str, Any]] = []
    for model_id, model in sorted(bank["by_id"].items()):
        if model.get("is_family"):
            continue
        blocks = list(bank.get("effective_blocks", {}).get(model_id, []))
        objective = model.get("objective_block")
        if any(b not in CONSTRAINT_BUILDERS for b in blocks):
            continue
        if objective not in OBJECTIVE_BUILDERS:
            continue
        out.append({"id": model_id, "blocks": blocks, "objective": objective})
    return out


__all__ = ["supported_models"]
