"""Regression: the offline IR + solver benchmark tiers must stay green in CI.

Guards the IR normalization pipeline and the ``RunSolverTool`` execution path
across all block-structured problem families (p-median, set covering, max
covering, p-center, UFLP, knapsack) plus real OR-Library p-median instances.
"""

from __future__ import annotations

import pytest

from benchmarks.run_benchmark import _load_cases, run_offline, run_solver


@pytest.fixture(scope="module")
def cases():
    return _load_cases()


@pytest.fixture(scope="module")
def offline_report(cases):
    return run_offline(cases)


@pytest.fixture(scope="module")
def solver_report(cases):
    return run_solver(cases)


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


@pytest.mark.parametrize("case_id", ["p_median_community", "knapsack_gadget"])
def test_offline_covers_block_structured_families(offline_report, case_id: str):
    case_results = [r for r in offline_report["results"] if r["case_id"] == case_id]
    assert case_results and case_results[0]["passed"]


@pytest.mark.parametrize("case_id", ["p_median_community", "pmed_1"])
def test_solver_matches_reference_objective(solver_report, case_id: str):
    case_results = [r for r in solver_report["results"] if r["case_id"] == case_id]
    assert case_results and case_results[0]["passed"]
