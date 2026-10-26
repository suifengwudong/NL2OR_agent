"""Tests for main.py CLI and web entry points."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _run_cli tests
# ---------------------------------------------------------------------------


class TestRunCli:
    @pytest.mark.parametrize("exit_word", ["quit", "exit", "q", "退出"])
    def test_exit_words_break_loop(self, exit_word: str):
        from main import _run_cli

        mock_agent = MagicMock()
        with (
            patch("agents.build_nl2or_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=[exit_word]),
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

    def test_cli_displays_saved_artifact_status(self, tmp_path, monkeypatch):
        import utils.session as session_mod

        monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        session = session_mod.get_session()
        session.save_model({"valid": True})
        session.save_code("print('Objective: 1')", "solve.py")

        from main import _run_cli

        mock_agent = MagicMock()
        mock_agent.run.return_value = "模型求解完成"
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

        assert any(
            "[产物]" in message and "模型：已生成" in message for message in printed_messages
        )
        assert any(
            "[代码文件]" in message and "solve.py" in message for message in printed_messages
        )

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
        assert any("not-json" in m for m in printed_messages)
        assert not any("FINAL_ANSWER_FORMAT_ERROR" in m for m in printed_messages)

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

    def test_cli_builds_agent_with_given_mode(self):
        from main import _run_cli

        with (
            patch("agents.build_nl2or_agent") as mock_build,
            patch("builtins.input", side_effect=["quit"]),
            patch("builtins.print"),
        ):
            _run_cli(agent_mode="automatic")

        assert mock_build.call_args.kwargs["mode"] == "automatic"


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
        assert mock_launch.call_args.kwargs["default_mode"] == "interactive"

    def test_run_web_forwards_agent_mode(self):
        from main import _run_web

        with (
            patch("agents.build_nl2or_agent", return_value=MagicMock()),
            patch("web.launch_web") as mock_launch,
            patch("utils.session.prune_old_sessions", return_value=0),
        ):
            _run_web(agent_mode="automatic")
        assert mock_launch.call_args.kwargs["default_mode"] == "automatic"


# ---------------------------------------------------------------------------
# web/app.py helpers tests
# ---------------------------------------------------------------------------


class TestDisplayAnswer:
    def test_passes_through_plain_answer(self):
        from core.output_format import format_agent_output as _display_answer

        result = _display_answer("请确认：\n已解析为 p-中位问题，p=2")
        assert "请确认" in result
        assert "p-中位问题" in result

    def test_fallback_on_invalid_format(self):
        from core.output_format import format_agent_output as _display_answer

        raw = "Thought: let me think\nCode: print('hi')\n```\nsome code```\nraw output"
        result = _display_answer(raw)
        assert result  # should not crash
        assert "raw output" in result

    def test_empty_fallback(self):
        from core.output_format import format_agent_output as _display_answer

        result = _display_answer("")
        assert isinstance(result, str)


class TestGetWorkspaceFiles:
    def test_no_sessions_returns_message(self, tmp_path, monkeypatch):
        import utils.session as mod
        from web.views import get_workspace_files

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "nosessions")
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
        from web.views import get_workspace_files

        result = get_workspace_files("test123")
        assert "test123" in result or "solve" in result


# ---------------------------------------------------------------------------
# web/app.py mode selector tests
# ---------------------------------------------------------------------------


class TestRunAgentTurn:
    def test_applies_selected_mode(self, tmp_path, monkeypatch):
        import utils.session as session_mod
        from web.app import run_agent_turn

        monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        mock_agent = MagicMock()
        mock_agent.run.return_value = "最优目标值 220"
        factory = MagicMock(return_value=mock_agent)

        with patch("web.app.apply_agent_mode") as mock_apply:
            history, cleared, sid = run_agent_turn(factory, "背包问题", [], "0", "automatic")

        mock_apply.assert_called_once_with(mock_agent, "automatic")
        assert cleared == ""
        assert sid
        assert history[0] == {"role": "user", "content": "背包问题"}
        assert "220" in history[1]["content"]

    def test_empty_message_returns_history_unchanged(self):
        from web.app import run_agent_turn

        history: list = []
        factory = MagicMock()
        result = run_agent_turn(factory, "   ", history, "0", "interactive")

        assert result == ([], "", "0")
        factory.assert_not_called()


class TestCreateUi:
    def test_mode_selector_default_and_choices(self):
        import gradio as gr

        from web.app import create_ui

        ui = create_ui(lambda: None, default_mode="automatic")
        radios = [b for b in ui.blocks.values() if isinstance(b, gr.Radio)]

        assert len(radios) == 1
        assert radios[0].value == "automatic"
        assert [c[1] for c in radios[0].choices] == ["interactive", "automatic"]

    def test_ui_exposes_model_and_code_views(self):
        import gradio as gr

        from web.app import create_ui

        ui = create_ui(lambda: None)
        blocks = list(ui.blocks.values())
        tab_labels = [b.label for b in blocks if isinstance(b, gr.Tab)]

        assert tab_labels == ["对话", "模型", "代码"]
        assert any(isinstance(b, gr.Code) and b.language == "python" for b in blocks)
        assert any(isinstance(b, gr.Code) and b.language == "json" for b in blocks)


# ---------------------------------------------------------------------------
# Model view (IR vs template requirement)
# ---------------------------------------------------------------------------


def _model_payload() -> dict:
    from core.ir_validate import validate_problem_ir

    ir = {
        "problem_families": [{"id": "p_median"}],
        "entities": {"I": {"size": 6}, "J": {"size": 5}},
        "parameters": {
            "p": 3,
            "demand": [80, 120, 100, 90, 110, 70],
            "distance": [
                [4, 6, 9, 7, 8],
                [5, 3, 8, 6, 7],
                [9, 7, 4, 5, 6],
                [8, 6, 5, 3, 4],
                [6, 5, 7, 4, 3],
                [7, 8, 6, 5, 4],
            ],
        },
        "constraint_blocks": [
            {"block_id": "assignment", "parameters": {}},
            {"block_id": "cardinality", "parameters": {"p": 3}},
        ],
        "objective": {
            "block_id": "weighted_service_distance_objective",
            "parameters": {"distance": "给定"},
        },
    }
    report = validate_problem_ir(ir)
    return {"report": report}


class TestModelView:
    def test_empty_state_prompts_the_user(self):
        from web.views import render_model_view

        assert "尚未解析" in render_model_view(None)

    def test_shows_missing_template_block(self):
        from web.views import render_model_view

        view = render_model_view(_model_payload())

        assert "校验未通过" in view
        assert "| `link_assignment_to_open` | 缺失 |" in view
        assert "`assign_each_demand_once` | 命中" in view
        assert "weighted_service_distance_objective" in view

    def test_shows_validation_messages(self):
        from web.views import render_model_view

        view = render_model_view(_model_payload())

        assert "错误：" in view

    def test_json_view_is_the_normalized_ir(self):
        import json

        from web.views import render_model_json

        payload = _model_payload()
        rendered = json.loads(render_model_json(payload))

        assert rendered == payload["report"]["normalized_ir"]
        assert render_model_json(None) == ""


def test_agent_cache_evicts_the_least_recently_used(monkeypatch):
    from collections import OrderedDict

    import web.app as app

    monkeypatch.setattr(app, "_MAX_AGENTS", 2)
    monkeypatch.setattr(app, "_agents", OrderedDict())

    def factory():
        return object()

    first = app._get_or_create_agent("a", factory)
    second = app._get_or_create_agent("b", factory)
    assert app._get_or_create_agent("a", factory) is first
    third = app._get_or_create_agent("c", factory)

    assert list(app._agents) == ["a", "c"]
    assert first is app._agents["a"]
    assert third is app._agents["c"]
    assert second not in app._agents.values()


class TestModelStateFromSession:
    def test_reads_the_session_model_of_record(self, tmp_path, monkeypatch):
        import utils.session as session_mod
        from web.views import get_model_state

        monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        payload = _model_payload()
        session_mod.Session(session_id="web01").save_model(payload["report"])

        view, raw = get_model_state("web01")

        assert "校验未通过" in view
        assert "assign_each_demand_once" in raw

    def test_unknown_session_is_empty(self, tmp_path, monkeypatch):
        import utils.session as session_mod
        from web.views import get_model_state

        monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        view, raw = get_model_state("0")

        assert "尚未解析" in view
        assert raw == ""


class TestAgentSessionBinding:
    def test_agent_turn_persists_artifacts_in_browser_session(self, tmp_path, monkeypatch):
        import utils.session as session_mod
        from web.app import run_agent_turn

        monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        session_mod.Session(session_id="browser01")

        agent = MagicMock()

        def run_agent(*_args, **_kwargs):
            current = session_mod.get_session()
            current.save_model({"valid": True})
            current.save_code("print('Objective: 1')", "solve.py")
            return "模型求解完成"

        agent.run.side_effect = run_agent

        def factory():
            return agent

        history, _, sid = run_agent_turn(factory, "question", [], "browser01", "interactive")

        assert sid == "browser01"
        assert history[-1]["content"] == "模型求解完成"
        session = session_mod.Session.load("browser01")
        assert session is not None
        assert session.load_model() is not None
        assert [path.name for path in session.list_code_files()] == ["solve.py"]


# ---------------------------------------------------------------------------
# Code view (edit and re-run the artifact in place)
# ---------------------------------------------------------------------------


class TestCodeView:
    def _prepare(self, tmp_path, monkeypatch) -> str:
        import utils.session as session_mod

        monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        session_mod.Session(session_id="code01").save_code("print('Objective: 1')", "a.py")
        return "code01"

    def test_list_choices_puts_newest_first(self, tmp_path, monkeypatch):
        from web.views import list_code_choices

        sid = self._prepare(tmp_path, monkeypatch)
        import utils.session as session_mod

        session_mod.Session(session_id=sid).save_code("print('Objective: 2')", "b.py")

        update = list_code_choices(sid)
        assert update["choices"] == ["b.py", "a.py"]

    def test_load_and_save_round_trip(self, tmp_path, monkeypatch):
        from web.views import load_code, save_code

        sid = self._prepare(tmp_path, monkeypatch)

        assert load_code(sid, "a.py") == "print('Objective: 1')"
        assert "已保存" in save_code(sid, "a.py", "print('Objective: 9')")
        assert load_code(sid, "a.py") == "print('Objective: 9')"

    def test_run_code_executes_the_edited_script(self, tmp_path, monkeypatch):
        from web.views import run_code

        sid = self._prepare(tmp_path, monkeypatch)
        output = run_code(sid, "a.py", "print('Objective: 2210')")

        assert "[RESULT] Objective: 2210" in output

    def test_missing_selection_is_reported(self, tmp_path, monkeypatch):
        from web.views import load_code, run_code, save_code

        sid = self._prepare(tmp_path, monkeypatch)

        assert load_code(sid, None) == ""
        assert "未选择文件" in save_code(sid, None, "print(1)")
        assert "未选择文件" in run_code(sid, None, "print(1)")


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

    def test_main_default_agent_mode_is_interactive(self):
        from main import main

        with (
            patch("main._run_cli") as mock_cli,
            patch("sys.argv", ["main.py"]),
        ):
            main()
        assert mock_cli.call_args[0][0] == "interactive"

    def test_main_forwards_automatic_agent_mode(self):
        from main import main

        with (
            patch("main._run_cli") as mock_cli,
            patch("main._run_web") as mock_web,
            patch("sys.argv", ["main.py", "--mode", "web", "--agent-mode", "automatic"]),
        ):
            main()
        mock_web.assert_called_once_with("automatic")
        mock_cli.assert_not_called()
