"""Query whole-model templates and composable constraint blocks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hamlet.core.tools import Tool

from core._defaults import BLOCKS_CATALOG_PATH, MODEL_BANK_PATH
from utils.search import parse_keywords, score_keywords, search_by_keywords

_DEFAULT_BANK_PATH = MODEL_BANK_PATH
_DEFAULT_BLOCKS_PATH = BLOCKS_CATALOG_PATH


def _search_models(
    bank: dict[str, Any], keyword_list: list[str], limit: int = 3
) -> list[dict[str, Any]]:
    """Search models by keywords, returning top matches ordered by score."""
    return search_by_keywords(
        bank.get("models", []),
        keyword_list,
        search_fields=["keywords"],
        limit=limit,
    )


def _search_blocks(
    blocks_bank: dict[str, Any], keyword_list: list[str], limit: int = 8
) -> list[dict[str, Any]]:
    """Search constraint blocks by keywords, returning top matches."""
    return search_by_keywords(
        blocks_bank.get("blocks", []),
        keyword_list,
        search_fields=["keywords", "id", "name", "category"],
        limit=limit,
    )


def _compact_model(
    m: dict[str, Any],
    blocks_bank: dict[str, Any],
    *,
    mb: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": m["id"],
        "name": m["name"],
        "description": m.get("description", ""),
    }
    # Preserve old-style fields if present (backward compat with tests)
    if "type" in m:
        out["type"] = m["type"]
    if "variables" in m:
        out["variables"] = m["variables"]
    if "objective" in m:
        out["objective"] = m["objective"]
    if "constraints" in m:
        out["constraints"] = m["constraints"]
    if "solver_hint" in m:
        out["solver_hint"] = m["solver_hint"]
    if "template_code" in m:
        out["template_code"] = m["template_code"]
    # New-style family / blocks fields
    if m.get("family"):
        out["family"] = m["family"]
    if m.get("is_family"):
        out["is_family"] = True
        out["base_blocks"] = m.get("base_blocks", [])
    if m.get("objective_block"):
        out["objective_block"] = m["objective_block"]
    if m.get("parameters"):
        out["parameters"] = m["parameters"]
    # Resolve effective blocks via family inheritance
    all_ids = list(m.get("blocks") or [])
    if family_name := m.get("family"):
        # Prefer the already-loaded bank; fall back to disk read (legacy).
        if mb is not None:
            by_model_id = {mo["id"]: mo for mo in mb.get("models", [])}
            family = by_model_id.get(family_name)
        else:
            from core.ir_catalog import load_model_bank  # pragma: no cover

            mb = load_model_bank()
            family = mb["by_id"].get(family_name)
        if family:
            base = family.get("base_blocks") or []
            for bid in reversed(base):
                if bid not in all_ids:
                    all_ids.insert(0, bid)
    if all_ids:
        out["blocks"] = all_ids
        by_id = {b["id"]: b for b in blocks_bank.get("blocks", [])}
        resolved = [by_id[bid] for bid in all_ids if bid in by_id]
        if resolved:
            out["block_details"] = [
                {
                    "id": b["id"],
                    "name": b["name"],
                    "category": b["category"],
                    "parameters": b.get("parameters", []),
                    "template_snippet": b.get("template_snippet", ""),
                }
                for b in resolved
            ]
    return out


def _compact_block(b: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": b["id"],
        "name": b["name"],
        "category": b["category"],
        "description": b["description"],
        "math": b.get("math", ""),
        "parameters": b.get("parameters", []),
        "template_snippet": b.get("template_snippet", ""),
    }


class QueryModelLibraryTool(Tool):
    """Search model templates and composable constraint/objective blocks."""

    name = "query_model_library"
    description = (
        "Search OR library: whole templates (keywords) and/or constraint blocks (block_keywords). "
        "Pass comma-separated strings, e.g. keywords='p-median, facility location' and "
        "block_keywords='cardinality, linking, forcing, p'."
    )
    inputs = {
        "keywords": {
            "type": "string",
            "description": "Template keywords, comma-separated string.",
        },
        "block_keywords": {
            "type": "string",
            "description": "Optional block keywords, comma-separated. Empty string if unused.",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(
        self,
        bank_path: str | Path | None = None,
        blocks_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        self._bank_path = Path(bank_path) if bank_path else _DEFAULT_BANK_PATH
        self._blocks_path = Path(blocks_path) if blocks_path else _DEFAULT_BLOCKS_PATH

    def forward(
        self,
        keywords: str | list[str],
        block_keywords: str | list[str] | None = "",
    ) -> str:
        with open(self._bank_path, encoding="utf-8") as f:
            bank = json.load(f)
        blocks_bank: dict[str, Any] = {"blocks": []}
        if self._blocks_path.is_file():
            with open(self._blocks_path, encoding="utf-8") as f:
                blocks_bank = json.load(f)

        template_kws = parse_keywords(keywords)
        block_kws = parse_keywords(block_keywords)
        payload: dict[str, Any] = {}

        if template_kws:
            models = _search_models(bank, template_kws)
            payload["templates"] = (
                [_compact_model(m, blocks_bank, mb=bank) for m in models] if models else []
            )

        if block_kws:
            blocks = _search_blocks(blocks_bank, block_kws)
            payload["blocks"] = [_compact_block(b) for b in blocks] if blocks else []

        if not template_kws and not block_kws:
            return json.dumps(
                {"message": "Provide keywords and/or block_keywords."}, ensure_ascii=False
            )

        if not payload.get("templates") and not payload.get("blocks"):
            return json.dumps(
                {"message": "No match.", "hint": "Compose from IR and custom code."},
                ensure_ascii=False,
            )

        payload["usage_hint"] = "Compose model from blocks; templates are references only."
        return json.dumps(payload, ensure_ascii=False, indent=2)
