"""Tool: solve one Problem IR deterministically, optionally under parameter overrides."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hamlet.core.tools import Tool

from core.block_model import describe_model, format_solution, prepare_overrides, render_script
from core.block_model import solve_ir as solve_problem_ir
from core.ir_validate import validate_problem_ir
from core.problem_ir import ProblemIR, fingerprint
from core.report import default_report_spec, render_report
from utils.session import get_session, save_code_file

_SCRIPT_NAME = "solver_from_ir.py"


class SolveIrTool(Tool):
    """Solve a Problem IR through the library's executable block semantics.

    Scenarios are deliberately not looped here: the agent asks for one variant per
    call (the baseline, then each override set) and tabulates the results itself,
    so every number stays traceable to a single explicit input.
    """

    name = "solve_ir"
    description = (
        "Solve a Problem IR deterministically from the library's block semantics, without "
        "writing a solver script. This is the default way to solve: use run_solver only when "
        "a block has no executable semantics or the user asks for hand-written code. "
        "Use it for comparison questions about parameters too: call it once for the baseline "
        "and once per override set, then tabulate the objective values. "
        "Every call rebuilds the model from the same formulation, so the differences you "
        "report come from the parameters and nothing else. "
        "Input: ir_json (the Problem IR dict or its JSON string) and overrides_json (an object "
        'mapping top-level parameter keys to new values, e.g. {"p": 4}; omit or pass {} for the '
        "baseline). Only keys this model's own blocks read are accepted, and each value must "
        "match the key's shape, so a typo fails instead of leaving the scenario unchanged. "
        "Output: plain text with the status, the applied overrides, the objective on a "
        "`[RESULT]` line, a decision summary, and (for the baseline) the saved script path."
    )
    inputs = {
        "ir_json": {
            "type": "string",
            "description": "Problem IR as a dict or its JSON string; normalized before solving.",
        },
        "overrides_json": {
            "type": "string",
            "nullable": True,
            "description": (
                "Object (or its JSON string) of top-level parameter overrides, "
                'e.g. {"p": 4}. Omit or pass {} for the baseline.'
            ),
        },
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        # None 时脚本写进当前会话目录（生产路径），显式给出时写进该目录（测试/评测）
        self._workspace: Path | None = Path(workspace_dir) if workspace_dir else None

    def forward(
        self,
        ir_json: str | dict[str, Any],
        overrides_json: str | dict[str, Any] | None = None,
    ) -> str:
        try:
            parsed = ProblemIR.parse(ir_json)
            report = validate_problem_ir(parsed.data)
            if report["errors"]:
                return "无法求解：" + "；".join(report["errors"])
            ir = ProblemIR(report["normalized_ir"])
            overrides = prepare_overrides(ir.data, overrides_json)
            solved = ir.with_overrides(overrides)
            result = solve_problem_ir(solved.data)
        except ValueError as exc:
            return f"无法求解：{exc}"

        spec = default_report_spec(solved.data)
        if overrides:
            spec["tables"] = ["objective_breakdown"]
        solution_text = format_solution(result, overrides)
        report_text = render_report(solved.data, result, spec=spec)
        parts = [describe_model(ir.data), solution_text, report_text]
        if not overrides:
            # 快路径也要留下可查看、可重跑的脚本；情景变体不落盘，避免刷出一堆文件
            parts.append(f"脚本：{self._save_script(solved.data)}")
            self._save_solve_result(solved.data, solution_text, report_text)
        return "\n\n".join(parts)

    def _save_script(self, ir: dict[str, Any]) -> Path:
        """Write the rendered script through the same path run_solver uses."""
        directory = self._workspace if self._workspace is not None else get_session().code_dir
        return save_code_file(directory, render_script(ir), _SCRIPT_NAME)

    def _save_solve_result(self, ir: dict[str, Any], solution: str, report: str) -> None:
        """Persist the baseline result for the [SOLVE_RESULT] placeholder.

        Only the baseline is saved and it is fingerprinted against the IR, so a
        later answer can never quote a result from an older model.
        """
        target = (
            self._workspace / "solve_result.json"
            if self._workspace is not None
            else get_session().solve_result_file
        )
        payload = {
            "ir_fingerprint": fingerprint(ir),
            "text": f"{solution}\n\n{report}",
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
