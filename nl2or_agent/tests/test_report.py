"""Strict report mapping: profile derivation from blocks and table rendering."""

from __future__ import annotations

import json

import pytest

from benchmarks.run_benchmark import _load_cases, _normalized_ir
from core.block_model import SolveResult, solve_ir
from core.report import (
    PROFILES,
    default_report_spec,
    render_report,
    resolve_report_profile,
)
from tools import SolveIrTool


@pytest.fixture(scope="module")
def cases() -> dict[str, dict]:
    return {case["id"]: case for case in _load_cases()}


@pytest.mark.parametrize(
    ("case_id", "profile"),
    [
        ("p_median_community", "location"),
        ("facility_location_logistics", "location"),
        ("set_covering_emergency", "set_covering"),
        ("maximum_covering_cities", "covering"),
        ("knapsack_gadget", "knapsack"),
        ("p_dispersion", "dispersion"),
        ("capacitated_p_center", "capacity"),
        ("cflp_cap61", "capacity"),
        ("capacitated_maximum_covering", "covering_capacity"),
    ],
)
def test_profile_is_derived_from_the_blocks(cases, case_id, profile):
    assert resolve_report_profile(_normalized_ir(cases[case_id])) == profile


def test_default_spec_lists_the_required_tables(cases):
    ir = _normalized_ir(cases["p_median_community"])
    spec = default_report_spec(ir)
    assert spec["profile"] == "location"
    assert spec["tables"] == list(PROFILES["location"])


def test_p_median_report_has_openings_assignments_and_objective(cases):
    ir = _normalized_ir(cases["p_median_community"])
    text = render_report(ir, solve_ir(ir))
    for heading in ("开设设施", "分配关系", "目标项"):
        assert heading in text
    assert "| B | 是 |" in text
    assert "2210" in text
    assert "**状态**" not in text
    assert "**目标值**" not in text


def test_set_covering_report_has_no_assignment_table(cases):
    ir = _normalized_ir(cases["set_covering_emergency"])
    text = render_report(ir, solve_ir(ir))
    assert "开设设施" in text
    assert "覆盖状态" not in text
    assert "分配关系" not in text


def test_knapsack_report_lists_selected_items(cases):
    ir = _normalized_ir(cases["knapsack_gadget"])
    text = render_report(ir, solve_ir(ir))
    assert "选中物品" in text
    assert "价值" in text
    assert "220" in text


def test_dispersion_report_shows_the_minimum_pair(cases):
    ir = _normalized_ir(cases["p_dispersion"])
    text = render_report(ir, solve_ir(ir))
    assert "最小设施间距" in text
    assert "B - D" in text


def test_capacity_report_adds_facility_load(cases):
    ir = _normalized_ir(cases["capacitated_p_center"])
    text = render_report(ir, solve_ir(ir))
    assert "设施负荷" in text
    assert "利用率" in text


def test_covering_capacity_report_has_coverage_and_load(cases):
    ir = _normalized_ir(cases["capacitated_maximum_covering"])
    text = render_report(ir, solve_ir(ir))
    assert "覆盖状态" in text
    assert "设施负荷" in text


def test_infeasible_report_does_not_invent_rows(cases):
    ir = _normalized_ir(cases["capacitated_p_center"])
    text = render_report(ir, SolveResult(objective=None, status="Infeasible"))
    assert "只保留目标项" in text
    assert "**目标值**：" not in text
    assert "设施负荷" not in text


def test_infeasible_solver_residual_is_not_reported(cases):
    ir = _normalized_ir(cases["p_median_community"])
    ir["parameters"]["p"] = 6
    result = solve_ir(ir)
    assert result.status == "Infeasible"
    text = render_report(ir, result)
    assert "**目标值**：" not in text
    assert "| — |" in text


def test_solve_ir_tool_appends_the_report(cases, tmp_path):
    case = cases["p_median_community"]
    tool = SolveIrTool(workspace_dir=tmp_path)
    output = tool.forward(json.dumps(case["input_ir"]), None)
    assert "[RESULT] Objective: 2210" in output
    assert "## 结果报表" in output
    assert "开设设施" in output
