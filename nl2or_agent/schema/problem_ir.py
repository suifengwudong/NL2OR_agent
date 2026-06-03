"""Canonical Problem IR alignment with constraint_blocks.json.

Defines alias maps and constants for the Problem IR.
Data structures (TypedDict) live in ``.ir_types``.
Processing logic (normalization, validation) lives in ``core/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .ir_types import (  # noqa: F401
        BlockCatalog,
        ConstraintBlock,
        ObjectiveBlock,
        ProblemFamily,
        ProblemIR,
        ValidationReport,
    )

# Re-export type definitions for backward compatibility
from .ir_types import (  # noqa: F401  (re-export for backward compat)
    BlockCatalog,
    ConstraintBlock,
    ObjectiveBlock,
    ProblemFamily,
    ProblemIR,
    ValidationReport,
)

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
