"""Problem IR vocabulary: alias maps and constants.

The IR is a plain dict at the wire boundary; the behaviour lives in
``core/problem_ir.py``.
"""

from __future__ import annotations

OBJECTIVE_BLOCK_ALIASES: dict[str, str] = {
    "minimize_total_weighted_distance": "weighted_service_distance_objective",
    "weighted_distance": "weighted_service_distance_objective",
    "min_sum_weighted_distance": "weighted_service_distance_objective",
    "minimize_service_cost": "service_cost_objective",
    "max_min_distance": "maximize_min_pairwise_distance_objective",
    "maximize_min_distance": "maximize_min_pairwise_distance_objective",
}

FAMILY_ID_ALIASES: dict[str, str] = {
    "p-median": "p_median",
    "p median": "p_median",
    "facility location": "facility_location",
    "facility_location_problem": "facility_location",
    "p-dispersion": "p_dispersion",
    "p dispersion": "p_dispersion",
    "capacitated p-center": "capacitated_p_center",
    "capacitated p center": "capacitated_p_center",
    "p-median with distance limit": "p_median_service_limit",
    "p median with distance limit": "p_median_service_limit",
    "p-median with forbidden assignments": "p_median_availability",
    "maximum covering with budget": "maximum_covering_budget",
    "budgeted facility location": "budgeted_facility_location",
}

FORBIDDEN_AS_BLOCK = frozenset({"custom_constraints", "custom", "objective"})

VALID_STATUS = frozenset({"required", "optional", "user_specified"})
