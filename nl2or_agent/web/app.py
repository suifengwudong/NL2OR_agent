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
from collections import OrderedDict
from typing import Any, Callable

import gradio as gr
from gradio.themes import Soft

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

_CSS = """
.gradio-container { max-width: 1180px !important; margin: 0 auto; }
#nl2or-hero { padding: 4px 0 8px; border-bottom: 1px solid var(--border-color-primary); }
#nl2or-hero h1 { margin-bottom: 4px; letter-spacing: 0.2px; }
#nl2or-hero p { margin: 0; color: var(--body-text-color-subdued); font-size: 14px; }
.nl2or-panel { border: 1px solid var(--border-color-primary); border-radius: 10px; padding: 12px 14px; }
.nl2or-panel h3 { margin: 0 0 6px; font-size: 14px; letter-spacing: 0.3px; }
.nl2or-hint { color: var(--body-text-color-subdued); font-size: 13px; line-height: 1.6; }
.markdown-body table { font-size: 13px; }
.markdown-body th, .markdown-body td { padding: 4px 10px; }
.gradio-container .cm-editor { font-size: 13px; }
footer { display: none !important; }
"""

_THEME = Soft(primary_hue="indigo", neutral_hue="slate", radius_size="md")
_LATEX_DELIMITERS = [
    {"left": "$$", "right": "$$", "display": True},
    {"left": "$", "right": "$", "display": False},
]


# Per-session agent cache (sid → agent instance).
# Evict the least recently used entry when exceeding _MAX_AGENTS.
_agents: OrderedDict[str, Any] = OrderedDict()
_agents_lock = threading.Lock()


def _get_or_create_agent(sid: str, agent_factory: Callable[[], Any]) -> Any:
    """Thread-safely get or create an agent instance for *sid*, evicting LRU."""
    with _agents_lock:
        if sid in _agents:
            _agents.move_to_end(sid)
            return _agents[sid]
        if len(_agents) >= _MAX_AGENTS:
            _agents.popitem(last=False)
        _agents[sid] = agent_factory()
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
        answer = format_agent_output(result)
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
        gr.Markdown(
            "# NL2OR Agent\n"
            "自然语言运筹学问题 → 数学模型 → 求解。验收对象是模型的约束块与目标函数，与代码写法无关。",
            elem_id="nl2or-hero",
        )

        state_key = gr.Textbox(value="0", visible=False)

        with gr.Tabs():
            with gr.Tab("对话"):
                with gr.Row():
                    with gr.Column(scale=7):
                        chatbot = gr.Chatbot(label="对话", height=460, latex_delimiters=_LATEX_DELIMITERS)
                        msg = gr.Textbox(
                            label="输入运筹学问题",
                            placeholder=(
                                "例如：5 个候选仓库、10 个需求点，开设 3 个，"
                                "每个需求点只能由一个已开设仓库服务，使加权总距离最小。"
                            ),
                            lines=3,
                        )
                        with gr.Row():
                            submit_btn = gr.Button("发送", variant="primary", scale=3)
                            clear_btn = gr.Button("清空对话", variant="secondary", scale=1)
                    with gr.Column(scale=3):
                        with gr.Group(elem_classes="nl2or-panel"):
                            mode_selector = gr.Radio(
                                choices=list(AGENT_MODES),
                                value=default_mode,
                                label="模式",
                            )
                            mode_info = gr.Markdown(
                                _MODE_INFO[default_mode], elem_classes="nl2or-hint"
                            )
                        with gr.Accordion("使用说明", open=True):
                            gr.Markdown(
                                "- **interactive**：输入问题 → 确认解析结果 → 查库与求解，逐步推进\n"
                                "- **automatic**：粘贴完整需求 → 一次运行自动完成建模与求解\n"
                                "- 生成后到「模型」看约束块与目标函数的对照，到「代码」看求解脚本并可改后重跑",
                                elem_classes="nl2or-hint",
                            )

            with gr.Tab("模型"):
                gr.Markdown(
                    "归一化后的 Problem IR 与模板要求逐块对照：命中 / 替代 / 缺失 / 额外。",
                    elem_classes="nl2or-hint",
                )
                with gr.Row():
                    with gr.Column(scale=3):
                        model_view = gr.Markdown(render_model_view(None), latex_delimiters=_LATEX_DELIMITERS)
                    with gr.Column(scale=2):
                        model_json = gr.Code(
                            label="归一化 Problem IR", language="json", lines=28, interactive=False
                        )
                        model_refresh = gr.Button("刷新模型", variant="secondary")

            with gr.Tab("代码"):
                gr.Markdown(
                    "agent 写出的求解脚本：可编辑后原地重跑，输出走真实的 run_solver 路径。",
                    elem_classes="nl2or-hint",
                )
                with gr.Row():
                    code_picker = gr.Dropdown(label="求解脚本", choices=[], value=None, scale=4)
                    code_refresh = gr.Button("刷新列表", variant="secondary", scale=1)
                code_editor = gr.Code(label="求解脚本", language="python", lines=24)
                with gr.Row():
                    code_save = gr.Button("保存", variant="secondary")
                    code_run = gr.Button("运行", variant="primary")
                code_output = gr.Textbox(label="运行输出", lines=12, interactive=False)
                status_line = gr.Markdown("", elem_classes="nl2or-hint")
                with gr.Accordion("全部会话的求解文件", open=False):
                    files_display = gr.Textbox(
                        value="(no sessions yet)", lines=8, interactive=False
                    )
                    files_refresh = gr.Button("刷新文件列表", variant="secondary")

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
    ui.launch(share=False, theme=_THEME, css=_CSS, **kwargs)
