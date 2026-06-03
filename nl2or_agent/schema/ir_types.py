"""Problem IR data structures (TypedDict definitions).

Separated from problem_ir.py to keep pure type definitions isolated from
alias constants.
"""

from __future__ import annotations

from typing import TypedDict


class ProblemFamily(TypedDict, total=False):
    """A problem family entry in the IR."""

    id: str
    name: str
    confidence: str  # "high" | "medium" | "low"
    notes: str


class ConstraintBlock(TypedDict, total=False):
    """A normalized constraint block in the IR."""

    block_id: str
    category: str
    name: str
    parameters: dict[str, object]
    status: str  # "required" | "optional" | "user_specified"
    natural_language: str


class ObjectiveBlock(TypedDict, total=False):
    """A normalized objective block in the IR."""

    block_id: str
    sense: str  # "minimize" | "maximize"
    expression: str
    natural_language: str
    parameters: dict[str, object]


class ProblemIR(TypedDict, total=False):
    """The complete Problem IR shape after normalization."""

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
    """Validation report returned by validate_problem_ir()."""

    valid: bool
    normalized_ir: ProblemIR
    errors: list[str]
    warnings: list[str]
    catalog_block_ids: list[str]


class BlockCatalog(TypedDict):
    """Block catalog with lookup indices."""

    blocks: list[dict[str, object]]
    by_id: dict[str, dict[str, object]]
    alias_to_id: dict[str, str]
    block_ids: list[str]
    objective_block_ids: list[str]
