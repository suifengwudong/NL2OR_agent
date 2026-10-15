"""Tool for executing generated OR solver code in a sandboxed subprocess."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from hamlet.core.tools import Tool
from utils.session import get_session


_TIMEOUT_SECONDS = 60

# 结果契约：脚本按此格式打印目标值，评测与答复都以它为准
_OBJECTIVE_LINE_RE = re.compile(r"Objective:\s*(-?\d+(?:\.\d+)?)")


class RunSolverTool(Tool):
    """Execute Python solver code (gurobipy / scipy / PuLP) and return the output.

    In production, solver code is written to a session-isolated directory
    under ``data/workspace/sessions/{id}/code/``.  When *workspace_dir* is
    explicitly provided (e.g. in tests), that directory is used instead.
    """

    name = "run_solver"
    description = (
        "Execute Python code that formulates and solves an Operations Research model. "
        "The script runs in this project's Python environment, where the installed solver "
        "libraries are gurobipy, pulp and scipy.optimize; OR-Tools and other libraries are not "
        "available. The script should print its result as a line `Objective: <value>`; the "
        "returned text repeats it on a `[RESULT]` line, and the final answer must quote that "
        "value. "
        "Input: a complete, self-contained Python script as a string. "
        "Output: the stdout/stderr produced by running the script, as plain text "
        "(not an object with attributes); call the tool as a statement and read the returned text."
    )
    inputs = {
        "code": {
            "type": "string",
            "description": (
                "A complete, self-contained Python script that solves the OR model "
                "and prints `Objective: <value>` plus the decision variables. "
                "Must not require manual user input."
            ),
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        # _workspace is only used when explicitly set (tests).  In production
        # save_code() delegates to the session system.
        self._workspace: Path | None = Path(workspace_dir) if workspace_dir else None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def save_code(self, code: str, filename: str | None = None) -> Path:
        """Persist *code* and return the file path.

        If a custom workspace was set at construction time, files go there
        (test mode).  Otherwise they are stored under the current session.
        """
        if self._workspace is not None:
            self._workspace.mkdir(parents=True, exist_ok=True)
            fname = filename or f"solver_{uuid.uuid4().hex[:8]}.py"
            path = self._workspace / fname
            path.write_text(code, encoding="utf-8")
            return path
        session = get_session()
        return session.save_code(code, filename)

    # ------------------------------------------------------------------
    # Tool entry point
    # ------------------------------------------------------------------

    def forward(self, code: str) -> str:
        """Tool entry point: write *code* to a new file, run it, return the output."""
        return self._execute(code, None)

    def run_file(self, code: str, filename: str) -> str:
        """Run *code* in place under *filename*.

        Used by the web code editor so an edited artifact is re-run instead of
        piling up new files; the agent never takes this path.
        """
        return self._execute(code, filename)

    def _execute(self, code: str, filename: str | None) -> str:
        """Write *code* to a file, run it, and return captured output."""
        script_path = self.save_code(code, filename)

        env = os.environ.copy()
        python_exe = sys.executable

        try:
            result = subprocess.run(
                [python_exe, str(script_path)],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return f"[ERROR] Solver timed out after {_TIMEOUT_SECONDS} seconds."
        except Exception as exc:  # noqa: BLE001
            return f"[ERROR] Failed to run solver script: {exc}"

        output_parts: list[str] = []
        objective_line = ""
        if result.stdout:
            output_parts.append(f"[STDOUT]\n{result.stdout.strip()}")
            match = _OBJECTIVE_LINE_RE.search(result.stdout)
            if match:
                objective_line = match.group(0).strip()
        if result.stderr:
            output_parts.append(f"[STDERR]\n{result.stderr.strip()}")
        if result.returncode != 0:
            output_parts.append(f"[EXIT CODE] {result.returncode}")
            output_parts.append(
                "[RETRY REQUIRED] 脚本未跑通。请根据上面的 STDERR 修正脚本并再次调用 run_solver，"
                "不要以这次输出作为最终结果。"
            )

        if not output_parts:
            output_parts.append("[INFO] Script ran successfully with no output.")
        elif result.returncode == 0 and not objective_line:
            output_parts.append(
                "[CONTRACT] 脚本已运行但没有输出目标值，请在脚本末尾打印 `Objective: <目标值>`。"
            )

        output_parts.append(f"\n[Script saved to: {script_path}]")
        if objective_line:
            # 规范化结果放在最后一行：答复里的目标值必须与它一致
            output_parts.append(f"[RESULT] {objective_line}")
        return "\n\n".join(output_parts)
