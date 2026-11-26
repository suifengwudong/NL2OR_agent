"""Tool: solve a Problem IR or an existing model/patch artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hamlet.core.tools import Tool

from core.block_model import (
    describe_model,
    format_solution,
    prepare_overrides,
    render_script,
)
from core.block_model import solve_ir as solve_problem_ir
from core.ir_validate import validate_problem_ir
from core.problem_ir import ProblemIR, fingerprint
from core.report import default_report_spec, render_report
from utils.artifact_store import ArtifactError, ArtifactStore, ModelRef
from utils.session import get_session, save_code_file

_SCRIPT_NAME = "solver_from_ir.py"


def _numeric_variables(variables: dict[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in (variables or {}).items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


class SolveIrTool(Tool):
    """Solve a Problem IR, a full model artifact or a parameter patch."""

    name = "solve_ir"
    description = (
        "Solve a Problem IR deterministically from the library's block semantics, or "
        "solve an existing model/patch artifact via model_artifact_id. This tool only "
        "solves and writes a solve artifact; it never creates model/patch files. "
        "Pass model_artifact_id (model_… / patch_…) for a named what-if; otherwise pass "
        "ir_json and optional overrides_json. A solve with overrides but no matching "
        "artifact is stored as unassociated (with the overrides recorded), not silently "
        "attached. Every call writes one immutable solve_*.json."
    )
    inputs = {
        "ir_json": {
            "type": "string",
            "nullable": True,
            "description": "Problem IR as a dict or JSON string; omit when model_artifact_id is given.",
        },
        "overrides_json": {
            "type": "string",
            "nullable": True,
            "description": 'Top-level parameter overrides, e.g. {"demand": [...]}; omit for baseline.',
        },
        "name": {
            "type": "string",
            "nullable": True,
            "description": "Logical solve name; defaults to the linked model name or solve_N.",
        },
        "model_artifact_id": {
            "type": "string",
            "nullable": True,
            "description": "Model/patch artifact id to solve (model_… / patch_…).",
        },
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        self._workspace: Path | None = Path(workspace_dir) if workspace_dir else None

    def forward(
        self,
        ir_json: str | dict[str, Any] | None = None,
        overrides_json: str | dict[str, Any] | None = None,
        name: str | None = None,
        model_artifact_id: str | None = None,
    ) -> str:
        store = ArtifactStore(self._root())
        try:
            artifact = None
            overrides: dict[str, Any] = {}
            base_model = None
            if model_artifact_id:
                artifact = store.load_model_artifact(model_artifact_id)
                if overrides_json:
                    raise ValueError("指定 model_artifact_id 时不要再传 overrides；补丁已包含覆盖")
                normalized = store.effective_ir(artifact)
                if ir_json is not None:
                    parsed = ProblemIR.parse(ir_json)
                    if fingerprint(parsed.data) != artifact.fingerprint:
                        raise ValueError("ir_json 与 model_artifact_id 的指纹不一致")
                solved = ProblemIR(normalized)
                base = solved
            else:
                if ir_json is None:
                    raise ValueError("需要 ir_json 或 model_artifact_id")
                parsed = ProblemIR.parse(ir_json)
                report = validate_problem_ir(parsed.data)
                if report["errors"]:
                    return "无法求解：" + "；".join(report["errors"])
                base = ProblemIR(report["normalized_ir"])
                overrides = prepare_overrides(base.data, overrides_json)
                solved = base.with_overrides(overrides)
                if overrides:
                    patched_report = validate_problem_ir(solved.data)
                    if patched_report["errors"]:
                        return "无法求解：" + "；".join(patched_report["errors"])
                    solved = ProblemIR(patched_report["normalized_ir"])
                    matches = store.find_models_by_fingerprint(
                        fingerprint(base.data), valid_only=True
                    )
                    if len(matches) == 1:
                        base_model = matches[0]
                else:
                    solved = base

            result = solve_problem_ir(solved.data)
        except (ArtifactError, ValueError) as exc:
            return f"无法求解：{exc}"

        spec = default_report_spec(solved.data)
        if overrides:
            spec["tables"] = ["objective_breakdown"]
        solution_text = format_solution(result, overrides)
        report_text = render_report(solved.data, result, spec=spec)
        parts = [describe_model(base.data), solution_text, report_text]

        solve_artifact = None
        try:
            solve_artifact = store.save_solve_artifact(
                solved.data,
                status=result.status,
                objective=result.objective,
                text=f"{solution_text}\n\n{report_text}",
                name=name or None,
                model_artifact_id=artifact.artifact_id if artifact is not None else None,
                variables=_numeric_variables(result.variables),
                overrides=overrides,
                base_model_ref=(
                    ModelRef(base_model.artifact_id, base_model.name, base_model.fingerprint)
                    if base_model is not None
                    else None
                ),
            )
            parts.append(
                f"求解 artifact：{solve_artifact.artifact_id}"
                f"（name={solve_artifact.name}，{solve_artifact.association_status}）"
            )
        except ArtifactError as exc:
            parts.append(f"求解 artifact 未保存：{exc}")

        baseline = store.get_baseline_model()
        linked_to_baseline = (
            solve_artifact is not None
            and solve_artifact.model_ref is not None
            and baseline is not None
            and solve_artifact.model_ref.artifact_id == baseline.artifact_id
        )
        if not overrides and artifact is None and (linked_to_baseline or not store.has_models()):
            # Transitional compatibility: only the baseline keeps the old files.
            parts.append(f"脚本：{self._save_script(solved.data)}")
            self._save_solve_result(solved.data, solution_text, report_text)
        return "\n\n".join(parts)

    def _root(self) -> Path:
        return self._workspace if self._workspace is not None else get_session().workspace

    def _save_script(self, ir: dict[str, Any]) -> Path:
        directory = self._workspace if self._workspace is not None else get_session().code_dir
        return save_code_file(directory, render_script(ir), _SCRIPT_NAME)

    def _save_solve_result(self, ir: dict[str, Any], solution: str, report: str) -> None:
        target = (
            self._workspace / "solve_result.json"
            if self._workspace is not None
            else get_session().solve_result_file
        )
        payload = {
            "ir_fingerprint": fingerprint(ir),
            "text": f"{solution}\n\n{report}",
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
