"""Problem IR schema and block-catalog alignment."""

from .problem_ir import (
    BLOCK_ID_ALIASES,
    load_block_catalog,
    normalize_problem_ir,
    validate_problem_ir,
)

__all__ = [
    "BLOCK_ID_ALIASES",
    "load_block_catalog",
    "normalize_problem_ir",
    "validate_problem_ir",
]
