"""Tool: render the solver script for a Problem IR, so it can be inspected or edited.

Not part of the solving workflow: `solve_ir` already solves the IR and saves the same
script. This tool exists for the case where the user wants the script itself (to read,
adapt, or hand on), so the agent can print it and edit it from there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hamlet.core.tools import Tool

from core.block_model import render_script
from core.problem_ir import ProblemIR
from utils.session import get_session, save_code_file

_SCRIPT_NAME = "solver_ir_script.py"


class IrScriptTool(Tool):
    """Render the standalone solver script described by a Problem IR."""

    name = "ir_to_script"
    description = (
        "Render the solver script that the library's block semantics would run for a Problem IR, "
        "without solving it. Use it when the user wants to read or adapt the code: the script is "
        "returned as text and also saved in the session workspace. For a plain answer use solve_ir. "
        "Input: ir_json (the Problem IR dict or its JSON string)."
    )
    inputs = {
        "ir_json": {
            "type": "string",
            "description": "Problem IR as a dict or its JSON string; normalized before rendering.",
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        self._workspace: Path | None = Path(workspace_dir) if workspace_dir else None

    def forward(self, ir_json: str | dict[str, Any]) -> str:
        try:
            ir = ProblemIR.parse(ir_json).normalized
            script = render_script(ir.data)
        except ValueError as exc:
            return f"无法生成脚本：{exc}"

        directory = self._workspace if self._workspace is not None else get_session().code_dir
        path = save_code_file(directory, script, _SCRIPT_NAME)
        return f"脚本已保存：{path}\n\n```python\n{script}```"
