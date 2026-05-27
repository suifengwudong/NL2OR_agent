"""Simple Gradio-based web GUI for NL2OR Agent."""

from __future__ import annotations

from pathlib import Path
import re

import gradio as gr


def _extract_final_answer(raw: str) -> str:
    """Extract the content of the last ``final_answer(...)`` call from HAMLET output.

    HAMLET returns the full execution trace (Thought → Code → Observation).
    For the web UI we only want the user-facing answer text.
    """
    # Try to find final_answer("...") or final_answer("""...""")
    # Match the last occurrence
    pattern = r'final_answer\((["\']{1,3})(.*?)\1\s*\)'
    matches = list(re.finditer(pattern, raw, re.DOTALL))
    if matches:
        return matches[-1].group(2).strip()
    # Fallback: return last non-empty line after stripping thought traces
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    # Remove "Thought:", "Code:" prefixed lines and code blocks
    clean = [l for l in lines if not l.startswith(("Thought:", "Code:", "```", "import", "╭", "╰", "━━"))]
    return "\n".join(clean[-20:]) or raw[-500:]


def create_ui(agent, workspace_dir: str | Path | None = None):
    """Build and return a Gradio Blocks UI for the NL2OR agent."""

    workspace = Path(workspace_dir) if workspace_dir else (
        Path(__file__).parent.parent / "data" / "workspace"
    )

    def run_agent(message: str, history: list) -> tuple[list, str]:
        if not message or not message.strip():
            return history, ""
        try:
            result = agent.run(message.strip())
            # Extract only final_answer content, skip intermediate IR / Thought blocks
            answer = _extract_final_answer(result)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": answer})
            return history, ""
        except Exception as exc:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": f"❌ 出错了：{exc}"})
            return history, ""

    def get_workspace_files() -> str:
        if not workspace.exists():
            return "(workspace not found)"
        files = sorted(workspace.glob("solver_*.py"))
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
    ui.launch(share=False, theme=gr.themes.Soft(), **kwargs)
