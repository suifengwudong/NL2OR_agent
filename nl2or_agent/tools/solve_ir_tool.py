"""Tool: solve one Problem IR deterministically, optionally under parameter overrides."""

from __future__ import annotations

from typing import Any

from hamlet.core.tools import Tool

from core.block_model import describe_model, format_solution
from core.block_model import solve_ir as solve_problem_ir
from core.problem_ir import ProblemIR


class SolveIrTool(Tool):
    """Solve a Problem IR through the library's executable block semantics.

    Scenarios are deliberately not looped here: the agent asks for one variant per
    call (the baseline, then each override set) and tabulates the results itself,
    so every number stays traceable to a single explicit input.
    """

    name = "solve_ir"
    description = (
        "Solve a Problem IR deterministically from the library's block semantics, without "
        "writing a solver script. Use it for comparison questions about parameters: call it "
        "once for the baseline and once per override set, then tabulate the objective values. "
        "Every call rebuilds the model from the same formulation, so the differences you "
        "report come from the parameters and nothing else. "
        "Input: ir_json (the Problem IR dict or its JSON string) and overrides_json (an object "
        'mapping top-level parameter keys to new values, e.g. {"p": 4}; omit or pass {} for the '
        "baseline). Only keys the block model actually reads are accepted. "
        "Output: plain text with the status, the applied overrides, the objective on a "
        "`[RESULT]` line and a decision summary."
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

    def forward(
        self,
        ir_json: str | dict[str, Any],
        overrides_json: str | dict[str, Any] | None = None,
    ) -> str:
        try:
            ir = ProblemIR.parse(ir_json).normalized
            overrides = ProblemIR.parse_overrides(overrides_json)
            result = solve_problem_ir(ir.with_overrides(overrides).data)
        except ValueError as exc:
            return f"无法求解：{exc}"

        return "\n\n".join([describe_model(ir.data), format_solution(result, overrides)])
