"""Session-scoped artifact store for models and solve results.

Phase 1 of the artifact architecture: persistence, identity, versioning and
association only.  The legacy ``model.json`` / ``solve_result.json`` files are
imported lazily and never modified here; tools and the web UI keep using them
until Phase 2.

Layout::

    sessions/<sid>/artifacts/
        index.json                  # derived index
        baseline.json               # small, non-derived baseline pointer
        models/<name>.json          # logical-name pointer, not a payload
        model_versions/<id>.json    # immutable model artifacts
        solves/<id>.json            # immutable solve artifacts
        answers/<id>.json           # AnswerManifest records
        imports/*.json              # direct, unvalidated model files
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.problem_ir import fingerprint as ir_fingerprint

if TYPE_CHECKING:
    from utils.session import Session

SCHEMA_VERSION = 2
FINGERPRINT_ALGO = "md5"
_LOCK = threading.RLock()
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
_OBJECTIVE_RE = re.compile(r"\[RESULT\]\s*Objective:\s*([-+]?\d+(?:\.\d+)?)")


class ArtifactError(Exception):
    """Base class for artifact-store errors."""


class ArtifactNameConflict(ArtifactError):
    """The logical name already points at different content."""

    def __init__(self, name: str, current_id: str) -> None:
        super().__init__(
            f"模型名称 {name!r} 已存在（当前 {current_id}）；"
            "如需在同一名称下追加新版本，请使用 revise=True；"
            "否则请换一个名称。"
        )
        self.name = name
        self.current_id = current_id


class ArtifactLinkError(ArtifactError):
    """A solve result cannot be linked to the requested model artifact."""


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
    kind: str
    validation_status: str
    saved_at: str
    fingerprint: str
    fingerprint_algo: str = FINGERPRINT_ALGO
    source: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelArtifact":
        report = data.get("report")
        status = str(data.get("validation_status") or "")
        if not status:
            status = "valid" if isinstance(report, dict) and report.get("valid") else "invalid"
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
        )


@dataclass
class SolveArtifact:
    artifact_id: str
    name: str
    revision: int
    saved_at: str
    model_ref: ModelRef | None
    association_status: str
    ir_fingerprint: str
    fingerprint_algo: str = FINGERPRINT_ALGO
    status: str = "Unknown"
    objective: float | None = None
    result: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

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
        )


@dataclass
class ArtifactIndex:
    schema_version: int = SCHEMA_VERSION
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    solves: dict[str, dict[str, Any]] = field(default_factory=dict)
    baseline_model: str | None = None
    baseline_solve: str | None = None
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


class ArtifactStore:
    """Read/write the artifact files for one session."""

    def __init__(self, session: "Session | Path") -> None:
        if isinstance(session, Path):
            self.session = None
            self.workspace = session
        else:
            self.session = session
            self.workspace = Path(session.workspace)
        self.root = self.workspace / "artifacts"
        self.models_dir = self.root / "models"
        self.versions_dir = self.root / "model_versions"
        self.solves_dir = self.root / "solves"
        self.answers_dir = self.root / "answers"
        self.imports_dir = self.root / "imports"
        # 只记录路径，不建目录：读取路径（glob/is_file）对缺失目录安全，
        # 写路径由 _atomic_write_json 按需创建，避免只读访问产生副作用。

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @property
    def index_file(self) -> Path:
        return self.root / "index.json"

    @property
    def baseline_file(self) -> Path:
        return self.root / "baseline.json"

    @property
    def legacy_model_file(self) -> Path:
        return self.workspace / "model.json"

    @property
    def legacy_solve_file(self) -> Path:
        return self.workspace / "solve_result.json"

    def model_version_file(self, artifact_id: str) -> Path:
        return self.versions_dir / f"{artifact_id}.json"

    def solve_file(self, artifact_id: str) -> Path:
        return self.solves_dir / f"{artifact_id}.json"

    def answer_file(self, answer_id: str) -> Path:
        return self.answers_dir / f"{answer_id}.json"

    def model_pointer_file(self, name: str) -> Path:
        return self.models_dir / f"{name}.json"

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def load_index(self, *, ensure_legacy: bool = True) -> ArtifactIndex:
        with _LOCK:
            index = self._read_index_file()
            if index is None:
                return self.rebuild_index()
            if ensure_legacy and self._ensure_legacy_files():
                return self.rebuild_index()
            if self._index_is_stale(index):
                return self.rebuild_index()
            return index

    def rebuild_index(self) -> ArtifactIndex:
        with _LOCK:
            self._ensure_legacy_files()
            index = ArtifactIndex()
            models: dict[str, list[ModelArtifact]] = {}
            for path in sorted(self.versions_dir.glob("*.json")):
                artifact = self._read_model_file(path)
                if artifact is not None:
                    models.setdefault(artifact.name, []).append(artifact)
            for name, artifacts in models.items():
                artifacts.sort(key=lambda item: (item.revision, item.saved_at, item.artifact_id))
                index.models[name] = {
                    "current": artifacts[-1].artifact_id,
                    "versions": [item.artifact_id for item in artifacts],
                }

            solves: dict[str, list[SolveArtifact]] = {}
            for path in sorted(self.solves_dir.glob("*.json")):
                artifact = self._read_solve_file(path)
                if artifact is not None:
                    solves.setdefault(artifact.name, []).append(artifact)
            for name, artifacts in solves.items():
                artifacts.sort(key=lambda item: (item.revision, item.saved_at, item.artifact_id))
                index.solves[name] = {
                    "current": artifacts[-1].artifact_id,
                    "versions": [item.artifact_id for item in artifacts],
                }

            all_models = [item for items in models.values() for item in items]
            all_solves = [item for items in solves.values() for item in items]
            pointer = self._read_baseline_file()
            index.baseline_model = str(pointer.get("baseline_model") or "") or None
            baseline_artifact = (
                self._read_model_file(self.model_version_file(index.baseline_model))
                if index.baseline_model
                else None
            )
            if baseline_artifact is None or baseline_artifact.validation_status != "valid":
                valid = [item for item in all_models if item.validation_status == "valid"]
                baseline_kind = [item for item in valid if item.kind == "baseline"]
                pool = baseline_kind or valid
                pool.sort(key=lambda item: (item.saved_at, item.revision, item.artifact_id))
                index.baseline_model = pool[-1].artifact_id if pool else None

            index.baseline_solve = str(pointer.get("baseline_solve") or "") or None
            baseline_solve = (
                self._read_solve_file(self.solve_file(index.baseline_solve))
                if index.baseline_solve
                else None
            )
            if (
                baseline_solve is None
                or baseline_solve.model_ref is None
                or baseline_solve.model_ref.artifact_id != index.baseline_model
            ):
                linked = [
                    item
                    for item in all_solves
                    if item.model_ref is not None
                    and item.model_ref.artifact_id == index.baseline_model
                    and item.status == "Optimal"
                ]
                linked.sort(key=lambda item: (item.saved_at, item.revision, item.artifact_id))
                index.baseline_solve = linked[-1].artifact_id if linked else None

            index.updated_at = _now()
            self._write_index(index)
            self._write_baseline(index)
            self._write_model_pointers(index)
            return index

    def _read_index_file(self) -> ArtifactIndex | None:
        data = _read_json(self.index_file)
        if not data or data.get("schema_version") != SCHEMA_VERSION:
            return None
        models = data.get("models")
        solves = data.get("solves")
        if not isinstance(models, dict) or not isinstance(solves, dict):
            return None
        for entry in models.values():
            if not isinstance(entry, dict):
                return None
            if not entry.get("current") or not isinstance(entry.get("versions"), list):
                return None
        for entry in solves.values():
            if not isinstance(entry, dict):
                return None
            if not entry.get("current") or not isinstance(entry.get("versions"), list):
                return None
        return ArtifactIndex(
            schema_version=SCHEMA_VERSION,
            models=models,
            solves=solves,
            baseline_model=data.get("baseline_model"),
            baseline_solve=data.get("baseline_solve"),
            updated_at=str(data.get("updated_at") or ""),
        )

    def _index_is_stale(self, index: ArtifactIndex) -> bool:
        version_files = list(self.versions_dir.glob("*.json"))
        solve_files = list(self.solves_dir.glob("*.json"))
        indexed_versions = sum(len(entry["versions"]) for entry in index.models.values())
        indexed_solves = sum(len(entry["versions"]) for entry in index.solves.values())
        if len(version_files) != indexed_versions or len(solve_files) != indexed_solves:
            return True
        for entry in index.models.values():
            if not self.model_version_file(str(entry["current"])).is_file():
                return True
        for entry in index.solves.values():
            if not self.solve_file(str(entry["current"])).is_file():
                return True
        if index.baseline_model:
            baseline = self._read_model_file(self.model_version_file(index.baseline_model))
            if baseline is None or baseline.validation_status != "valid":
                return True
        if index.baseline_solve:
            solve = self._read_solve_file(self.solve_file(index.baseline_solve))
            if solve is None:
                return True
            if index.baseline_model and (
                solve.model_ref is None or solve.model_ref.artifact_id != index.baseline_model
            ):
                return True
        return False

    def _write_index(self, index: ArtifactIndex) -> None:
        _atomic_write_json(self.index_file, index.to_dict())

    def _read_baseline_file(self) -> dict[str, Any]:
        return _read_json(self.baseline_file) or {}

    def _write_baseline(self, index: ArtifactIndex) -> None:
        _atomic_write_json(
            self.baseline_file,
            {
                "schema_version": 1,
                "baseline_model": index.baseline_model,
                "baseline_solve": index.baseline_solve,
                "updated_at": index.updated_at or _now(),
            },
        )

    def _write_model_pointers(self, index: ArtifactIndex) -> None:
        for name, entry in index.models.items():
            _atomic_write_json(
                self.model_pointer_file(name),
                {
                    "generated_by": "artifact_store",
                    "name": name,
                    "current": entry["current"],
                    "versions": list(entry["versions"]),
                    "updated_at": index.updated_at,
                },
            )

    # ------------------------------------------------------------------
    # Artifact readers
    # ------------------------------------------------------------------

    def _read_model_file(self, path: Path) -> ModelArtifact | None:
        data = _read_json(path)
        if not data:
            return None
        try:
            return ModelArtifact.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return None

    def _read_solve_file(self, path: Path) -> SolveArtifact | None:
        data = _read_json(path)
        if not data:
            return None
        try:
            return SolveArtifact.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return None

    def load_model_artifact(self, artifact_id: str) -> ModelArtifact:
        path = self.model_version_file(artifact_id)
        artifact = self._read_model_file(path) if path.is_file() else None
        if artifact is not None:
            return artifact
        if artifact_id.startswith("model_import_"):
            for item in self.scan_imported_models():
                if item.artifact_id == artifact_id:
                    return item
        raise ArtifactNotFound(f"模型 artifact 不存在：{artifact_id}")

    def load_solve_artifact(self, artifact_id: str) -> SolveArtifact:
        path = self.solve_file(artifact_id)
        artifact = self._read_solve_file(path) if path.is_file() else None
        if artifact is not None:
            return artifact
        raise ArtifactNotFound(f"求解 artifact 不存在：{artifact_id}")

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
        """Persist one validation report as an immutable model version.

        ``report`` must be the full report returned by ``validate_problem_ir``.
        Same name + same fingerprint is idempotent; same name + different
        content requires ``revise=True``.  ``overwrite`` is a compatibility
        alias for ``revise``: it appends a version and never deletes history.
        """
        if overwrite is not None:
            revise = bool(revise or overwrite)
        if not isinstance(report, dict) or not isinstance(report.get("normalized_ir"), dict):
            raise ArtifactError("需要 validate_problem_ir 的完整报告（含 normalized_ir）")
        normalized_ir = report["normalized_ir"]
        fingerprint = ir_fingerprint(normalized_ir)
        valid = bool(report.get("valid"))
        validation_status = "valid" if valid else "invalid"
        if baseline and not valid:
            raise ArtifactError("校验失败的模型不能设为 baseline")

        with _LOCK:
            index = self.load_index()
            if name is None:
                name = self._auto_model_name(index, kind, valid)
            name = _clean_name(name)
            existing = index.models.get(name)
            if existing and not revise:
                current = self.load_model_artifact(str(existing["current"]))
                if (
                    current.fingerprint == fingerprint
                    and current.validation_status == validation_status
                ):
                    if baseline or (kind == "baseline" and valid and index.baseline_model is None):
                        self._set_baseline_model(index, current.artifact_id)
                        index.updated_at = _now()
                        self._write_index(index)
                        self._write_baseline(index)
                    return current
                raise ArtifactNameConflict(name, current.artifact_id)

            revision = self._next_revision(index, name)
            artifact_id = self._new_id("model", self.versions_dir)
            artifact = ModelArtifact(
                artifact_id=artifact_id,
                name=name,
                revision=revision,
                kind=kind,
                validation_status=validation_status,
                saved_at=_now(),
                fingerprint=fingerprint,
                fingerprint_algo=FINGERPRINT_ALGO,
                source=dict(source or {"type": "validate_problem_ir", "tool_generated": True}),
                report=report,
            )
            _atomic_write_json(self.model_version_file(artifact_id), artifact.to_dict())
            entry = index.models.setdefault(name, {"current": artifact_id, "versions": []})
            entry["versions"].append(artifact_id)
            entry["current"] = artifact_id

            if baseline or (valid and index.baseline_model is None):
                self._set_baseline_model(index, artifact_id)
            if kind == "baseline" and valid and index.baseline_model is None:
                self._set_baseline_model(index, artifact_id)

            index.updated_at = _now()
            self._write_index(index)
            self._write_baseline(index)
            _atomic_write_json(
                self.model_pointer_file(name),
                {
                    "generated_by": "artifact_store",
                    "name": name,
                    "current": entry["current"],
                    "versions": list(entry["versions"]),
                    "updated_at": index.updated_at,
                },
            )
            return artifact

    def _set_baseline_model(self, index: ArtifactIndex, artifact_id: str) -> None:
        if index.baseline_model != artifact_id:
            index.baseline_solve = None
        index.baseline_model = artifact_id

    def _auto_model_name(self, index: ArtifactIndex, kind: str, valid: bool) -> str:
        if valid and index.baseline_model is None and "baseline" not in index.models:
            return "baseline"
        base = "baseline" if kind == "baseline" else ("scenario" if kind == "scenario" else "model")
        return self._unique_name(index.models, base)

    @staticmethod
    def _unique_name(names: dict[str, Any], base: str) -> str:
        if base not in names:
            return base
        suffix = 2
        while f"{base}_{suffix}" in names:
            suffix += 1
        return f"{base}_{suffix}"

    def _next_revision(self, index: ArtifactIndex, name: str) -> int:
        entry = index.models.get(name)
        if not entry:
            return 1
        revisions = []
        for artifact_id in entry.get("versions", []):
            artifact = self._read_model_file(self.model_version_file(str(artifact_id)))
            if artifact is not None:
                revisions.append(artifact.revision)
        return (max(revisions) if revisions else len(entry.get("versions", []))) + 1

    def _new_id(self, prefix: str, directory: Path) -> str:
        while True:
            candidate = f"{prefix}_{uuid.uuid4().hex[:8]}"
            if not (directory / f"{candidate}.json").exists():
                return candidate

    # ------------------------------------------------------------------
    # Solve writes
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
        source: dict[str, Any] | None = None,
    ) -> SolveArtifact:
        """Persist one solve result and link it to a model version when possible."""
        fingerprint = ir_fingerprint(normalized_ir)
        with _LOCK:
            index = self.load_index()
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
                    baselines = [
                        item for item in matches if item.artifact_id == index.baseline_model
                    ]
                    if len(baselines) == 1:
                        model = baselines[0]
                        model_ref = ModelRef(model.artifact_id, model.name, model.fingerprint)
                        association_status = "linked"
                    else:
                        association_status = "ambiguous"

            if name is None:
                name = model_ref.name if model_ref else self._auto_solve_name(index)
            name = _clean_name(name)
            revision = self._next_solve_revision(index, name)
            artifact_id = self._new_id("solve", self.solves_dir)
            artifact = SolveArtifact(
                artifact_id=artifact_id,
                name=name,
                revision=revision,
                saved_at=_now(),
                model_ref=model_ref,
                association_status=association_status,
                ir_fingerprint=fingerprint,
                fingerprint_algo=FINGERPRINT_ALGO,
                status=str(status or "Unknown"),
                objective=float(objective) if isinstance(objective, (int, float)) else None,
                result={
                    "text": str(text or ""),
                    **({"variables": variables} if variables is not None else {}),
                },
                source=dict(source or {"type": "solve_ir", "tool_generated": True}),
            )
            _atomic_write_json(self.solve_file(artifact_id), artifact.to_dict())
            entry = index.solves.setdefault(name, {"current": artifact_id, "versions": []})
            entry["versions"].append(artifact_id)
            entry["current"] = artifact_id
            if model_ref is not None and model_ref.artifact_id == index.baseline_model:
                index.baseline_solve = artifact_id
            index.updated_at = _now()
            self._write_index(index)
            self._write_baseline(index)
            return artifact

    def _auto_solve_name(self, index: ArtifactIndex) -> str:
        return self._unique_name(index.solves, "solve")

    def _next_solve_revision(self, index: ArtifactIndex, name: str) -> int:
        entry = index.solves.get(name)
        if not entry:
            return 1
        revisions = []
        for artifact_id in entry.get("versions", []):
            artifact = self._read_solve_file(self.solve_file(str(artifact_id)))
            if artifact is not None:
                revisions.append(artifact.revision)
        return (max(revisions) if revisions else len(entry.get("versions", []))) + 1

    # ------------------------------------------------------------------
    # Resolution and queries
    # ------------------------------------------------------------------

    def resolve_model(self, ref: str) -> ModelArtifact:
        value = str(ref).strip()
        if not value:
            raise ArtifactNotFound("模型引用为空")
        if value.startswith("model_"):
            try:
                return self.load_model_artifact(value)
            except ArtifactNotFound:
                pass
        index = self.load_index()
        entry = index.models.get(value)
        if entry:
            return self.load_model_artifact(str(entry["current"]))
        imported = [item for item in self.scan_imported_models() if item.name == value]
        if imported:
            return imported[-1]
        raise ArtifactNotFound(f"模型不存在：{value}")

    def resolve_solve(self, ref: str) -> SolveArtifact:
        value = str(ref).strip()
        if not value:
            raise ArtifactNotFound("求解结果引用为空")
        if value.startswith("solve_"):
            try:
                return self.load_solve_artifact(value)
            except ArtifactNotFound:
                pass
        index = self.load_index()
        entry = index.solves.get(value)
        if entry:
            return self.load_solve_artifact(str(entry["current"]))
        if value in index.models:
            solve = self.latest_solve_for_model(str(index.models[value]["current"]))
            if solve is not None:
                return solve
        raise ArtifactNotFound(f"求解结果不存在：{value}")

    def list_model_versions(self, name: str) -> list[ModelArtifact]:
        """All versions of one logical model, oldest first."""
        entry = self.load_index().models.get(name) or {}
        items: list[ModelArtifact] = []
        for artifact_id in entry.get("versions", []):
            artifact = self._read_model_file(self.model_version_file(str(artifact_id)))
            if artifact is not None:
                items.append(artifact)
        items.sort(key=lambda item: (item.revision, item.saved_at, item.artifact_id))
        return items

    def find_models_by_fingerprint(
        self, fingerprint: str, *, valid_only: bool = False
    ) -> list[ModelArtifact]:
        matches: list[ModelArtifact] = []
        for path in sorted(self.versions_dir.glob("*.json")):
            artifact = self._read_model_file(path)
            if artifact is None or artifact.fingerprint != fingerprint:
                continue
            if valid_only and artifact.validation_status != "valid":
                continue
            matches.append(artifact)
        matches.sort(key=lambda item: (item.name, item.revision, item.artifact_id))
        return matches

    def find_solves_by_model(self, artifact_id: str) -> list[SolveArtifact]:
        matches: list[SolveArtifact] = []
        for path in sorted(self.solves_dir.glob("*.json")):
            artifact = self._read_solve_file(path)
            if (
                artifact is not None
                and artifact.model_ref is not None
                and artifact.model_ref.artifact_id == artifact_id
            ):
                matches.append(artifact)
        matches.sort(key=lambda item: (item.saved_at, item.revision, item.artifact_id))
        return matches

    def latest_solve_for_model(
        self, artifact_id: str, *, successful_only: bool = True
    ) -> SolveArtifact | None:
        solves = self.find_solves_by_model(artifact_id)
        if successful_only:
            solves = [item for item in solves if item.status == "Optimal"]
        return solves[-1] if solves else None

    def list_model_artifacts(
        self, *, current_only: bool = False, include_imports: bool = False
    ) -> list[ModelArtifact]:
        index = self.load_index()
        items: list[ModelArtifact] = []
        for entry in index.models.values():
            ids = [entry["current"]] if current_only else list(entry.get("versions", []))
            for artifact_id in ids:
                artifact = self._read_model_file(self.model_version_file(str(artifact_id)))
                if artifact is not None:
                    items.append(artifact)
        if include_imports:
            items.extend(self.scan_imported_models())
        return items

    def list_solve_artifacts(self, *, current_only: bool = False) -> list[SolveArtifact]:
        index = self.load_index()
        items: list[SolveArtifact] = []
        for entry in index.solves.values():
            ids = [entry["current"]] if current_only else list(entry.get("versions", []))
            for artifact_id in ids:
                artifact = self._read_solve_file(self.solve_file(str(artifact_id)))
                if artifact is not None:
                    items.append(artifact)
        return items

    def get_baseline_model(self) -> ModelArtifact | None:
        index = self.load_index()
        if not index.baseline_model:
            return None
        return self.load_model_artifact(index.baseline_model)

    def get_baseline_solve(self) -> SolveArtifact | None:
        index = self.load_index()
        if not index.baseline_solve:
            return None
        return self.load_solve_artifact(index.baseline_solve)

    def scan_imported_models(self) -> list[ModelArtifact]:
        items: list[ModelArtifact] = []
        for path in sorted(self.imports_dir.glob("*.json")):
            try:
                text = path.read_text(encoding="utf-8")
                saved_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            except OSError:
                continue
            digest = hashlib.sha256(f"{path.stem}\0{text}".encode("utf-8")).hexdigest()
            items.append(
                ModelArtifact(
                    artifact_id=f"model_import_{digest[:8]}",
                    name=path.stem,
                    revision=1,
                    kind="imported",
                    validation_status="unvalidated",
                    saved_at=saved_at,
                    fingerprint=f"sha256:{digest}",
                    fingerprint_algo="sha256",
                    source={
                        "type": "direct_file",
                        "tool_generated": False,
                        "path": str(path),
                    },
                    report=None,
                )
            )
        return items

    # ------------------------------------------------------------------
    # Legacy import (lazy, never modifies the legacy files)
    # ------------------------------------------------------------------

    def _has_model_fingerprint(self, fingerprint: str) -> bool:
        for path in self.versions_dir.glob("*.json"):
            artifact = self._read_model_file(path)
            if artifact is not None and artifact.fingerprint == fingerprint:
                return True
        return False

    def _has_solve_fingerprint(self, fingerprint: str) -> bool:
        for path in self.solves_dir.glob("*.json"):
            artifact = self._read_solve_file(path)
            if artifact is not None and artifact.ir_fingerprint == fingerprint:
                return True
        return False

    def _ensure_legacy_files(self) -> bool:
        changed = False
        model_file = self.legacy_model_file
        if model_file.is_file():
            payload = _read_json(model_file) or {}
            report = payload.get("report")
            if not isinstance(report, dict):
                report = payload
            normalized = report.get("normalized_ir")
            if isinstance(normalized, dict):
                fingerprint = ir_fingerprint(normalized)
                artifact_id = f"model_legacy_{fingerprint[:8]}"
                path = self.model_version_file(artifact_id)
                equivalent = self._has_model_fingerprint(fingerprint)
                if not path.is_file() and not equivalent:
                    artifact = ModelArtifact(
                        artifact_id=artifact_id,
                        name="baseline",
                        revision=1,
                        kind="baseline",
                        validation_status=("valid" if report.get("valid") else "invalid"),
                        saved_at=str(payload.get("saved_at") or _now()),
                        fingerprint=fingerprint,
                        fingerprint_algo=FINGERPRINT_ALGO,
                        source={"type": "legacy", "tool_generated": False},
                        report=report,
                    )
                    _atomic_write_json(path, artifact.to_dict())
                    changed = True

        solve_file = self.legacy_solve_file
        if solve_file.is_file():
            payload = _read_json(solve_file) or {}
            text = str(payload.get("text") or "")
            fingerprint = str(payload.get("ir_fingerprint") or "")
            if fingerprint:
                artifact_id = f"solve_legacy_{fingerprint[:8]}"
                path = self.solve_file(artifact_id)
                equivalent = self._has_solve_fingerprint(fingerprint)
                if not path.is_file() and not equivalent:
                    model_ref = None
                    for model_path in self.versions_dir.glob("*.json"):
                        model = self._read_model_file(model_path)
                        if model is not None and model.fingerprint == fingerprint:
                            model_ref = ModelRef(model.artifact_id, model.name, model.fingerprint)
                            break
                    artifact = SolveArtifact(
                        artifact_id=artifact_id,
                        name=model_ref.name if model_ref else "baseline",
                        revision=1,
                        saved_at=str(payload.get("saved_at") or _now()),
                        model_ref=model_ref,
                        association_status="linked" if model_ref else "unassociated",
                        ir_fingerprint=fingerprint,
                        fingerprint_algo=FINGERPRINT_ALGO,
                        status=_status_from_text(text),
                        objective=_objective_from_text(text),
                        result={"text": text},
                        source={"type": "legacy", "tool_generated": False},
                    )
                    _atomic_write_json(path, artifact.to_dict())
                    changed = True
        return changed


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
    session_or_sid: "Session | str", report: dict, **kwargs: Any
) -> ModelArtifact:
    return store_for(session_or_sid).save_model_artifact(report, **kwargs)


def save_solve_artifact(
    session_or_sid: "Session | str", normalized_ir: dict, **kwargs: Any
) -> SolveArtifact:
    return store_for(session_or_sid).save_solve_artifact(normalized_ir, **kwargs)


def load_model_artifact(session_or_sid: "Session | str", artifact_id: str) -> ModelArtifact:
    return store_for(session_or_sid).load_model_artifact(artifact_id)


def load_solve_artifact(session_or_sid: "Session | str", artifact_id: str) -> SolveArtifact:
    return store_for(session_or_sid).load_solve_artifact(artifact_id)


def resolve_model(session_or_sid: "Session | str", ref: str) -> ModelArtifact:
    return store_for(session_or_sid).resolve_model(ref)


def resolve_solve(session_or_sid: "Session | str", ref: str) -> SolveArtifact:
    return store_for(session_or_sid).resolve_solve(ref)


def list_model_artifacts(session_or_sid: "Session | str", **kwargs: Any) -> list[ModelArtifact]:
    return store_for(session_or_sid).list_model_artifacts(**kwargs)


def list_solve_artifacts(session_or_sid: "Session | str", **kwargs: Any) -> list[SolveArtifact]:
    return store_for(session_or_sid).list_solve_artifacts(**kwargs)


def load_artifact_index(session_or_sid: "Session | str") -> ArtifactIndex:
    return store_for(session_or_sid).load_index()


def rebuild_artifact_index(session_or_sid: "Session | str") -> ArtifactIndex:
    return store_for(session_or_sid).rebuild_index()


__all__ = [
    "ArtifactError",
    "ArtifactIndex",
    "ArtifactLinkError",
    "ArtifactNameConflict",
    "ArtifactNotFound",
    "ArtifactStore",
    "FINGERPRINT_ALGO",
    "ModelArtifact",
    "ModelRef",
    "SCHEMA_VERSION",
    "SolveArtifact",
    "list_model_artifacts",
    "list_solve_artifacts",
    "load_artifact_index",
    "load_model_artifact",
    "load_solve_artifact",
    "rebuild_artifact_index",
    "resolve_model",
    "resolve_solve",
    "save_model_artifact",
    "save_solve_artifact",
    "store_for",
]
