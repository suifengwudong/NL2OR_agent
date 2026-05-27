"""NL2OR Agent — entry point.

Modes
-----
CLI (default)
    uv run python main.py
    uv run python main.py --mode cli

Web (Gradio GUI)
    uv run python main.py --mode web
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow imports from the project root when running directly
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()

def _run_cli() -> None:
    """Interactive CLI loop: read user input, run the agent, print the result."""
    from agents import build_nl2or_agent
    from output_format import format_for_display

    print("=" * 60)
    print("  NL2OR Agent  (输入 'quit' 或 'exit' 退出)")
    print("=" * 60)
    print()

    agent = build_nl2or_agent(verbosity_level=1)
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
            try:
                display_result = format_for_display(str(result))
            except ValueError as exc:
                display_result = (
                    f"[FINAL_ANSWER_FORMAT_ERROR] {exc}\n"
                    "原始输出如下，请修复 final_answer 的结构化格式后重试：\n"
                    f"{result}"
                )
            print(f"\nNL2OR > {display_result}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[错误] {exc}\n")


def _run_web() -> None:
    """Launch the NL2OR web GUI."""
    from agents import build_nl2or_agent
    from web import launch_web

    agent = build_nl2or_agent(verbosity_level=0)
    launch_web(agent)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NL2OR Agent — 将自然语言运筹学问题转化为数学模型并自动求解"
    )
    parser.add_argument(
        "--mode",
        choices=["cli", "web"],
        default="cli",
        help="运行模式：cli（命令行，默认）或 web（Gradio 界面）",
    )
    args = parser.parse_args()

    if args.mode == "web":
        _run_web()
    else:
        _run_cli()


if __name__ == "__main__":
    main()
