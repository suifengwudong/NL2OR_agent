"""Tools for Problem IR validation and block-catalog alignment."""

from __future__ import annotations

import json
from pathlib import Path

from hamlet.core.tools import Tool

from core.ir_catalog import load_block_catalog
from core.ir_validate import validate_problem_ir
from core.model_document import render_model_document
from core.problem_ir import ProblemIR
from utils.session import get_session, write_model_of_record


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
            "objective_sense": catalog["objective_sense"],
            "blocks": [
                {
                    "block_id": b["id"],
                    "category": b.get("category"),
                    "name": b.get("name"),
                    "required_parameters": [
                        p["name"] for p in b.get("parameters", []) if p.get("required")
                    ],
                    "requires_one_of": b.get("requires_one_of", []),
                    "aliases": b.get("aliases", []),
                }
                for b in catalog["blocks"]
            ],
            "usage": (
                "In Problem IR use exact block_id values. "
                "Put non-library rules in custom_constraints, not in constraint_blocks. "
                "objective.block_id must be one of objective_block_ids, and objective.sense "
                "must match objective_sense."
            ),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


class ValidateProblemIrTool(Tool):
    """Validate and normalize Problem IR against the block catalog."""

    name = "validate_problem_ir"
    description = (
        "Validate a Problem IR JSON string: normalize block_id aliases to canonical ids, "
        "check required parameters, separate custom_constraints from constraint_blocks, "
        "and check the model skeleton (constraint blocks required by the declared "
        "family/model, block dependencies, objective block and its optimization direction). "
        "The report carries errors, warnings and a `skeleton` summary. "
        "Always call in Step 1 after building ir, before final_answer."
    )
    inputs = {
        "ir_json": {
            "type": "string",
            "description": "JSON string of the Problem IR dict (from json.dumps(ir)).",
        }
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        # None 时把模型写进当前会话目录（生产路径），显式给出时写进该目录（测试/评测）
        self._workspace: Path | None = Path(workspace_dir) if workspace_dir else None

    def forward(self, ir_json: str) -> str:
        try:
            ir = ProblemIR.parse(ir_json)
        except ValueError as exc:
            return json.dumps(
                {"valid": False, "errors": [str(exc)], "warnings": []},
                ensure_ascii=False,
                indent=2,
            )
        report = validate_problem_ir(ir.data)
        self._save_model(report)
        return json.dumps(report, ensure_ascii=False, indent=2)

    def _save_model(self, report: dict) -> None:
        """记录本次校验的模型：IR 是内容的载体，前端与后续对照都以它为准。"""
        target = self._workspace if self._workspace is not None else get_session().workspace
        write_model_of_record(target / "model.json", report)


class ModelMathTool(Tool):
    """Render the validated Problem IR as a Markdown + LaTeX model document."""

    name = "model_math"
    description = (
        "Render the Problem IR as a complete mathematical model in Markdown with LaTeX: "
        "index sets, parameters, decision variables, objective and every constraint. "
        "Call it after validate_problem_ir and include the returned document in the "
        "formal-model section of the final answer. Input: ir_json (the Problem IR dict "
        "or its JSON string)."
    )
    inputs = {
        "ir_json": {
            "type": "string",
            "description": "JSON string of the Problem IR dict (from json.dumps(ir)).",
        }
    }
    output_type = "string"

    def forward(self, ir_json: str | dict) -> str:
        try:
            ir = ProblemIR.parse(ir_json).normalized
        except ValueError as exc:
            return f"无法生成数学模型：{exc}"
        return render_model_document(ir.data)
