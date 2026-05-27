"""Simple Gradio-based web GUI for NL2OR Agent."""

from __future__ import annotations

import gradio as gr

from core.output_format import format_for_display


def _display_answer(raw: str) -> str:
    """Render agent output for web display — tries structured format, falls back to raw."""
    try:
        return format_for_display(str(raw))
    except ValueError:
        # Fallback: strip HAMLET trace noise
        lines = [l.strip() for l in str(raw).split("\n") if l.strip()]
        clean = [l for l in lines if not l.startswith(("Thought:", "Code:", "```", "import", "╭", "╰", "━━"))]
        return "\n".join(clean[-20:]) or str(raw)[-500:]


def create_ui(agent):
    """Build and return a Gradio Blocks UI for the NL2OR agent."""

    def run_agent(message: str, history: list) -> tuple[list, str]:
        if not message or not message.strip():
            return history, ""
        try:
            result = agent.run(message.strip(), reset=False)
            answer = _display_answer(result)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": answer})
            return history, ""
        except Exception as exc:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": f"❌ Error: {exc}"})
            return history, ""

    def get_workspace_files() -> str:
        from utils.session import Session
        sessions = Session.list_all()
        if not sessions:
            return "(no sessions yet)"
        # Show files from the most recent session
        latest = Session.load(sessions[-1])
        if latest is None:
            return "(session not found)"
        files = latest.list_code_files()
        if not files:
            return "(no solver files yet)"
        return "\n".join(f.name for f in files)

    with gr.Blocks(title="NL2OR Agent") as ui:
        gr.Markdown(
            """
            # NL2OR Agent
            将自然语言运筹学问题转化为数学模型并自动求解。
            """
        )

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
                    value=get_workspace_files(),
                    lines=8,
                    interactive=False,
                )
                refresh_btn = gr.Button("刷新文件列表")
                gr.Markdown(
                    """
                    ### 使用说明
                    1. 输入自然语言描述的运筹学问题
                    2. Agent 自动解析并生成求解代码
                    3. 查看运行结果
                    """
                )

        submit_btn.click(
            fn=run_agent,
            inputs=[msg, chatbot],
            outputs=[chatbot, msg],
        )

        msg.submit(
            fn=run_agent,
            inputs=[msg, chatbot],
            outputs=[chatbot, msg],
        )

        clear_btn.click(lambda: ([], ""), None, [chatbot, msg])
        refresh_btn.click(get_workspace_files, None, [files_display])

    return ui


def launch_web(agent, **kwargs):
    """Launch the NL2OR web GUI."""
    ui = create_ui(agent)
    ui.launch(share=False, **kwargs)
