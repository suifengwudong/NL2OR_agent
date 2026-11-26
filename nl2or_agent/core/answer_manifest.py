"""Answer-level manifest: freeze which model/solve versions one answer used.

The manifest is not persisted as a separate file.  ``run_turn`` writes its
fields inline into the assistant entry of ``conversation.jsonl``:

    {"role": "assistant", "answer_id": ..., "model_refs": {...}, "solve_refs": {...}}
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from utils.artifact_store import (
    ArtifactLinkError,
    ArtifactNotFound,
    ArtifactStore,
    ModelArtifact,
    SolveArtifact,
)

if TYPE_CHECKING:
    from utils.session import Session


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

    def __post_init__(self) -> None:
        if not self.answer_id:
            self.answer_id = f"answer_{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = _now()

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_model(self, store: ArtifactStore, ref: str | None = None) -> ModelArtifact:
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
        solve: SolveArtifact | None = None
        if ref is None or ref == "baseline":
            if model_artifact_id:
                solve = store.latest_solve_for_model(model_artifact_id)
                if solve is None:
                    unassociated = [
                        item.artifact_id for item in store.list_solves() if item.model_ref is None
                    ]
                    hint = (
                        f"；存在未关联的求解结果：{', '.join(unassociated)}" if unassociated else ""
                    )
                    raise ArtifactNotFound(
                        f"模型 {model_artifact_id} 没有已关联的求解结果{hint}。"
                        "请检查求解用的模型/补丁是否一致，或重新求解并显式关联。"
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
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnswerManifest":
        return cls(
            answer_id=str(data.get("answer_id") or ""),
            session_id=str(data.get("session_id") or ""),
            created_at=str(data.get("created_at") or ""),
            model_refs=dict(data.get("model_refs") or {}),
            solve_refs=dict(data.get("solve_refs") or {}),
            text_hash=str(data.get("text_hash") or ""),
        )

    def note_text(self, text: str) -> None:
        self.text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def entry_extra(self) -> dict[str, Any]:
        extra: dict[str, Any] = {"answer_id": self.answer_id}
        if self.model_refs:
            extra["model_refs"] = self.model_refs
        if self.solve_refs:
            extra["solve_refs"] = self.solve_refs
        return extra


def latest_answer_manifest(session_or_store: "Session | ArtifactStore") -> AnswerManifest | None:
    """Read the last assistant entry that carries answer refs."""
    if isinstance(session_or_store, ArtifactStore):
        session = session_or_store.session
    else:
        session = session_or_store
    if session is None:
        return None
    for entry in reversed(session.load_conversation_entries()):
        if entry.get("role") != "assistant":
            continue
        refs = entry.get("model_refs") or entry.get("solve_refs") or entry.get("answer_id")
        if not refs:
            continue
        return AnswerManifest(
            answer_id=str(entry.get("answer_id") or ""),
            session_id=session.session_id,
            created_at=str(entry.get("timestamp") or ""),
            model_refs=dict(entry.get("model_refs") or {}),
            solve_refs=dict(entry.get("solve_refs") or {}),
        )
    return None


__all__ = ["AnswerManifest", "latest_answer_manifest"]
