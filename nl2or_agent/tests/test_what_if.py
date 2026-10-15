"""Tests for what-if analysis: 参数情景对比、本地 manual 与工具入口。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.references.block_model import READABLE_DATA_KEYS
from core.ir_normalizer import validate_problem_ir
from core.what_if import (
    apply_overrides,
    describe_model,
    load_manual,
    manual_markdown,
    render_comparison,
    run_scenarios,
    supported_models,
)
from tools import WhatIfTool

_BASE = Path(__file__).parent.parent


def _model_ir(case_id: str) -> dict:
    from benchmarks.run_benchmark import _load_cases

    case = next(c for c in _load_cases() if c["id"] == case_id)
    return validate_problem_ir(dict(case["input_ir"]))["normalized_ir"]


# ---------------------------------------------------------------------------
# 覆盖
# ---------------------------------------------------------------------------


class TestApplyOverrides:
    def test_sets_a_top_level_parameter(self):
        ir = {"parameters": {"p": 3}}
        out = apply_overrides(ir, [{"path": "parameters.p", "value": 4}])

        assert out["parameters"]["p"] == 4
        assert ir["parameters"]["p"] == 3  # 原模型不被改动

    def test_rejects_unsupported_path(self):
        with pytest.raises(ValueError, match="只支持 parameters"):
            apply_overrides({}, [{"path": "constraint_blocks.0.block_id", "value": "x"}])

    def test_rejects_unknown_parameter(self):
        with pytest.raises(ValueError, match="可覆盖的键"):
            apply_overrides({}, [{"path": "parameters.not_a_key", "value": 1}])

    def test_rejects_missing_value(self):
        with pytest.raises(ValueError, match="缺少 value"):
            apply_overrides({}, [{"path": "parameters.p"}])

    def test_every_readable_key_is_accepted(self):
        overrides = [{"path": f"parameters.{key}", "value": 1} for key in READABLE_DATA_KEYS]
        out = apply_overrides({}, overrides)

        assert set(out["parameters"]) == set(READABLE_DATA_KEYS)


# ---------------------------------------------------------------------------
# 情景对比
# ---------------------------------------------------------------------------


class TestRunScenarios:
    def test_baseline_row_comes_first(self):
        result = run_scenarios(_model_ir("p_median_community"), [])

        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["id"] == "(基准)"
        assert row["objective"] == 2210.0
        assert row["delta"] == 0

    @pytest.mark.parametrize(
        ("p", "objective", "delta"),
        [(1, 2840.0, 630.0), (2, 2400.0, 190.0), (4, 2050.0, -160.0), (5, 1960.0, -250.0)],
    )
    def test_facility_count_sweep(self, p: int, objective: float, delta: float):
        result = run_scenarios(
            _model_ir("p_median_community"),
            [{"id": f"p={p}", "overrides": [{"path": "parameters.p", "value": p}]}],
        )

        row = result["rows"][1]
        assert row["objective"] == objective
        assert row["delta"] == delta
        assert "开设" in row["decisions"]

    @pytest.mark.parametrize(
        ("forced", "objective"), [([], 2210.0), (["D"], 2220.0), (["A", "D"], 2240.0)]
    )
    def test_forcing_scenario_needs_the_block(self, forced: list, objective: float):
        """基准模型已含 forcing 块，覆盖 forced_open 才生效。"""
        result = run_scenarios(
            _model_ir("p_median_force_open"),
            [{"id": "forced", "overrides": [{"path": "parameters.forced_open", "value": forced}]}],
        )

        assert result["rows"][1]["objective"] == objective

    def test_forcing_parameter_is_inert_without_the_block(self):
        """基准模型没有 forcing 块时，覆盖 forced_open 不改变结论。"""
        result = run_scenarios(
            _model_ir("p_median_community"),
            [{"id": "forced", "overrides": [{"path": "parameters.forced_open", "value": ["A"]}]}],
        )

        assert result["rows"][1]["delta"] == 0

    @pytest.mark.parametrize(
        ("capacity", "objective"), [(30, 160.0), (40, 180.0), (60, 280.0), (100, 280.0)]
    )
    def test_knapsack_capacity_sweep(self, capacity: int, objective: float):
        result = run_scenarios(
            _model_ir("knapsack_gadget"),
            [
                {
                    "id": f"capacity={capacity}",
                    "overrides": [{"path": "parameters.capacity", "value": capacity}],
                }
            ],
        )

        assert result["rows"][1]["objective"] == objective

    def test_infeasible_scenario_is_reported_not_skipped(self):
        result = run_scenarios(
            _model_ir("p_median_community"),
            [{"id": "p=6", "overrides": [{"path": "parameters.p", "value": 6}]}],
        )

        row = result["rows"][1]
        assert row["status"] == "不可行"
        assert row["objective"] is None and row["delta"] is None

    def test_invalid_scenario_is_reported_per_row(self):
        result = run_scenarios(
            _model_ir("p_median_community"),
            [
                {"id": "好场景", "overrides": [{"path": "parameters.p", "value": 2}]},
                {"id": "坏场景", "overrides": [{"path": "nope", "value": 1}]},
            ],
        )

        assert result["rows"][1]["objective"] == 2400.0
        assert result["rows"][2]["status"] == "覆盖无效"
        assert "只支持 parameters" in result["rows"][2]["note"]

    def test_missing_data_fails_fast(self):
        ir = {
            "problem_families": [{"id": "p_median"}],
            "constraint_blocks": [{"block_id": "assign_each_demand_once", "parameters": {}}],
            "objective": {"block_id": "weighted_service_distance_objective", "sense": "minimize"},
        }
        with pytest.raises(ValueError, match="基准模型无法求解"):
            run_scenarios(ir, [{"id": "p=2", "overrides": [{"path": "parameters.p", "value": 2}]}])


class TestRenderComparison:
    def test_table_contains_sense_baseline_and_rows(self):
        result = run_scenarios(
            _model_ir("p_median_community"),
            [{"id": "p=2", "overrides": [{"path": "parameters.p", "value": 2}]}],
        )
        text = render_comparison(result)

        assert "目标方向：最小化" in text
        assert "| (基准) | 最优 | 2210 | 0 |" in text
        assert "| p=2 | 最优 | 2400 | +190 |" in text

    def test_zero_delta_is_printed_plainly(self):
        result = run_scenarios(_model_ir("knapsack_gadget"), [])
        assert "| 0 |" in render_comparison(result)

    def test_notes_are_listed_below_the_table(self):
        result = run_scenarios(
            _model_ir("p_median_community"),
            [{"id": "坏", "overrides": [{"path": "nope", "value": 1}]}],
        )
        text = render_comparison(result)

        assert "- 坏：不支持的覆盖路径" in text


def test_describe_model_reports_family_and_objective():
    text = describe_model(_model_ir("p_median_community"))

    assert "p_median" in text
    assert "weighted_service_distance_objective" in text


# ---------------------------------------------------------------------------
# 本地 manual
# ---------------------------------------------------------------------------


class TestManual:
    def test_loads_with_schema_version(self):
        manual = load_manual()

        assert manual["name"] == "what_if"
        assert manual["scenario"]["overrides"][0]["path"].startswith("parameters.")

    def test_renders_prose_and_derived_tables(self):
        text = manual_markdown()

        assert "何时使用" in text and "场景结构" in text and "边界" in text
        assert "可覆盖的键" in text
        assert "`p_median`" in text and "`capacitated_facility_location`" in text
        assert len(text) < 2500  # 附录进每次请求，保持紧凑

    def test_manual_parameter_keys_are_readable_by_the_block_model(self):
        """manual 里出现的参数键必须都在 block_model 真正读取的键集合内。"""
        manual = load_manual()
        mentioned = set()
        for override in manual["scenario"]["overrides"]:
            mentioned.add(override["path"].split(".")[1])
        for example in manual["examples"]:
            for scenario in example["scenarios"]:
                for override in scenario["overrides"]:
                    mentioned.add(override["path"].split(".")[1])

        assert mentioned <= READABLE_DATA_KEYS

    def test_readable_keys_match_the_block_model_source(self):
        """防止 READABLE_DATA_KEYS 与实际读取的键漂移（双向）。"""
        import re

        source = (_BASE / "benchmarks" / "references" / "block_model.py").read_text(
            encoding="utf-8"
        )
        used = set(re.findall(r'(?:data\.get|list_value|matrix|indices)\("([a-z_]+)"', source))
        assert used == set(READABLE_DATA_KEYS)

    def test_supported_models_are_executable(self):
        from benchmarks.references.block_model import CONSTRAINT_BUILDERS, OBJECTIVE_BUILDERS

        models = supported_models()
        assert {m["id"] for m in models} >= {"p_median", "facility_location", "knapsack"}
        for model in models:
            assert all(b in CONSTRAINT_BUILDERS for b in model["blocks"])
            assert model["objective"] in OBJECTIVE_BUILDERS


# ---------------------------------------------------------------------------
# 工具入口
# ---------------------------------------------------------------------------


class TestWhatIfTool:
    def _write_model(self, directory: Path, case_id: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        ir = _model_ir(case_id)
        report = validate_problem_ir(ir)
        (directory / "model.json").write_text(
            json.dumps({"saved_at": None, "ir": ir, "report": report}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_answers_a_comparison_question(self, tmp_path: Path):
        self._write_model(tmp_path, "p_median_community")
        tool = WhatIfTool(workspace_dir=tmp_path)

        output = tool.forward(
            json.dumps(
                [
                    {"id": "p=2", "overrides": [{"path": "parameters.p", "value": 2}]},
                    {"id": "p=4", "overrides": [{"path": "parameters.p", "value": 4}]},
                ]
            )
        )

        assert "| (基准) | 最优 | 2210 | 0 |" in output
        assert "| p=2 | 最优 | 2400 | +190 |" in output
        assert "| p=4 | 最优 | 2050 | -160 |" in output

    def test_reports_when_no_model_exists_yet(self, tmp_path: Path):
        output = WhatIfTool(workspace_dir=tmp_path).forward("[]")

        assert "还没有模型" in output and "validate_problem_ir" in output

    def test_reports_unparsable_scenarios(self, tmp_path: Path):
        self._write_model(tmp_path, "p_median_community")

        assert "无法解析 scenarios_json" in WhatIfTool(workspace_dir=tmp_path).forward("{not json")

    def test_reports_non_list_scenarios(self, tmp_path: Path):
        self._write_model(tmp_path, "p_median_community")

        assert "必须是一个场景列表" in WhatIfTool(workspace_dir=tmp_path).forward('{"id": "x"}')

    def test_accepts_a_python_list_like_the_agent_writes(self, tmp_path: Path):
        """代码块里直接写 Python 列表是正常写法，不该要求先 json.dumps。"""
        self._write_model(tmp_path, "p_median_community")
        tool = WhatIfTool(workspace_dir=tmp_path)

        output = tool.forward([{"id": "p=4", "overrides": [{"path": "parameters.p", "value": 4}]}])

        assert "| p=4 | 最优 | 2050 | -160 |" in output

    def test_reports_unsupported_argument_type(self, tmp_path: Path):
        self._write_model(tmp_path, "p_median_community")

        output = WhatIfTool(workspace_dir=tmp_path).forward(7)  # type: ignore[arg-type]
        assert "必须是场景列表或它的 JSON 字符串" in output

    def test_reports_baseline_failure(self, tmp_path: Path):
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "model.json").write_text(
            json.dumps({"ir": {"objective": {"block_id": "weighted_service_distance_objective"}}}),
            encoding="utf-8",
        )

        output = WhatIfTool(workspace_dir=tmp_path).forward("[]")

        assert "无法执行情景对比" in output and "基准模型无法求解" in output

    def test_registered_on_the_agent(self, monkeypatch):
        monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o-mini")
        from agents import build_nl2or_agent

        agent = build_nl2or_agent(verbosity_level=0)

        assert "what_if" in agent.tools
        assert "what_if" in agent.system_prompt
        assert "Appendix: what_if" in agent.system_prompt
