"""The IR must be renderable as one mathematical model with LaTeX formulas."""

from __future__ import annotations

import json

import pytest

from benchmarks.run_benchmark import _load_cases, _normalized_ir
from core.ir_validate import validate_problem_ir
from core.model_document import render_model_document
from tools import ModelMathTool


@pytest.fixture(scope="module")
def cases() -> dict[str, dict]:
    return {case["id"]: case for case in _load_cases()}


def _document(case_id: str, cases: dict[str, dict]) -> str:
    return render_model_document(_normalized_ir(cases[case_id]))


def test_p_median_document_has_sets_variables_and_all_blocks(cases):
    document = _document("p_median_community", cases)

    assert document.startswith("## 数学模型")
    assert "$|I| = 6$" in document
    assert "$|J| = 5$" in document
    assert "$x_{ij} \\in \\{0,1\\}$" in document
    assert "\\min \\sum" in document
    assert document.index("**符号说明**") < document.index("**目标函数")
    assert "$h_i$：需求点 i 的需求量或权重" in document
    assert "$d_{ij}$：" in document
    assert "每个需求点 i 恰好分配给一个设施" in document
    for block_id in (
        "assign_each_demand_once",
        "link_assignment_to_open",
        "cardinality_open_p_facilities",
    ):
        assert block_id not in document
    assert "weighted_service_distance_objective" not in document
    assert document.count("$$") % 2 == 0


def test_dispersion_document_uses_the_big_m_form(cases):
    document = _document("p_dispersion", cases)

    assert "$D \\ge 0$" in document
    assert "D \\leq d_{jk} + M" in document
    assert "min_pairwise_distance_bound" not in document


def test_weighted_objective_defines_default_demand_symbol(cases):
    ir = _normalized_ir(cases["p_median_community"])
    ir["parameters"].pop("demand", None)
    document = render_model_document(ir)
    assert "$h_i$：" in document
    assert "默认 1" in document


def test_covering_objective_defines_demand_as_weight(cases):
    ir = _normalized_ir(cases["maximum_covering_cities"])
    document = render_model_document(ir)
    assert "$h_i$：" in document
    assert "$d_i$：" not in document

    ir["parameters"].pop("demand", None)
    document = render_model_document(ir)
    assert "$h_i$：" in document
    assert "默认 1" in document


def test_capacitated_covering_defines_both_demand_symbols(cases):
    document = _document("capacitated_maximum_covering", cases)
    assert "$d_i$：" in document
    assert "$h_i = d_i$：" in document


def test_objective_headings_do_not_repeat_the_sense(cases):
    for case_id in (
        "maximum_covering_cities",
        "p_center_emergency",
        "p_dispersion",
        "cappmed_1",
    ):
        document = _document(case_id, cases)
        heading = next(line for line in document.splitlines() if line.startswith("**目标函数："))
        name = heading.removeprefix("**目标函数：").removesuffix("**")
        assert "最小化最小化" not in name
        assert "最大化最大化" not in name
        assert "目标" not in name


def test_all_valid_documents_hide_catalog_ids(cases):
    from core.ir_catalog import load_block_catalog

    catalog = load_block_catalog()
    catalog_ids = set(catalog["block_ids"]) | set(catalog["objective_block_ids"])
    for case in cases.values():
        report = validate_problem_ir(dict(case["input_ir"]))
        if not report["valid"]:
            continue
        document = render_model_document(report["normalized_ir"])
        leaked = sorted(catalog_id for catalog_id in catalog_ids if catalog_id in document)
        assert not leaked, (case["id"], leaked)


def test_knapsack_document_derives_its_variable_without_a_model_entry(cases):
    document = _document("knapsack_gadget", cases)

    assert "$x_i \\in \\{0,1\\}$" in document
    assert "\\max \\sum" in document
    assert "knapsack_capacity" not in document


def test_parameter_symbols_come_from_the_model_bank(cases):
    capacity_document = _document("capacitated_p_center", cases)
    budget_document = _document("budgeted_facility_location", cases)

    assert "$Q_j$：" in capacity_document
    assert "$B$：" in budget_document


def test_out_of_catalog_objective_falls_back_to_its_expression():
    ir = {
        "entities": {"I": {"size": 2}, "J": {"size": 2}},
        "parameters": {"p": 1, "distance": [[1, 2], [2, 1]]},
        "constraint_blocks": [{"block_id": "assign_each_demand_once"}],
        "objective": {
            "block_id": "weighted_sum_objective",
            "sense": "minimize",
            "expression": "minimize sum of weighted distances",
        },
    }
    document = render_model_document(ir)
    assert "库外目标" in document
    assert "minimize sum of weighted distances" in document


def test_model_math_tool_returns_the_document(cases):
    case = cases["p_median_community"]
    tool = ModelMathTool()
    document = tool.forward(json.dumps(case["input_ir"]))
    assert "## 数学模型" in document
    assert "cardinality_open_p_facilities" not in document


def test_model_math_tool_marks_invalid_ir(cases):
    ir = _normalized_ir(cases["p_median_community"])
    ir["constraint_blocks"] = [
        block for block in ir["constraint_blocks"] if block["block_id"] != "link_assignment_to_open"
    ]

    document = ModelMathTool().forward(json.dumps(ir))

    assert document.startswith("校验未通过")
    assert "每个需求点 i 恰好分配给一个设施" in document


def test_model_math_tool_reports_bad_json():
    output = ModelMathTool().forward("{not json")
    assert output.startswith("无法生成数学模型")


def test_every_case_is_renderable(cases):
    for case in cases.values():
        report = validate_problem_ir(dict(case["input_ir"]))
        document = render_model_document(report["normalized_ir"])
        assert document.startswith("## 数学模型")
        assert document.count("$$") % 2 == 0
