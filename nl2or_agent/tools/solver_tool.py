"""Tool for executing generated OR solver code in a sandboxed subprocess."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path

from hamlet.core.tools import Tool


_DEFAULT_WORKSPACE = Path(__file__).parent.parent / "data" / "workspace"
_TIMEOUT_SECONDS = 60


class RunSolverTool(Tool):
    """Execute Python solver code (gurobipy / scipy / PuLP) and return the output.

    The code is written to a temporary file under the workspace directory and
    executed in a subprocess so that any import or runtime errors are captured
    cleanly without crashing the agent.

    Returns a plain-text string with stdout + stderr from the solver run.
    """

    name = "run_solver"
    description = (
        "Execute Python code that formulates and solves an Operations Research model "
        "(using gurobipy, scipy.optimize, or PuLP). "
        "Input: a complete, self-contained Python script as a string. "
        "Output: the stdout/stderr produced by running the script, including the optimal solution."
    )
    inputs = {
        "code": {
            "type": "string",
            "description": (
                "A complete, self-contained Python script that solves the OR model "
                "and prints the results. Must not require manual user input."
            ),
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        self._workspace = Path(workspace_dir) if workspace_dir else _DEFAULT_WORKSPACE
        self._workspace.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def save_code(self, code: str, filename: str | None = None) -> Path:
        """Persist *code* to the workspace and return the file path."""
        fname = filename or f"solver_{uuid.uuid4().hex[:8]}.py"
        path = self._workspace / fname
        path.write_text(textwrap.dedent(code), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Tool entry point
    # ------------------------------------------------------------------

    def forward(self, code: str) -> str:  # noqa: D102
        """Write *code* to a temp file, run it, and return captured output."""
        script_path = self.save_code(code)

        env = os.environ.copy()
        # Make sure the virtual-env python is used if available
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
        if result.stdout:
            output_parts.append(f"[STDOUT]\n{result.stdout.strip()}")
        if result.stderr:
            output_parts.append(f"[STDERR]\n{result.stderr.strip()}")
        if result.returncode != 0:
            output_parts.append(f"[EXIT CODE] {result.returncode}")

        if not output_parts:
            return "[INFO] Script ran successfully with no output."

        output_parts.append(f"\n[Script saved to: {script_path}]")
        return "\n\n".join(output_parts)
