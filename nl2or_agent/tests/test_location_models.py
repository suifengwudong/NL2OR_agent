"""Semantic checks for the extended location models.

Each test solves one benchmark case and verifies the property the model is
supposed to enforce, so the objective alone is not the only thing locked.
"""

from __future__ import annotations

import pytest

from benchmarks.run_benchmark import _load_cases, _normalized_ir
from core.block_model import solve_ir
from core.ir_validate import validate_problem_ir
from core.what_if import supported_models

NEW_MODELS = (
    "p_median_service_limit",
    "p_median_availability",
    "capacitated_p_center",
    "maximum_covering_budget",
    "capacitated_maximum_covering",
    "p_dispersion",
    "budgeted_facility_location",
)


@pytest.fixture(scope="module")
def cases() -> dict[str, dict]:
    return {case["id"]: case for case in _load_cases()}


def _solve(case: dict):
    result = solve_ir(_normalized_ir(case))
    assert result.status == "Optimal"
    return result


def _value(variables: dict[str, float], name: str) -> float:
    return variables.get(name, 0.0)


def test_service_distance_limit_forbids_long_edges(cases):
    case = cases["p_median_service_limit"]
    ir = _normalized_ir(case)
    result = _solve(case)
    distance = ir["parameters"]["distance"]
    limit = ir["parameters"]["service_distance_limit"]

    for i in range(len(distance)):
        for j in range(len(distance[0])):
            if _value(result.variables, f"x2[{i},{j}]") > 0.5:
                assert distance[i][j] <= limit


def test_service_distance_limit_override_changes_the_optimum(cases):
    case = cases["p_median_service_limit"]
    ir = _normalized_ir(case)

    relaxed = dict(ir)
    relaxed["parameters"] = {**ir["parameters"], "service_distance_limit": 6}
    assert solve_ir(relaxed).objective == pytest.approx(2210.0)

    tight = dict(ir)
    tight["parameters"] = {**ir["parameters"], "service_distance_limit": 4}
    assert solve_ir(tight).status == "Infeasible"


def test_availability_forbids_the_declared_pair(cases):
    case = cases["p_median_availability"]
    ir = _normalized_ir(case)
    result = _solve(case)

    assert ir["parameters"]["availability"][1][1] == 0
    assert _value(result.variables, "x2[1,1]") == 0.0


def test_capacitated_p_center_respects_capacity(cases):
    case = cases["capacitated_p_center"]
    ir = _normalized_ir(case)
    result = _solve(case)
    demand = ir["parameters"]["demand"]
    capacity = ir["parameters"]["facility_capacity"]

    for j in range(len(capacity)):
        load = sum(demand[i] * _value(result.variables, f"x2[{i},{j}]") for i in range(len(demand)))
        opened = _value(result.variables, f"y[{j}]")
        assert load <= capacity[j] * opened + 1e-9


def test_capacitated_maximum_covering_respects_capacity_and_coverage(cases):
    case = cases["capacitated_maximum_covering"]
    ir = _normalized_ir(case)
    result = _solve(case)
    demand = ir["parameters"]["demand"]
    capacity = ir["parameters"]["facility_capacity"]
    coverage = ir["parameters"]["coverage_matrix"]

    for j in range(len(capacity)):
        load = sum(demand[i] * _value(result.variables, f"x2[{i},{j}]") for i in range(len(demand)))
        assert load <= capacity[j] * _value(result.variables, f"y[{j}]") + 1e-9

    for i in range(len(demand)):
        if _value(result.variables, f"z[{i}]") > 0.5:
            assigned = [
                j for j in range(len(capacity)) if _value(result.variables, f"x2[{i},{j}]") > 0.5
            ]
            assert assigned and coverage[i][assigned[0]] == 1


def test_opening_budget_is_respected(cases):
    for case_id in ("maximum_covering_budget", "budgeted_facility_location"):
        case = cases[case_id]
        ir = _normalized_ir(case)
        result = _solve(case)
        fixed = ir["parameters"]["fixed_cost"]
        budget = ir["parameters"]["opening_budget"]
        spent = sum(fixed[j] * _value(result.variables, f"y[{j}]") for j in range(len(fixed)))
        assert spent <= budget + 1e-9


def test_p_dispersion_objective_is_the_minimum_open_pair_distance(cases):
    case = cases["p_dispersion"]
    ir = _normalized_ir(case)
    result = _solve(case)
    distance = ir["parameters"]["facility_distance"]
    opened = [j for j in range(len(distance)) if _value(result.variables, f"y[{j}]") > 0.5]

    assert len(opened) == ir["parameters"]["p"]
    minimum = min(distance[j][k] for index, j in enumerate(opened) for k in opened[index + 1 :])
    assert result.objective == pytest.approx(minimum)


def test_p_dispersion_override_keeps_the_same_semantics(cases):
    case = cases["p_dispersion"]
    ir = _normalized_ir(case)
    for p, expected in ((3, 12.0), (4, 10.0)):
        variant = dict(ir)
        variant["parameters"] = {**ir["parameters"], "p": p}
        result = solve_ir(variant)
        opened = [
            j
            for j in range(len(ir["parameters"]["facility_distance"]))
            if _value(result.variables, f"y[{j}]") > 0.5
        ]
        minimum = min(
            ir["parameters"]["facility_distance"][j][k]
            for index, j in enumerate(opened)
            for k in opened[index + 1 :]
        )
        assert result.objective == pytest.approx(expected)
        assert result.objective == pytest.approx(minimum)


def test_facility_distance_dimension_is_checked():
    report = validate_problem_ir(
        {
            "entities": {"J": {"size": 4}},
            "parameters": {"p": 2, "facility_distance": [[0, 1, 2], [1, 0, 3], [2, 3, 0]]},
            "constraint_blocks": [
                {"block_id": "cardinality_open_p_facilities"},
                {"block_id": "min_pairwise_distance_bound"},
            ],
            "objective": {"block_id": "maximize_min_pairwise_distance_objective"},
        }
    )
    assert not report["valid"]
    assert any("facility_distance" in error for error in report["errors"])


def test_availability_dimension_is_checked():
    report = validate_problem_ir(
        {
            "entities": {"I": {"size": 2}, "J": {"size": 3}},
            "parameters": {
                "p": 1,
                "distance": [[1, 2, 3], [2, 1, 2]],
                "availability": [[1, 1], [1, 1]],
            },
            "constraint_blocks": [
                {"block_id": "assign_each_demand_once"},
                {"block_id": "link_assignment_to_open"},
                {"block_id": "cardinality_open_p_facilities"},
                {"block_id": "assignment_availability"},
            ],
            "objective": {
                "block_id": "weighted_service_distance_objective",
                "parameters": {"distance": "给定"},
            },
        }
    )
    assert not report["valid"]
    assert any("availability" in error for error in report["errors"])


def test_new_models_have_executable_what_if_support():
    supported = {entry["id"] for entry in supported_models()}
    for model_id in NEW_MODELS:
        assert model_id in supported
