"""Tests for structured final-answer format helpers."""

from __future__ import annotations

import json

import pytest

from output_format import (
    extract_json_payload,
    format_for_display,
    validate_payload_dict,
)


def _build_payload(
    *,
    conclusion: str = "最优方案可行且收益最大。",
    key_evidence: list[str] | None = None,
    constraints_assumptions: list[str] | None = None,
    actionable_steps: list[str] | None = None,
) -> dict[str, object]:
    return {
        "conclusion": conclusion,
        "key_evidence": key_evidence or ["目标函数值达到当前可行域上界。"],
        "constraints_assumptions": constraints_assumptions or ["默认参数均为确定性输入。"],
        "actionable_steps": actionable_steps or ["确认参数后直接执行求解脚本。"],
    }


class TestValidatePayloadDict:
    @pytest.mark.parametrize(
        "payload",
        [
            _build_payload(
                conclusion="线性规划可得唯一最优解。",
                key_evidence=["单纯形求解收敛，目标值为 1250。"],
                constraints_assumptions=["变量非负且资源上限固定。"],
                actionable_steps=["按最优解执行生产排程。"],
            ),
            _build_payload(
                conclusion="整数规划最优选址为 A 与 C。",
                key_evidence=["分支定界搜索完成且最优性间隙为 0。"],
                constraints_assumptions=["需求预测按当前月度基线。"],
                actionable_steps=["在 A、C 启动部署并监控负载。"],
            ),
            _build_payload(
                conclusion="运输模型建议主仓转运至东区。",
                key_evidence=["总成本从 980 降至 910。"],
                constraints_assumptions=["运力约束保持不变。"],
                actionable_steps=["更新运输计划并复核次日需求。"],
            ),
        ],
    )
    def test_accepts_representative_problem_types(self, payload: dict[str, object]):
        parsed = validate_payload_dict(payload)
        assert parsed.conclusion

    def test_rejects_missing_fields(self):
        payload = _build_payload()
        payload.pop("constraints_assumptions")
        with pytest.raises(ValueError, match="Invalid field order or fields"):
            validate_payload_dict(payload)

    def test_rejects_wrong_field_order(self):
        payload = {
            "conclusion": "ok",
            "constraints_assumptions": ["x"],
            "key_evidence": ["x"],
            "actionable_steps": ["x"],
        }
        with pytest.raises(ValueError, match="Expected keys in order"):
            validate_payload_dict(payload)

    def test_rejects_empty_item(self):
        payload = _build_payload(key_evidence=["   "])
        with pytest.raises(ValueError, match="Schema validation failed"):
            validate_payload_dict(payload)


class TestExtractAndDisplay:
    def test_extracts_json_from_fenced_block(self):
        payload = _build_payload()
        raw = f"说明\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
        extracted = extract_json_payload(raw)
        assert extracted["conclusion"] == payload["conclusion"]

    def test_rejects_non_json_text(self):
        with pytest.raises(ValueError, match="Missing JSON payload"):
            extract_json_payload("plain text only")

    def test_formats_human_and_json(self):
        payload = _build_payload()
        result = format_for_display(json.dumps(payload, ensure_ascii=False))
        assert "结论" in result
        assert "关键依据" in result
        assert "约束/假设" in result
        assert "可执行步骤" in result
        assert "```json" in result
