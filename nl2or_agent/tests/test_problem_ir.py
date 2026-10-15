"""Tests for the ProblemIR value object: 解析、归一化、参数视图与覆盖。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.problem_ir import READABLE_DATA_KEYS, ProblemIR

_BASE = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# 解析：工具入参 dict / JSON 字符串 / None
# ---------------------------------------------------------------------------


class TestParse:
    def test_accepts_a_dict(self):
        assert ProblemIR.parse({"parameters": {"p": 2}}).data == {"parameters": {"p": 2}}

    def test_accepts_a_json_string(self):
        assert ProblemIR.parse('{"parameters": {"p": 2}}').data == {"parameters": {"p": 2}}

    def test_accepts_an_existing_value(self):
        ir = ProblemIR({"parameters": {"p": 2}})

        assert ProblemIR.parse(ir) is ir

    @pytest.mark.parametrize("value", [None, "", "  ", "null"])
    def test_empty_inputs_become_an_empty_ir(self, value):
        assert ProblemIR.parse(value).data == {}

    def test_reports_invalid_json(self):
        with pytest.raises(ValueError, match="无法解析 ir_json"):
            ProblemIR.parse("{not json")

    def test_rejects_a_non_object_payload(self):
        with pytest.raises(ValueError, match="必须是一个对象"):
            ProblemIR.parse(json.dumps([1, 2]))

    def test_rejects_an_unsupported_type(self):
        with pytest.raises(ValueError, match="必须是一个对象或它的 JSON 字符串"):
            ProblemIR.parse(7)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------


class TestNormalized:
    def test_normalizes_family_aliases(self):
        ir = ProblemIR({"problem_families": [{"id": "p-median"}]})

        assert ir.normalized.data["problem_families"][0]["id"] == "p_median"

    def test_leaves_the_original_untouched(self):
        ir = ProblemIR({"problem_families": [{"id": "p-median"}]})
        ir.normalized

        assert ir.data["problem_families"][0]["id"] == "p-median"


class TestParameters:
    def test_top_level_data_wins_and_placeholder_strings_are_dropped(self):
        ir = ProblemIR(
            {
                "parameters": {"p": 2, "distance": "由距离矩阵给定"},
                "constraint_blocks": [{"block_id": "x", "parameters": {"p": 3, "demand": [1]}}],
                "objective": {"parameters": {"distance": [[1, 2]]}},
            }
        )

        assert ir.parameters == {"p": 2, "demand": [1], "distance": [[1, 2]]}


# ---------------------------------------------------------------------------
# 覆盖
# ---------------------------------------------------------------------------


class TestOverrides:
    def test_replaces_a_top_level_parameter(self):
        base = ProblemIR({"parameters": {"p": 3}})

        applied = base.with_overrides({"p": 4})

        assert applied.data["parameters"]["p"] == 4
        assert base.data["parameters"]["p"] == 3  # 原模型不被改动

    def test_no_overrides_returns_an_independent_copy(self):
        base = ProblemIR({"parameters": {"p": 3}})

        copied = base.with_overrides()
        copied.data["parameters"]["p"] = 9

        assert base.data["parameters"]["p"] == 3

    def test_parse_overrides_accepts_a_dict_and_a_json_string(self):
        assert ProblemIR.parse_overrides({"p": 4}) == {"p": 4}
        assert ProblemIR.parse_overrides('{"p": 4}') == {"p": 4}
        assert ProblemIR.parse_overrides(None) == {}

    def test_parse_overrides_rejects_unknown_keys(self):
        with pytest.raises(ValueError, match="可覆盖的键"):
            ProblemIR.parse_overrides({"not_a_key": 1})

    def test_parse_overrides_rejects_a_non_object(self):
        with pytest.raises(ValueError, match="必须是一个对象"):
            ProblemIR.parse_overrides(["p"])  # type: ignore[arg-type]

    def test_every_readable_key_is_accepted(self):
        overrides = dict.fromkeys(READABLE_DATA_KEYS, 1)

        assert ProblemIR.parse_overrides(overrides) == overrides

    def test_readable_keys_match_what_the_block_model_reads(self):
        """防止可覆盖键与 block_model 实际读取的键漂移（双向）。"""
        source = (_BASE / "core" / "block_model.py").read_text(encoding="utf-8")
        used = set(re.findall(r'(?:data\.get|list_value|matrix|indices)\("([a-z_]+)"', source))

        assert used == set(READABLE_DATA_KEYS)
