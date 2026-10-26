"""Tests for Problem IR normalization and block catalog alignment."""

from __future__ import annotations

import json
from pathlib import Path

from core.ir_catalog import load_block_catalog, load_model_bank
from core.ir_normalize import normalize_problem_ir
from core.ir_validate import validate_problem_ir
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
            assert data.get("schema_version") == 2, f"{name} missing or incorrect schema_version"

    def test_objective_blocks_declare_sense(self):
        _, catalog = self._load_both()
        for b in catalog.get("blocks", []):
            if b.get("category") != "objective":
                continue
            assert b.get("sense") in {"minimize", "maximize"}, (
                f"Objective block {b['id']} must declare sense"
            )

    def test_requires_one_of_references_existing_blocks(self):
        _, catalog = self._load_both()
        block_ids = set(catalog["block_ids"])
        for b in catalog.get("blocks", []):
            for ref in b.get("requires_one_of") or []:
                assert ref in block_ids, f"Block {b['id']} requires unknown block '{ref}'"


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
        assert "skeleton" in out

    def test_list_block_catalog(self):
        tool = ListBlockCatalogTool()
        data = json.loads(tool.forward())
        assert "assign_each_demand_once" in data["block_ids"]
        assert data["objective_sense"]["covered_demand_objective"] == "maximize"


# ---------------------------------------------------------------------------
# Objective handling: 目标函数是骨架的一部分，不做静默替换
# ---------------------------------------------------------------------------


class TestObjectiveSkeleton:
    def test_unknown_objective_kept_and_warned(self):
        report = validate_problem_ir({"objective": {"block_id": "weighted_sum_objective"}})
        assert report["valid"]
        assert report["normalized_ir"]["objective"]["block_id"] == "weighted_sum_objective"
        assert report["skeleton"]["objective_in_catalog"] is False
        assert any("不在库中" in w for w in report["warnings"])

    def test_missing_objective_warns_instead_of_defaulting(self):
        report = validate_problem_ir(
            {
                "constraint_blocks": [
                    {"block_id": "knapsack_capacity", "parameters": {"capacity": 5}}
                ]
            }
        )
        assert report["valid"]
        assert report["normalized_ir"]["objective"]["block_id"] == ""
        assert report["normalized_ir"]["objective"]["sense"] == ""
        assert any("未声明目标函数" in w for w in report["warnings"])

    def test_sense_inherited_from_catalog(self):
        report = validate_problem_ir({"objective": {"block_id": "knapsack_objective"}})
        assert report["normalized_ir"]["objective"]["block_id"] == "total_value_objective"
        assert report["normalized_ir"]["objective"]["sense"] == "maximize"

    def test_sense_contradiction_is_error(self):
        report = validate_problem_ir(
            {"objective": {"block_id": "covered_demand_objective", "sense": "minimize"}}
        )
        assert not report["valid"]
        assert any("优化方向" in e for e in report["errors"])

    def test_sense_alias_normalized(self):
        report = validate_problem_ir(
            {"objective": {"block_id": "weighted_service_distance_objective", "sense": "MIN"}}
        )
        assert report["normalized_ir"]["objective"]["sense"] == "minimize"

    def test_constraint_block_rejected_as_objective(self):
        report = validate_problem_ir({"objective": {"block_id": "assignment"}})
        assert not report["valid"]
        assert any("不是目标块" in e for e in report["errors"])

    def test_unbound_required_params_reported(self):
        report = validate_problem_ir(
            {"objective": {"block_id": "weighted_service_distance_objective"}}
        )
        assert report["skeleton"]["unbound_objective_params"] == ["distance"]

    def test_objective_params_satisfy_binding(self):
        report = validate_problem_ir(
            {
                "objective": {
                    "block_id": "weighted_service_distance_objective",
                    "parameters": {"distance": "由距离矩阵给定"},
                }
            }
        )
        assert report["skeleton"]["unbound_objective_params"] == []


# ---------------------------------------------------------------------------
# Skeleton checks: 约束集是否构成完整模型
# ---------------------------------------------------------------------------


class TestSkeletonChecks:
    def _ir(
        self, blocks: list[str], family: str = "p_median", objective: str = "weighted_distance"
    ):
        return {
            "problem_families": [{"id": family}],
            "constraint_blocks": [{"block_id": b, "parameters": {"p": 2}} for b in blocks],
            "objective": {"block_id": objective, "parameters": {"distance": "给定"}},
        }

    def test_missing_template_block_is_error(self):
        report = validate_problem_ir(self._ir(["assignment", "cardinality"]))
        assert not report["valid"]
        assert report["skeleton"]["missing_required_blocks"] == ["link_assignment_to_open"]
        assert any("骨架缺少" in e for e in report["errors"])

    def test_complete_template_passes(self):
        report = validate_problem_ir(self._ir(["assignment", "linking", "cardinality"]))
        assert report["valid"]
        assert report["skeleton"]["missing_required_blocks"] == []

    def test_same_category_optional_block_substitutes(self):
        report = validate_problem_ir(
            {
                "problem_families": [{"id": "maximum_covering"}],
                "constraint_blocks": [
                    {
                        "block_id": "demand_coverage_activation",
                        "parameters": {"coverage_matrix": "给定"},
                    },
                    {"block_id": "cardinality_open_at_most_p_facilities", "parameters": {"p": 2}},
                ],
                "objective": {
                    "block_id": "covered_demand_objective",
                    "parameters": {"demand": "给定"},
                },
            }
        )
        assert report["valid"]
        assert report["skeleton"]["substituted_blocks"] == ["cardinality_open_p_facilities"]
        assert any("同类别可选块" in w for w in report["warnings"])

    def test_requires_one_of_violation_is_error(self):
        report = validate_problem_ir(
            {
                "constraint_blocks": [
                    {
                        "block_id": "demand_coverage_activation",
                        "parameters": {"coverage_matrix": "给定"},
                    }
                ]
            }
        )
        assert not report["valid"]
        assert any("需要同时使用" in e for e in report["errors"])

    def test_block_from_other_family_warns(self):
        report = validate_problem_ir(self._ir(["assignment", "linking", "coverage_activation"]))
        assert report["skeleton"]["inconsistent_blocks"] == ["demand_coverage_activation"]

    def test_unknown_family_skips_template_check(self):
        report = validate_problem_ir(
            {
                "problem_families": [{"id": "vehicle_routing"}],
                "objective": {
                    "block_id": "weighted_service_distance_objective",
                    "parameters": {"distance": "给定"},
                },
            }
        )
        assert report["valid"]
        assert report["skeleton"]["unknown_models"] == ["vehicle_routing"]
        assert any("不在模型库中" in w for w in report["warnings"])

    def test_objective_mismatch_with_family_warns(self):
        report = validate_problem_ir(
            self._ir(["assignment", "linking", "cardinality"], objective="covered_demand_objective")
        )
        assert any("与声明的族/模型不一致" in w for w in report["warnings"])


# ---------------------------------------------------------------------------
# Index-set / data-dimension checks
# ---------------------------------------------------------------------------


class TestEntityChecks:
    _DISTANCE = [
        [4, 6, 9, 7, 8],
        [5, 3, 8, 6, 7],
        [9, 7, 4, 5, 6],
        [8, 6, 5, 3, 4],
        [6, 5, 7, 4, 3],
        [7, 8, 6, 5, 4],
    ]

    def _ir(self, entities, parameters):
        return {
            "entities": entities,
            "parameters": parameters,
            "objective": {
                "block_id": "weighted_service_distance_objective",
                "parameters": {"distance": "给定"},
            },
        }

    def test_dimension_mismatch_is_error(self):
        report = validate_problem_ir(
            self._ir(
                {"I": {"size": 6}, "J": {"size": 4}},
                {"p": 2, "distance": self._DISTANCE},
            )
        )
        assert not report["valid"]
        assert any("维度" in e for e in report["errors"])

    def test_p_exceeding_facility_count_is_error(self):
        report = validate_problem_ir(
            self._ir(
                {"I": {"size": 6}, "J": {"size": 5}},
                {"p": 6, "distance": self._DISTANCE},
            )
        )
        assert not report["valid"]
        assert any("超过候选设施数" in e for e in report["errors"])

    def test_forced_facility_outside_j_is_error(self):
        report = validate_problem_ir(
            self._ir(
                {"I": {"size": 6}, "J": {"size": 5, "ids": ["A", "B", "C", "D", "E"]}},
                {"p": 2, "distance": self._DISTANCE, "forced_open": ["Z"]},
            )
        )
        assert not report["valid"]
        assert any("不在设施集合 J 中" in e for e in report["errors"])

    def test_unread_parameter_is_flagged(self):
        report = validate_problem_ir(
            {
                "entities": {"I": {"size": 2}, "J": {"size": 2}},
                "parameters": {
                    "p": 1,
                    "distance": [[1, 2], [2, 1]],
                    "weight": [10, 20],
                },
                "constraint_blocks": [
                    {"block_id": "assign_each_demand_once"},
                    {"block_id": "link_assignment_to_open"},
                    {"block_id": "cardinality_open_p_facilities"},
                ],
                "objective": {
                    "block_id": "weighted_service_distance_objective",
                    "parameters": {"distance": "给定"},
                },
            }
        )
        assert report["valid"]
        assert any("weight" in warning for warning in report["warnings"])

    def test_checks_skipped_without_entities(self):
        report = validate_problem_ir(self._ir({}, {"p": 2, "distance": self._DISTANCE}))
        assert report["valid"]
        assert report["skeleton"]["entities"]["problems"] == []

    def test_data_may_live_in_block_parameters(self):
        ir = {
            "entities": {"I": {"size": 6}, "J": {"size": 5}},
            "constraint_blocks": [
                {
                    "block_id": "force_facility_open",
                    "parameters": {"forced_open": ["A"]},
                    "status": "required",
                }
            ],
            "objective": {
                "block_id": "weighted_service_distance_objective",
                "parameters": {"distance": "给定"},
            },
        }
        report = validate_problem_ir(ir)
        assert report["valid"]
        assert report["skeleton"]["entities"]["problems"] == []
