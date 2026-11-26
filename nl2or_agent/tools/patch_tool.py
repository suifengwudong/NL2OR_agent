"""Tool: create a parameter patch on top of an existing model artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hamlet.core.tools import Tool

from core.problem_ir import ProblemIR
from utils.artifact_store import ArtifactError, ArtifactStore
from utils.session import get_session


class CreateModelPatchTool(Tool):
    """Persist parameter overrides as a small patch artifact."""

    name = "create_model_patch"
    description = (
        "Create a parameter patch (patch_*.json) from an existing model/patch: "
        "base_model_ref + overrides + patched-IR fingerprint + validation verdict. "
        "Use it for what-ifs that only change parameter values. It rejects patches "
        "that change the constraint block set, objective or entities; use "
        "validate_problem_ir for those structural changes. The patch itself is not "
        "solved; pass patch_id as model_artifact_id to solve_ir."
    )
    inputs = {
        "base_model_id": {
            "type": "string",
            "description": "Artifact id of the base model or patch (model_… / patch_…).",
        },
        "overrides_json": {
            "type": "string",
            "description": "Object (or JSON string) of top-level parameter overrides.",
        },
        "name": {
            "type": "string",
            "nullable": True,
            "description": "Logical scenario name; omit to auto-name patch/patch_2/…",
        },
        "revise": {
            "type": "boolean",
            "nullable": True,
            "description": "Append a new version under the same name; old versions are kept.",
        },
        "overwrite": {
            "type": "boolean",
            "nullable": True,
            "description": "Alias for revise=True.",
        },
    }
    output_type = "string"

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        super().__init__()
        self._workspace: Path | None = Path(workspace_dir) if workspace_dir else None

    def forward(
        self,
        base_model_id: str,
        overrides_json: str | dict[str, Any],
        name: str | None = None,
        revise: bool | None = False,
        overwrite: bool | None = None,
    ) -> str:
        try:
            overrides = ProblemIR.parse_overrides(overrides_json)
            store = ArtifactStore(self._root())
            patch = store.save_model_patch(
                base_model_id,
                overrides,
                name=name,
                revise=bool(revise),
                overwrite=overwrite,
            )
        except (ArtifactError, ValueError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        return json.dumps(
            {
                "ok": True,
                "patch": {
                    "artifact_id": patch.artifact_id,
                    "name": patch.name,
                    "revision": patch.revision,
                    "fingerprint": patch.fingerprint,
                    "base_model_ref": patch.base_model_ref.to_dict()
                    if patch.base_model_ref
                    else None,
                    "validation": patch.validation,
                },
            },
            ensure_ascii=False,
            indent=2,
        )

    def _root(self) -> Path:
        return self._workspace if self._workspace is not None else get_session().workspace
