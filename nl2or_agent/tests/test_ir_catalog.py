"""Tests for the IR catalog loaders: 索引构建与基于文件状态的缓存。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.ir_catalog import load_block_catalog, load_model_bank


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_model_bank_builds_family_indices(tmp_path: Path):
    bank = _write(
        tmp_path / "models.json",
        {
            "schema_version": 1,
            "models": [
                {"id": "location_problem", "is_family": True, "base_blocks": ["assign"]},
                {"id": "p_median", "family": "location_problem", "blocks": ["cardinality"]},
            ],
        },
    )

    loaded = load_model_bank(bank)

    assert set(loaded["by_id"]) == {"location_problem", "p_median"}
    assert loaded["effective_blocks"]["p_median"] == ["assign", "cardinality"]


def test_block_catalog_builds_lookup_indices(tmp_path: Path):
    catalog = _write(
        tmp_path / "constraint_blocks.json",
        {
            "schema_version": 1,
            "blocks": [
                {
                    "id": "assign_each_demand_once",
                    "category": "assignment",
                    "aliases": ["Assignment"],
                },
                {
                    "id": "minimize_max_distance_objective",
                    "category": "objective",
                    "sense": "minimize",
                },
            ],
        },
    )

    loaded = load_block_catalog(catalog)

    assert loaded["block_ids"] == ["assign_each_demand_once", "minimize_max_distance_objective"]
    assert loaded["alias_to_id"]["assignment"] == "assign_each_demand_once"
    assert loaded["objective_block_ids"] == ["minimize_max_distance_objective"]
    assert loaded["objective_sense"] == {"minimize_max_distance_objective": "minimize"}


def test_repeated_loads_are_equal_but_independent(tmp_path: Path):
    """缓存命中时也必须交出独立副本，否则一个调用方的改动会污染别人。"""
    bank = _write(tmp_path / "models.json", {"schema_version": 1, "models": [{"id": "m"}]})

    first = load_model_bank(bank)
    second = load_model_bank(bank)
    first["models"].append({"id": "injected"})

    assert "injected" not in second["models"]
    assert second["by_id"] == {"m": {"id": "m"}}


def test_editing_the_file_invalidates_the_cache(tmp_path: Path):
    bank = _write(tmp_path / "models.json", {"schema_version": 1, "models": [{"id": "first"}]})
    assert "first" in load_model_bank(bank)["by_id"]

    _write(bank, {"schema_version": 1, "models": [{"id": "second_longer"}]})

    assert "second_longer" in load_model_bank(bank)["by_id"]


def test_rejects_an_unsupported_schema_version(tmp_path: Path):
    bank = _write(tmp_path / "models.json", {"schema_version": 99, "models": []})

    with pytest.raises(ValueError, match="schema_version"):
        load_model_bank(bank)
