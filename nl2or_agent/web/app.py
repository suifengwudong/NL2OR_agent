"""Gradio web GUI for NL2OR Agent.

Three views over one session:

对话  聊天与模式选择（interactive / automatic）
模型  归一化 Problem IR 与模板要求的对照，含校验结论（内容层，与代码写法无关）
代码  agent 写出的求解脚本，可编辑后原地重跑
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import gradio as gr

from agents import AGENT_MODES, apply_agent_mode
from core.output_format import format_agent_output
from utils.session import Session

_MAX_AGENTS = 100

_MODE_INFO = {
    "interactive": "逐步确认：先给出解析结果，确认后再查库与求解。",
    "automatic": "自动完成：粘贴完整需求，一次运行完成解析、查库、建模与求解。",
}


def _display_answer(raw: str) -> str:
    """Render agent output for web display."""
    return format_agent_output(raw)


# Per-session agent cache (sid → agent instance).
# Evict oldest when exceeding _MAX_AGENTS to prevent memory leaks.
_agents: dict[str, Any] = {}
_agent_access_order: list[str] = []
_agents_lock = threading.Lock()


def _get_or_create_agent(sid: str, agent_factory: Callable[[], Any]) -> Any:
    """Thread-safely get or create an agent instance for *sid*, evicting LRU."""
    with _agents_lock:
        if sid not in _agents:
            if len(_agents) >= _MAX_AGENTS:
                oldest = _agent_access_order.pop(0)
                _agents.pop(oldest, None)
            _agents[sid] = agent_factory()
        if sid in _agent_access_order:
            _agent_access_order.remove(sid)
        _agent_access_order.append(sid)
        if len(_agent_access_order) > _MAX_AGENTS * 2:
            _agent_access_order[:] = _agent_access_order[-_MAX_AGENTS:]
        return _agents[sid]


def _resolve_session(sid: str) -> Session:
    """Return the session for *sid*, creating one when none is given."""
    if sid and sid != "0":
        existing = Session.load(sid)
        if existing is not None:
            return existing
    return Session()


def get_workspace_files(sid: str) -> str:
    """List solver files from all sessions on disk."""
    sessions = Session.list_all()
    if not sessions:
        return "(no sessions yet)"
    lines: list[str] = []
    for sid_iter in reversed(sessions):
        s = Session.load(sid_iter)
        if s is None:
            continue
        files = s.list_code_files()
        if files:
            marker = " ← 当前" if sid_iter == sid else ""
            lines.append(f"   [{sid_iter[:8]}]{marker}")
            lines.extend(f"      {f.name}" for f in files)
    return "\n".join(lines) or "(no solver files yet)"


def run_agent_turn(
    agent_factory: Callable[[], Any],
    message: str,
    history: list,
    sid: str,
    mode: str,
) -> tuple[list, str, str]:
    """Run one chat turn in *mode* and append the exchange to *history*.

    Returns the updated ``(history, cleared_input, session_id)``.
    """
    if not message or not message.strip():
        return history, "", sid
    try:
        session = _resolve_session(sid)
        sid = session.session_id
        agent = _get_or_create_agent(sid, agent_factory)
        apply_agent_mode(agent, mode)
        session.save_conversation_entry(role="user", content=message.strip())
        result = agent.run(message.strip(), reset=False)
        answer = _display_answer(result)
        session.save_conversation_entry(role="assistant", content=answer)
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": answer})
        return history, "", sid
    except Exception as exc:
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": f"❌ Error: {exc}"})
        return history, "", sid


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
                f"| `{block_id}` | {status} | {_fmt_params(present.get(block_id, {}).get('parameters') or {})} |"
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
    import json

    if not payload:
        return ""
    return json.dumps(payload.get("ir") or {}, ensure_ascii=False, indent=2)


def get_model_state(sid: str) -> tuple[str, str]:
    """Read the session's model of record and render both views."""
    session = _resolve_session(sid)
    payload = session.load_model()
    return render_model_view(payload), render_model_json(payload)


# ---------------------------------------------------------------------------
# Code view: agent 产出的求解脚本，可编辑后重跑
# ---------------------------------------------------------------------------


def list_code_choices(sid: str) -> Any:
    """Refresh the code file dropdown for the session."""
    session = _resolve_session(sid)
    names = [f.name for f in reversed(session.list_code_files())]
    if not names:
        return gr.update(choices=[], value=None)
    return gr.update(choices=names, value=names[0])


def load_code(sid: str, filename: str | None) -> str:
    """Read one solver file from the session workspace."""
    if not filename:
        return ""
    path = _resolve_session(sid).code_dir / filename
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def save_code(sid: str, filename: str | None, code: str) -> str:
    """Write edited code back to the session workspace."""
    if not filename:
        return "未选择文件。"
    path = _resolve_session(sid).save_code(code, filename)
    return f"已保存：{path.name}"


def run_code(sid: str, filename: str | None, code: str) -> str:
    """Re-run the (possibly edited) script through the real run_solver path."""
    from tools.solver_tool import RunSolverTool

    if not filename:
        return "未选择文件。"
    session = _resolve_session(sid)
    return RunSolverTool(workspace_dir=session.code_dir).run_file(code, filename)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def create_ui(agent_factory: Callable[[], Any], default_mode: str = "interactive"):
    """Build the Gradio Blocks UI. Session state is held in a hidden Textbox."""

    def run_agent(message: str, history: list, sid: str, mode: str) -> tuple[list, str, str]:
        return run_agent_turn(agent_factory, message, history, sid, mode)

    with gr.Blocks(title="NL2OR Agent") as ui:
        gr.Markdown("# NL2OR Agent\n将自然语言运筹学问题转化为数学模型并自动求解。")

        state_key = gr.Textbox(value="0", visible=False)

        with gr.Tabs():
            with gr.Tab("对话"):
                with gr.Row():
                    with gr.Column(scale=3):
                        chatbot = gr.Chatbot(label="对话", height=420)
                        mode_selector = gr.Radio(
                            choices=list(AGENT_MODES),
                            value=default_mode,
                            label="模式",
                        )
                        mode_info = gr.Markdown(_MODE_INFO[default_mode])
                        msg = gr.Textbox(
                            label="输入你的运筹学问题",
                            placeholder="例如：有5个候选仓库和10个需求点，选3个使总距离最小...",
                            lines=2,
                        )
                        with gr.Row():
                            submit_btn = gr.Button("发送", variant="primary")
                            clear_btn = gr.Button("清空对话")
                    with gr.Column(scale=1):
                        gr.Markdown("### 使用说明")
                        gr.Markdown(
                            "**interactive**：输入问题 → 确认解析结果 → 查库与求解，逐步推进。\n\n"
                            "**automatic**：粘贴完整需求 → 一次运行自动完成建模与求解。\n\n"
                            "生成结果可在「模型」与「代码」两个标签查看。"
                        )

            with gr.Tab("模型"):
                with gr.Row():
                    model_view = gr.Markdown(render_model_view(None))
                    with gr.Column():
                        model_json = gr.Code(
                            label="归一化 Problem IR", language="json", lines=26, interactive=False
                        )
                        model_refresh = gr.Button("刷新模型")

            with gr.Tab("代码"):
                with gr.Row():
                    code_picker = gr.Dropdown(label="求解脚本", choices=[], value=None, scale=3)
                    code_refresh = gr.Button("刷新列表", scale=1)
                code_editor = gr.Code(label="求解脚本（可修改后重跑）", language="python", lines=22)
                with gr.Row():
                    code_save = gr.Button("保存")
                    code_run = gr.Button("运行", variant="primary")
                code_output = gr.Textbox(label="运行输出", lines=10, interactive=False)
                status_line = gr.Markdown("")
                with gr.Accordion("全部会话的求解文件", open=False):
                    files_display = gr.Textbox(
                        value="(no sessions yet)", lines=8, interactive=False
                    )
                    files_refresh = gr.Button("刷新文件列表")

        submit_btn.click(
            fn=run_agent,
            inputs=[msg, chatbot, state_key, mode_selector],
            outputs=[chatbot, msg, state_key],
        ).then(fn=get_model_state, inputs=[state_key], outputs=[model_view, model_json])
        msg.submit(
            fn=run_agent,
            inputs=[msg, chatbot, state_key, mode_selector],
            outputs=[chatbot, msg, state_key],
        ).then(fn=get_model_state, inputs=[state_key], outputs=[model_view, model_json])
        clear_btn.click(fn=lambda: ([], ""), inputs=None, outputs=[chatbot, msg])
        mode_selector.change(
            fn=lambda mode: _MODE_INFO[mode],
            inputs=[mode_selector],
            outputs=[mode_info],
        )

        model_refresh.click(get_model_state, [state_key], [model_view, model_json])

        code_refresh.click(list_code_choices, [state_key], [code_picker]).then(
            load_code, [state_key, code_picker], [code_editor]
        )
        code_picker.change(load_code, [state_key, code_picker], [code_editor])
        code_save.click(save_code, [state_key, code_picker, code_editor], [status_line])
        code_run.click(run_code, [state_key, code_picker, code_editor], [code_output]).then(
            get_workspace_files, [state_key], [files_display]
        )
        files_refresh.click(get_workspace_files, [state_key], [files_display])

    return ui


def launch_web(
    agent_factory: Callable[[], Any],
    default_mode: str = "interactive",
    **kwargs: Any,
):
    """Launch the NL2OR web GUI."""
    ui = create_ui(agent_factory, default_mode=default_mode)
    ui.launch(share=False, **kwargs)
