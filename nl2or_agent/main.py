"""NL2OR Agent — entry point.

Interfaces
----------
CLI (default)
    uv run python main.py
    uv run python main.py --mode cli

Web (Gradio GUI)
    uv run python main.py --mode web

Agent modes
-----------
`--agent-mode interactive` (default) advances one workflow step per user turn.
`--agent-mode automatic` runs the whole pipeline in a single turn.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow imports from the project root when running directly
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()


def _run_cli(agent_mode: str = "interactive") -> None:
    """Interactive CLI loop: read user input, run the agent, print the result."""
    from agents import build_nl2or_agent
    from core.output_format import format_agent_output
    from utils.session import get_session

    print("=" * 60)
    print(f"  NL2OR Agent  [{agent_mode}]  (输入 'quit' 或 'exit' 退出)")
    print("=" * 60)
    print()

    agent = build_nl2or_agent(mode=agent_mode, verbosity_level=1)
    while True:
        try:
            user_input = input("用户 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "q", "退出"}:
            print("再见！")
            break

        try:
            # Pass the previous state to maintain conversation in CodeAgent
            result = agent.run(user_input, reset=False)
            display_result = format_agent_output(str(result))
            print(f"\nNL2OR > {display_result}\n")
            session = get_session()
            model_status = "已生成" if session.model_file.is_file() else "未生成"
            code_files = session.list_code_files()
            print(
                f"[产物] 模型：{model_status}；"
                f"代码：{len(code_files)} 个文件；"
                f"会话目录：{session.workspace}"
            )
            if code_files:
                print("[代码文件] " + ", ".join(str(path) for path in code_files))
        except Exception as exc:  # noqa: BLE001
            print(f"\n[错误] {exc}\n")


def _run_web(agent_mode: str = "interactive") -> None:
    """Launch the NL2OR web GUI.

    Each browser tab gets its own agent instance (keyed by the hidden session
    textbox) so conversation history and solver artifacts are isolated per user.
    The mode selector in the UI starts on *agent_mode*.
    """
    from agents import build_nl2or_agent
    from web import launch_web
    from utils.session import prune_old_sessions

    prune_old_sessions(max_age_days=30)

    def agent_factory():
        return build_nl2or_agent(verbosity_level=0)

    launch_web(agent_factory, default_mode=agent_mode)


def main() -> None:
    from core.prompt_loader import AGENT_MODES

    parser = argparse.ArgumentParser(
        description="NL2OR Agent — 将自然语言运筹学问题转化为数学模型并自动求解"
    )
    parser.add_argument(
        "--mode",
        choices=["cli", "web"],
        default="cli",
        help="运行界面：cli（命令行，默认）或 web（Gradio 界面）",
    )
    parser.add_argument(
        "--agent-mode",
        choices=list(AGENT_MODES),
        default="interactive",
        help=(
            "Agent 工作模式：interactive（逐步确认，默认）或 "
            "automatic（粘贴完整需求，一次运行完成建模与求解）"
        ),
    )
    args = parser.parse_args()

    if args.mode == "web":
        _run_web(args.agent_mode)
    else:
        _run_cli(args.agent_mode)


if __name__ == "__main__":
    main()
