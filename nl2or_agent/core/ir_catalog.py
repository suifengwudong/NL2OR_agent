"""IR catalog: load model bank and constraint block catalog.

Both loaders read a file once per (path, mtime, size). The data files are static,
but the system prompt is assembled on every turn, so re-parsing them per call is
pure waste; keying the cache on the file stamp keeps edits on disk visible.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ._defaults import BLOCKS_CATALOG_PATH as _BLOCKS_PATH
from ._defaults import MODEL_BANK_PATH as _MODELS_PATH

_SUPPORTED_SCHEMA_VERSION = 1
_CACHE_SIZE = 8


def _stamp(path: Path) -> tuple[str, int, int]:
    """Cache key for *path*: name plus mtime and size."""
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


# ---------------------------------------------------------------------------
# Model bank
# ---------------------------------------------------------------------------


@lru_cache(maxsize=_CACHE_SIZE)
def _model_bank_at(path_str: str, _mtime_ns: int, _size: int) -> dict[str, Any]:
    path = Path(path_str)
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
            base = by_id[family_name].get("base_blocks") or []
            for b in reversed(base):
                if b not in blocks:
                    blocks.insert(0, b)
        effective_blocks[m["id"]] = blocks

    bank["by_id"] = by_id
    bank["effective_blocks"] = effective_blocks
    return bank


def load_model_bank(models_path: Path | None = None) -> dict[str, Any]:
    """Load models.json and build a family-resolution index.

    Returns a fresh copy, so callers may modify what they get without poisoning
    the cache.
    """
    path = Path(models_path or _MODELS_PATH)
    return copy.deepcopy(_model_bank_at(*_stamp(path)))


# ---------------------------------------------------------------------------
# Block catalog
# ---------------------------------------------------------------------------


@lru_cache(maxsize=_CACHE_SIZE)
def _block_catalog_at(path_str: str, _mtime_ns: int, _size: int) -> dict[str, Any]:
    path = Path(path_str)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _assert_schema_version(data, path)
    blocks = data.get("blocks", [])
    by_id = {b["id"]: b for b in blocks}
    alias_to_id: dict[str, str] = {}
    for block in blocks:
        for alias in block.get("aliases", []):
            alias_to_id[str(alias).strip().lower()] = block["id"]
    objective_blocks = [b for b in blocks if b.get("category") == "objective"]
    return {
        "blocks": blocks,
        "by_id": by_id,
        "alias_to_id": alias_to_id,
        "block_ids": sorted(by_id.keys()),
        "objective_block_ids": sorted(b["id"] for b in objective_blocks),
        # 目标块的优化方向（minimize / maximize）；缺失时按未声明处理
        "objective_sense": {b["id"]: b["sense"] for b in objective_blocks if b.get("sense")},
    }


def load_block_catalog(blocks_path: Path | None = None) -> dict[str, Any]:
    """Load constraint_blocks.json and build lookup indices.

    Returns a fresh copy, so callers may modify what they get without poisoning
    the cache.
    """
    path = Path(blocks_path or _BLOCKS_PATH)
    return copy.deepcopy(_block_catalog_at(*_stamp(path)))


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
