"""Gradio web GUI for NL2OR Agent.

Holds agent lifetime, the chat turn pipeline and the UI wiring; the session-backed
views it feeds live in ``web/views.py``.

Three views over one session:

对话  聊天与模式选择（interactive / automatic）
模型  归一化 Problem IR 与模板要求的对照（内容层，与代码写法无关）
代码  agent 写出的求解脚本，可编辑后原地重跑
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import gradio as gr

from agents import AGENT_MODES, apply_agent_mode
from core.output_format import format_agent_output
from utils.session import get_session, resolve_session

from .views import (
    get_model_state,
    get_workspace_files,
    list_code_choices,
    load_code,
    render_model_view,
    run_code,
    save_code,
)

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
        session = resolve_session(sid)
        sid = session.session_id
        # Tools persist model/code through the thread-local session when they
        # are created without an explicit workspace. Bind that session to the
        # browser's session id before running the agent.
        get_session(sid)
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

        submit_event = submit_btn.click(
            fn=run_agent,
            inputs=[msg, chatbot, state_key, mode_selector],
            outputs=[chatbot, msg, state_key],
        ).then(fn=get_model_state, inputs=[state_key], outputs=[model_view, model_json])
        submit_event.then(fn=list_code_choices, inputs=[state_key], outputs=[code_picker]).then(
            fn=load_code, inputs=[state_key, code_picker], outputs=[code_editor]
        )

        submit_event = msg.submit(
            fn=run_agent,
            inputs=[msg, chatbot, state_key, mode_selector],
            outputs=[chatbot, msg, state_key],
        ).then(fn=get_model_state, inputs=[state_key], outputs=[model_view, model_json])
        submit_event.then(fn=list_code_choices, inputs=[state_key], outputs=[code_picker]).then(
            fn=load_code, inputs=[state_key, code_picker], outputs=[code_editor]
        )
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
