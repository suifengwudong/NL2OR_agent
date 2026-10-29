"""Tests for agent-output rendering."""

from __future__ import annotations

from core.output_format import format_agent_output


class TestFormatAgentOutput:
    def test_natural_language_passthrough(self):
        result = format_agent_output("请确认：\n已解析为 p-中位问题，p=2")
        assert "请确认" in result
        assert "p-中位问题" in result

    def test_strips_code_noise(self):
        raw = "Thought: let me think\nCode: import json\n```\nsnippet```\n最终结论是 1250。"
        result = format_agent_output(raw)
        assert "最终结论是 1250。" in result
        assert "Thought:" not in result
        assert "```" not in result

    def test_preserves_complete_long_reply(self):
        result = format_agent_output("\n".join(f"第 {i} 行" for i in range(40)))
        assert "第 39 行" in result
        assert "第 0 行" in result

    def test_preserves_math_sections_and_spacing(self):
        raw = "**符号说明**\n\n- $h_i$：需求量\n\n**目标函数**\n\n$$\n\\min h_i\n$$"
        assert format_agent_output(raw) == raw

    def test_empty_output_returns_empty_string(self):
        assert format_agent_output("") == ""
