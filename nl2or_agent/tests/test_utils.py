"""Tests for utils/search.py, utils/session.py, web/app.py."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from utils.search import (
    filter_by_predicate,
    parse_keywords,
    score_keywords,
    search_by_keywords,
)
from utils.session import Session, get_session, reset_session


# ---------------------------------------------------------------------------
# parse_keywords
# ---------------------------------------------------------------------------

class TestParseKeywords:
    def test_none(self):
        assert parse_keywords(None) == []

    def test_empty_string(self):
        assert parse_keywords("") == []

    def test_whitespace_string(self):
        assert parse_keywords("  , , ") == []

    def test_single(self):
        assert parse_keywords("hello") == ["hello"]

    def test_comma_separated(self):
        assert parse_keywords("a, b, c") == ["a", "b", "c"]

    def test_list_input(self):
        assert parse_keywords(["A", "B"]) == ["a", "b"]

    def test_tuple_input(self):
        assert parse_keywords(("X", "Y")) == ["x", "y"]


# ---------------------------------------------------------------------------
# score_keywords
# ---------------------------------------------------------------------------

class TestScoreKeywords:
    def test_no_match(self):
        assert score_keywords(["abc"], ["xyz"]) == 0

    def test_exact_match(self):
        assert score_keywords(["knapsack"], ["knapsack", "other"]) == 1

    def test_substring_match(self):
        assert score_keywords(["knap"], ["knapsack"]) == 1

    def test_partial_reverse(self):
        assert score_keywords(["knapsack"], ["knap"]) == 1

    def test_multiple_keywords(self):
        assert score_keywords(["a", "b"], ["a", "b", "c"]) == 2

    def test_case_insensitive(self):
        assert score_keywords(["abc"], ["ABC"]) == 1

    def test_case_insensitive_reverse(self):
        # haystack is already lower-cased internally, keywords are lower-cased by parse_keywords
        assert score_keywords(parse_keywords("ABC"), ["abc"]) == 1


# ---------------------------------------------------------------------------
# search_by_keywords
# ---------------------------------------------------------------------------

class TestSearchByKeywords:
    def test_empty_keywords(self):
        items = [{"id": "x"}]
        assert search_by_keywords(items, []) == []

    def test_single_match(self):
        # "knap" is substring of "knapsack" → 1 match
        items = [{"id": "knapsack", "name": "Knap"}, {"id": "other", "name": "other"}]
        result = search_by_keywords(items, ["knap"])
        assert len(result) == 1  # only "knapsack" id/name contain "knap"

    def test_limit(self):
        items = [{"id": f"item_{i}", "name": "match"} for i in range(10)]
        result = search_by_keywords(items, ["match"], limit=3)
        assert len(result) == 3

    def test_search_specific_fields(self):
        items = [
            {"id": "match", "name": "no"},
            {"id": "no", "name": "match"},
        ]
        result = search_by_keywords(items, ["match"], search_fields=["id"])
        assert len(result) == 1
        assert result[0]["id"] == "match"

    def test_order_by_score(self):
        items = [
            {"tags": ["a"]},
            {"tags": ["a", "b"]},
        ]
        result = search_by_keywords(items, ["a", "b"])
        # item with two matches should come first
        assert len(result[0]["tags"]) == 2


# ---------------------------------------------------------------------------
# filter_by_predicate
# ---------------------------------------------------------------------------

class TestFilterByPredicate:
    def test_keep_families(self):
        items = [
            {"id": "a", "is_family": True},
            {"id": "b"},
            {"id": "c", "is_family": True},
        ]
        result = filter_by_predicate(items, lambda x: x.get("is_family"))
        assert len(result) == 2

    def test_remove_none(self):
        # filter_by_predicate returns items where predicate returns True.
        # item 2 has val=None, predicate returns True for that one.
        items = [{"id": 1, "val": "ok"}, {"id": 2, "val": None}]
        result = filter_by_predicate(items, lambda x: x.get("val") is None)
        assert len(result) == 1
        assert result[0]["id"] == 2


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class TestSession:
    def test_create(self, tmp_path: Path, monkeypatch):
        import utils.session as mod
        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        s = Session()
        assert s.session_id
        assert s.workspace.exists()
        assert s.code_dir.exists()
        assert s.output_dir.exists()

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

    def test_list_all(self, tmp_path: Path, monkeypatch):
        import utils.session as mod
        monkeypatch.setattr(mod, "_SESSIONS_ROOT", tmp_path / "sessions")
        s1 = Session(session_id="aaa")
        s2 = Session(session_id="bbb")
        ids = Session.list_all()
        assert "aaa" in ids
        assert "bbb" in ids

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
        # set mtime to 100 days ago
        old = s.workspace.stat().st_mtime - 100 * 86400
        for d in s.workspace.rglob("*"):
            if d.is_file():
                d.touch()
        import os as _os
        _os.utime(str(s.workspace), (old, old))
        removed = Session.prune(max_age_days=30)
        assert removed >= 1  # the session we just created


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
