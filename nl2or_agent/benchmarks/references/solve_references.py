"""Compute ground-truth objective values for NL2OR benchmark cases.

Runs each standalone solver script in ``references/solvers/`` and parses the
objective it prints.  These scripts are the single source of truth: the same
files are fed to ``RunSolverTool`` by the benchmark's *solver* tier, so the
ground truth and the harness-under-test share one definition.

Run:  uv run python benchmarks/references/solve_references.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SOLVERS_DIR = Path(__file__).parent / "solvers"
_OBJ_RE = re.compile(r"Objective:\s*(-?\d+(?:\.\d+)?)")


def run_solver_script(path: Path) -> float:
    """Execute a solver script and return the objective it prints."""
    result = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    match = _OBJ_RE.search(result.stdout)
    if not match:
        raise RuntimeError(
            f"{path.name}: no objective in output:\n{result.stdout}\n{result.stderr}"
        )
    return float(match.group(1))


def all_objectives() -> dict[str, float]:
    return {p.stem: run_solver_script(p) for p in sorted(SOLVERS_DIR.glob("*.py"))}


if __name__ == "__main__":
    for name, value in all_objectives().items():
        print(f"{name}: {value}")
