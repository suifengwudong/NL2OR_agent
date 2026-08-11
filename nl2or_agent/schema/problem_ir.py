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
