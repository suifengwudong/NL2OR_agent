"""Agent output rendering for the CLI and the web UI.

The agent's content of record is the Problem IR (constraint set and objective),
so this module no longer imposes a prose schema on the reply: it strips harness
noise and expands the placeholders that carry the authoritative sections.

Placeholders may name an artifact::

    [MODEL_MATH]            baseline model
    [MODEL_MATH:cap400]     logical name or artifact id
    [SOLVE_RESULT]          baseline solve
    [SOLVE_RESULT:cap400]   logical name or artifact id

When the session has artifacts, both sections are resolved from the artifact
store and an AnswerManifest freezes the chosen artifact ids after the whole
answer renders. Legacy sessions that only have ``model.json`` / ``solve_result.json``
keep the old fingerprint-checked path.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from core.answer_manifest import AnswerManifest
from core.model_document import render_model_document
from core.problem_ir import fingerprint
from utils.artifact_store import ArtifactStore

if TYPE_CHECKING:
    from utils.session import Session

MODEL_MATH_PLACEHOLDER = "[MODEL_MATH]"
SOLVE_RESULT_PLACEHOLDER = "[SOLVE_RESULT]"

_NOISE_PREFIXES = ("Thought:", "Code:", "```", "import", "╭", "╰", "━━")

_PLACEHOLDER_RE = re.compile(r"\\?\[(MODEL_MATH|SOLVE_RESULT)(?::([^\\\]\s]+))?\\?\]")
_MODEL_RE = re.compile(r"\[MODEL_MATH(?::([^\]\s]+))?\]")
_SOLVE_RE = re.compile(r"\[SOLVE_RESULT(?::([^\]\s]+))?\]")
_VARIANT_RE = re.compile(r"\[[A-Z0-9_]*(MODEL_MATH|SOLVE_RESULT)[A-Z0-9_]*\]")


def format_agent_output(raw: str) -> str:
    """Clean agent output for display.

    Drops harness noise lines while preserving the complete answer and its
    Markdown spacing (especially display math and lists).
    """
    text = str(raw).strip()
    if not text:
        return ""

    lines = text.splitlines()
    clean = [
        line
        for line in lines
        if not line.lstrip().startswith(_NOISE_PREFIXES) and "```" not in line
    ]
    return "\n".join(clean).strip() or text


def _has_artifacts(store: ArtifactStore) -> bool:
    return store.has_artifacts()


def _normalize_placeholders(text: str) -> str:
    def canonical(match: re.Match[str]) -> str:
        suffix = f":{match.group(2)}" if match.group(2) else ""
        return f"[{match.group(1)}{suffix}]"

    text = _PLACEHOLDER_RE.sub(canonical, text)
    # Tolerate model-invented variants such as [MODEL_SOLVE_RESULT_PLACEHOLDER].
    return _VARIANT_RE.sub(lambda match: f"[{match.group(1)}]", text)


def _expand_legacy(text: str, session: "Session") -> str:
    """Original single-model path, kept for sessions without artifacts."""
    if _MODEL_RE.search(text) and any(m.group(1) for m in _MODEL_RE.finditer(text)):
        raise ValueError("命名占位符需要 artifact store；当前会话只有旧版 model.json")
    if _SOLVE_RE.search(text) and any(m.group(1) for m in _SOLVE_RE.finditer(text)):
        raise ValueError("命名占位符需要 artifact store；当前会话只有旧版 solve_result.json")

    if MODEL_MATH_PLACEHOLDER in text:
        model = session.load_model()
        if model is None:
            raise ValueError(
                f"{MODEL_MATH_PLACEHOLDER} 没有对应的已校验模型：请先调用 validate_problem_ir"
            )
        document = render_model_document(model["report"]["normalized_ir"])
        text = text.replace(MODEL_MATH_PLACEHOLDER, document)
        # 占位符自带 ## 数学模型 标题；agent 若又写了一个，相邻的重复标题去掉一个
        text = re.sub(r"(?m)^## 数学模型\s*\n## 数学模型\s*$", "## 数学模型", text)

    if SOLVE_RESULT_PLACEHOLDER in text:
        model = session.load_model()
        if model is None:
            raise ValueError(
                f"{SOLVE_RESULT_PLACEHOLDER} 没有对应的已校验模型：请先调用 validate_problem_ir"
            )
        path = session.solve_result_file
        if not path.is_file():
            raise ValueError(
                f"{SOLVE_RESULT_PLACEHOLDER} 没有已保存的基准求解结果：请先调用 solve_ir"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        current = fingerprint(model["report"]["normalized_ir"])
        if payload.get("ir_fingerprint") != current:
            raise ValueError(
                f"{SOLVE_RESULT_PLACEHOLDER} 对应的模型已变更：请对当前模型重新调用 solve_ir"
            )
        text = text.replace(SOLVE_RESULT_PLACEHOLDER, str(payload["text"]))
    return text


def _expand_artifacts(
    text: str,
    session: "Session",
    store: ArtifactStore,
    manifest: AnswerManifest,
) -> str:
    def render_model(match: re.Match[str]) -> str:
        ref = match.group(1)
        artifact = manifest.resolve_model(store, ref)
        return render_model_document(store.effective_ir(artifact))

    def render_solve(match: re.Match[str]) -> str:
        ref = match.group(1)
        model_id = manifest.model_refs.get(ref) if ref else None
        if ref is None:
            baseline = store.get_baseline_model()
            model_id = baseline.artifact_id if baseline is not None else None
        artifact = manifest.resolve_solve(store, ref, model_artifact_id=model_id)
        result_text = str((artifact.result or {}).get("text") or "")
        if not result_text:
            raise ValueError(f"求解结果 {artifact.artifact_id} 没有可展示的文本")
        return result_text

    # Resolve models first so a solve with the same logical name can be checked
    # against the exact model version this answer references.
    text = _MODEL_RE.sub(render_model, text)
    text = _SOLVE_RE.sub(render_solve, text)
    manifest.note_text(text)
    return text


def expand_placeholders(
    text: str, session: "Session", manifest: AnswerManifest | None = None
) -> str:
    """Replace the authoritative-section placeholders from session artifacts.

    An unresolved placeholder fails loudly: leaving it as a literal, or filling
    it with a stale result from an earlier IR, would silently put a wrong model
    in front of the user.  When *manifest* is given, it records the resolved
    ids so the runtime can store them inline in the conversation entry.
    """
    text = _normalize_placeholders(text)
    store = ArtifactStore(session)
    if _has_artifacts(store):
        return _expand_artifacts(
            text, session, store, manifest or AnswerManifest(session_id=session.session_id)
        )
    return _expand_legacy(text, session)
