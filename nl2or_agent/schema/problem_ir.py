"""Canonical Problem IR — TypedDict definitions, alias maps, and constants.

Processing logic (normalization, validation) lives in ``core/``.
"""

from __future__ import annotations

from typing import TypedDict


# ---------------------------------------------------------------------------
# TypedDict data structures
# ---------------------------------------------------------------------------


class ProblemFamily(TypedDict, total=False):
    id: str
    name: str
    confidence: str
    notes: str


class ConstraintBlock(TypedDict, total=False):
    block_id: str
    category: str
    name: str
    parameters: dict[str, object]
    status: str
    natural_language: str


class ObjectiveBlock(TypedDict, total=False):
    block_id: str
    sense: str
    expression: str
    natural_language: str
    parameters: dict[str, object]


class ProblemIR(TypedDict, total=False):
    problem_families: list[ProblemFamily]
    is_hybrid: bool
    hybrid_notes: str
    parameters: dict[str, object]
    decision_variables: list[object]
    objective: ObjectiveBlock
    constraint_blocks: list[ConstraintBlock]
    custom_constraints: list[str]
    missing_data: list[str]


class ValidationReport(TypedDict):
    valid: bool
    normalized_ir: ProblemIR
    errors: list[str]
    warnings: list[str]
    catalog_block_ids: list[str]


class BlockCatalog(TypedDict):
    blocks: list[dict[str, object]]
    by_id: dict[str, dict[str, object]]
    alias_to_id: dict[str, str]
    block_ids: list[str]
    objective_block_ids: list[str]


# ---------------------------------------------------------------------------
# Aliases and constants
# ---------------------------------------------------------------------------
BLOCK_ID_ALIASES: dict[str, str] = {
    "assignment": "assign_each_demand_once",
    "demand_assignment": "assign_each_demand_once",
    "unique_assignment": "assign_each_demand_once",
    "linking": "link_assignment_to_open",
    "capacity_link": "link_assignment_to_open",
    "cardinality": "cardinality_open_p_facilities",
    "p_facility": "cardinality_open_p_facilities",
    "select_p": "cardinality_open_p_facilities",
    "forcing": "force_facility_open",
    "forcing_open": "force_facility_open",
    "must_open": "force_facility_open",
    "prohibiting": "force_facility_closed",
    "forcing_closed": "force_facility_closed",
    "must_close": "force_facility_closed",
    "force_closed": "force_facility_closed",
    "weighted_distance": "weighted_service_distance_objective",
    "minimize_weighted_distance": "weighted_service_distance_objective",
    "service_distance": "weighted_service_distance_objective",
    "knapsack": "knapsack_capacity",
}

OBJECTIVE_BLOCK_ALIASES: dict[str, str] = {
    "minimize_total_weighted_distance": "weighted_service_distance_objective",
    "weighted_distance": "weighted_service_distance_objective",
    "min_sum_weighted_distance": "weighted_service_distance_objective",
}

FAMILY_ID_ALIASES: dict[str, str] = {
    "p-median": "p_median",
    "p median": "p_median",
    "facility location": "facility_location",
    "facility_location_problem": "facility_location",
}

FORBIDDEN_AS_BLOCK = frozenset({"custom_constraints", "custom", "objective"})

VALID_STATUS = frozenset({"required", "optional", "user_specified"})
