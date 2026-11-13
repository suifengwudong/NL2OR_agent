"""Model-library retrieval: 有界候选索引与模板细节，公式一律不出现。"""

from __future__ import annotations

import pytest

from core.model_library import describe_model, search_entries


class TestSearchEntries:
    def test_without_keywords_lists_every_model(self):
        text = search_entries()

        assert "`p_median`" in text
        assert "`facility_location`" in text
        assert "`knapsack`" in text

    def test_chinese_keywords_narrow_the_result(self):
        text = search_entries("选址 容量")

        assert "`capacitated_facility_location`" in text
        assert "| `p_median` |" not in text

    def test_block_keywords_surface_composable_blocks(self):
        text = search_entries("强制 开设")

        assert "`force_facility_open`" in text
        assert "`p_median`" not in text

    def test_no_match_tells_the_agent_to_retry(self):
        text = search_entries("随机词组")

        assert "无匹配" in text

    def test_never_carries_latex(self):
        text = search_entries("") + describe_model("p_median") + describe_model("location_problem")

        assert "$$" not in text
        assert "\\sum" not in text


class TestDescribeModel:
    def test_lists_required_blocks_with_parameters(self):
        text = describe_model("facility_location")

        assert "`assign_each_demand_once`" in text
        assert "`link_assignment_to_open`" in text
        assert "`fixed_plus_service_cost_objective`" in text
        assert "minimize" in text
        assert "`fixed_cost`" in text
        assert "`service_cost`" in text

    def test_does_not_advertise_other_variants(self):
        """模板细节只含必需块：容量、基数、预算块不出现在无容量选址的视图里。"""
        text = describe_model("facility_location")

        assert "facility_capacity" not in text
        assert "cardinality_open_p_facilities" not in text
        assert "opening_budget" not in text

    def test_family_template_uses_its_base_blocks(self):
        text = describe_model("location_problem")

        assert "`assign_each_demand_once`" in text
        assert "`link_assignment_to_open`" in text

    def test_variables_are_declared(self):
        text = describe_model("p_median")

        assert "$y_j$" in text
        assert "$x_ij$" in text

    def test_unknown_model_lists_available_ids(self):
        text = describe_model("vehicle_routing")

        assert "没有 'vehicle_routing'" in text
        assert "`p_median`" in text


@pytest.mark.parametrize(
    "model_id",
    ["p_median", "facility_location", "knapsack", "capacitated_p_center", "p_dispersion"],
)
def test_every_supported_template_describes_a_complete_skeleton(model_id: str):
    text = describe_model(model_id)

    assert "必需约束块" in text or "目标块" in text
    assert "未知" not in text
