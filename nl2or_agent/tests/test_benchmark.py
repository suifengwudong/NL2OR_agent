"""Regression: the benchmark tiers must stay green in CI.

Guards (a) the IR verdict pipeline, (b) the ``RunSolverTool`` execution path and its
block-removal variants across the location families (p-median, set covering, maximum
covering, p-center, UFLP, CFLP, capacitated p-median, knapsack) plus OR-Library
instances with published optima.
"""

from __future__ import annotations

import pytest

from core.block_model import solve_ir
from benchmarks.run_benchmark import (
    _extract_objectives,
    _load_cases,
    _normalized_ir,
    _objective_matches,
    run_offline,
    run_solver,
)


@pytest.fixture(scope="module")
def cases():
    return _load_cases()


@pytest.fixture(scope="module")
def offline_report(cases):
    return run_offline(cases)


@pytest.fixture(scope="module")
def solver_report(cases):
    return run_solver(cases)


# ---------------------------------------------------------------------------
# Unified case schema
# ---------------------------------------------------------------------------


def test_every_case_declares_the_same_fields(cases):
    for case in cases:
        assert case["id"] and case["problem"] and case["input_ir"] and case["expected"]
        assert case["family"], f"{case['id']} 缺少 family"
        assert case["scale"] in {"s", "m", "l"}, f"{case['id']} 的 scale 不合法"
        assert set(case["tiers"]) <= {"ir", "solver", "online", "tightness"}
        if "solver" in case["tiers"]:
            assert case["solver_objective"] is not None, f"{case['id']} 缺少 solver_objective"


def test_negative_cases_declare_expected_errors(cases):
    negatives = [c for c in cases if c["kind"] == "negative"]
    warnings_cases = [c for c in cases if c["kind"] == "warning"]
    assert len(negatives) >= 8 and len(warnings_cases) >= 3, "负例与提示类用例都应存在"
    for case in negatives:
        assert case["expected"].get("error_contains"), f"{case['id']} 缺少 error_contains"
        assert case["expected"]["valid"] is False
    for case in warnings_cases:
        assert case["expected"].get("warning_contains"), f"{case['id']} 缺少 warning_contains"
        assert case["expected"]["valid"] is True
    for case in cases:
        if case["kind"] != "positive":
            assert "solver" not in case["tiers"], f"{case['id']} 不应进入求解层"


def test_metadata_covers_every_block(cases):
    """每个约束块至少被一个用例覆盖（location 范围内的完整性检查）。"""
    from core.ir_catalog import load_block_catalog

    covered = set()
    for case in cases:
        if case["expected"]["valid"]:
            covered |= set(case["expected"].get("block_ids") or [])
    catalog = load_block_catalog()
    constraint_blocks = {b["id"] for b in catalog["blocks"] if b.get("category") != "objective"}
    assert constraint_blocks - covered == set(), (
        f"未被任何用例覆盖的约束块: {sorted(constraint_blocks - covered)}"
    )


# ---------------------------------------------------------------------------
# Tier results
# ---------------------------------------------------------------------------


def test_all_offline_cases_pass(offline_report):
    assert offline_report["passed"] == offline_report["total"], (
        f"{offline_report['passed']}/{offline_report['total']} cases passed. "
        "Run `uv run python benchmarks/run_benchmark.py` for details."
    )


def test_all_solver_cases_pass(solver_report):
    assert solver_report["passed"] == solver_report["total"], (
        f"{solver_report['passed']}/{solver_report['total']} solver cases passed. "
        "Run `uv run python benchmarks/run_benchmark.py --mode solver` for details."
    )


def test_report_grouping_uses_kind_family_and_scale(offline_report):
    assert set(offline_report["groups"]) == {"kind", "family", "scale"}
    assert (
        sum(v["total"] for v in offline_report["groups"]["family"].values())
        == (offline_report["total"])
    )


@pytest.mark.parametrize(
    "case_id",
    ["p_median_community", "knapsack_gadget", "uflp_cap71", "cflp_cap41"],
)
def test_solver_matches_reference_objective(solver_report, case_id: str):
    case_results = [r for r in solver_report["results"] if r["case_id"] == case_id]
    assert case_results and case_results[0]["passed"]


@pytest.mark.parametrize("case_id", ["p_median_force_open", "p_median_force_closed"])
def test_solver_asserts_tight_variants(solver_report, case_id: str):
    result = [r for r in solver_report["results"] if r["case_id"] == case_id][0]
    assert any(name.startswith("tight:") for name in result["checks"])


def test_solver_asserts_nonbinding_variant(solver_report):
    result = next(
        r for r in solver_report["results"] if r["case_id"] == "p_median_force_closed_nonbinding"
    )
    assert result["checks"]["nonbinding:force_facility_closed"]


# ---------------------------------------------------------------------------
# Block model (executable semantics of the catalog)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id",
    [
        "p_median_community",
        "set_covering_emergency",
        "maximum_covering_cities",
        "p_center_emergency",
        "facility_location_logistics",
        "knapsack_gadget",
        "uflp_cap71",
        "cflp_cap41",
        "cappmed_1",
    ],
)
def test_block_model_reproduces_case_objective(cases, case_id: str):
    case = next(c for c in cases if c["id"] == case_id)
    result = solve_ir(_normalized_ir(case))
    assert result.objective == pytest.approx(float(case["solver_objective"]), rel=1e-6)


def test_every_catalog_block_has_executable_semantics():
    """目录里的每个块都必须有可执行语义（统一接口的核心保证）。"""
    from core.block_model import CONSTRAINT_BUILDERS, OBJECTIVE_BUILDERS
    from core.ir_catalog import load_block_catalog

    for block in load_block_catalog()["blocks"]:
        builders = OBJECTIVE_BUILDERS if block["category"] == "objective" else CONSTRAINT_BUILDERS
        assert block["id"] in builders, f"{block['id']} 在 block_model 中缺少可执行语义"


def test_block_model_rejects_unknown_block():
    with pytest.raises(ValueError, match="没有可执行语义"):
        solve_ir(
            {
                "parameters": {"p": 2},
                "constraint_blocks": [{"block_id": "no_such_block", "parameters": {}}],
                "objective": {"block_id": "weighted_service_distance_objective"},
            }
        )


# ---------------------------------------------------------------------------
# Objective extraction (contract-first, no bare-number fallback)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected", "matched"),
    [
        ("Objective: 2210", 2210.0, True),
        ("最优目标值为 2210.0", 2210.0, True),
        ("最优总成本: 174.0 元", 174.0, True),
        ("总共有 42 个城市，最优值为 99", 42.0, False),
        ("解的最优值为 99", 42.0, False),
    ],
)
def test_objective_matching_requires_a_label(text: str, expected: float, matched: bool):
    assert _objective_matches(text, expected) is matched


def test_extraction_prefers_the_contract_line():
    kinds = [kind for kind, _ in _extract_objectives("最优值为 7\nObjective: 2210")]
    assert kinds[0] == "contract"


# ---------------------------------------------------------------------------
# Artifact check (replaying the agent's own script)
# ---------------------------------------------------------------------------


class TestArtifactObjective:
    def test_accepts_a_script_that_reproduces_the_objective(self, tmp_path):
        from benchmarks.run_benchmark import _artifact_objective

        (tmp_path / "solver_a.py").write_text("print('Objective: 2210')", encoding="utf-8")
        ok, note = _artifact_objective(tmp_path, 2210.0)
        assert ok and note == "solver_a.py"

    def test_rejects_a_script_with_a_different_objective(self, tmp_path):
        from benchmarks.run_benchmark import _artifact_objective

        (tmp_path / "solver_a.py").write_text("print('Objective: 1590')", encoding="utf-8")
        ok, note = _artifact_objective(tmp_path, 2210.0)
        assert not ok and "2210" in note

    def test_uses_the_latest_working_script(self, tmp_path):
        from benchmarks.run_benchmark import _artifact_objective

        bad = tmp_path / "solver_old.py"
        bad.write_text("print('Objective: 1590')", encoding="utf-8")
        good = tmp_path / "solver_new.py"
        good.write_text("print('Objective: 2210')", encoding="utf-8")
        ok, note = _artifact_objective(tmp_path, 2210.0)
        assert ok and note == "solver_new.py"

    def test_reports_missing_script(self, tmp_path):
        from benchmarks.run_benchmark import _artifact_objective

        ok, note = _artifact_objective(tmp_path, 2210.0)
        assert not ok and "no solver script" in note


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Error code: 429 - Provider returned error", True),
        ("deepseek/deepseek-chat is temporarily rate-limited upstream", True),
        ("APIConnectionError: Connection error", True),
        ("ValueError: agent produced no final answer", False),
    ],
)
def test_infrastructure_errors_are_classified(message: str, expected: bool):
    from benchmarks.run_benchmark import _is_infrastructure_error

    assert _is_infrastructure_error(message) is expected


def test_agent_workspace_dir_isolates_solver_files(tmp_path, monkeypatch):
    """build_nl2or_agent(workspace_dir=...) 让 run_solver 写到指定目录。"""
    monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o-mini")
    from agents import build_nl2or_agent

    target = tmp_path / "workspace"
    agent = build_nl2or_agent(verbosity_level=0, workspace_dir=target)
    output = agent.tools["run_solver"].forward("print('Objective: 1')")

    assert "[RESULT] Objective: 1" in output
    assert target.is_dir()
    assert list(target.glob("solver_*.py"))
