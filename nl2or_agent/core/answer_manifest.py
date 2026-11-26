"""Answer-level manifest: freeze which model/solve versions one answer used.

Phase 1 provides the value object and its persistence.  Phase 2 wires it into
``expand_placeholders`` so a named placeholder resolves once, then the answer
keeps that artifact id even if a later turn creates a new version under the same
logical name.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from utils.artifact_store import (
    ArtifactLinkError,
    ArtifactNotFound,
    ArtifactStore,
    ModelArtifact,
    SolveArtifact,
    _atomic_write_json,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AnswerManifest:
    answer_id: str = ""
    session_id: str = ""
    created_at: str = ""
    model_refs: dict[str, str] = field(default_factory=dict)
    solve_refs: dict[str, str] = field(default_factory=dict)
    text_hash: str = ""
    committed: bool = False

    def __post_init__(self) -> None:
        if not self.answer_id:
            self.answer_id = f"answer_{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = _now()

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_model(self, store: ArtifactStore, ref: str | None = None) -> ModelArtifact:
        """Resolve *ref* once and freeze the artifact id in this manifest.

        ``ref`` None means the current baseline model.  A logical name resolves
        to that name's current version at resolution time; later versions under
        the same name do not change this manifest.
        """
        if ref is None or ref == "baseline":
            artifact = store.get_baseline_model()
            if artifact is None:
                raise ArtifactNotFound("没有 baseline 模型可引用")
        else:
            artifact = store.resolve_model(ref)
        self.model_refs[str(ref) if ref else artifact.name] = artifact.artifact_id
        self.model_refs[artifact.name] = artifact.artifact_id
        return artifact

    def resolve_solve(
        self,
        store: ArtifactStore,
        ref: str | None = None,
        *,
        model_artifact_id: str | None = None,
    ) -> SolveArtifact:
        """Resolve a solve result, optionally pinned to one model artifact.

        Resolution order for a logical name:
        1. an existing solve name;
        2. a model name/artifact id, using its latest successful solve;
        3. the baseline solve when ``ref`` is None.
        If ``model_artifact_id`` is given, the solve must be linked to exactly
        that model version; an unlinked or differently-linked solve is rejected.
        """
        solve: SolveArtifact | None = None
        if ref is None or ref == "baseline":
            if model_artifact_id:
                solve = store.latest_solve_for_model(model_artifact_id)
                if solve is None:
                    unassociated = [
                        item.artifact_id
                        for item in store.list_solve_artifacts()
                        if item.model_ref is None
                    ]
                    hint = (
                        f"；存在未关联的求解结果：{', '.join(unassociated)}" if unassociated else ""
                    )
                    raise ArtifactNotFound(
                        f"模型 {model_artifact_id} 没有已关联的求解结果{hint}。"
                        "请检查求解用的 IR 是否与校验时一致，或重新求解并显式关联。"
                    )
            else:
                solve = store.get_baseline_solve()
                if solve is None:
                    raise ArtifactNotFound("没有 baseline 求解结果可引用")
        else:
            try:
                solve = store.resolve_solve(ref)
            except ArtifactNotFound:
                try:
                    model = store.resolve_model(ref)
                except ArtifactNotFound:
                    raise
                solve = store.latest_solve_for_model(model.artifact_id)
                if solve is None:
                    raise ArtifactNotFound(f"模型 {ref!r} 还没有成功求解结果")

        if model_artifact_id is not None:
            if solve.model_ref is None:
                raise ArtifactLinkError(f"求解结果 {solve.artifact_id} 未关联模型，不能按模型引用")
            if solve.model_ref.artifact_id != model_artifact_id:
                raise ArtifactLinkError(
                    f"求解结果 {solve.artifact_id} 关联的是 "
                    f"{solve.model_ref.artifact_id}，不是 {model_artifact_id}"
                )

        self.solve_refs[str(ref) if ref else solve.name] = solve.artifact_id
        self.solve_refs[solve.name] = solve.artifact_id
        return solve

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = 1
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnswerManifest":
        return cls(
            answer_id=str(data.get("answer_id") or ""),
            session_id=str(data.get("session_id") or ""),
            created_at=str(data.get("created_at") or ""),
            model_refs=dict(data.get("model_refs") or {}),
            solve_refs=dict(data.get("solve_refs") or {}),
            text_hash=str(data.get("text_hash") or ""),
            committed=bool(data.get("committed", False)),
        )

    def save(self, store: ArtifactStore, *, text: str = "") -> str:
        """Persist the manifest after the whole answer rendered successfully."""
        self.committed = True
        if text:
            self.text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path = store.answer_file(self.answer_id)
        _atomic_write_json(path, self.to_dict())
        return self.answer_id

    @classmethod
    def load(cls, store: ArtifactStore, answer_id: str) -> "AnswerManifest":
        path = store.answer_file(answer_id)
        if not path.is_file():
            raise ArtifactNotFound(f"回答 manifest 不存在：{answer_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactNotFound(f"回答 manifest 无法读取：{answer_id}") from exc
        return cls.from_dict(data)


def latest_answer_manifest(store: ArtifactStore) -> AnswerManifest | None:
    """Return the most recently saved answer manifest, if any."""
    manifests = list_answer_manifests(store)
    return manifests[-1] if manifests else None


def list_answer_manifests(store: ArtifactStore) -> list[AnswerManifest]:
    manifests: list[AnswerManifest] = []
    for path in store.answers_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            manifests.append(AnswerManifest.from_dict(data))
    manifests.sort(key=lambda item: (item.created_at, item.answer_id))
    return manifests


__all__ = [
    "AnswerManifest",
    "latest_answer_manifest",
    "list_answer_manifests",
]
