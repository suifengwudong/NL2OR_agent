"""Tool for executing generated OR solver code in a sandboxed subprocess."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from hamlet.core.tools import Tool
from utils.session import get_session


_TIMEOUT_SECONDS = 60


class RunSolverTool(Tool):
    """Execute Python solver code (gurobipy / scipy / PuLP) and return the output.

    In production, solver code is written to a session-isolated directory
    under ``data/workspace/sessions/{id}/code/``.  When *workspace_dir* is
    explicitly provided (e.g. in tests), that directory is used instead.
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

    def forward(self, code: str) -> str:  # noqa: D102
        """Write *code* to a temp file, run it, and return captured output."""
        script_path = self.save_code(code)

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
