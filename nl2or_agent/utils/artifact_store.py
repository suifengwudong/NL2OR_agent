"""Session-scoped artifact store for models, parameter patches and solve results.

Minimal layout (no index, no pointer files)::

    sessions/<sid>/artifacts/
        model_<id>.json      # full model: report.normalized_ir
        patch_<id>.json      # parameter patch: base_model_ref + overrides
        solve_<id>.json      # solve result, optionally linked to model/patch
        state.json           # baseline_model / baseline_solve

Files are scanned on demand; sessions are small enough that a cache/index would
only add consistency bugs.  Legacy ``model.json`` / ``solve_result.json`` are
read as synthetic artifacts and never rewritten.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.ir_validate import validate_problem_ir
from core.problem_ir import fingerprint as ir_fingerprint

if TYPE_CHECKING:
    from utils.session import Session

FINGERPRINT_ALGO = "md5"
_LOCK = threading.RLock()
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
_OBJECTIVE_RE = re.compile(r"\[RESULT\]\s*Objective:\s*([-+]?\d+(?:\.\d+)?)")


class ArtifactError(Exception):
    """Base class for artifact-store errors."""


class ArtifactNameConflict(ArtifactError):
    """The logical name exists with different content or representation."""

    def __init__(self, name: str, current_id: str, detail: str = "") -> None:
        suffix = f"（当前 {current_id}{('，' + detail) if detail else ''}）"
        super().__init__(
            f"模型名称 {name!r} 已存在{suffix}；"
            "如需在同一名称下追加新版本，请使用 revise=True；否则请换一个名称。"
        )
        self.name = name
        self.current_id = current_id


class ArtifactLinkError(ArtifactError):
    """A solve result cannot be linked to the requested artifact."""


class ArtifactNotFound(ArtifactError):
    """The requested artifact does not exist."""


@dataclass(frozen=True)
class ModelRef:
    artifact_id: str
    name: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ModelRef | None":
        if not data:
            return None
        return cls(
            artifact_id=str(data.get("artifact_id") or ""),
            name=str(data.get("name") or ""),
            fingerprint=str(data.get("fingerprint") or ""),
        )


@dataclass
class ModelArtifact:
    artifact_id: str
    name: str
    revision: int
    kind: str  # baseline | scenario | parameter_patch | legacy
    validation_status: str  # valid | invalid | unvalidated
    saved_at: str
    fingerprint: str
    fingerprint_algo: str = FINGERPRINT_ALGO
    source: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    base_model_ref: ModelRef | None = None
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def is_patch(self) -> bool:
        return self.kind == "parameter_patch"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.base_model_ref is not None:
            data["base_model_ref"] = self.base_model_ref.to_dict()
        else:
            data.pop("base_model_ref", None)
        if self.report is None:
            data.pop("report", None)
        if self.validation is None:
            data.pop("validation", None)
        if not self.overrides:
            data.pop("overrides", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelArtifact":
        report = data.get("report")
        validation = data.get("validation")
        status = str(data.get("validation_status") or "")
        if not status:
            source = validation if isinstance(validation, dict) else report
            status = "valid" if isinstance(source, dict) and source.get("valid") else "invalid"
        return cls(
            artifact_id=str(data["artifact_id"]),
            name=str(data["name"]),
            revision=int(data.get("revision") or 1),
            kind=str(data.get("kind") or "scenario"),
            validation_status=status,
            saved_at=str(data.get("saved_at") or ""),
            fingerprint=str(data.get("fingerprint") or ""),
            fingerprint_algo=str(data.get("fingerprint_algo") or FINGERPRINT_ALGO),
            source=dict(data.get("source") or {}),
            report=report if isinstance(report, dict) else None,
            validation=validation if isinstance(validation, dict) else None,
            base_model_ref=ModelRef.from_dict(data.get("base_model_ref")),
            overrides=dict(data.get("overrides") or {}),
        )


@dataclass
class SolveArtifact:
    artifact_id: str
    name: str
    revision: int
    saved_at: str
    model_ref: ModelRef | None
    association_status: str  # linked | ambiguous | unassociated
    ir_fingerprint: str
    fingerprint_algo: str = FINGERPRINT_ALGO
    status: str = "Unknown"
    objective: float | None = None
    result: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    base_model_ref: ModelRef | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["model_ref"] = self.model_ref.to_dict() if self.model_ref else None
        data["base_model_ref"] = self.base_model_ref.to_dict() if self.base_model_ref else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SolveArtifact":
        objective = data.get("objective")
        return cls(
            artifact_id=str(data["artifact_id"]),
            name=str(data["name"]),
            revision=int(data.get("revision") or 1),
            saved_at=str(data.get("saved_at") or ""),
            model_ref=ModelRef.from_dict(data.get("model_ref")),
            association_status=str(
                data.get("association_status")
                or ("linked" if data.get("model_ref") else "unassociated")
            ),
            ir_fingerprint=str(data.get("ir_fingerprint") or ""),
            fingerprint_algo=str(data.get("fingerprint_algo") or FINGERPRINT_ALGO),
            status=str(data.get("status") or "Unknown"),
            objective=float(objective) if isinstance(objective, (int, float)) else None,
            result=dict(data.get("result") or {}),
            source=dict(data.get("source") or {}),
            overrides=dict(data.get("overrides") or {}),
            base_model_ref=ModelRef.from_dict(data.get("base_model_ref")),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_name(name: str) -> str:
    value = str(name).strip()
    if not value:
        raise ArtifactError("name 不能为空")
    if not _SAFE_NAME.match(value):
        raise ArtifactError("name 只能包含字母、数字、下划线、短横线或中文")
    return value


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _status_from_text(text: str) -> str:
    if "状态：不可行" in text or "Infeasible" in text:
        return "Infeasible"
    if "状态：无界" in text or "Unbounded" in text:
        return "Unbounded"
    if "状态：最优" in text or "[RESULT]" in text:
        return "Optimal"
    return "Unknown"


def _objective_from_text(text: str) -> float | None:
    match = _OBJECTIVE_RE.search(text)
    return float(match.group(1)) if match else None


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    """Keep the verdict/skeleton but drop the full normalized IR."""
    return {
        "valid": bool(report.get("valid")),
        "errors": list(report.get("errors") or []),
        "warnings": list(report.get("warnings") or []),
        "skeleton": report.get("skeleton") or {},
    }


def _compact_ir(ir: dict[str, Any]) -> dict[str, Any]:
    """Strip prose/empty fields while keeping the executable fingerprint content.

    Block/objective parameters are kept: ``ProblemIR._executable_view`` reads
    them, so dropping them would change the model identity.  Prose fields
    (category/name/natural_language/status) and empty parameter objects do not
    participate in the fingerprint and are removed.
    """
    out: dict[str, Any] = {
        "problem_families": [
            {"id": family.get("id")} for family in ir.get("problem_families") or []
        ],
        "entities": {
            key: {
                field: entry.get(field) for field in ("size", "ids") if entry.get(field) is not None
            }
            for key, entry in (ir.get("entities") or {}).items()
        },
        "parameters": dict(ir.get("parameters") or {}),
    }
    objective = ir.get("objective") or {}
    compact_objective: dict[str, Any] = {
        "block_id": objective.get("block_id"),
        "sense": objective.get("sense"),
    }
    if objective.get("expression"):
        compact_objective["expression"] = objective["expression"]
    if objective.get("parameters"):
        compact_objective["parameters"] = dict(objective["parameters"])
    out["objective"] = compact_objective
    out["constraint_blocks"] = [
        {
            "block_id": block.get("block_id"),
            **({"parameters": dict(block["parameters"])} if block.get("parameters") else {}),
        }
        for block in ir.get("constraint_blocks") or []
    ]
    if ir.get("custom_constraints"):
        out["custom_constraints"] = list(ir["custom_constraints"])
    if ir.get("missing_data"):
        out["missing_data"] = list(ir["missing_data"])
    return out


def _skeleton_signature(ir: dict[str, Any]) -> dict[str, Any]:
    return {
        "families": sorted(str(f.get("id")) for f in ir.get("problem_families") or []),
        "blocks": sorted(str(block.get("block_id")) for block in ir.get("constraint_blocks") or []),
        "objective": (
            str((ir.get("objective") or {}).get("block_id") or ""),
            str((ir.get("objective") or {}).get("sense") or ""),
        ),
        "entities": {
            key: ((entry.get("size") or 0), tuple(str(item) for item in entry.get("ids") or []))
            for key, entry in (ir.get("entities") or {}).items()
        },
    }


def _apply_patch(base_ir: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Apply overrides to top-level and owning block/objective parameters.

    Keeping both places in sync makes the patched IR canonical, so a patch and
    a full model with the same content produce the same fingerprint.
    """
    patched = copy.deepcopy(base_ir)
    patched.setdefault("parameters", {}).update(overrides)
    for block in patched.get("constraint_blocks") or []:
        params = block.get("parameters")
        if isinstance(params, dict):
            for key, value in overrides.items():
                if key in params:
                    params[key] = value
    objective = patched.get("objective") or {}
    params = objective.get("parameters")
    if isinstance(params, dict):
        for key, value in overrides.items():
            if key in params:
                params[key] = value
    return patched


class ArtifactStore:
    """Read/write the flat artifact files for one session."""

    def __init__(self, session: "Session | Path") -> None:
        if isinstance(session, Path):
            self.session = None
            self.workspace = session
        else:
            self.session = session
            self.workspace = Path(session.workspace)
        self.root = self.workspace / "artifacts"

    # ------------------------------------------------------------------
    # Paths / low-level IO
    # ------------------------------------------------------------------

    def _model_files(self) -> list[Path]:
        return sorted(self.root.glob("model_*.json"))

    def _patch_files(self) -> list[Path]:
        return sorted(self.root.glob("patch_*.json"))

    def _solve_files(self) -> list[Path]:
        return sorted(self.root.glob("solve_*.json"))

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"

    def _artifact_file(self, artifact_id: str) -> Path:
        return self.root / f"{artifact_id}.json"

    def _read_model(self, path: Path) -> ModelArtifact | None:
        data = _read_json(path)
        if not data:
            return None
        try:
            return ModelArtifact.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return None

    def _read_solve(self, path: Path) -> SolveArtifact | None:
        data = _read_json(path)
        if not data:
            return None
        try:
            return SolveArtifact.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def load_state(self) -> dict[str, Any]:
        return _read_json(self.state_file) or {}

    def save_state(self, state: dict[str, Any]) -> None:
        _atomic_write_json(
            self.state_file,
            {
                "baseline_model": state.get("baseline_model"),
                "baseline_solve": state.get("baseline_solve"),
                "updated_at": state.get("updated_at") or _now(),
            },
        )

    def _set_baseline_model(self, artifact_id: str) -> None:
        state = self.load_state()
        if state.get("baseline_model") != artifact_id:
            state["baseline_solve"] = None
        state["baseline_model"] = artifact_id
        state["updated_at"] = _now()
        self.save_state(state)

    def _set_baseline_solve(self, artifact_id: str) -> None:
        state = self.load_state()
        state["baseline_solve"] = artifact_id
        state["updated_at"] = _now()
        self.save_state(state)

    # ------------------------------------------------------------------
    # Model writes
    # ------------------------------------------------------------------

    def save_model_artifact(
        self,
        report: dict[str, Any],
        *,
        name: str | None = None,
        kind: str = "scenario",
        baseline: bool = False,
        revise: bool = False,
        overwrite: bool | None = None,
        source: dict[str, Any] | None = None,
    ) -> ModelArtifact:
        if overwrite is not None:
            revise = bool(revise or overwrite)
        if not isinstance(report, dict) or not isinstance(report.get("normalized_ir"), dict):
            raise ArtifactError("需要 validate_problem_ir 的完整报告（含 normalized_ir）")
        normalized = report["normalized_ir"]
        fingerprint = ir_fingerprint(normalized)
        valid = bool(report.get("valid"))
        status = "valid" if valid else "invalid"
        if baseline and not valid:
            raise ArtifactError("校验失败的模型不能设为 baseline")

        with _LOCK:
            duplicates = [
                item
                for item in self.list_models()
                if item.fingerprint == fingerprint
                and item.validation_status == status
                and not item.is_patch
            ]
            if duplicates and not revise:
                existing = next(
                    (item for item in duplicates if name and item.name == name),
                    duplicates[0],
                )
                if baseline:
                    self._set_baseline_model(existing.artifact_id)
                return existing
            if name is None:
                name = self._auto_model_name(kind, valid)
            name = _clean_name(name)
            versions = self.list_model_versions(name)
            current = versions[-1] if versions else None
            if current is not None:
                if current.kind != kind:
                    raise ArtifactNameConflict(
                        name, current.artifact_id, f"{current.kind} → {kind} 不允许"
                    )
                if not revise:
                    if current.fingerprint == fingerprint and current.validation_status == status:
                        if baseline:
                            self._set_baseline_model(current.artifact_id)
                        return current
                    raise ArtifactNameConflict(name, current.artifact_id)
            revision = (current.revision + 1) if current else 1
            artifact_id = self._new_id("model")
            stored_report = {
                "valid": bool(report.get("valid")),
                "errors": list(report.get("errors") or []),
                "warnings": list(report.get("warnings") or []),
                "skeleton": report.get("skeleton") or {},
                "normalized_ir": _compact_ir(normalized),
            }
            artifact = ModelArtifact(
                artifact_id=artifact_id,
                name=name,
                revision=revision,
                kind=kind,
                validation_status=status,
                saved_at=_now(),
                fingerprint=fingerprint,
                source=dict(source or {"type": "validate_problem_ir", "tool_generated": True}),
                report=stored_report,
                validation=None,
            )
            _atomic_write_json(self._artifact_file(artifact_id), artifact.to_dict())
            state = self.load_state()
            if baseline or (valid and not state.get("baseline_model")):
                self._set_baseline_model(artifact_id)
            return artifact

    def save_model_patch(
        self,
        base_model_id: str,
        overrides: dict[str, Any],
        *,
        name: str | None = None,
        revise: bool = False,
        overwrite: bool | None = None,
        source: dict[str, Any] | None = None,
    ) -> ModelArtifact:
        if overwrite is not None:
            revise = bool(revise or overwrite)
        if not isinstance(overrides, dict) or not overrides:
            raise ArtifactError("参数补丁需要至少一个 override")
        base = self.load_model_artifact(base_model_id)
        base_ir = self.effective_ir(base)
        patched = _apply_patch(base_ir, overrides)
        report = validate_problem_ir(patched)
        if _skeleton_signature(base_ir) != _skeleton_signature(report["normalized_ir"]):
            raise ArtifactError(
                "补丁改变了约束块/目标/实体结构；请用 validate_problem_ir 建完整模型"
            )
        normalized = report["normalized_ir"]
        fingerprint = ir_fingerprint(normalized)
        validation = _compact(report)
        status = "valid" if validation["valid"] else "invalid"

        with _LOCK:
            duplicates = [
                item
                for item in self.list_models()
                if item.is_patch
                and item.fingerprint == fingerprint
                and item.base_model_ref is not None
                and item.base_model_ref.artifact_id == base.artifact_id
            ]
            if duplicates and not revise:
                return duplicates[0]
            if name is None:
                name = self._auto_model_name("parameter_patch", True)
            name = _clean_name(name)
            versions = self.list_model_versions(name)
            current = versions[-1] if versions else None
            if current is not None:
                if current.kind != "parameter_patch":
                    raise ArtifactNameConflict(
                        name, current.artifact_id, f"{current.kind} → parameter_patch 不允许"
                    )
                if not revise:
                    same_base = (
                        current.base_model_ref is not None
                        and current.base_model_ref.artifact_id == base.artifact_id
                    )
                    if current.fingerprint == fingerprint and same_base:
                        return current
                    raise ArtifactNameConflict(name, current.artifact_id)
            revision = (current.revision + 1) if current else 1
            artifact_id = self._new_id("patch")
            artifact = ModelArtifact(
                artifact_id=artifact_id,
                name=name,
                revision=revision,
                kind="parameter_patch",
                validation_status=status,
                saved_at=_now(),
                fingerprint=fingerprint,
                source=dict(source or {"type": "create_model_patch", "tool_generated": True}),
                report=None,
                validation=validation,
                base_model_ref=ModelRef(base.artifact_id, base.name, base.fingerprint),
                overrides=dict(overrides),
            )
            _atomic_write_json(self._artifact_file(artifact_id), artifact.to_dict())
            return artifact

    def _auto_model_name(self, kind: str, valid: bool) -> str:
        if valid and not self.load_state().get("baseline_model") and kind != "parameter_patch":
            return "baseline"
        base = "patch" if kind == "parameter_patch" else "scenario"
        used = {artifact.name for artifact in self.list_models()}
        if base not in used:
            return base
        suffix = 2
        while f"{base}_{suffix}" in used:
            suffix += 1
        return f"{base}_{suffix}"

    def _new_id(self, prefix: str) -> str:
        while True:
            candidate = f"{prefix}_{uuid.uuid4().hex[:8]}"
            if not self._artifact_file(candidate).exists():
                return candidate

    # ------------------------------------------------------------------
    # Model reads / resolution
    # ------------------------------------------------------------------

    def list_model_versions(self, name: str) -> list[ModelArtifact]:
        items: list[ModelArtifact] = []
        for path in self._model_files() + self._patch_files():
            artifact = self._read_model(path)
            if artifact is not None and artifact.name == name:
                items.append(artifact)
        items.sort(key=lambda item: (item.revision, item.saved_at, item.artifact_id))
        return items

    def list_models(self, *, current_only: bool = False) -> list[ModelArtifact]:
        grouped: dict[str, list[ModelArtifact]] = {}
        for path in self._model_files() + self._patch_files():
            artifact = self._read_model(path)
            if artifact is not None:
                grouped.setdefault(artifact.name, []).append(artifact)
        items: list[ModelArtifact] = []
        for versions in grouped.values():
            versions.sort(key=lambda item: (item.revision, item.saved_at, item.artifact_id))
            items.append(versions[-1] if current_only else versions[0])
            if not current_only:
                items.extend(versions[1:])
        items.sort(key=lambda item: (item.name, item.revision))
        return items

    def get_current_model(self, name: str) -> ModelArtifact | None:
        versions = self.list_model_versions(name)
        return versions[-1] if versions else None

    def load_model_artifact(self, artifact_id: str) -> ModelArtifact:
        path = self._artifact_file(artifact_id)
        if path.is_file() and artifact_id.startswith(("model_", "patch_")):
            artifact = self._read_model(path)
            if artifact is not None:
                return artifact
        if artifact_id.startswith("model_legacy_"):
            legacy = self.load_legacy_model()
            if legacy is not None and legacy.artifact_id == artifact_id:
                return legacy
        raise ArtifactNotFound(f"模型 artifact 不存在：{artifact_id}")

    def resolve_model(self, ref: str) -> ModelArtifact:
        value = str(ref).strip()
        if not value:
            raise ArtifactNotFound("模型引用为空")
        if value.startswith(("model_", "patch_")):
            try:
                return self.load_model_artifact(value)
            except ArtifactNotFound:
                pass
        current = self.get_current_model(value)
        if current is not None:
            return current
        legacy = self.load_legacy_model()
        if legacy is not None and value in {"baseline", "legacy", legacy.artifact_id}:
            return legacy
        raise ArtifactNotFound(f"模型不存在：{value}")

    def effective_ir(self, artifact: ModelArtifact) -> dict[str, Any]:
        if not artifact.is_patch:
            report = artifact.report or {}
            normalized = report.get("normalized_ir")
            if not isinstance(normalized, dict):
                raise ArtifactError(f"模型 {artifact.artifact_id} 缺少 normalized_ir")
            return normalized
        if artifact.base_model_ref is None:
            raise ArtifactError(f"补丁 {artifact.artifact_id} 缺少 base_model_ref")
        base = self.load_model_artifact(artifact.base_model_ref.artifact_id)
        base_ir = self.effective_ir(base)
        report = validate_problem_ir(_apply_patch(base_ir, artifact.overrides))
        return report["normalized_ir"]

    def find_models_by_fingerprint(
        self, fingerprint: str, *, valid_only: bool = False
    ) -> list[ModelArtifact]:
        matches = [
            artifact
            for artifact in self.list_models()
            if artifact.fingerprint == fingerprint
            and (not valid_only or artifact.validation_status == "valid")
        ]
        matches.sort(key=lambda item: (item.name, item.revision, item.artifact_id))
        return matches

    # ------------------------------------------------------------------
    # Solve writes / reads
    # ------------------------------------------------------------------

    def save_solve_artifact(
        self,
        normalized_ir: dict[str, Any],
        *,
        status: str,
        objective: float | None = None,
        text: str = "",
        name: str | None = None,
        model_artifact_id: str | None = None,
        variables: dict[str, Any] | None = None,
        overrides: dict[str, Any] | None = None,
        base_model_ref: ModelRef | None = None,
        source: dict[str, Any] | None = None,
    ) -> SolveArtifact:
        fingerprint = ir_fingerprint(normalized_ir)
        with _LOCK:
            model_ref: ModelRef | None = None
            association_status = "unassociated"
            if model_artifact_id:
                model = self.load_model_artifact(model_artifact_id)
                if model.validation_status != "valid":
                    raise ArtifactLinkError(
                        f"模型 {model.artifact_id} 未通过校验，不能关联求解结果"
                    )
                if model.fingerprint != fingerprint:
                    raise ArtifactLinkError(
                        f"求解的 IR 指纹与模型 {model.artifact_id} 不一致，拒绝关联"
                    )
                model_ref = ModelRef(model.artifact_id, model.name, model.fingerprint)
                association_status = "linked"
            else:
                matches = self.find_models_by_fingerprint(fingerprint, valid_only=True)
                if len(matches) == 1:
                    model = matches[0]
                    model_ref = ModelRef(model.artifact_id, model.name, model.fingerprint)
                    association_status = "linked"
                elif len(matches) > 1:
                    baseline_id = self.load_state().get("baseline_model")
                    baselines = [item for item in matches if item.artifact_id == baseline_id]
                    if len(baselines) == 1:
                        model = baselines[0]
                        model_ref = ModelRef(model.artifact_id, model.name, model.fingerprint)
                        association_status = "linked"
                    else:
                        association_status = "ambiguous"

            if name is None:
                name = model_ref.name if model_ref else self._auto_solve_name()
            name = _clean_name(name)
            revision = self._next_solve_revision(name)
            artifact_id = self._new_id("solve")
            artifact = SolveArtifact(
                artifact_id=artifact_id,
                name=name,
                revision=revision,
                saved_at=_now(),
                model_ref=model_ref,
                association_status=association_status,
                ir_fingerprint=fingerprint,
                status=str(status or "Unknown"),
                objective=float(objective) if isinstance(objective, (int, float)) else None,
                result={
                    "text": str(text or ""),
                    **({"variables": variables} if variables is not None else {}),
                },
                source=dict(source or {"type": "solve_ir", "tool_generated": True}),
                overrides=dict(overrides or {}),
                base_model_ref=base_model_ref,
            )
            _atomic_write_json(self._artifact_file(artifact_id), artifact.to_dict())
            baseline_id = self.load_state().get("baseline_model")
            if model_ref is not None and model_ref.artifact_id == baseline_id:
                self._set_baseline_solve(artifact_id)
            return artifact

    def _auto_solve_name(self) -> str:
        used = {artifact.name for artifact in self.list_solves()}
        if "solve" not in used:
            return "solve"
        suffix = 2
        while f"solve_{suffix}" in used:
            suffix += 1
        return f"solve_{suffix}"

    def _next_solve_revision(self, name: str) -> int:
        versions = [artifact for artifact in self.list_solves() if artifact.name == name]
        return (max((item.revision for item in versions), default=0)) + 1

    def list_solves(self) -> list[SolveArtifact]:
        items: list[SolveArtifact] = []
        for path in self._solve_files():
            artifact = self._read_solve(path)
            if artifact is not None:
                items.append(artifact)
        items.sort(key=lambda item: (item.saved_at, item.revision, item.artifact_id))
        return items

    def load_solve_artifact(self, artifact_id: str) -> SolveArtifact:
        path = self._artifact_file(artifact_id)
        if path.is_file() and artifact_id.startswith("solve_"):
            artifact = self._read_solve(path)
            if artifact is not None:
                return artifact
        if artifact_id.startswith("solve_legacy_"):
            legacy = self.load_legacy_solve()
            if legacy is not None and legacy.artifact_id == artifact_id:
                return legacy
        raise ArtifactNotFound(f"求解 artifact 不存在：{artifact_id}")

    def resolve_solve(self, ref: str) -> SolveArtifact:
        value = str(ref).strip()
        if not value:
            raise ArtifactNotFound("求解结果引用为空")
        if value.startswith("solve_"):
            try:
                return self.load_solve_artifact(value)
            except ArtifactNotFound:
                pass
        versions = [artifact for artifact in self.list_solves() if artifact.name == value]
        if versions:
            return versions[-1]
        model = self.get_current_model(value)
        if model is not None:
            solve = self.latest_solve_for_model(model.artifact_id)
            if solve is not None:
                return solve
        legacy = self.load_legacy_solve()
        if legacy is not None and value in {"baseline", "legacy", legacy.artifact_id}:
            return legacy
        raise ArtifactNotFound(f"求解结果不存在：{value}")

    def find_solves_by_model(self, artifact_id: str) -> list[SolveArtifact]:
        matches = [
            artifact
            for artifact in self.list_solves()
            if artifact.model_ref is not None and artifact.model_ref.artifact_id == artifact_id
        ]
        matches.sort(key=lambda item: (item.saved_at, item.revision, item.artifact_id))
        return matches

    def latest_solve_for_model(
        self, artifact_id: str, *, successful_only: bool = True
    ) -> SolveArtifact | None:
        solves = self.find_solves_by_model(artifact_id)
        if successful_only:
            solves = [item for item in solves if item.status == "Optimal"]
        return solves[-1] if solves else None

    # ------------------------------------------------------------------
    # Baseline
    # ------------------------------------------------------------------

    def get_baseline_model(self) -> ModelArtifact | None:
        state = self.load_state()
        artifact_id = state.get("baseline_model")
        if artifact_id:
            try:
                artifact = self.load_model_artifact(str(artifact_id))
                if artifact.validation_status == "valid" and not artifact.is_patch:
                    return artifact
            except ArtifactNotFound:
                pass
        candidates = [
            item
            for item in self.list_models()
            if item.validation_status == "valid" and not item.is_patch and item.kind != "legacy"
        ]
        candidates.sort(key=lambda item: (item.saved_at, item.revision, item.artifact_id))
        if candidates:
            return candidates[0]
        return self.load_legacy_model()

    def get_baseline_solve(self) -> SolveArtifact | None:
        state = self.load_state()
        artifact_id = state.get("baseline_solve")
        if artifact_id:
            try:
                return self.load_solve_artifact(str(artifact_id))
            except ArtifactNotFound:
                pass
        baseline = self.get_baseline_model()
        if baseline is None:
            return None
        solve = self.latest_solve_for_model(baseline.artifact_id)
        if solve is not None:
            return solve
        return self.load_legacy_solve()

    # ------------------------------------------------------------------
    # Legacy compatibility (read-only, never writes)
    # ------------------------------------------------------------------

    def load_legacy_model(self) -> ModelArtifact | None:
        path = self.workspace / "model.json"
        if not path.is_file():
            return None
        payload = _read_json(path) or {}
        report = payload.get("report")
        if not isinstance(report, dict):
            report = payload
        normalized = report.get("normalized_ir")
        if not isinstance(normalized, dict):
            return None
        fingerprint = ir_fingerprint(normalized)
        return ModelArtifact(
            artifact_id=f"model_legacy_{fingerprint[:8]}",
            name="baseline",
            revision=1,
            kind="legacy",
            validation_status="valid" if report.get("valid") else "invalid",
            saved_at=str(payload.get("saved_at") or _now()),
            fingerprint=fingerprint,
            source={"type": "legacy", "tool_generated": False},
            report=report,
            validation=_compact(report),
        )

    def load_legacy_solve(self) -> SolveArtifact | None:
        path = self.workspace / "solve_result.json"
        if not path.is_file():
            return None
        payload = _read_json(path) or {}
        text = str(payload.get("text") or "")
        fingerprint = str(payload.get("ir_fingerprint") or "")
        if not fingerprint:
            return None
        model_ref = None
        legacy_model = self.load_legacy_model()
        if legacy_model is not None and legacy_model.fingerprint == fingerprint:
            model_ref = ModelRef(
                legacy_model.artifact_id, legacy_model.name, legacy_model.fingerprint
            )
        return SolveArtifact(
            artifact_id=f"solve_legacy_{fingerprint[:8]}",
            name=model_ref.name if model_ref else "baseline",
            revision=1,
            saved_at=str(payload.get("saved_at") or _now()),
            model_ref=model_ref,
            association_status="linked" if model_ref else "unassociated",
            ir_fingerprint=fingerprint,
            status=_status_from_text(text),
            objective=_objective_from_text(text),
            result={"text": text},
            source={"type": "legacy", "tool_generated": False},
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def has_artifacts(self) -> bool:
        """True when any new-style model/patch/solve file exists."""
        return bool(self._model_files() or self._patch_files() or self._solve_files())

    def has_models(self) -> bool:
        return (
            bool(self._model_files() or self._patch_files())
            or (self.workspace / "model.json").is_file()
        )

    def has_solves(self) -> bool:
        return bool(self._solve_files()) or (self.workspace / "solve_result.json").is_file()

    def model_counts(self) -> tuple[int, int]:
        """(full models, patches) on disk, excluding legacy."""
        return len(self._model_files()), len(self._patch_files())


def _session_of(session_or_sid: "Session | str") -> "Session":
    from utils.session import Session

    if isinstance(session_or_sid, str):
        session = Session.load(session_or_sid)
        return session if session is not None else Session(session_id=session_or_sid)
    return session_or_sid


def store_for(session_or_sid: "Session | str | Path") -> ArtifactStore:
    if isinstance(session_or_sid, Path):
        return ArtifactStore(session_or_sid)
    return ArtifactStore(_session_of(session_or_sid))


# Module-level convenience wrappers ------------------------------------------------


def save_model_artifact(
    session_or_sid: "Session | str | Path", report: dict, **kwargs: Any
) -> ModelArtifact:
    return store_for(session_or_sid).save_model_artifact(report, **kwargs)


def save_model_patch(
    session_or_sid: "Session | str | Path", base_model_id: str, overrides: dict, **kwargs: Any
) -> ModelArtifact:
    return store_for(session_or_sid).save_model_patch(base_model_id, overrides, **kwargs)


def save_solve_artifact(
    session_or_sid: "Session | str | Path", normalized_ir: dict, **kwargs: Any
) -> SolveArtifact:
    return store_for(session_or_sid).save_solve_artifact(normalized_ir, **kwargs)


def load_model_artifact(session_or_sid: "Session | str | Path", artifact_id: str) -> ModelArtifact:
    return store_for(session_or_sid).load_model_artifact(artifact_id)


def load_solve_artifact(session_or_sid: "Session | str | Path", artifact_id: str) -> SolveArtifact:
    return store_for(session_or_sid).load_solve_artifact(artifact_id)


def resolve_model(session_or_sid: "Session | str | Path", ref: str) -> ModelArtifact:
    return store_for(session_or_sid).resolve_model(ref)


def resolve_solve(session_or_sid: "Session | str | Path", ref: str) -> SolveArtifact:
    return store_for(session_or_sid).resolve_solve(ref)


__all__ = [
    "ArtifactError",
    "ArtifactLinkError",
    "ArtifactNameConflict",
    "ArtifactNotFound",
    "ArtifactStore",
    "FINGERPRINT_ALGO",
    "ModelArtifact",
    "ModelRef",
    "SolveArtifact",
    "load_model_artifact",
    "load_solve_artifact",
    "resolve_model",
    "resolve_solve",
    "save_model_artifact",
    "save_model_patch",
    "save_solve_artifact",
    "store_for",
]
