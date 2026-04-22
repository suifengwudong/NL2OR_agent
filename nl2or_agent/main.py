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

    print("=" * 60)
    print("  NL2OR Agent  (输入 'quit' 或 'exit' 退出)")
    print("=" * 60)
    print()

    agent = build_nl2or_agent(verbosity_level=1)
    state = None

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
            print(f"\nNL2OR > {result}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[错误] {exc}\n")


def _run_web() -> None:
    """Launch the Gradio GUI provided by HAMLET."""
    from agents import build_nl2or_agent
    from hamlet.serve import GradioUI

    workspace_dir = os.getenv("NL2OR_WORKSPACE_DIR", "./data/workspace")
    readme_path = os.getenv(
        "NL2OR_AGENT_README",
        str(Path(__file__).parent / "README.md"),
    )

    agent = build_nl2or_agent(workspace_dir=workspace_dir, verbosity_level=2)
    GradioUI(agent, file_upload_folder=workspace_dir, readme_md_path=readme_path).launch(
        share=False
    )


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
