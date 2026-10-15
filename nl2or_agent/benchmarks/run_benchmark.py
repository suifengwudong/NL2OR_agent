"""NL2OR benchmark runner.

Three tiers:
  offline (default, no LLM, deterministic):
      Feed each case's *dirty* IR (as an LLM might emit: aliases, non-canonical
      names) into ``validate_problem_ir`` and score the normalized output
      against the expected families / block_ids / objective block.

  solver (no LLM, deterministic):
      Feed each case's reference solver script to the agent's ``RunSolverTool``
      (subprocess execution path) and assert the emitted objective matches the
      known optimum.  Locks down the "run_solver -> subprocess -> objective"
      chain without invoking the LLM.

  online (requires OPENROUTER_API_KEY + HAMLET_MODEL_ID):
      Run the real agent end to end on each case's natural-language problem and
      check whether the optimal objective value appears in the final answer.

Usage:
  uv run python benchmarks/run_benchmark.py                 # offline, all cases
  uv run python benchmarks/run_benchmark.py --mode solver
  uv run python benchmarks/run_benchmark.py --mode online
  uv run python benchmarks/run_benchmark.py --cases p_median_community
  uv run python benchmarks/run_benchmark.py --json          # machine-readable report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")

CASES_PATH = Path(__file__).parent / "cases.json"
ORLIB_DIR = Path(__file__).parent / "orlib_cases"
SOLVERS_DIR = Path(__file__).parent / "references" / "solvers"

_OBJECTIVE_RE = re.compile(r"Objective:\s*(-?\d+(?:\.\d+)?)")


def _objective_matches(text: str, expected: float, tol: float = 1e-6) -> bool:
    """True if *text* contains a number equal to *expected* within tolerance."""
    for raw in _OBJECTIVE_RE.findall(text):
        if abs(float(raw) - expected) <= tol * max(1.0, abs(expected)):
            return True
    # Fallback: any standalone number matching the expected value.
    cand = str(int(expected))
    return re.search(rf"(?<!\d){re.escape(cand)}(?!\d)", text) is not None


def _load_cases(only: list[str] | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with open(CASES_PATH, encoding="utf-8") as f:
        cases.extend(json.load(f)["cases"])
    if ORLIB_DIR.is_dir():
        for p in sorted(ORLIB_DIR.glob("*.json")):
            with open(p, encoding="utf-8") as f:
                cases.append(json.load(f))
    if only:
        wanted = set(only)
        cases = [c for c in cases if c["id"] in wanted]
    return cases


# ---------------------------------------------------------------------------
# Offline (IR pipeline) evaluation
# ---------------------------------------------------------------------------


def _score_offline_case(case: dict[str, Any]) -> dict[str, Any]:
    from core.ir_normalizer import validate_problem_ir

    report = validate_problem_ir(case["input_ir"])
    expected = case["expected"]
    norm = report.get("normalized_ir", {})

    got_families = {f.get("id") for f in norm.get("problem_families", []) if f.get("id")}
    exp_families = set(expected["families"])

    got_blocks = {b["block_id"] for b in norm.get("constraint_blocks", [])}
    exp_blocks = set(expected["block_ids"])

    got_obj = (norm.get("objective") or {}).get("block_id")
    exp_obj = expected.get("objective_block")

    checks = {
        "valid": report.get("valid") is True,
        "families": got_families == exp_families,
        "block_ids": got_blocks == exp_blocks,
        "objective": (exp_obj is None) or (got_obj == exp_obj),
    }
    return {
        "case_id": case["id"],
        "checks": checks,
        "passed": all(checks.values()),
        "errors": report.get("errors", []),
        "got_families": sorted(got_families),
        "got_blocks": sorted(got_blocks),
        "got_objective": got_obj,
        "detail": f"got blocks {sorted(got_blocks)}; expected {sorted(exp_blocks)}",
    }


def run_offline(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [_score_offline_case(c) for c in cases]
    passed = sum(1 for r in results if r["passed"])
    return {
        "mode": "offline",
        "total": len(results),
        "passed": passed,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Solver-execution evaluation (RunSolverTool, no LLM)
# ---------------------------------------------------------------------------


def _score_solver_case(case: dict[str, Any], workspace: Path) -> dict[str, Any]:
    from tools.solver_tool import RunSolverTool

    case_id = case["id"]
    expected = case.get("solver_objective")
    script_path = SOLVERS_DIR / f"{case_id}.py"

    if expected is None:
        return {"case_id": case_id, "passed": False, "checks": {}, "detail": "no solver_objective"}
    if not script_path.is_file():
        return {"case_id": case_id, "passed": False, "checks": {}, "detail": "no reference script"}

    tool = RunSolverTool(workspace_dir=workspace / case_id)
    output = tool.forward(script_path.read_text(encoding="utf-8"))
    ok = _objective_matches(output, float(expected))
    return {
        "case_id": case_id,
        "checks": {"objective": ok},
        "passed": ok,
        "expected": expected,
        "detail": f"expected objective {expected}",
        "output_excerpt": output[-200:],
    }


def run_solver(cases: list[dict[str, Any]]) -> dict[str, Any]:
    import tempfile

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        for case in cases:
            results.append(_score_solver_case(case, workspace))
    passed = sum(1 for r in results if r["passed"])
    return {
        "mode": "solver",
        "total": len(results),
        "passed": passed,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Online (end-to-end, LLM) evaluation
# ---------------------------------------------------------------------------


def run_online(cases: list[dict[str, Any]], timeout_turns: int = 3) -> dict[str, Any]:
    import os

    if not os.getenv("OPENROUTER_API_KEY") or not os.getenv("HAMLET_MODEL_ID"):
        print("[online] OPENROUTER_API_KEY / HAMLET_MODEL_ID 未配置，跳过。")
        return {"mode": "online", "total": len(cases), "passed": 0, "results": [], "skipped": True}

    from agents import build_nl2or_agent

    agent = build_nl2or_agent(verbosity_level=0)
    results: list[dict[str, Any]] = []

    for case in cases:
        objective = case.get("solver_objective")
        start = time.time()
        transcript: list[str] = []
        solved = False
        answer = ""
        try:
            for turn in range(timeout_turns):
                prompt = case["problem"] if turn == 0 else "确认，请继续求解。"
                answer = str(agent.run(prompt, reset=False))
                transcript.append(answer)
                if objective is not None and _objective_matches(answer, float(objective)):
                    solved = True
                    break
        except Exception as exc:  # noqa: BLE001
            transcript.append(f"[EXCEPTION] {exc}")

        results.append(
            {
                "case_id": case["id"],
                "checks": {"objective": solved},
                "passed": solved,
                "elapsed_s": round(time.time() - start, 1),
                "answer_excerpt": answer[-300:],
            }
        )

    passed = sum(1 for r in results if r["passed"])
    return {"mode": "online", "total": len(results), "passed": passed, "results": results}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_report(report: dict[str, Any], json_out: bool) -> None:
    if json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(f"\n=== NL2OR Benchmark ({report['mode']}) ===")
    print(f"passed {report['passed']}/{report['total']}\n")
    for r in report.get("results", []):
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['case_id']}")
        if not r["passed"]:
            for name, ok in r.get("checks", {}).items():
                if not ok:
                    print(f"        - {name}: mismatch")
            if r.get("errors"):
                print(f"        - errors: {r['errors']}")
            if r.get("detail"):
                print(f"        - {r['detail']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="NL2OR benchmark runner")
    parser.add_argument("--mode", choices=["offline", "solver", "online"], default="offline")
    parser.add_argument("--cases", help="comma-separated case ids to run")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args()

    only = [c.strip() for c in args.cases.split(",") if c.strip()] if args.cases else None
    cases = _load_cases(only)

    if args.mode == "online":
        report = run_online(cases)
    elif args.mode == "solver":
        report = run_solver(cases)
    else:
        report = run_offline(cases)

    _format_report(report, args.json)


if __name__ == "__main__":
    main()
