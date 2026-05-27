"""Core processing logic for Problem IR normalization, validation, and catalog management.

This module separates the "processing engine" from the "data definition" layer (schema/).
Schema defines what the IR looks like; core implements how it is transformed and validated.
"""

from .ir_processor import (
    catalog_markdown,
    load_block_catalog,
    load_model_bank,
    normalize_problem_ir,
)
from .ir_validator import validate_problem_ir
from .output_format import (
    extract_json_payload,
    format_for_display,
    validate_payload_dict,
)
from .prompt_loader import load_system_prompt

__all__ = [
    "catalog_markdown",
    "extract_json_payload",
    "format_for_display",
    "load_block_catalog",
    "load_model_bank",
    "load_system_prompt",
    "normalize_problem_ir",
    "validate_payload_dict",
    "validate_problem_ir",
]
