"""Tests for RunSolverTool."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import RunSolverTool


@pytest.fixture()
def solver_tool(tmp_path: Path) -> RunSolverTool:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return RunSolverTool(workspace_dir=workspace)


class TestRunSolverTool:
    def test_initialization_default_workspace(self):
        tool = RunSolverTool()
        assert tool.name == "run_solver"
        # _workspace is None by default — session-based storage
        assert tool._workspace is None

    def test_initialization_custom_workspace(self, tmp_path: Path):
        workspace = tmp_path / "my_workspace"
        tool = RunSolverTool(workspace_dir=workspace)
        assert tool._workspace == workspace
        # Directory is lazily created on first save_code() call, not in __init__
        assert not workspace.exists()

    def test_save_code_creates_file(self, solver_tool: RunSolverTool):
        code = "print('hello')"
        path = solver_tool.save_code(code)
        assert path.exists()
        assert path.read_text(encoding="utf-8").strip() == "print('hello')"

    def test_save_code_custom_filename(self, solver_tool: RunSolverTool):
        code = "x = 1"
        path = solver_tool.save_code(code, filename="my_solver.py")
        assert path.name == "my_solver.py"
        assert path.exists()

    def test_save_code_auto_filename(self, solver_tool: RunSolverTool):
        path = solver_tool.save_code("pass")
        assert path.name.startswith("solver_")
        assert path.suffix == ".py"

    def test_forward_simple_print(self, solver_tool: RunSolverTool):
        result = solver_tool.forward("print('test_output_42')")
        assert "test_output_42" in result
        assert "[STDOUT]" in result

    def test_forward_no_output(self, solver_tool: RunSolverTool):
        result = solver_tool.forward("x = 1 + 1")
        assert "[INFO] Script ran successfully with no output." in result

    def test_forward_stderr_captured(self, solver_tool: RunSolverTool):
        code = "import sys; sys.stderr.write('error_msg\\n')"
        result = solver_tool.forward(code)
        assert "error_msg" in result
        assert "[STDERR]" in result

    def test_forward_runtime_error_captured(self, solver_tool: RunSolverTool):
        code = "raise ValueError('intentional error')"
        result = solver_tool.forward(code)
        assert "[STDERR]" in result or "[EXIT CODE]" in result

    def test_forward_nonzero_exit_code(self, solver_tool: RunSolverTool):
        code = "import sys; sys.exit(1)"
        result = solver_tool.forward(code)
        assert "[EXIT CODE] 1" in result
        assert "[RETRY REQUIRED]" in result

    def test_forward_script_path_appended(self, solver_tool: RunSolverTool):
        result = solver_tool.forward("print('hello')")
        assert "[Script saved to:" in result

    def test_forward_can_reuse_a_filename(self, solver_tool: RunSolverTool):
        first = solver_tool.run_file("print('Objective: 1')", "solver_fixed.py")
        second = solver_tool.run_file("print('Objective: 2')", "solver_fixed.py")

        assert "solver_fixed.py" in first and "solver_fixed.py" in second
        assert "Objective: 2" in second
        assert len(list(solver_tool._workspace.glob("*.py"))) == 1  # type: ignore[union-attr]

    def test_forward_flags_missing_objective_contract(self, solver_tool: RunSolverTool):
        result = solver_tool.forward("print('solved')")
        assert "[CONTRACT]" in result
        assert "Objective:" in result

    def test_forward_accepts_objective_contract(self, solver_tool: RunSolverTool):
        result = solver_tool.forward("print('Objective: 42')")
        assert "[CONTRACT]" not in result
        assert "Objective: 42" in result

    def test_forward_echoes_result_line_last(self, solver_tool: RunSolverTool):
        result = solver_tool.forward("print('Objective: 2210')")
        assert "[RESULT] Objective: 2210" in result
        assert result.strip().splitlines()[-1] == "[RESULT] Objective: 2210"

    def test_forward_omits_result_line_without_objective(self, solver_tool: RunSolverTool):
        result = solver_tool.forward("print('no objective here')")
        assert "[RESULT]" not in result

    def test_long_stdout_is_truncated_to_the_tail(self, solver_tool: RunSolverTool):
        """求解器日志会随步数反复重发，观测只保留尾部若干行。"""
        code = "\n".join(
            ["for i in range(200):", "    print('log line', i)", "print('Objective: 42')"]
        )
        result = solver_tool.forward(code)

        assert "前段省略" in result
        assert "[RESULT] Objective: 42" in result
        assert "log line 199" in result
        assert "log line 0" not in result

    def test_forward_timeout(self, solver_tool: RunSolverTool):
        """Simulate a timeout scenario."""
        with patch("tools.solver_tool.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=60)
            result = solver_tool.forward("import time; time.sleep(999)")
        assert "[ERROR]" in result
        assert "timed out" in result

    def test_forward_execution_exception(self, solver_tool: RunSolverTool):
        """Simulate an unexpected exception during subprocess.run."""
        with patch("tools.solver_tool.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("no such file or directory")
            result = solver_tool.forward("print('x')")
        assert "[ERROR]" in result
        assert "Failed to run solver script" in result

    def test_forward_math_computation(self, solver_tool: RunSolverTool):
        code = "print(2 + 2)"
        result = solver_tool.forward(code)
        assert "4" in result

    def test_forward_multiline_code(self, solver_tool: RunSolverTool):
        code = """
result = 0
for i in range(5):
    result += i
print(f'sum={result}')
"""
        result = solver_tool.forward(code)
        assert "sum=10" in result
