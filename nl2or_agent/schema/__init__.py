"""Problem IR schema — data definitions (TypedDicts, constants, aliases).

Processing logic (normalization, validation, catalog) lives in core/.
"""

from .problem_ir import (
    BLOCK_ID_ALIASES,
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
    "BLOCK_ID_ALIASES",
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


# ---------------------------------------------------------------------------
# Lazy proxies for backward compatibility
# ---------------------------------------------------------------------------

_LAZY_EXPORTS = {
    "catalog_markdown",
    "load_block_catalog",
    "load_model_bank",
    "normalize_problem_ir",
    "validate_problem_ir",
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        import core

        return getattr(core, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
