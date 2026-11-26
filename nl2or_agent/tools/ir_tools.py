"""Tool: validate and persist the Problem IR, plus the math document renderer."""

from __future__ import annotations

import json
from pathlib import Path

from hamlet.core.tools import Tool

from core.ir_validate import validate_problem_ir
from core.model_document import render_model_document
from core.problem_ir import ProblemIR
from utils.artifact_store import ArtifactError, ArtifactStore
from utils.session import get_session


class ValidateProblemIrTool(Tool):
    """Validate and normalize Problem IR against the block catalog."""

    name = "validate_problem_ir"
    description = (
        "Validate a Problem IR JSON string: normalize block_id aliases to canonical ids, "
        "check required parameters, separate custom_constraints from constraint_blocks, "
        "and check the model skeleton (constraint blocks required by the declared "
        "family/model, block dependencies, objective block and its optimization direction). "
        "The report carries errors, warnings and a `skeleton` summary. "
        "It also stores one immutable model version and returns its artifact id/name/"
        "revision/fingerprint. Same name + same content is idempotent; changing an "
        "existing name requires revise=True (or overwrite=True as an alias), which "
        "appends a new version instead of deleting history."
    )
    inputs = {
        "ir_json": {
            "type": "string",
            "description": "JSON string of the Problem IR dict (from json.dumps(ir)).",
        },
        "name": {
            "type": "string",
            "nullable": True,
            "description": (
                "Logical model name. Omit to auto-name: the first valid model becomes "
                "baseline; later models become scenario/scenario_2/…"
            ),
        },
        "kind": {
            "type": "string",
            "nullable": True,
            "description": "baseline / scenario (default scenario). Descriptive only.",
        },
        "baseline": {
            "type": "boolean",
            "nullable": True,
            "description": "Set this valid model as the session baseline. Invalid models are rejected.",
        },
        "revise": {
            "type": "boolean",
            "nullable": True,
            "description": "Append a new version under the same logical name; old versions are kept.",
        },
        "overwrite": {
            "type": "boolean",
            "nullable": True,
            "description": "Alias for revise=True; never deletes old versions.",
        },
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        # None 时把模型写进当前会话目录（生产路径），显式给出时写进该目录（测试/评测）
        self._workspace: Path | None = Path(workspace_dir) if workspace_dir else None

    def forward(
        self,
        ir_json: str,
        name: str | None = None,
        kind: str | None = "scenario",
        baseline: bool | None = False,
        revise: bool | None = False,
        overwrite: bool | None = None,
    ) -> str:
        try:
            ir = ProblemIR.parse(ir_json)
        except ValueError as exc:
            return json.dumps(
                {"valid": False, "errors": [str(exc)], "warnings": []},
                ensure_ascii=False,
                indent=2,
            )
        report = validate_problem_ir(ir.data)
        payload = dict(report)
        store = ArtifactStore(self._root())
        try:
            artifact = store.save_model_artifact(
                report,
                name=name,
                kind=kind or "scenario",
                baseline=bool(baseline),
                revise=bool(revise),
                overwrite=overwrite,
            )
        except ArtifactError as exc:
            payload["artifact_error"] = str(exc)
        else:
            baseline_model = store.get_baseline_model()
            is_baseline = (
                baseline_model is not None and baseline_model.artifact_id == artifact.artifact_id
            )
            payload["artifact"] = {
                "artifact_id": artifact.artifact_id,
                "name": artifact.name,
                "revision": artifact.revision,
                "kind": artifact.kind,
                "validation_status": artifact.validation_status,
                "fingerprint": artifact.fingerprint,
                "is_baseline": is_baseline,
            }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _root(self) -> Path:
        return self._workspace if self._workspace is not None else get_session().workspace


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
            ir = ProblemIR.parse(ir_json)
        except ValueError as exc:
            return f"无法生成数学模型：{exc}"
        report = validate_problem_ir(ir.data)
        document = render_model_document(report["normalized_ir"])
        if report["errors"]:
            return "校验未通过，以下文档仅供排查：\n\n" + document
        return document
