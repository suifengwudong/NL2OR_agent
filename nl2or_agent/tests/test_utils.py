"""Tests for utils/session.py and web/app.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from utils.session import Session, get_session, reset_session, write_model_of_record


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class TestSession:
    def test_create(self, tmp_path: Path, monkeypatch):
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        s = Session()
        assert len(s.session_id) == 12
        assert s.workspace.exists()
        assert s.code_dir.exists()

    def test_custom_id(self, tmp_path: Path, monkeypatch):
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        s = Session(session_id="test123")
        assert s.session_id == "test123"

    def test_save_code(self, tmp_path: Path, monkeypatch):
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        s = Session()
        p = s.save_code("print(1)", filename="test.py")
        assert p.exists()
        assert p.read_text() == "print(1)"

    def test_list_code_files(self, tmp_path: Path, monkeypatch):
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        s = Session()
        s.save_code("a", "a.py")
        s.save_code("b", "b.py")
        assert len(s.list_code_files()) == 2

    @pytest.mark.parametrize("session_id", ["aaa", "bbb"])
    def test_list_all(self, tmp_path: Path, monkeypatch, session_id: str):
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        Session(session_id="aaa")
        Session(session_id="bbb")
        ids = Session.list_all()
        assert session_id in ids

    def test_load_existing(self, tmp_path: Path, monkeypatch):
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        Session(session_id="loadme")
        s2 = Session.load("loadme")
        assert s2 is not None
        assert s2.session_id == "loadme"

    def test_load_missing(self, tmp_path: Path, monkeypatch):
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        assert Session.load("nope") is None

    def test_prune(self, tmp_path: Path, monkeypatch):
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        s = Session()
        s.save_code("")
        old = s.workspace.stat().st_mtime - 100 * 86400
        os.utime(s.workspace, (old, old))
        removed = Session.prune(max_age_days=30)
        assert removed >= 1


# ---------------------------------------------------------------------------
# get_session singleton
# ---------------------------------------------------------------------------


class TestGetSession:
    def test_same_session_returned(self, tmp_path: Path, monkeypatch):
        reset_session()
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "ss")
        s1 = get_session()
        s2 = get_session()
        assert s1.session_id == s2.session_id

    def test_new_session_after_reset(self, tmp_path: Path, monkeypatch):
        reset_session()
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "ss")
        s1 = get_session()
        reset_session()
        s2 = get_session()
        assert s1.session_id != s2.session_id


# ---------------------------------------------------------------------------
# Model of record
# ---------------------------------------------------------------------------


class TestModelOfRecord:
    def _session(self, tmp_path: Path, monkeypatch) -> Session:
        import utils.session as mod

        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        return Session(session_id="model01")

    def test_load_model_is_none_when_absent(self, tmp_path: Path, monkeypatch):
        session = self._session(tmp_path, monkeypatch)
        assert session.load_model() is None

    def test_save_and_load_model_round_trip(self, tmp_path: Path, monkeypatch):
        session = self._session(tmp_path, monkeypatch)
        report = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "normalized_ir": {"constraint_blocks": [{"block_id": "assign_each_demand_once"}]},
        }

        path = write_model_of_record(session.model_file, report)
        loaded = session.load_model()

        assert path.name == "model.json"
        assert loaded is not None
        assert loaded["report"] == report
        assert loaded["saved_at"]

    def test_model_of_record_overwrites_previous(self, tmp_path: Path, monkeypatch):
        session = self._session(tmp_path, monkeypatch)
        write_model_of_record(session.model_file, {"valid": True, "normalized_ir": {"a": 1}})

        write_model_of_record(session.model_file, {"valid": False, "normalized_ir": {"b": 2}})

        loaded = session.load_model()
        assert loaded is not None and loaded["report"]["normalized_ir"] == {"b": 2}
