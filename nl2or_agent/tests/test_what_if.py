"""Tests for the what-if flow: 单情景求解、结果渲染与本地 manual。

循环与对照表由 skill 层承担，因此这里只测原语：一份 IR 加一组覆盖，算一个解。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.block_model import (
    CONSTRAINT_BUILDERS,
    OBJECTIVE_BUILDERS,
    describe_model,
    format_solution,
    prepare_overrides,
    readable_keys,
    solve_ir,
    summarize_decisions,
)
from core.ir_validate import validate_problem_ir
from core.problem_ir import READABLE_DATA_KEYS, ProblemIR
from core.what_if import load_manual, manual_markdown, supported_models
from tools import SolveIrTool

_BASE = Path(__file__).parent.parent


def _model_ir(case_id: str) -> dict:
    from benchmarks.run_benchmark import _load_cases

    case = next(c for c in _load_cases() if c["id"] == case_id)
    return validate_problem_ir(dict(case["input_ir"]))["normalized_ir"]


def _solve(case_id: str, overrides: dict | None = None):
    return solve_ir(ProblemIR(_model_ir(case_id)).with_overrides(overrides).data)


# ---------------------------------------------------------------------------
# 结果渲染
# ---------------------------------------------------------------------------


class TestFormatSolution:
    def test_optimal_solution_carries_a_result_line(self):
        text = format_solution(_solve("p_median_community", {"p": 2}), {"p": 2})

        assert "[RESULT] Objective: 2400" in text
        assert "状态：最优" in text
        assert "应用的覆盖：p=2" in text

    def test_baseline_says_no_overrides(self):
        assert "应用的覆盖：无（基准）" in format_solution(_solve("p_median_community"), None)

    def test_infeasible_scenario_is_flagged_instead_of_numbered(self):
        text = format_solution(_solve("p_median_community", {"p": 6}), {"p": 6})

        assert "状态：不可行" in text
        assert "[RESULT]" not in text
        assert "不要为它编造目标值" in text


def test_summarize_decisions_groups_by_variable():
    text = summarize_decisions({"y[0]": 1.0, "y[2]": 1.0, "x2[0,0]": 1.0, "x2[1,2]": 1.0})

    assert "开设 [0, 2]" in text
    assert "分配 2 条" in text


def test_describe_model_reports_family_and_objective():
    text = describe_model(_model_ir("p_median_community"))

    assert "p_median" in text
    assert "weighted_service_distance_objective" in text


# ---------------------------------------------------------------------------
# 本地 manual（skill 层）
# ---------------------------------------------------------------------------


class TestManual:
    def test_loads_with_schema_version(self):
        manual = load_manual()

        assert manual["name"] == "what_if"
        assert manual["schema_version"] == 1

    def test_renders_the_procedure_and_derived_tables(self):
        text = manual_markdown()

        assert "何时使用" in text and "做法" in text and "边界" in text
        assert "可覆盖的键" in text
        assert "`p_median`" in text and "`capacitated_facility_location`" in text
        assert len(text) < 2500  # 附录进每次请求，保持紧凑

    def test_manual_parameter_keys_are_readable_by_the_block_model(self):
        """manual 的示例里出现的参数键必须都在 block_model 真正读取的键集合内。"""
        manual = load_manual()
        mentioned = {
            key
            for example in manual["examples"]
            for call in example["calls"]
            for key in re.findall(r'"([a-z_]+)":', call)
        }

        assert mentioned <= READABLE_DATA_KEYS

    def test_supported_models_are_executable(self):
        models = supported_models()

        assert {m["id"] for m in models} >= {"p_median", "facility_location", "knapsack"}
        for model in models:
            assert all(b in CONSTRAINT_BUILDERS for b in model["blocks"])
            assert model["objective"] in OBJECTIVE_BUILDERS


# ---------------------------------------------------------------------------
# 工具入口：一次调用算一个情景，不碰会话状态
# ---------------------------------------------------------------------------


class TestSolveIrTool:
    def test_solves_the_baseline_without_a_session(self):
        output = SolveIrTool().forward(_model_ir("p_median_community"))

        assert "[RESULT] Objective: 2210" in output
        assert "应用的覆盖：无（基准）" in output

    def test_applies_overrides_written_as_a_python_dict(self):
        """代码块里直接传 Python dict 是正常写法，不必先 json.dumps。"""
        tool = SolveIrTool()
        ir = _model_ir("p_median_community")

        assert "[RESULT] Objective: 2400" in tool.forward(ir, {"p": 2})
        assert "[RESULT] Objective: 2050" in tool.forward(ir, {"p": 4})

    def test_accepts_json_strings_for_both_arguments(self):
        ir = _model_ir("p_median_community")

        output = SolveIrTool().forward(json.dumps(ir), json.dumps({"p": 2}))

        assert "[RESULT] Objective: 2400" in output

    def test_matches_the_documented_capacity_sweep(self):
        tool = SolveIrTool()
        ir = _model_ir("knapsack_gadget")

        assert "[RESULT] Objective: 180" in tool.forward(ir, {"capacity": 40})
        assert "[RESULT] Objective: 280" in tool.forward(ir, {"capacity": 60})

    def test_reports_unparsable_json(self):
        assert "无法解析 ir_json" in SolveIrTool().forward("{not json")

    def test_reports_a_non_object_argument(self):
        assert "必须是一个对象" in SolveIrTool().forward(json.dumps([1, 2]))

    def test_reports_an_unsupported_override_key(self):
        output = SolveIrTool().forward(_model_ir("p_median_community"), {"nope": 1})

        assert "无法求解" in output
        assert "可覆盖的键" in output

    def test_reports_a_key_this_model_does_not_read(self):
        """别的模型读的键不能静默放过：p-median 上没有容量块。"""
        output = SolveIrTool().forward(_model_ir("p_median_community"), {"capacity": 10})

        assert "无法求解" in output
        assert "capacity" in output

    def test_reports_a_block_without_executable_semantics(self):
        """库外目标块要如实报错，agent 才能按 appendix 回退到 run_solver。"""
        ir = {
            "problem_families": [{"id": "p_median"}],
            "entities": {"I": {"size": 2}, "J": {"size": 2}},
            "parameters": {"p": 1, "distance": [[1, 2], [3, 4]]},
            "constraint_blocks": [{"block_id": "assign_each_demand_once"}],
            "objective": {"block_id": "not_in_the_catalog", "sense": "minimize"},
        }

        output = SolveIrTool().forward(ir)

        assert "无法求解" in output
        assert "没有可执行语义" in output

    def test_registered_on_the_agent(self, monkeypatch):
        monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o-mini")
        from agents import build_nl2or_agent

        agent = build_nl2or_agent(verbosity_level=0)

        assert "solve_ir" in agent.tools
        assert "what_if" not in agent.tools
        assert "Appendix: what_if" in agent.system_prompt
        assert "solve_ir" in agent.system_prompt


# ---------------------------------------------------------------------------
# 覆盖校验：键按模型取，值按维度查
# ---------------------------------------------------------------------------


class TestOverrideValidation:
    def test_readable_keys_follow_the_active_blocks(self):
        assert readable_keys(_model_ir("p_median_community")) == {"p", "distance", "demand"}

    def test_key_of_another_model_is_rejected(self):
        with pytest.raises(ValueError, match="capacity"):
            prepare_overrides(_model_ir("p_median_community"), {"capacity": 10})

    def test_wrong_list_length_is_rejected(self):
        with pytest.raises(ValueError, match="长度 3"):
            prepare_overrides(_model_ir("knapsack_gadget"), {"weight": [10, 20]})

    def test_matrix_shape_is_checked(self):
        with pytest.raises(ValueError, match="6x5"):
            prepare_overrides(_model_ir("p_median_community"), {"distance": [[1]]})

    def test_p_must_be_an_integer(self):
        with pytest.raises(ValueError, match="非负整数"):
            prepare_overrides(_model_ir("p_median_community"), {"p": 2.5})
