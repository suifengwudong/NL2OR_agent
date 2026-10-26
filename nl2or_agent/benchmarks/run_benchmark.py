"""NL2OR benchmark runner.

Every tier consumes the same case schema (``cases.json`` + ``orlib_cases/*.json``):

    id, name, family, scale, tiers, problem, input_ir, expected, solver_objective,
    tight_blocks, nonbinding_blocks, scenarios

  ir         (default, no LLM):  dirty IR -> validate_problem_ir -> normalized verdict
  solver     (no LLM):           reference script + block-removal variants -> RunSolverTool
  online     (needs LLM):        real agent on `problem` -> objective extracted and compared
  tightness  (no LLM):           recompute which blocks change the optimum, `--write` to store
  what_if    (no LLM):           baseline + declared parameter scenarios -> objective per scenario

Usage:
  uv run python benchmarks/run_benchmark.py                       # ir, all cases
  uv run python benchmarks/run_benchmark.py --mode solver
  uv run python benchmarks/run_benchmark.py --mode what_if
  uv run python benchmarks/run_benchmark.py --mode online --agent-mode automatic --repeats 3
  uv run python benchmarks/run_benchmark.py --mode tightness --write
  uv run python benchmarks/run_benchmark.py --cases p_median_community --json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

from core.block_model import SOLVE_STATUSES, objective_close  # noqa: E402
from utils.contract import OBJECTIVE_LINE_RE  # noqa: E402

load_dotenv(_ROOT / ".env")

CASES_PATH = Path(__file__).parent / "cases.json"
LOCATION_CASES_PATH = Path(__file__).parent / "location_cases.json"
ORLIB_DIR = Path(__file__).parent / "orlib_cases"
SOLVERS_DIR = Path(__file__).parent / "references" / "solvers"

TIERS = ("ir", "solver", "online", "tightness", "what_if")
SCALES = ("s", "m", "l")

_CONTEXT_RE = re.compile(
    r"(?:目标值|最优值|最优目标|总成本|总价值|最大距离|最小距离|Objective|objective)"
    r"[^\d\n-]{0,16}(-?\d+(?:\.\d+)?)"
)


# ---------------------------------------------------------------------------
# Case loading (single schema for every case file)
# ---------------------------------------------------------------------------


def _normalize_case(raw: dict[str, Any], origin: str) -> dict[str, Any]:
    """Fill defaults and fail fast on a malformed case (uniform interface)."""
    case = dict(raw)
    for key in ("id", "problem", "input_ir", "expected"):
        if key not in case:
            raise ValueError(f"{origin}: case {case.get('id', '?')} 缺少字段 {key!r}")
    expected = dict(case["expected"])
    expected.setdefault("valid", True)
    case["expected"] = expected

    if not expected["valid"]:
        kind = "negative"
        if not expected.get("error_contains"):
            raise ValueError(f"{origin}: 负例 {case['id']} 必须给出 expected.error_contains")
    elif expected.get("warning_contains"):
        kind = "warning"
    else:
        kind = "positive"
    case["kind"] = kind
    if "kind" in raw and raw["kind"] != kind:
        raise ValueError(
            f"{origin}: case {case['id']} 声明的 kind={raw['kind']!r} 与 expected 不一致（应为 {kind!r}）"
        )

    families = expected.get("families") or []
    case.setdefault("family", families[0] if families else "unknown")
    case.setdefault("scale", "s")
    if case["scale"] not in SCALES:
        raise ValueError(f"{origin}: case {case['id']} 的 scale 必须是 {SCALES}")

    tiers = case.setdefault("tiers", ["ir"])
    unknown = [t for t in tiers if t not in TIERS]
    if unknown:
        raise ValueError(f"{origin}: case {case['id']} 含未知评测层 {unknown}")
    if "solver" in tiers and case.get("solver_objective") is None:
        raise ValueError(f"{origin}: case {case['id']} 声明了 solver 层但没有 solver_objective")
    if "what_if" in tiers and case.get("solver_objective") is None:
        raise ValueError(f"{origin}: case {case['id']} 声明了 what_if 层但没有 solver_objective")
    if kind != "positive" and {"solver", "what_if"} & set(tiers):
        raise ValueError(f"{origin}: {kind} 用例 {case['id']} 不应进入求解层")
    case.setdefault("tight_blocks", [])
    case.setdefault("nonbinding_blocks", [])
    scenarios = case.setdefault("scenarios", [])
    if "what_if" in tiers and not scenarios:
        raise ValueError(f"{origin}: case {case['id']} 声明了 what_if 层但没有 scenarios")
    if scenarios and "what_if" not in tiers:
        raise ValueError(f"{origin}: case {case['id']} 有 scenarios 但没有声明 what_if 层")
    seen: set[str] = set()
    for scenario in scenarios:
        for key in ("id", "overrides"):
            if key not in scenario:
                raise ValueError(f"{origin}: case {case['id']} 的情景缺少字段 {key!r}")
        if scenario["id"] in seen:
            raise ValueError(f"{origin}: case {case['id']} 的情景 id {scenario['id']!r} 重复")
        seen.add(scenario["id"])
        if not isinstance(scenario["overrides"], dict):
            raise ValueError(
                f"{origin}: case {case['id']} 情景 {scenario['id']} 的 overrides 必须是对象"
            )
        has_objective = "expected_objective" in scenario
        has_status = "expected_status" in scenario
        if has_objective == has_status:
            raise ValueError(
                f"{origin}: case {case['id']} 情景 {scenario['id']} 需要且只需要一个"
                " expected_objective / expected_status"
            )
        if has_status and scenario["expected_status"] not in SOLVE_STATUSES:
            raise ValueError(
                f"{origin}: case {case['id']} 情景 {scenario['id']} 的 expected_status 必须是"
                f" {sorted(SOLVE_STATUSES)} 之一"
            )
        if has_objective:
            value = scenario["expected_objective"]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(
                    f"{origin}: case {case['id']} 情景 {scenario['id']} 的 expected_objective"
                    " 必须是数值"
                )
    case["origin"] = origin
    return case


def _load_cases(only: list[str] | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in (CASES_PATH, LOCATION_CASES_PATH):
        with open(path, encoding="utf-8") as f:
            for raw in json.load(f)["cases"]:
                cases.append(_normalize_case(raw, path.name))
    if ORLIB_DIR.is_dir():
        for path in sorted(ORLIB_DIR.glob("*.json")):
            with open(path, encoding="utf-8") as f:
                cases.append(_normalize_case(json.load(f), f"{ORLIB_DIR.name}/{path.name}"))
    if only:
        wanted = set(only)
        cases = [c for c in cases if c["id"] in wanted]
    return cases


def _tier_cases(cases: list[dict[str, Any]], tier: str) -> list[dict[str, Any]]:
    return [c for c in cases if tier in c["tiers"]]


def _reference_script_path(case: dict[str, Any]) -> Path:
    return Path(case.get("reference_script") or SOLVERS_DIR / f"{case['id']}.py")


def _normalized_ir(case: dict[str, Any]) -> dict[str, Any]:
    from core.ir_validate import validate_problem_ir

    report = validate_problem_ir(dict(case["input_ir"]))
    return report["normalized_ir"]


# ---------------------------------------------------------------------------
# Tier 1: IR verdict (no LLM)
# ---------------------------------------------------------------------------


def _score_ir_case(case: dict[str, Any]) -> dict[str, Any]:
    from core.ir_validate import validate_problem_ir

    report = validate_problem_ir(dict(case["input_ir"]))
    expected = case["expected"]
    errors = report["errors"]
    warnings = report["warnings"]
    skeleton = report["skeleton"]
    norm = report["normalized_ir"]

    checks: dict[str, bool] = {"valid": report["valid"] is bool(expected["valid"])}
    if expected["valid"]:
        got_families = {f.get("id") for f in norm.get("problem_families", []) if f.get("id")}
        got_blocks = {b["block_id"] for b in norm.get("constraint_blocks", [])}
        got_objective = (norm.get("objective") or {}).get("block_id")
        checks["families"] = got_families == set(expected.get("families") or got_families)
        checks["block_ids"] = got_blocks == set(expected.get("block_ids") or got_blocks)
        if expected.get("objective_block"):
            checks["objective"] = got_objective == expected["objective_block"]
        checks["substituted_blocks"] = set(skeleton["substituted_blocks"]) == set(
            expected.get("substituted_blocks") or []
        )
        checks["skeleton_clean"] = (
            not skeleton["missing_required_blocks"]
            and not skeleton["inconsistent_blocks"]
            and not skeleton["entities"]["problems"]
        )
        checks["warnings"] = all(
            kw in " ".join(warnings) for kw in (expected.get("warning_contains") or [])
        )
    else:
        checks["errors"] = all(
            any(kw in e for e in errors) for kw in expected.get("error_contains") or []
        )

    return {
        "case_id": case["id"],
        "kind": case["kind"],
        "family": case["family"],
        "scale": case["scale"],
        "checks": checks,
        "passed": all(checks.values()),
        "errors": errors,
        "warnings": warnings,
        "skeleton": skeleton,
        "got_families": sorted(
            f.get("id") for f in norm.get("problem_families", []) if f.get("id")
        ),
        "got_blocks": sorted(b["block_id"] for b in norm.get("constraint_blocks", [])),
        "got_objective": (norm.get("objective") or {}).get("block_id"),
        "detail": f"errors={errors} warnings={warnings}",
    }


def run_offline(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """IR tier over every case that declares the ``ir`` tier."""
    selected = _tier_cases(cases, "ir")
    results = [_score_ir_case(c) for c in selected]
    return {
        "mode": "ir",
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "results": results,
        "groups": _group_summary(results, ("kind", "family", "scale")),
    }


# ---------------------------------------------------------------------------
# Tier 2: solver execution (no LLM)
# ---------------------------------------------------------------------------


def _run_script(script: str, workspace: Path) -> str:
    from tools.solver_tool import RunSolverTool

    return RunSolverTool(workspace_dir=workspace).forward(script)


def _score_solver_case(case: dict[str, Any], workspace: Path) -> dict[str, Any]:
    case_id = case["id"]
    expected = float(case["solver_objective"])
    script_path = _reference_script_path(case)
    checks: dict[str, bool] = {}
    detail: list[str] = []

    variants = list(case.get("tight_blocks") or []) + list(case.get("nonbinding_blocks") or [])
    ir = _normalized_ir(case) if not script_path.is_file() or variants else None

    if script_path.is_file():
        script = script_path.read_text(encoding="utf-8")
    else:
        from core.block_model import render_script

        script = render_script(ir)
        detail.append(f"参考脚本由 IR 现场渲染（{script_path.name} 不存在）")

    output = _run_script(script, workspace / case_id)
    checks["reference"] = _objective_matches(output, expected)
    if not checks["reference"]:
        detail.append(f"参考脚本目标值不等于 {expected}")

    if variants:
        from core.block_model import render_script

        for block in case.get("tight_blocks") or []:
            script = render_script(ir, drop=(block,))
            out = _run_script(script, workspace / f"{case_id}__drop_{block}")
            changed = not _objective_matches(out, expected)
            checks[f"tight:{block}"] = changed
            if not changed:
                detail.append(f"去掉 {block} 后目标值仍为 {expected}，该块在该用例上并非紧约束")
        for block in case.get("nonbinding_blocks") or []:
            script = render_script(ir, drop=(block,))
            out = _run_script(script, workspace / f"{case_id}__drop_{block}")
            same = _objective_matches(out, expected)
            checks[f"nonbinding:{block}"] = same
            if not same:
                detail.append(f"去掉 {block} 后目标值改变，该块并非非紧约束")

    return {
        "case_id": case_id,
        "family": case["family"],
        "scale": case["scale"],
        "checks": checks,
        "passed": all(checks.values()),
        "expected": expected,
        "detail": "; ".join(detail),
    }


def run_solver(cases: list[dict[str, Any]]) -> dict[str, Any]:
    import tempfile

    selected = _tier_cases(cases, "solver")
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        for case in selected:
            results.append(_score_solver_case(case, workspace))
    return {
        "mode": "solver",
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "results": results,
        "groups": _group_summary(results, ("family", "scale")),
    }


# ---------------------------------------------------------------------------
# Tier 3: end-to-end (LLM)
# ---------------------------------------------------------------------------


def _extract_objectives(text: str) -> list[tuple[str, float]]:
    """Ordered objective candidates: the `Objective:` contract first, then labelled numbers."""
    found: list[tuple[str, float]] = []
    for raw in OBJECTIVE_LINE_RE.findall(text):
        found.append(("contract", float(raw)))
    for raw in _CONTEXT_RE.findall(text):
        found.append(("labelled", float(raw)))
    return found


def _objective_matches(text: str, expected: float, tol: float = 1e-6) -> bool:
    """True if *text* reports *expected* as an objective value."""
    candidates = [float(raw) for raw in OBJECTIVE_LINE_RE.findall(text)]
    if not candidates:
        candidates = [float(raw) for raw in _CONTEXT_RE.findall(text)]
    return any(objective_close(value, expected, tol) for value in candidates)


def _objective_match_kind(text: str, expected: float, tol: float = 1e-6) -> str | None:
    for kind, value in _extract_objectives(text):
        if objective_close(value, expected, tol):
            return kind
    return None


def _tokens_of(result: Any) -> int:
    usage = getattr(result, "token_usage", None)
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(sum(v for v in usage.values() if isinstance(v, (int, float))))
    total = 0
    for attr in ("input_tokens", "output_tokens"):
        value = getattr(usage, attr, None)
        if isinstance(value, int):
            total += value
    return total


_INFRA_ERROR_MARKERS = (
    "429",
    "rate limit",
    "rate-limit",
    "temporarily rate",
    "timed out",
    "timeout",
    "connection error",
    "connection reset",
    "apiconnectionerror",
    "502",
    "503",
    "bad gateway",
    "service unavailable",
)


def _is_infrastructure_error(message: str) -> bool:
    """True when a failed attempt was caused by the API/network, not by the agent."""
    text = message.lower()
    return any(marker in text for marker in _INFRA_ERROR_MARKERS)


def _artifact_objective(workspace: Path, expected: float) -> tuple[bool, str]:
    """Re-run the agent's own solver script and check the objective it really produces.

    This verifies the produced artifact (the model the agent actually built) rather
    than the number the agent claimed in prose.
    """
    scripts = sorted(workspace.rglob("solver_*.py"), key=lambda p: p.stat().st_mtime)
    if not scripts:
        return False, "no solver script written"
    recheck = workspace.parent / f"{workspace.name}__recheck"
    for script in reversed(scripts):
        output = _run_script(script.read_text(encoding="utf-8"), recheck)
        if _objective_matches(output, expected):
            return True, script.name
    return False, f"{scripts[-1].name} 及更早的脚本都未能复现 {expected}"


def run_online(
    cases: list[dict[str, Any]],
    *,
    agent_mode: str = "automatic",
    turns: int = 3,
    repeats: int = 1,
    budget_seconds: float | None = None,
    budget_tokens: int | None = None,
) -> dict[str, Any]:
    import os
    import tempfile

    selected = _tier_cases(cases, "online")
    if not os.getenv("OPENROUTER_API_KEY") or not os.getenv("HAMLET_MODEL_ID"):
        print("[online] OPENROUTER_API_KEY / HAMLET_MODEL_ID 未配置，跳过。")
        return {
            "mode": "online",
            "total": len(selected),
            "passed": 0,
            "results": [],
            "skipped": True,
        }

    from agents import build_nl2or_agent

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="nl2or_online_") as tmp:
        root = Path(tmp)
        for case in selected:
            expected = float(case["solver_objective"])
            attempts: list[dict[str, Any]] = []
            for attempt in range(repeats):
                workspace = root / f"{case['id']}_{attempt}"
                agent = build_nl2or_agent(
                    mode=agent_mode, verbosity_level=0, workspace_dir=workspace
                )
                start = time.time()
                answer = ""
                tokens = 0
                status = "solved"
                try:
                    prompts = (
                        [case["problem"]]
                        if agent_mode == "automatic"
                        else ([case["problem"]] + ["确认，请继续求解。"] * (turns - 1))
                    )
                    for prompt in prompts:
                        result = agent.run(prompt, reset=False)
                        answer = str(result)
                        tokens += _tokens_of(result)
                        if _objective_match_kind(answer, expected):
                            break
                except Exception as exc:  # noqa: BLE001
                    status = (
                        "infrastructure_error"
                        if _is_infrastructure_error(str(exc))
                        else f"exception: {exc}"
                    )
                elapsed = round(time.time() - start, 1)
                claimed = _objective_match_kind(answer, expected)
                artifact_ok, artifact_note = _artifact_objective(workspace, expected)
                over_budget = (budget_seconds is not None and elapsed > budget_seconds) or (
                    budget_tokens is not None and tokens > budget_tokens
                )
                if over_budget:
                    claimed = None
                    artifact_ok = False
                    status = "over_budget"
                attempts.append(
                    {
                        "passed": claimed is not None and artifact_ok,
                        "claimed": claimed,
                        "artifact": artifact_ok,
                        "artifact_note": artifact_note,
                        "status": status,
                        "elapsed_s": elapsed,
                        "tokens": tokens,
                        "answer_excerpt": answer[-300:],
                    }
                )
            passed = [a for a in attempts if a["passed"]]
            results.append(
                {
                    "case_id": case["id"],
                    "family": case["family"],
                    "scale": case["scale"],
                    "checks": {"objective": len(passed) == repeats},
                    "passed": len(passed) == repeats,
                    "pass_rate": round(len(passed) / repeats, 3),
                    "elapsed_s": statistics.mean(a["elapsed_s"] for a in attempts),
                    "elapsed_std": statistics.pstdev([a["elapsed_s"] for a in attempts])
                    if repeats > 1
                    else 0.0,
                    "tokens": statistics.mean(a["tokens"] for a in attempts),
                    "attempts": attempts,
                }
            )

    total_attempts = sum(len(r["attempts"]) for r in results)
    flat = [a for r in results for a in r["attempts"]]
    claimed_ok = sum(1 for a in flat if a["claimed"] is not None)
    artifact_ok = sum(1 for a in flat if a["artifact"])
    infra = sum(1 for a in flat if a["status"] == "infrastructure_error")
    times = sorted(a["elapsed_s"] for a in flat if a["passed"])
    return {
        "mode": "online",
        "agent_mode": agent_mode,
        "repeats": repeats,
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "attempts": total_attempts,
        "claim_pass_rate": round(claimed_ok / total_attempts, 3) if total_attempts else 0.0,
        "artifact_pass_rate": round(artifact_ok / total_attempts, 3) if total_attempts else 0.0,
        "attempt_pass_rate": (
            round(sum(1 for a in flat if a["passed"]) / total_attempts, 3)
            if total_attempts
            else 0.0
        ),
        "infrastructure_errors": infra,
        "time_to_success_s": times[-1] if times else None,
        "results": results,
        "groups": _group_summary(results, ("family", "scale")),
    }


# ---------------------------------------------------------------------------
# Tier 4: tightness (no LLM)
# ---------------------------------------------------------------------------


def run_tightness(cases: list[dict[str, Any]], *, write: bool = False) -> dict[str, Any]:
    from core.block_model import analyze_tightness

    selected = _tier_cases(cases, "tightness")
    results: list[dict[str, Any]] = []
    for case in selected:
        try:
            report = analyze_tightness(_normalized_ir(case))
        except Exception as exc:  # noqa: BLE001
            results.append({"case_id": case["id"], "passed": False, "detail": f"无法求解: {exc}"})
            continue
        baseline = report["baseline_objective"]
        ok = baseline is not None and not report["unsolved_blocks"]
        if ok and case.get("solver_objective") is not None and baseline is not None:
            ok = objective_close(baseline, float(case["solver_objective"]))
        if write and ok:
            _write_tightness(case, report)
            _write_reference_script(case)
        results.append(
            {
                "case_id": case["id"],
                "family": case["family"],
                "scale": case["scale"],
                "passed": ok,
                "baseline": report["baseline_objective"],
                "tight_blocks": report["tight_blocks"],
                "nonbinding_blocks": report["nonbinding_blocks"],
                "unsolved_blocks": report["unsolved_blocks"],
                "detail": "" if ok else f"baseline={report['baseline_objective']}",
            }
        )
    return {
        "mode": "tightness",
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "written": write,
        "results": results,
        "groups": _group_summary(results, ("family", "scale")),
    }


def _score_scenario(ir: Any, scenario: dict[str, Any]) -> dict[str, Any]:
    """Apply one scenario to *ir* and compare the result with its declared expectation."""
    from core.block_model import prepare_overrides, solve_ir

    row: dict[str, Any] = {
        "id": scenario["id"],
        "passed": False,
        "status": None,
        "objective": None,
        "overrides": scenario["overrides"],
        "expected": scenario.get("expected_objective", scenario.get("expected_status")),
        "detail": "",
    }
    try:
        overrides = prepare_overrides(ir.data, scenario["overrides"])
        result = solve_ir(ir.with_overrides(overrides).data)
    except Exception as exc:  # noqa: BLE001
        row["detail"] = str(exc)
        return row

    row["status"] = result.status
    row["objective"] = result.objective
    if "expected_status" in scenario:
        expected = scenario["expected_status"]
        ok = result.status == expected
        row["detail"] = "" if ok else f"状态 {result.status}，期望 {expected}"
    else:
        expected = float(scenario["expected_objective"])
        ok = result.objective is not None and objective_close(result.objective, expected)
        row["detail"] = "" if ok else f"目标值 {result.objective}，期望 {expected}"
    row["passed"] = ok
    return row


def run_what_if(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Solve the baseline plus every declared parameter scenario."""
    from core.block_model import solve_ir
    from core.problem_ir import ProblemIR

    selected = _tier_cases(cases, "what_if")
    results: list[dict[str, Any]] = []
    for case in selected:
        identity = {
            "case_id": case["id"],
            "family": case["family"],
            "scale": case["scale"],
        }
        try:
            ir = ProblemIR(_normalized_ir(case))
            baseline = solve_ir(ir.data)
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    **identity,
                    "passed": False,
                    "checks": {"baseline": False},
                    "baseline": None,
                    "scenarios": [],
                    "detail": f"基准求解失败：{exc}",
                }
            )
            continue

        declared = case.get("solver_objective")
        baseline_ok = (
            baseline.status == "Optimal"
            and baseline.objective is not None
            and (declared is None or objective_close(baseline.objective, float(declared)))
        )
        rows = [_score_scenario(ir, scenario) for scenario in case["scenarios"]]
        results.append(
            {
                **identity,
                "passed": baseline_ok and all(row["passed"] for row in rows),
                "checks": {"baseline": baseline_ok},
                "baseline": baseline.objective,
                "scenarios": rows,
                "detail": ""
                if baseline_ok
                else f"基准 {baseline.status} {baseline.objective}，solver_objective 为 {declared}",
            }
        )
    return {
        "mode": "what_if",
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "results": results,
        "groups": _group_summary(results, ("family", "scale")),
    }


def _write_reference_script(case: dict[str, Any]) -> None:
    """Refresh the reference script derived from the case IR."""
    from core.block_model import render_script

    path = SOLVERS_DIR / f"{case['id']}.py"
    path.write_text(render_script(_normalized_ir(case)), encoding="utf-8")


def _write_tightness(case: dict[str, Any], report: dict[str, Any]) -> None:
    """Persist tight/non-binding block lists back into the case file."""
    path = CASES_PATH if case["origin"] == CASES_PATH.name else ORLIB_DIR / f"{case['id']}.json"
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if "cases" in payload:
        for raw in payload["cases"]:
            if raw["id"] == case["id"]:
                raw["tight_blocks"] = report["tight_blocks"]
                raw["nonbinding_blocks"] = report["nonbinding_blocks"]
    else:
        payload["tight_blocks"] = report["tight_blocks"]
        payload["nonbinding_blocks"] = report["nonbinding_blocks"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _group_summary(results: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in keys:
        buckets: dict[str, list[bool]] = {}
        for result in results:
            buckets.setdefault(str(result.get(key, "?")), []).append(bool(result["passed"]))
        summary[key] = {
            name: {"passed": sum(values), "total": len(values)}
            for name, values in sorted(buckets.items())
        }
    return summary


def _format_report(report: dict[str, Any], json_out: bool) -> None:
    if json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(f"\n=== NL2OR Benchmark ({report['mode']}) ===")
    print(f"passed {report['passed']}/{report['total']}\n")
    for result in report.get("results", []):
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {result['case_id']}")
        if report["mode"] == "what_if":
            print(f"        - 基准 {result.get('baseline')}")
            for row in result.get("scenarios", []):
                # 非最优场景 PuLP 会残留上一次的目标值，它不是该场景的解
                objective = row.get("objective") if row.get("status") == "Optimal" else None
                mark = "" if row["passed"] else "  ← 不符"
                print(
                    f"        - {row['id']}: {row.get('status') or '—'}"
                    f" {objective if objective is not None else '—'}"
                    f" | overrides {row.get('overrides')}"
                    f" | 期望 {row.get('expected')}{mark}"
                )
                if not row["passed"]:
                    print(f"          {row['detail']}")
        if not result["passed"]:
            for name, ok in result.get("checks", {}).items():
                if not ok:
                    print(f"        - {name}: mismatch")
            for name in ("tight_blocks", "nonbinding_blocks", "unsolved_blocks"):
                if result.get(name):
                    print(f"        - {name}: {result[name]}")
            if result.get("detail"):
                print(f"        - {result['detail']}")
    groups = report.get("groups") or {}
    for key, buckets in groups.items():
        if not buckets:
            continue
        print(f"\n-- by {key} --")
        for name, counts in buckets.items():
            print(f"   {name:24s} {counts['passed']}/{counts['total']}")
    if report["mode"] == "online":
        print(
            f"\nclaim pass rate {report.get('claim_pass_rate')}"
            f" | artifact pass rate {report.get('artifact_pass_rate')}"
            f" | attempt pass rate {report['attempt_pass_rate']}"
            f" | infrastructure errors {report.get('infrastructure_errors', 0)}"
            f" | time-to-success {report['time_to_success_s']}s"
            f" | agent mode {report['agent_mode']} | repeats {report['repeats']}"
        )
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="NL2OR benchmark runner")
    parser.add_argument(
        "--mode",
        choices=["offline", "solver", "online", "tightness", "what_if"],
        default="offline",
    )
    parser.add_argument("--cases", help="comma-separated case ids to run")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument("--agent-mode", choices=["interactive", "automatic"], default="automatic")
    parser.add_argument("--repeats", type=int, default=1, help="online: repeats per case")
    parser.add_argument("--turns", type=int, default=3, help="online: max turns (interactive)")
    parser.add_argument("--budget-seconds", type=float, default=None)
    parser.add_argument("--budget-tokens", type=int, default=None)
    parser.add_argument("--write", action="store_true", help="tightness: store results in cases")
    args = parser.parse_args()

    only = [c.strip() for c in args.cases.split(",") if c.strip()] if args.cases else None
    cases = _load_cases(only)

    if args.mode == "solver":
        report = run_solver(cases)
    elif args.mode == "online":
        report = run_online(
            cases,
            agent_mode=args.agent_mode,
            turns=args.turns,
            repeats=args.repeats,
            budget_seconds=args.budget_seconds,
            budget_tokens=args.budget_tokens,
        )
    elif args.mode == "tightness":
        report = run_tightness(cases, write=args.write)
    elif args.mode == "what_if":
        report = run_what_if(cases)
    else:
        report = run_offline(cases)

    _format_report(report, args.json)


if __name__ == "__main__":
    main()
