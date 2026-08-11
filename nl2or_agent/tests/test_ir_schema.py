"""Tests for Problem IR normalization and block catalog alignment."""

from __future__ import annotations

import json
from pathlib import Path

from core.ir_catalog import load_block_catalog, load_model_bank
from core.ir_normalizer import normalize_problem_ir
from core.ir_normalizer import validate_problem_ir
from tools import ListBlockCatalogTool, ValidateProblemIrTool

_BASE = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Cross-file integrity
# ---------------------------------------------------------------------------


class TestDataIntegrity:
    """Verify cross-references between models.json and constraint_blocks.json."""

    def _load_both(self):
        bank = load_model_bank()
        catalog = load_block_catalog()
        return bank, catalog

    def test_all_model_blocks_exist_in_catalog(self):
        bank, catalog = self._load_both()
        block_ids = set(catalog["block_ids"])
        for m in bank.get("models", []):
            for bid in m.get("blocks") or []:
                assert bid in block_ids, f"Model {m['id']} references unknown block '{bid}'"

    def test_all_model_objective_blocks_exist(self):
        bank, catalog = self._load_both()
        obj_ids = set(catalog["objective_block_ids"])
        for m in bank.get("models", []):
            ob = m.get("objective_block")
            if ob:
                assert ob in obj_ids, f"Model {m['id']} references unknown objective_block '{ob}'"

    def test_all_family_base_blocks_exist(self):
        bank, catalog = self._load_both()
        block_ids = set(catalog["block_ids"])
        for m in bank.get("models", []):
            if not m.get("is_family"):
                continue
            for bid in m.get("base_blocks") or []:
                assert bid in block_ids, f"Family {m['id']} references unknown base_block '{bid}'"

    def test_all_typical_models_exist(self):
        _, catalog = self._load_both()
        model_ids = {m["id"] for m in load_model_bank().get("models", [])}
        for b in catalog.get("blocks", []):
            for tm in b.get("typical_models") or []:
                assert tm in model_ids, f"Block {b['id']} references unknown model '{tm}'"

    def test_all_aliases_resolve(self):
        _, catalog = self._load_both()
        alias_to_id = catalog["alias_to_id"]
        for alias, resolved in alias_to_id.items():
            assert resolved in catalog["by_id"], (
                f"Alias '{alias}' resolves to unknown block '{resolved}'"
            )

    def test_schema_version_present(self):
        for name in ("models.json", "constraint_blocks.json"):
            path = _BASE / "data" / "model_bank" / name
            with open(path) as f:
                data = json.load(f)
            assert data.get("schema_version") == 1, f"{name} missing or incorrect schema_version"


class TestNormalizeProblemIr:
    def test_alias_block_ids_normalized(self):
        ir = {
            "problem_families": [{"id": "p-median", "confidence": 0.9}],
            "parameters": {"p": 3},
            "constraint_blocks": [
                {"block_id": "assignment", "parameters": {}, "status": "required"},
                {"block_id": "linking", "parameters": {}, "status": "required"},
                {"block_id": "cardinality_open_p_facilities", "parameters": {"p": 3}},
            ],
            "objective": "minimize_total_weighted_distance",
        }
        normalized, errors, warnings = normalize_problem_ir(ir)
        ids = [b["block_id"] for b in normalized["constraint_blocks"]]
        assert "assign_each_demand_once" in ids
        assert "link_assignment_to_open" in ids
        assert normalized["objective"]["block_id"] == "weighted_service_distance_objective"
        assert any("assignment" in w for w in warnings)

    def test_custom_constraints_not_in_blocks(self):
        ir = {
            "constraint_blocks": [
                {"block_id": "custom_constraints", "parameters": {"x": 1}},
            ],
        }
        _, errors, _ = normalize_problem_ir(ir)
        assert any("custom_constraints" in e for e in errors)

    def test_forcing_open_parameter_alias(self):
        ir = {
            "constraint_blocks": [
                {
                    "block_id": "forcing",
                    "parameters": {"facility_ids": ["B"]},
                    "status": "required",
                },
            ],
        }
        normalized, errors, warnings = normalize_problem_ir(ir)
        assert not errors
        block = normalized["constraint_blocks"][0]
        assert block["block_id"] == "force_facility_open"
        assert block["parameters"]["forced_open"] == ["B"]

    def test_hybrid_emergency_problem(self):
        ir = {
            "problem_families": [
                {"name": "facility_location", "confidence": 0.9},
                {"name": "p-median", "confidence": 0.8},
            ],
            "parameters": {"p": 2},
            "constraint_blocks": [
                {"block_id": "cardinality_open_p_facilities", "parameters": {"p": 2}},
                {"block_id": "assignment", "parameters": {}},
                {"block_id": "linking", "parameters": {}},
                {"block_id": "forcing", "parameters": {"facility_ids": [1]}},
                {"block_id": "prohibiting", "parameters": {"facility_ids": [3]}},
            ],
            "custom_constraints": ["灾区3与灾区5由同一分发点服务"],
        }
        report = validate_problem_ir(ir)
        assert report["valid"]
        n = report["normalized_ir"]
        assert n["is_hybrid"] is True
        ids = {b["block_id"] for b in n["constraint_blocks"]}
        assert "force_facility_open" in ids
        assert "force_facility_closed" in ids
        assert len(n["custom_constraints"]) == 1


class TestIrTools:
    def test_validate_tool_json_string(self):
        tool = ValidateProblemIrTool()
        ir = {
            "constraint_blocks": [
                {"block_id": "cardinality_open_p_facilities", "parameters": {"p": 2}},
            ],
            "objective": {"block_id": "weighted_service_distance_objective"},
        }
        out = json.loads(tool.forward(json.dumps(ir)))
        assert out["valid"]
        assert "normalized_ir" in out

    def test_list_block_catalog(self):
        tool = ListBlockCatalogTool()
        data = json.loads(tool.forward())
        assert "assign_each_demand_once" in data["block_ids"]
