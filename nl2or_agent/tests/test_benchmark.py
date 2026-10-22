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
    TIERS,
    _extract_objectives,
    _format_report,
    _load_cases,
    _normalize_case,
    _normalized_ir,
    _objective_matches,
    run_offline,
    run_solver,
    run_what_if,
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
        assert set(case["tiers"]) <= set(TIERS)
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
    ["p_median_community", "knapsack_gadget", "uflp_cap71", "cflp_cap61"],
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
        "cflp_cap61",
        "cappmed_1",
        "cappmed_emergency_network",
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


def test_every_executable_block_declares_its_readable_keys():
    """新增块时必须登记它读取的参数键，否则覆盖会一律被拒。"""
    from core.block_model import CONSTRAINT_BUILDERS, OBJECTIVE_BUILDERS, READ_BLOCK_KEYS

    assert set(READ_BLOCK_KEYS) == set(CONSTRAINT_BUILDERS) | set(OBJECTIVE_BUILDERS)


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


def test_agent_workspace_dir_reaches_solve_ir(tmp_path, monkeypatch, cases):
    """快路径的脚本也要落进指定的 workspace，评测的回放才找得到。"""
    monkeypatch.setenv("HAMLET_MODEL_ID", "openai/gpt-4o-mini")
    from agents import build_nl2or_agent

    case = next(c for c in cases if c["id"] == "p_median_community")
    agent = build_nl2or_agent(verbosity_level=0, workspace_dir=tmp_path)
    output = agent.tools["solve_ir"].forward(_normalized_ir(case), None)

    assert "[RESULT] Objective: 2210" in output
    assert (tmp_path / "solver_from_ir.py").is_file()


# ---------------------------------------------------------------------------
# what_if tier (baseline + declared parameter scenarios)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def what_if_report(cases):
    return run_what_if(cases)


def _synthetic_what_if(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": "synthetic",
        "problem": "x",
        "family": "p_median",
        "tiers": ["ir", "what_if"],
        "solver_objective": 0.0,
        "input_ir": {
            "entities": {"I": {"size": 1}, "J": {"size": 1}},
            "parameters": {"p": 1, "demand": [1], "distance": [[0]]},
            "constraint_blocks": [{"block_id": "assign_each_demand_once", "parameters": {}}],
            "objective": {
                "block_id": "weighted_service_distance_objective",
                "sense": "minimize",
            },
        },
        "expected": {"valid": True},
        "scenarios": [{"id": "s", "overrides": {"p": 1}, "expected_objective": 0}],
    }
    raw.update(overrides)
    return raw


def test_all_what_if_cases_pass(what_if_report):
    assert what_if_report["passed"] == what_if_report["total"], (
        f"{what_if_report['passed']}/{what_if_report['total']} cases passed. "
        "Run `uv run python benchmarks/run_benchmark.py --mode what_if` for details."
    )


def test_what_if_metadata_is_declared_consistently(cases):
    with_scenarios = [c for c in cases if c["scenarios"]]
    assert len(with_scenarios) >= 5, "至少应有 5 个用例带情景"
    for case in cases:
        assert ("what_if" in case["tiers"]) is bool(case["scenarios"]), (
            f"{case['id']} 的 what_if 层与 scenarios 不一致"
        )
        for scenario in case["scenarios"]:
            has_objective = "expected_objective" in scenario
            assert has_objective != ("expected_status" in scenario)


def test_what_if_includes_an_infeasible_scenario(cases):
    infeasible = [
        (case["id"], scenario["id"])
        for case in cases
        for scenario in case["scenarios"]
        if "expected_status" in scenario
    ]
    assert infeasible, "至少要有一个不可行的情景，用来锁住「不可行不被跳过」"


def test_every_scenario_override_is_accepted_by_its_model(cases):
    """每个情景的覆盖键与值的形状都要通过该用例模型自己的校验。"""
    from core.block_model import prepare_overrides

    for case in cases:
        if not case["scenarios"]:
            continue
        ir = _normalized_ir(case)
        for scenario in case["scenarios"]:
            prepare_overrides(ir, scenario["overrides"])


def test_what_if_rows_carry_their_expectation(what_if_report):
    """报告行同构，且带回期望值，失败时才能就地解释。"""
    for result in what_if_report["results"]:
        for row in result["scenarios"]:
            assert set(row) == {
                "id",
                "passed",
                "status",
                "objective",
                "overrides",
                "expected",
                "detail",
            }
            if isinstance(row["expected"], str):
                assert row["status"] == row["expected"]
            else:
                assert row["objective"] == pytest.approx(row["expected"])


def test_what_if_reports_infeasible_status(what_if_report):
    result = next(r for r in what_if_report["results"] if r["case_id"] == "p_median_community")
    row = next(r for r in result["scenarios"] if "p=6" in r["id"])

    assert row["status"] == "Infeasible"


def test_what_if_tier_requires_scenarios():
    with pytest.raises(ValueError, match="没有 scenarios"):
        _normalize_case(_synthetic_what_if(scenarios=[]), "test")


def test_scenarios_without_the_tier_are_rejected():
    with pytest.raises(ValueError, match="没有声明 what_if 层"):
        _normalize_case(_synthetic_what_if(tiers=["ir"]), "test")


@pytest.mark.parametrize(
    "scenario",
    [
        {"id": "s", "overrides": {"p": 2}},
        {
            "id": "s",
            "overrides": {"p": 2},
            "expected_objective": 1,
            "expected_status": "Optimal",
        },
    ],
)
def test_what_if_scenario_needs_exactly_one_expectation(scenario: dict[str, object]):
    with pytest.raises(ValueError, match="expected_objective / expected_status"):
        _normalize_case(_synthetic_what_if(scenarios=[scenario]), "test")


def test_what_if_scenario_ids_must_be_unique():
    scenarios = [
        {"id": "s", "overrides": {"p": 1}, "expected_objective": 0},
        {"id": "s", "overrides": {"p": 2}, "expected_objective": 0},
    ]

    with pytest.raises(ValueError, match="重复"):
        _normalize_case(_synthetic_what_if(scenarios=scenarios), "test")


@pytest.mark.parametrize("status", ["Infeasable", 3])
def test_what_if_expected_status_must_be_a_known_status(status: object):
    scenario = {"id": "s", "overrides": {"p": 1}, "expected_status": status}

    with pytest.raises(ValueError, match="expected_status 必须是"):
        _normalize_case(_synthetic_what_if(scenarios=[scenario]), "test")


def test_what_if_expected_objective_must_be_numeric():
    scenario = {"id": "s", "overrides": {"p": 1}, "expected_objective": "2400"}

    with pytest.raises(ValueError, match="必须是数值"):
        _normalize_case(_synthetic_what_if(scenarios=[scenario]), "test")


def test_what_if_requires_a_declared_baseline():
    raw = _synthetic_what_if()
    del raw["solver_objective"]

    with pytest.raises(ValueError, match="没有 solver_objective"):
        _normalize_case(raw, "test")


def test_non_positive_cases_cannot_enter_the_what_if_tier():
    raw = _synthetic_what_if(expected={"valid": False, "error_contains": ["x"]})

    with pytest.raises(ValueError, match="不应进入求解层"):
        _normalize_case(raw, "test")


def test_unknown_override_key_fails_the_row_rather_than_passing_silently():
    """情景走的是与 solve_ir 工具同一套覆盖校验：不认识的键不会静默放过。"""
    case = _normalize_case(
        _synthetic_what_if(
            scenarios=[{"id": "typo", "overrides": {"pp": 2}, "expected_objective": 0}]
        ),
        "test",
    )

    row = run_what_if([case])["results"][0]["scenarios"][0]

    assert not row["passed"]
    assert row["status"] is None
    assert "不支持的参数" in row["detail"]


def test_key_the_model_does_not_read_fails_the_row(cases):
    case = next(c for c in cases if c["id"] == "p_median_community")
    case = {
        **case,
        "scenarios": [{"id": "容量", "overrides": {"capacity": 10}, "expected_objective": 2210.0}],
    }

    row = run_what_if([case])["results"][0]["scenarios"][0]

    assert not row["passed"]
    assert "capacity" in row["detail"]


def test_wrong_length_override_value_fails_the_row(cases):
    case = next(c for c in cases if c["id"] == "knapsack_gadget")
    case = {
        **case,
        "scenarios": [
            {"id": "重量只写了两项", "overrides": {"weight": [10, 20]}, "expected_objective": 280.0}
        ],
    }

    row = run_what_if([case])["results"][0]["scenarios"][0]

    assert not row["passed"]
    assert "长度 3" in row["detail"]


def test_baseline_solve_failure_is_a_case_failure_not_a_crash():
    case = _normalize_case(
        _synthetic_what_if(
            solver_objective=1.0,
            input_ir={
                "entities": {"I": {"size": 1}, "J": {"size": 1}},
                "parameters": {"p": 1},
                "constraint_blocks": [{"block_id": "assign_each_demand_once", "parameters": {}}],
                "objective": {
                    "block_id": "weighted_service_distance_objective",
                    "sense": "minimize",
                },
            },
            scenarios=[{"id": "p=2", "overrides": {"p": 1}, "expected_objective": 1}],
        ),
        "test",
    )

    report = run_what_if([case])
    result = report["results"][0]

    assert report["passed"] == 0
    assert not result["passed"]
    assert "基准求解失败" in result["detail"]


def test_report_prints_the_reason_for_a_failing_scenario(cases, capsys):
    case = next(c for c in cases if c["id"] == "knapsack_gadget")
    case = {
        **case,
        "scenarios": [
            {"id": "重量只写了两项", "overrides": {"weight": [10, 20]}, "expected_objective": 280.0}
        ],
    }

    _format_report(run_what_if([case]), False)
    output = capsys.readouterr().out

    assert "← 不符" in output
    assert "长度 3" in output
