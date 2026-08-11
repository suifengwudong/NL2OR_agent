"""Problem IR schema — TypedDict definitions, alias maps, and constants.

Processing logic (normalization, validation) lives in ``core/``.
"""

from .problem_ir import (
    BlockCatalog,
    ConstraintBlock,
    FAMILY_ID_ALIASES,
    FORBIDDEN_AS_BLOCK,
    OBJECTIVE_BLOCK_ALIASES,
    ObjectiveBlock,
    ProblemFamily,
    ProblemIR,
    VALID_STATUS,
    ValidationReport,
)

__all__ = [
    "BlockCatalog",
    "ConstraintBlock",
    "FAMILY_ID_ALIASES",
    "FORBIDDEN_AS_BLOCK",
    "OBJECTIVE_BLOCK_ALIASES",
    "ObjectiveBlock",
    "ProblemFamily",
    "ProblemIR",
    "VALID_STATUS",
    "ValidationReport",
]
