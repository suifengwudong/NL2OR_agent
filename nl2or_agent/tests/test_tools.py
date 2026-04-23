"""Tests for QueryModelLibraryTool and RunSolverTool."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import QueryModelLibraryTool, RunSolverTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_model_bank(tmp_path: Path) -> Path:
    """Create a minimal model bank JSON for testing."""
    bank = {
        "models": [
            {
                "id": "knapsack",
                "name": "背包问题",
                "type": "integer_programming",
                "keywords": ["knapsack", "背包", "binary", "capacity"],
                "description": "经典0-1背包问题",
                "variables": ["x_i: 二进制变量，表示物品i是否被选取"],
                "objective": "max sum(v_i * x_i)",
                "constraints": ["sum(w_i * x_i) <= W", "x_i in {0,1}"],
                "solver_hint": "gurobipy with GRB.BINARY",
                "template_code": "# knapsack template",
            },
            {
                "id": "lp_general",
                "name": "通用线性规划",
                "type": "linear_programming",
                "keywords": ["linear programming", "LP", "maximize", "minimize"],
                "description": "标准线性规划",
                "variables": ["x_i: 连续变量"],
                "objective": "min/max sum(c_i * x_i)",
                "constraints": ["sum(a_ij * x_j) <= b_i", "x_i >= 0"],
                "solver_hint": "gurobipy Model",
                "template_code": "# LP template",
            },
        ]
    }
    bank_file = tmp_path / "models.json"
    bank_file.write_text(json.dumps(bank, ensure_ascii=False), encoding="utf-8")
    return bank_file


@pytest.fixture()
def query_tool(tmp_model_bank: Path) -> QueryModelLibraryTool:
    return QueryModelLibraryTool(bank_path=tmp_model_bank)


@pytest.fixture()
def solver_tool(tmp_path: Path) -> RunSolverTool:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return RunSolverTool(workspace_dir=workspace)


# ---------------------------------------------------------------------------
# QueryModelLibraryTool tests
# ---------------------------------------------------------------------------

class TestQueryModelLibraryTool:
    def test_initialization_default_path(self):
        tool = QueryModelLibraryTool()
        assert tool.name == "query_model_library"
        assert tool._bank_path.name == "models.json"

    def test_initialization_custom_path(self, tmp_model_bank: Path):
        tool = QueryModelLibraryTool(bank_path=tmp_model_bank)
        assert tool._bank_path == tmp_model_bank

    def test_forward_matching_keyword(self, query_tool: QueryModelLibraryTool):
        result = query_tool.forward("knapsack")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["id"] == "knapsack"

    def test_forward_multiple_keywords(self, query_tool: QueryModelLibraryTool):
        result = query_tool.forward("knapsack, binary, capacity")
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["id"] == "knapsack"

    def test_forward_lp_keyword(self, query_tool: QueryModelLibraryTool):
        result = query_tool.forward("linear programming")
        data = json.loads(result)
        assert isinstance(data, list)
        assert any(m["id"] == "lp_general" for m in data)

    def test_forward_no_match_returns_message(self, query_tool: QueryModelLibraryTool):
        result = query_tool.forward("nonexistent_keyword_xyz")
        data = json.loads(result)
        assert "message" in data
        assert "No matching templates found" in data["message"]

    def test_forward_empty_keyword(self, query_tool: QueryModelLibraryTool):
        result = query_tool.forward("   ")
        data = json.loads(result)
        assert "message" in data

    def test_forward_results_contain_required_fields(self, query_tool: QueryModelLibraryTool):
        result = query_tool.forward("knapsack")
        data = json.loads(result)
        required_fields = {"id", "name", "type", "description", "variables",
                           "objective", "constraints", "solver_hint", "template_code"}
        for model in data:
            assert required_fields.issubset(model.keys())

    def test_forward_returns_at_most_3_results(self, tmp_path: Path):
        """Ensure no more than 3 results are returned."""
        bank = {
            "models": [
                {
                    "id": f"model_{i}",
                    "name": f"Model {i}",
                    "type": "lp",
                    "keywords": ["shared_keyword"],
                    "description": "",
                    "variables": [],
                    "objective": "",
                    "constraints": [],
                    "solver_hint": "",
                    "template_code": "",
                }
                for i in range(5)
            ]
        }
        bank_file = tmp_path / "big_bank.json"
        bank_file.write_text(json.dumps(bank), encoding="utf-8")
        tool = QueryModelLibraryTool(bank_path=bank_file)
        result = tool.forward("shared_keyword")
        data = json.loads(result)
        assert len(data) <= 3

    def test_forward_partial_keyword_match(self, query_tool: QueryModelLibraryTool):
        """Test that partial matches also work (e.g. 'knap' matches 'knapsack')."""
        result = query_tool.forward("knap")
        data = json.loads(result)
        # The keyword 'knap' is a substring of 'knapsack' in model keywords
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# RunSolverTool tests
# ---------------------------------------------------------------------------

class TestRunSolverTool:
    def test_initialization_default_workspace(self):
        tool = RunSolverTool()
        assert tool.name == "run_solver"
        assert tool._workspace.exists()

    def test_initialization_custom_workspace(self, tmp_path: Path):
        workspace = tmp_path / "my_workspace"
        tool = RunSolverTool(workspace_dir=workspace)
        assert tool._workspace == workspace
        assert workspace.exists()

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

    def test_forward_script_path_appended(self, solver_tool: RunSolverTool):
        result = solver_tool.forward("print('hello')")
        assert "[Script saved to:" in result

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
