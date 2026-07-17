"""Tests for main.py CLI and web entry points."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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
        mock_agent.run.return_value = (
            '{"conclusion":"ok","key_evidence":["x"],'
            '"constraints_assumptions":["x"],"actionable_steps":["x"]}'
        )
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["我有一个背包问题", "quit"]),
            patch("builtins.print"),
        ):
            _run_cli()
        mock_agent.run.assert_called_once_with("我有一个背包问题", reset=False)

    def test_cli_intercepts_invalid_final_answer_format(self):
        from main import _run_cli

        mock_agent = MagicMock()
        mock_agent.run.return_value = "not-json"
        printed_messages = []
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["question", "quit"]),
            patch(
                "builtins.print",
                side_effect=lambda *a, **kw: printed_messages.append(a[0] if a else ""),
            ),
        ):
            _run_cli()
        assert any("FINAL_ANSWER_FORMAT_ERROR" in m for m in printed_messages)

    def test_cli_handles_agent_exception(self):
        """Agent raising an exception should print an error and continue."""
        from main import _run_cli

        mock_agent = MagicMock()
        mock_agent.run.side_effect = RuntimeError("agent failed")
        printed_messages = []
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["question", "quit"]),
            patch(
                "builtins.print",
                side_effect=lambda *a, **kw: printed_messages.append(a[0] if a else ""),
            ),
        ):
            _run_cli()
        assert any("错误" in m or "agent failed" in m for m in printed_messages)


# ---------------------------------------------------------------------------
# _run_web tests
# ---------------------------------------------------------------------------


class TestRunWeb:
    def test_run_web_launches_gradio(self):
        """Verify _run_web calls launch_web with an agent factory function."""
        from main import _run_web

        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("web.launch_web") as mock_launch,
            patch("utils.session.prune_old_sessions", return_value=0),
        ):
            _run_web()
        # launch_web is called with a callable (agent factory), not an agent
        mock_launch.assert_called_once()
        factory_arg = mock_launch.call_args[0][0]
        assert callable(factory_arg)
        # Invoke the factory to verify it delegates to build_nl2or_agent
        agent = factory_arg()
        assert agent is mock_agent


# ---------------------------------------------------------------------------
# web/app.py helpers tests
# ---------------------------------------------------------------------------


class TestDisplayAnswer:
    def test_valid_json_payload(self):
        from web.app import _display_answer

        raw = '{"conclusion":"ok","key_evidence":["x"],"constraints_assumptions":["x"],"actionable_steps":["x"]}'
        result = _display_answer(raw)
        assert "结论" in result
        assert "关键依据" in result

    def test_fallback_on_invalid_format(self):
        from web.app import _display_answer

        raw = "Thought: let me think\nCode: print('hi')\n```\nsome code```\nraw output"
        result = _display_answer(raw)
        assert result  # should not crash
        assert "raw output" in result

    def test_empty_fallback(self):
        from web.app import _display_answer

        result = _display_answer("")
        assert isinstance(result, str)


class TestGetWorkspaceFiles:
    def test_no_sessions_returns_message(self, tmp_path, monkeypatch):
        import utils.session as session_mod

        monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "nosessions")
        from web.app import get_workspace_files

        # Need a minimal ui mock to extract the closure; use the actual module
        import web.app as web_mod

        # get_workspace_files is defined inside create_ui, so we test the logic
        # by calling Session.list_all directly
        from utils.session import Session

        assert Session.list_all() == []
        result = get_workspace_files("")
        assert "no sessions" in result or "(no sessions yet)" in result

    def test_with_session_files(self, tmp_path, monkeypatch):
        import utils.session as session_mod

        monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        from utils.session import Session

        s = Session(session_id="test123")
        s.save_code("print(1)", "solve.py")
        from web.app import get_workspace_files

        result = get_workspace_files("test123")
        assert "test123" in result or "solve" in result


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
