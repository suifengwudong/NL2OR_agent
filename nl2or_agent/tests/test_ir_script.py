"""ir_to_script 工具的测试。"""

from __future__ import annotations

import json

from core.block_model import solve_ir
from core.ir_validate import validate_problem_ir
from tools import IrScriptTool, RunSolverTool


def _ir() -> dict:
    from benchmarks.run_benchmark import _load_cases

    case = next(c for c in _load_cases() if c["id"] == "p_median_community")
    return validate_problem_ir(dict(case["input_ir"]))["normalized_ir"]


class TestIrScriptTool:
    def test_returns_and_saves_the_script(self, tmp_path):
        output = IrScriptTool(workspace_dir=tmp_path).forward(_ir())
        script = tmp_path / "solver_ir_script.py"

        assert script.is_file()
        assert "```python" in output
        assert "solve_ir(IR" in output

    def test_saved_script_reproduces_the_objective(self, tmp_path):
        IrScriptTool(workspace_dir=tmp_path).forward(_ir())
        script = (tmp_path / "solver_ir_script.py").read_text(encoding="utf-8")

        replay = RunSolverTool(workspace_dir=tmp_path).run_file(script, "replay.py")

        assert "[RESULT] Objective: 2210" in replay

    def test_accepts_a_json_string(self, tmp_path):
        output = IrScriptTool(workspace_dir=tmp_path).forward(json.dumps(_ir()))

        assert "solve_ir(IR" in output

    def test_reports_an_invalid_ir(self, tmp_path):
        output = IrScriptTool(workspace_dir=tmp_path).forward("{not json")

        assert "无法生成脚本" in output

    def test_rendered_script_matches_the_block_model(self, tmp_path):
        """脚本是块语义的渲染结果，不另外维护一份建模逻辑。"""
        ir = _ir()
        assert solve_ir(ir).objective == 2210.0
        output = IrScriptTool(workspace_dir=tmp_path).forward(ir)
        assert "core.block_model" in output


def test_registered_on_the_agent(monkeypatch):
    monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o-mini")
    from agents import build_nl2or_agent

    agent = build_nl2or_agent(verbosity_level=0)

    assert "ir_to_script" in agent.tools
    assert "ir_to_script" in agent.system_prompt
