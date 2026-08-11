"""IR catalog: load model bank and constraint block catalog.

Provides shared data-loading functions used by normalizer, validator,
prompt-loader, and the model-library tool.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._defaults import BLOCKS_CATALOG_PATH as _BLOCKS_PATH
from ._defaults import MODEL_BANK_PATH as _MODELS_PATH

_SUPPORTED_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Model bank
# ---------------------------------------------------------------------------


def load_model_bank(models_path: Path | None = None) -> dict[str, Any]:
    """Load models.json and build a family-resolution index."""
    path = models_path or _MODELS_PATH
    with open(path, encoding="utf-8") as f:
        bank = json.load(f)
    _assert_schema_version(bank, path)
    models = bank.get("models", [])
    by_id = {m["id"]: m for m in models}

    effective_blocks: dict[str, list[str]] = {}
    for m in models:
        if m.get("is_family"):
            continue
        family_name = m.get("family")
        blocks = list(m.get("blocks") or [])
        if family_name and family_name in by_id:
            family = by_id[family_name]
            base = family.get("base_blocks") or []
            for b in reversed(base):
                if b not in blocks:
                    blocks.insert(0, b)
        effective_blocks[m["id"]] = blocks

    bank["by_id"] = by_id
    bank["effective_blocks"] = effective_blocks
    return bank


# ---------------------------------------------------------------------------
# Block catalog
# ---------------------------------------------------------------------------


def load_block_catalog(blocks_path: Path | None = None) -> dict[str, Any]:
    """Load constraint_blocks.json and build lookup indices."""
    path = blocks_path or _BLOCKS_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _assert_schema_version(data, path)
    blocks = data.get("blocks", [])
    by_id = {b["id"]: b for b in blocks}
    alias_to_id: dict[str, str] = {}
    for block in blocks:
        for alias in block.get("aliases", []):
            alias_to_id[str(alias).strip().lower()] = block["id"]
    return {
        "blocks": blocks,
        "by_id": by_id,
        "alias_to_id": alias_to_id,
        "block_ids": sorted(by_id.keys()),
        "objective_block_ids": sorted(b["id"] for b in blocks if b.get("category") == "objective"),
    }


def _assert_schema_version(data: dict[str, Any], path: Path) -> None:
    version = data.get("schema_version", 0)
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"{path.name} schema_version={version}, expected {_SUPPORTED_SCHEMA_VERSION}. "
            "Please update the data file or the loader."
        )


def catalog_markdown(blocks_path: Path | None = None) -> str:
    """Compact block id list for prompts."""
    catalog = load_block_catalog(blocks_path)
    lines = ["| block_id | category | 必填参数 |", "|----------|----------|----------|"]
    for bid in catalog["block_ids"]:
        b = catalog["by_id"][bid]
        req = ", ".join(p["name"] for p in b.get("parameters", []) if p.get("required")) or "—"
        lines.append(f"| `{bid}` | {b.get('category', '')} | {req} |")
    return "\n".join(lines)
