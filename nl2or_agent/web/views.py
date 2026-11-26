"""Session-backed views for the Gradio UI: 模型对照与代码文件。

Rendering only. Each function reads the session identified by ``sid`` and returns
the value one Gradio component displays; agent lifetime and the turn pipeline live
in ``web/app.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr

from core.answer_manifest import latest_answer_manifest
from core.model_document import render_model_document
from utils.artifact_store import ArtifactNotFound, ArtifactStore, ModelArtifact, SolveArtifact
from utils.session import Session, resolve_session


def get_workspace_files(sid: str) -> str:
    """List solver files from all sessions on disk."""
    sessions = Session.list_all()
    if not sessions:
        return "(no sessions yet)"
    lines: list[str] = []
    for sid_iter in reversed(sessions):
        session = Session.load(sid_iter)
        if session is None:
            continue
        files = session.list_code_files()
        if files:
            marker = " ← 当前" if sid_iter == sid else ""
            lines.append(f"   [{sid_iter[:8]}]{marker}")
            lines.extend(f"      {f.name}" for f in files)
    return "\n".join(lines) or "(no solver files yet)"


# ---------------------------------------------------------------------------
# Model view: 归一化 IR 与模板要求的对照
# ---------------------------------------------------------------------------


def _fmt_value(value: Any) -> str:
    """Render a parameter value compactly."""
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            return f"{len(value)}x{len(value[0])} 矩阵"
        return f"列表({len(value)})"
    if isinstance(value, dict):
        return f"对象({len(value)} 键)"
    return str(value)


def _fmt_params(params: dict) -> str:
    if not params:
        return "—"
    return "、".join(f"{k}={_fmt_value(v)}" for k, v in params.items())


def render_unvalidated_view(artifact: ModelArtifact) -> str:
    """Report for a direct file that never went through validate_problem_ir."""
    source = artifact.source or {}
    return "\n".join(
        [
            f"### 模型文件：{artifact.name}（未校验）",
            "",
            f"- Artifact ID：`{artifact.artifact_id}`",
            f"- 来源：{source.get('path') or source.get('type') or '直接写入'}",
            "",
            "该文件不是 `validate_problem_ir` 生成的模型报告，",
            "无法给出约束块对照、骨架校验或数学模型。",
        ]
    )


def render_model_view(
    payload: dict | None,
    *,
    artifact: ModelArtifact | None = None,
    is_baseline: bool = False,
    linked_solves: list[SolveArtifact] | None = None,
) -> str:
    """Markdown comparison between the validated IR and the template requirement."""
    if artifact is not None and artifact.report is None:
        return render_unvalidated_view(artifact)
    if not payload:
        return "### 尚未解析\n提交问题后，这里显示归一化后的 Problem IR 与模板要求的对照。"

    report = payload.get("report") or {}
    ir = report.get("normalized_ir") or {}
    skeleton = report.get("skeleton") or {}
    families = ir.get("problem_families") or []
    entities = ir.get("entities") or {}
    objective = ir.get("objective") or {}
    present = {b["block_id"]: b for b in ir.get("constraint_blocks") or []}
    required = list(skeleton.get("required_blocks") or [])
    missing = set(skeleton.get("missing_required_blocks") or [])
    substituted = set(skeleton.get("substituted_blocks") or [])
    inconsistent = set(skeleton.get("inconsistent_blocks") or [])

    lines: list[str] = []
    verdict = "✅ 校验通过" if report.get("valid") else "❌ 校验未通过"
    if artifact is not None:
        lines.append(f"### 模型报告：{artifact.name}（{verdict}）")
        lines.append("")
        kind_label = "baseline（当前基准）" if is_baseline else artifact.kind
        lines.append(f"- 类型：{kind_label}")
        lines.append(f"- Artifact ID：`{artifact.artifact_id}`")
        lines.append(f"- 版本：v{artifact.revision}")
        lines.append(f"- 保存时间：{artifact.saved_at}")
        lines.append(f"- 指纹：`{artifact.fingerprint}`")
    else:
        lines.append(f"### 模型对照（{verdict}）")
    lines.append("")
    lines.append(f"- 问题族：{', '.join(str(f.get('id')) for f in families) or '未声明'}")
    size_i = (entities.get("I") or {}).get("size")
    size_j = (entities.get("J") or {}).get("size")
    lines.append(
        f"- 索引集合：|I| = {size_i if size_i else '未声明'}，|J| = {size_j if size_j else '未声明'}"
    )
    lines.append("")

    lines.append("**约束块：模板要求 与 IR 实际**")
    lines.append("")
    if required:
        lines.append("| 约束块 | 状态 | 参数 |")
        lines.append("|--------|------|------|")
        for block_id in required:
            if block_id in present:
                status = "命中"
            elif block_id in substituted:
                status = "被同类别可选块替代"
            elif block_id in missing:
                status = "缺失"
            else:
                status = "未出现"
            lines.append(
                f"| `{block_id}` | {status} | "
                f"{_fmt_params(present.get(block_id, {}).get('parameters') or {})} |"
            )
    else:
        lines.append("（未声明问题族，无法与模板对照）")
    for block_id, entry in present.items():
        if block_id in required:
            continue
        note = "与声明的族不一致" if block_id in inconsistent else "模板未要求"
        lines.append(
            f"| `{block_id}` | 额外（{note}） | {_fmt_params(entry.get('parameters') or {})} |"
        )
    lines.append("")

    lines.append("**目标函数**")
    lines.append("")
    lines.append(
        f"- 目标块：`{objective.get('block_id') or '未声明'}`"
        f"（方向 {objective.get('sense') or '未声明'}，"
        f"{'在库中' if skeleton.get('objective_in_catalog') else '库外目标'}）"
    )
    unbound = skeleton.get("unbound_objective_params") or []
    if unbound:
        lines.append(f"- 未绑定参数：{', '.join(unbound)}")
    lines.append("")

    custom = ir.get("custom_constraints") or []
    missing_data = ir.get("missing_data") or []
    if custom or missing_data:
        lines.append("**库外规则与缺失数据**")
        lines.append("")
        for item in custom:
            lines.append(f"- 自定义约束：{item}")
        for item in missing_data:
            lines.append(f"- 缺失数据：{item}")
        lines.append("")

    errors = report.get("errors") or []
    warnings = report.get("warnings") or []
    if errors or warnings:
        lines.append("**校验信息**")
        lines.append("")
        for message in errors:
            lines.append(f"- 错误：{message}")
        for message in warnings:
            lines.append(f"- 提示：{message}")
        lines.append("")

    if ir:
        lines.append(render_model_document(ir))

    if artifact is not None:
        lines.append("")
        lines.append("**关联求解**")
        lines.append("")
        solves = linked_solves or []
        if not solves:
            lines.append("尚未求解。")
        else:
            lines.append("| 求解 | 状态 | 目标值 | 时间 |")
            lines.append("|------|------|-------:|------|")
            for solve in solves:
                objective = (
                    solve.objective
                    if solve.status == "Optimal" and solve.objective is not None
                    else "—"
                )
                lines.append(
                    f"| `{solve.artifact_id}` | {solve.status} | {objective} | {solve.saved_at} |"
                )
    return "\n".join(lines)


def render_model_json(payload: dict | None) -> str:
    """Normalized IR as pretty JSON (the machine-readable model of record)."""
    if not payload:
        return ""
    normalized = (payload.get("report") or {}).get("normalized_ir") or {}
    return json.dumps(normalized, ensure_ascii=False, indent=2)


def _imported_json(artifact: ModelArtifact) -> str:
    path = (artifact.source or {}).get("path")
    if not path:
        return ""
    try:
        return Path(str(path)).read_text(encoding="utf-8")
    except OSError:
        return ""


def render_model_summary(store: ArtifactStore, *, selected_id: str | None = None) -> str:
    """Session-level artifact summary: one row per current logical model."""
    models = store.list_model_artifacts(current_only=True, include_imports=True)
    if not models:
        return ""
    index = store.load_index()
    models = sorted(
        models, key=lambda item: (item.artifact_id != index.baseline_model, item.saved_at)
    )
    solved = 0
    unvalidated = 0
    rows: list[str] = []
    for model in models:
        solves = store.find_solves_by_model(model.artifact_id)
        if solves:
            solved += 1
        if model.validation_status == "unvalidated":
            unvalidated += 1
        latest = solves[-1] if solves else None
        solve_text = latest.status if latest is not None else "尚未求解"
        objective = (
            latest.objective
            if latest is not None and latest.status == "Optimal" and latest.objective is not None
            else "—"
        )
        entry = index.models.get(model.name) or {}
        marker = (
            " **← 当前**"
            if selected_id == model.artifact_id or selected_id in entry.get("versions", [])
            else ""
        )
        kind_label = "baseline" if model.artifact_id == index.baseline_model else model.kind
        rows.append(
            f"| {model.name}{marker} | {kind_label} | {model.validation_status} | "
            f"{solve_text} | {objective} | {model.saved_at} |"
        )
    unassociated = [
        item for item in store.list_solve_artifacts(current_only=True) if item.model_ref is None
    ]
    lines = [
        f"### 会话模型（{len(models)} 个，已求解 {solved}，"
        f"未关联 {len(unassociated)}，未校验 {unvalidated}）",
        "",
        "| 模型 | 类型 | 校验 | 求解 | 目标值 | 时间 |",
        "|------|------|------|------|-------:|------|",
        *rows,
    ]
    if unassociated:
        lines.extend(
            [
                "",
                "**未关联求解**（IR 与已校验模型不一致，未强行关联）",
                "",
                "| 求解 | 状态 | 目标值 | 时间 |",
                "|------|------|-------:|------|",
            ]
        )
        for solve in unassociated:
            objective = (
                solve.objective
                if solve.status == "Optimal" and solve.objective is not None
                else "—"
            )
            lines.append(
                f"| `{solve.artifact_id}`（{solve.name}） | {solve.status} | "
                f"{objective} | {solve.saved_at} |"
            )
    return "\n".join(lines)


def _default_model(store: ArtifactStore, models: list[ModelArtifact]) -> ModelArtifact:
    manifest = latest_answer_manifest(store)
    if manifest is not None:
        for artifact_id in manifest.model_refs.values():
            try:
                return store.load_model_artifact(artifact_id)
            except ArtifactNotFound:
                continue
    baseline = store.get_baseline_model()
    return baseline if baseline is not None else models[0]


def get_model_state(sid: str, name: str | None = None) -> tuple[str, str]:
    """Read the selected model artifact (or legacy model.json) and render both views."""
    session = resolve_session(sid)
    store = ArtifactStore(session)
    models = store.list_model_artifacts(current_only=True, include_imports=True)
    if not models:
        payload = session.load_model()
        return render_model_view(payload), render_model_json(payload)

    if name:
        try:
            selected = store.resolve_model(name)
        except ArtifactNotFound as exc:
            return f"### 未找到模型\n\n{exc}", ""
    else:
        selected = _default_model(store, models)

    solves = store.find_solves_by_model(selected.artifact_id)
    index = store.load_index()
    if selected.report is None:
        detail = render_unvalidated_view(selected)
        raw = _imported_json(selected)
    else:
        detail = render_model_view(
            {"report": selected.report},
            artifact=selected,
            is_baseline=selected.artifact_id == index.baseline_model,
            linked_solves=solves,
        )
        raw = render_model_json({"report": selected.report})
    summary = render_model_summary(store, selected_id=selected.artifact_id)
    return f"{summary}\n\n{detail}", raw


def list_model_choices(sid: str) -> Any:
    """Refresh the model dropdown; every version is selectable, baseline first."""
    session = resolve_session(sid)
    store = ArtifactStore(session)
    index = store.load_index()
    models = store.list_model_artifacts(current_only=True, include_imports=True)
    choices: list[tuple[str, str]] = []
    for name, entry in sorted(
        index.models.items(),
        key=lambda kv: (kv[1]["current"] != index.baseline_model, kv[0]),
    ):
        for artifact in store.list_model_versions(name):
            kind_label = (
                "baseline" if artifact.artifact_id == index.baseline_model else artifact.kind
            )
            marker = " ← 当前" if artifact.artifact_id == entry["current"] else ""
            choices.append(
                (
                    f"{name} v{artifact.revision}{marker}（{kind_label}）",
                    artifact.artifact_id,
                )
            )
    for item in store.scan_imported_models():
        choices.append((f"{item.name}（imported，未校验）", item.artifact_id))
    if not choices:
        return gr.update(choices=[], value=None)
    default = _default_model(store, models).artifact_id if models else choices[-1][1]
    return gr.update(choices=choices, value=default)


def _open_directory(path: Path) -> None:
    """Open *path* in the platform file manager."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_model_session(sid: str) -> str:
    """Open the session workspace that holds model artifacts and solver scripts."""
    session = Session.load(sid) if sid and sid != "0" else None
    if session is None:
        return "当前会话尚未创建。"
    if not session.model_file.is_file() and not _artifact_model_count(session):
        return "当前会话尚未生成模型。"
    try:
        _open_directory(session.workspace)
    except OSError as exc:
        return f"无法打开会话目录：{exc}"
    return f"已打开模型会话目录：{session.workspace}"


# ---------------------------------------------------------------------------
# History view: previous sessions and their visible conversation
# ---------------------------------------------------------------------------


def _artifact_model_count(session: Session) -> int:
    """Count model artifacts on disk without triggering a lazy legacy import."""
    artifacts = session.workspace / "artifacts"
    count = len(list((artifacts / "model_versions").glob("*.json")))
    count += len(list((artifacts / "imports").glob("*.json")))
    if count == 0 and session.model_file.is_file():
        count = 1
    return count


def _artifact_solve_count(session: Session) -> int:
    """Count solve artifacts on disk without triggering a lazy legacy import."""
    artifacts = session.workspace / "artifacts"
    count = len(list((artifacts / "solves").glob("*.json")))
    if count == 0 and session.solve_result_file.is_file():
        count = 1
    return count


def history_choices() -> list[tuple[str, str]]:
    """Return ``(label, session_id)`` pairs, newest activity first."""
    choices: list[tuple[float, str, str]] = []
    for sid in Session.list_all():
        session = Session.load(sid)
        if session is None:
            continue
        messages = session.load_conversation()
        if not messages:
            # 历史会话列表只列有可见对话的会话；纯产物目录不混进来。
            continue
        try:
            activity = session.last_conversation_activity() or session.last_activity()
        except OSError:
            continue
        code_files = session.list_code_files()
        model_count = _artifact_model_count(session)
        solve_count = _artifact_solve_count(session)
        stamp = datetime.fromtimestamp(activity).strftime("%Y-%m-%d %H:%M")
        model_label = f"✓×{model_count}" if model_count else "—"
        label = (
            f"{stamp} · {sid[:8]} · {len(messages)} 条对话 · "
            f"模型 {model_label} · 求解 {solve_count} · "
            f"代码 {len(code_files)}"
        )
        choices.append((activity, label, sid))
    choices.sort(key=lambda item: item[0], reverse=True)
    return [(label, sid) for _, label, sid in choices]


def refresh_history_choices() -> Any:
    """Refresh the history dropdown from disk."""
    return gr.update(choices=history_choices())


def load_history(sid: str | None) -> tuple[Any, Any, str]:
    """Load one previous session's visible conversation.

    The selection becomes the active session, so the model and code views can
    follow it. A fresh agent in that session is hydrated by ``run_turn``.
    """
    if not sid:
        return gr.update(), gr.update(), "请选择历史会话。"
    session = Session.load(sid)
    if session is None:
        return gr.update(), gr.update(), "该会话不存在。"
    messages = session.load_conversation()
    if not messages:
        return messages, sid, "该会话没有对话记录，已加载可用产物。"
    return messages, sid, f"已加载 {len(messages)} 条历史记录。"


# ---------------------------------------------------------------------------
# Code view: agent 产出的求解脚本，可编辑后重跑
# ---------------------------------------------------------------------------


def list_code_choices(sid: str) -> Any:
    """Refresh the code file dropdown for the session."""
    names = [f.name for f in reversed(resolve_session(sid).list_code_files())]
    if not names:
        return gr.update(choices=[], value=None)
    return gr.update(choices=names, value=names[0])


def load_code(sid: str, filename: str | None) -> str:
    """Read one solver file from the session workspace."""
    if not filename:
        return ""
    path = resolve_session(sid).code_dir / filename
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def save_code(sid: str, filename: str | None, code: str) -> str:
    """Write edited code back to the session workspace."""
    if not filename:
        return "未选择文件。"
    path = resolve_session(sid).save_code(code, filename)
    return f"已保存：{path.name}"


def run_code(sid: str, filename: str | None, code: str) -> str:
    """Re-run the (possibly edited) script through the real run_solver path."""
    from tools.solver_tool import RunSolverTool

    if not filename:
        return "未选择文件。"
    session = resolve_session(sid)
    return RunSolverTool(workspace_dir=session.code_dir).run_file(code, filename)
