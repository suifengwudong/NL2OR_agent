"""Tests for the ProblemIR value object: 解析、归一化、参数视图与覆盖。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.problem_ir import READABLE_DATA_KEYS, ProblemIR, fingerprint

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
# 指纹：只认决定模型的内容
# ---------------------------------------------------------------------------


class TestFingerprint:
    def _ir(self) -> dict:
        return {
            "problem_families": [{"id": "facility_location"}],
            "entities": {
                "I": {"size": 2, "ids": ["a", "b"]},
                "J": {"size": 2, "ids": ["x", "y"]},
            },
            "parameters": {"fixed_cost": [10, 20], "service_cost": [[1, 2], [3, 4]]},
            "objective": {
                "block_id": "fixed_plus_service_cost_objective",
                "sense": "minimize",
                "natural_language": "最小化总成本",
            },
            "constraint_blocks": [
                {"block_id": "assign_each_demand_once", "natural_language": "每个区域分配一次"},
                {"block_id": "link_assignment_to_open", "natural_language": "只有开设才能分配"},
            ],
        }

    def test_prose_and_bookkeeping_do_not_change_the_fingerprint(self):
        first = self._ir()
        second = self._ir()
        second["objective"]["natural_language"] = "换一种说法"
        second["constraint_blocks"][0]["natural_language"] = "另一种说法"
        second["constraint_blocks"][0]["status"] = "user_specified"
        second["missing_data"] = ["未给出配送费"]

        assert fingerprint(first) == fingerprint(second)

    def test_block_order_does_not_change_the_fingerprint(self):
        first = self._ir()
        second = self._ir()
        second["constraint_blocks"].reverse()

        assert fingerprint(first) == fingerprint(second)

    def test_numeric_changes_change_the_fingerprint(self):
        first = self._ir()
        second = self._ir()
        second["parameters"]["fixed_cost"][0] = 11

        assert fingerprint(first) != fingerprint(second)

    def test_entity_id_changes_change_the_fingerprint(self):
        first = self._ir()
        second = self._ir()
        second["entities"]["J"]["ids"] = ["x", "z"]

        assert fingerprint(first) != fingerprint(second)

    def test_dict_keyed_and_list_parameters_match_after_normalization(self):
        """第一阶段按键写 fixed_cost、第二阶段按位置写，同一个模型必须同指纹。"""
        from core.ir_normalize import normalize_problem_ir

        keyed = self._ir()
        keyed["parameters"]["fixed_cost"] = {"x": 10, "y": 20}
        positional = self._ir()

        normalized_keyed, _, _ = normalize_problem_ir(keyed)
        normalized_positional, _, _ = normalize_problem_ir(positional)

        assert fingerprint(normalized_keyed) == fingerprint(normalized_positional)


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

    def test_parse_overrides_narrows_to_the_allowed_keys(self):
        assert ProblemIR.parse_overrides({"p": 2}, allowed=frozenset({"p"})) == {"p": 2}
        with pytest.raises(ValueError, match="该模型可覆盖的键为 p"):
            ProblemIR.parse_overrides({"capacity": 1}, allowed=frozenset({"p"}))

    def test_parse_overrides_reports_a_model_without_readable_keys(self):
        with pytest.raises(ValueError, match="没有可覆盖的参数"):
            ProblemIR.parse_overrides({"p": 2}, allowed=frozenset())

    def test_readable_keys_match_what_the_block_model_reads(self):
        """防止可覆盖键与 block_model 实际读取的键漂移（双向）。"""
        source = (_BASE / "core" / "block_model.py").read_text(encoding="utf-8")
        used = set(re.findall(r'(?:data\.get|list_value|matrix|indices)\("([a-z_]+)"', source))

        assert used == set(READABLE_DATA_KEYS)

    def test_block_key_map_covers_every_readable_key(self):
        """每个全局可覆盖键都要能由某个约束块或目标块读取。"""
        from core.block_model import READ_BLOCK_KEYS

        assert set().union(*READ_BLOCK_KEYS.values()) == set(READABLE_DATA_KEYS)
