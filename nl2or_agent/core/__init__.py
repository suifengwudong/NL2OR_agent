"""Core processing logic for Problem IR normalization, validation, and catalog management.

This module separates the "processing engine" from the "data definition" layer (schema/).
Schema defines what the IR looks like; core implements how it is transformed and validated.
"""

from .ir_processor import (
    catalog_markdown,
    load_block_catalog,
    load_model_bank,
    normalize_problem_ir,
    validate_problem_ir,
)

__all__ = [
    "catalog_markdown",
    "load_block_catalog",
    "load_model_bank",
    "normalize_problem_ir",
    "validate_problem_ir",
]
