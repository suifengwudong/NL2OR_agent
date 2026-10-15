"""Session-backed views for the Gradio UI: 模型对照与代码文件。

Rendering only. Each function reads the session identified by ``sid`` and returns
the value one Gradio component displays; agent lifetime and the turn pipeline live
in ``web/app.py``.
"""

from __future__ import annotations

import json
from typing import Any

import gradio as gr

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


def render_model_view(payload: dict | None) -> str:
    """Markdown comparison between the validated IR and the template requirement."""
    if not payload:
        return "### 尚未解析\n提交问题后，这里显示归一化后的 Problem IR 与模板要求的对照。"

    ir = payload.get("ir") or {}
    report = payload.get("report") or {}
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
    return "\n".join(lines)


def render_model_json(payload: dict | None) -> str:
    """Normalized IR as pretty JSON (the machine-readable model of record)."""
    if not payload:
        return ""
    return json.dumps(payload.get("ir") or {}, ensure_ascii=False, indent=2)


def get_model_state(sid: str) -> tuple[str, str]:
    """Read the session's model of record and render both views."""
    payload = resolve_session(sid).load_model()
    return render_model_view(payload), render_model_json(payload)


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
