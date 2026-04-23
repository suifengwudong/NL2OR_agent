"""Tests for main.py CLI and web entry points."""

from __future__ import annotations

import argparse
import sys
from io import StringIO
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: import main module functions
# ---------------------------------------------------------------------------

def _import_main():
    """Import main module with project root on sys.path."""
    import importlib
    import main as m
    return m


# ---------------------------------------------------------------------------
# _run_cli tests
# ---------------------------------------------------------------------------

class TestRunCli:
    def test_cli_quit_exits_cleanly(self):
        """Typing 'quit' should exit the loop without error."""
        from main import _run_cli
        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["quit"]),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_not_called()

    def test_cli_exit_command_exits(self):
        from main import _run_cli
        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["exit"]),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_not_called()

    def test_cli_q_command_exits(self):
        from main import _run_cli
        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["q"]),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_not_called()

    def test_cli_chinese_quit_exits(self):
        from main import _run_cli
        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["退出"]),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_not_called()

    def test_cli_eof_exits_cleanly(self):
        """EOFError (e.g., piped input ends) should exit gracefully."""
        from main import _run_cli
        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=EOFError),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_not_called()

    def test_cli_keyboard_interrupt_exits(self):
        from main import _run_cli
        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=KeyboardInterrupt),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_not_called()

    def test_cli_empty_input_skipped(self):
        """Empty input should be ignored; only quit should stop the loop."""
        from main import _run_cli
        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["", "  ", "quit"]),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_not_called()

    def test_cli_runs_agent_on_input(self):
        from main import _run_cli
        mock_agent = MagicMock()
        mock_agent.run.return_value = "answer"
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["我有一个背包问题", "quit"]),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_called_once_with("我有一个背包问题", reset=False)

    def test_cli_handles_agent_exception(self):
        """Agent raising an exception should print an error and continue."""
        from main import _run_cli
        mock_agent = MagicMock()
        mock_agent.run.side_effect = RuntimeError("agent failed")
        printed_messages = []
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["question", "quit"]),
            patch("builtins.print", side_effect=lambda *a, **kw: printed_messages.append(a[0] if a else "")),
        ):
            _run_cli()
        assert any("错误" in m or "agent failed" in m for m in printed_messages)


# ---------------------------------------------------------------------------
# _run_web tests
# ---------------------------------------------------------------------------

class TestRunWeb:
    def test_run_web_launches_gradio(self):
        from main import _run_web
        mock_agent = MagicMock()
        mock_ui = MagicMock()
        mock_ui_class = MagicMock(return_value=mock_ui)
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("hamlet.serve.GradioUI", mock_ui_class),
        ):
            _run_web()
        mock_ui.launch.assert_called_once_with(share=False)

    def test_run_web_uses_env_workspace(self, monkeypatch):
        from main import _run_web
        monkeypatch.setenv("NL2OR_WORKSPACE_DIR", "/tmp/test_ws")
        mock_agent = MagicMock()
        mock_ui = MagicMock()
        mock_ui_class = MagicMock(return_value=mock_ui)
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent) as mock_build,
            patch("hamlet.serve.GradioUI", mock_ui_class),
        ):
            _run_web()
        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args
        assert call_kwargs.kwargs.get("workspace_dir") == "/tmp/test_ws"


# ---------------------------------------------------------------------------
# main() argument parsing tests
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_default_mode_is_cli(self):
        from main import main
        with (
            patch("main._run_cli") as mock_cli,
            patch("main._run_web") as mock_web,
            patch("sys.argv", ["main.py"]),
        ):
            main()
        mock_cli.assert_called_once()
        mock_web.assert_not_called()

    def test_main_cli_mode(self):
        from main import main
        with (
            patch("main._run_cli") as mock_cli,
            patch("main._run_web") as mock_web,
            patch("sys.argv", ["main.py", "--mode", "cli"]),
        ):
            main()
        mock_cli.assert_called_once()
        mock_web.assert_not_called()

    def test_main_web_mode(self):
        from main import main
        with (
            patch("main._run_cli") as mock_cli,
            patch("main._run_web") as mock_web,
            patch("sys.argv", ["main.py", "--mode", "web"]),
        ):
            main()
        mock_web.assert_called_once()
        mock_cli.assert_not_called()
