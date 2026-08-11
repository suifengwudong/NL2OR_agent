"""Tools for Problem IR validation and block-catalog alignment."""

from __future__ import annotations

import json

from hamlet.core.tools import Tool

from core.ir_catalog import load_block_catalog
from core.ir_normalizer import validate_problem_ir


class ListBlockCatalogTool(Tool):
    """List canonical constraint/objective block ids from the library."""

    name = "list_block_catalog"
    description = (
        "Return the canonical block_id list and parameter requirements from "
        "constraint_blocks.json. Call before building Problem IR in Step 1."
    )
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        catalog = load_block_catalog()
        payload = {
            "block_ids": catalog["block_ids"],
            "objective_block_ids": catalog["objective_block_ids"],
            "blocks": [
                {
                    "block_id": b["id"],
                    "category": b.get("category"),
                    "name": b.get("name"),
                    "required_parameters": [
                        p["name"] for p in b.get("parameters", []) if p.get("required")
                    ],
                    "aliases": b.get("aliases", []),
                }
                for b in catalog["blocks"]
            ],
            "usage": (
                "In Problem IR use exact block_id values. "
                "Put non-library rules in custom_constraints, not in constraint_blocks."
            ),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


class ValidateProblemIrTool(Tool):
    """Validate and normalize Problem IR against the block catalog."""

    name = "validate_problem_ir"
    description = (
        "Validate a Problem IR JSON string: normalize block_id aliases to canonical ids, "
        "check required parameters, separate custom_constraints from constraint_blocks. "
        "Always call in Step 1 after building ir, before final_answer."
    )
    inputs = {
        "ir_json": {
            "type": "string",
            "description": "JSON string of the Problem IR dict (from json.dumps(ir)).",
        }
    }
    output_type = "string"

    def forward(self, ir_json: str) -> str:
        try:
            ir = json.loads(ir_json)
        except json.JSONDecodeError as exc:
            return json.dumps(
                {"valid": False, "errors": [f"Invalid JSON: {exc}"], "warnings": []},
                ensure_ascii=False,
                indent=2,
            )
        if not isinstance(ir, dict):
            return json.dumps(
                {
                    "valid": False,
                    "errors": ["IR must be a JSON object"],
                    "warnings": [],
                },
                ensure_ascii=False,
                indent=2,
            )
        report = validate_problem_ir(ir)
        return json.dumps(report, ensure_ascii=False, indent=2)
