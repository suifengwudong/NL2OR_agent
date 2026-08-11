"""Simple Gradio-based web GUI for NL2OR Agent."""

from __future__ import annotations

import threading
from typing import Any, Callable

import gradio as gr

from core.output_format import format_agent_output
from utils.session import Session

_MAX_AGENTS = 100


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


def create_ui(agent_factory: Callable[[], Any]):
    """Build a Gradio Blocks UI. State is stored keyed by a hidden Textbox."""

    def run_agent(message: str, history: list, sid: str) -> tuple[list, str, str]:
        if not message or not message.strip():
            return history, "", sid
        try:
            session = Session(session_id=sid) if sid and sid != "0" else Session()
            sid = session.session_id
            agent = _get_or_create_agent(sid, agent_factory)
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

    with gr.Blocks(title="NL2OR Agent") as ui:
        gr.Markdown("# NL2OR Agent\n将自然语言运筹学问题转化为数学模型并自动求解。")

        state_key = gr.Textbox(value="0", visible=False)

        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(label="对话", height=400)
                msg = gr.Textbox(
                    label="输入你的运筹学问题",
                    placeholder="例如：有5个候选仓库和10个需求点，选3个使总距离最小...",
                    lines=2,
                )
                with gr.Row():
                    submit_btn = gr.Button("发送", variant="primary")
                    clear_btn = gr.Button("清空对话")

            with gr.Column(scale=1):
                gr.Markdown("### 工作区文件")
                files_display = gr.Textbox(
                    label="已生成的求解器",
                    value="(no sessions yet)",
                    lines=12,
                    interactive=False,
                )
                refresh_btn = gr.Button("刷新文件列表")
                gr.Markdown(
                    "### 使用说明\n1. 输入运筹学问题\n2. Agent 解析并生成求解代码\n3. 查看运行结果"
                )

        submit_btn.click(
            fn=run_agent,
            inputs=[msg, chatbot, state_key],
            outputs=[chatbot, msg, state_key],
        )
        msg.submit(
            fn=run_agent,
            inputs=[msg, chatbot, state_key],
            outputs=[chatbot, msg, state_key],
        )
        clear_btn.click(
            fn=lambda: ([], ""),
            inputs=None,
            outputs=[chatbot, msg],
        )
        refresh_btn.click(get_workspace_files, [state_key], [files_display])

    return ui


def launch_web(agent_factory: Callable[[], Any], **kwargs: Any):
    """Launch the NL2OR web GUI."""
    ui = create_ui(agent_factory)
    ui.launch(share=False, **kwargs)
