"""Tests for Problem IR normalization and block catalog alignment."""

from __future__ import annotations

import json

from core.ir_normalizer import normalize_problem_ir
from core.ir_normalizer import validate_problem_ir
from tools import ListBlockCatalogTool, ValidateProblemIrTool


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
