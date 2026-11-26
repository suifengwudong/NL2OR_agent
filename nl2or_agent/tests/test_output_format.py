"""Tests for agent-output rendering."""

from __future__ import annotations

import json

import pytest

from core.answer_manifest import AnswerManifest, latest_answer_manifest
from core.ir_validate import validate_problem_ir
from core.output_format import format_agent_output
from utils.artifact_store import (
    ArtifactLinkError,
    ArtifactNotFound,
    ArtifactStore,
    ModelArtifact,
    SolveArtifact,
)
from utils.session import write_model_of_record


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


# ---------------------------------------------------------------------------
# 占位符：权威文本由运行时填充，模型不负责抄写
# ---------------------------------------------------------------------------


@pytest.fixture()
def session(tmp_path, monkeypatch):
    import utils.session as session_mod

    monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
    return session_mod.Session(session_id="ph01")


def _validated_session(session):
    from core.ir_validate import validate_problem_ir

    ir = {
        "problem_families": [{"id": "p_median"}],
        "entities": {"I": {"size": 2}, "J": {"size": 2}},
        "parameters": {"p": 1, "distance": [[1, 2], [2, 1]]},
        "constraint_blocks": [
            {"block_id": "assign_each_demand_once"},
            {"block_id": "link_assignment_to_open"},
            {"block_id": "cardinality_open_p_facilities"},
        ],
        "objective": {"block_id": "weighted_service_distance_objective"},
    }
    write_model_of_record(session.model_file, validate_problem_ir(ir))
    return ir


def _save_solve_result(session, ir: dict):
    from core.block_model import format_solution, solve_ir
    from core.ir_validate import validate_problem_ir
    from core.problem_ir import ProblemIR, fingerprint
    from core.report import default_report_spec, render_report

    normalized = validate_problem_ir(dict(ir))["normalized_ir"]
    solved = ProblemIR(normalized)
    result = solve_ir(solved.data)
    spec = default_report_spec(solved.data)
    payload = {
        "ir_fingerprint": fingerprint(solved.data),
        "text": f"{format_solution(result)}\n\n{render_report(solved.data, result, spec=spec)}",
    }
    session.solve_result_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestExpandPlaceholders:
    def test_model_math_is_rendered_from_the_model_of_record(self, session):
        from core.output_format import MODEL_MATH_PLACEHOLDER, expand_placeholders

        _validated_session(session)
        expanded = expand_placeholders(MODEL_MATH_PLACEHOLDER, session)

        assert expanded.startswith("## 数学模型")
        assert "\\min" in expanded
        assert MODEL_MATH_PLACEHOLDER not in expanded

    def test_a_duplicate_heading_from_the_agent_is_collapsed(self, session):
        """agent 若在占位符前又写了标题，粘贴文档的标题与之合并，不出现两个。"""
        from core.output_format import MODEL_MATH_PLACEHOLDER, expand_placeholders

        _validated_session(session)
        expanded = expand_placeholders(f"## 数学模型\n\n{MODEL_MATH_PLACEHOLDER}", session)

        assert expanded.count("## 数学模型") == 1

    def test_a_placeholder_with_an_escaped_bracket_is_still_expanded(self, session):
        """模型偶尔把占位符写成 ``[MODEL_MATH\\]``，仍按占位符处理。"""
        from core.output_format import expand_placeholders

        _validated_session(session)
        expanded = expand_placeholders(r"模型如下：[MODEL_MATH\]", session)

        assert expanded.startswith("模型如下：## 数学模型")
        assert r"[MODEL_MATH\]" not in expanded

    def test_model_invented_placeholder_variant_is_normalized(self, session):
        from core.output_format import expand_placeholders

        _validated_session(session)
        expanded = expand_placeholders("[MODEL_MATH_PLACEHOLDER]", session)

        assert expanded.startswith("## 数学模型")
        assert "PLACEHOLDER" not in expanded

    def test_solve_result_expands_the_saved_artifact(self, session):
        from core.output_format import SOLVE_RESULT_PLACEHOLDER, expand_placeholders

        ir = _validated_session(session)
        _save_solve_result(session, ir)

        expanded = expand_placeholders(f"## 求解结果\n\n{SOLVE_RESULT_PLACEHOLDER}", session)

        assert "[RESULT] Objective:" in expanded
        assert "## 结果报表" in expanded

    def test_unresolved_model_math_fails_the_turn(self, session):
        from core.output_format import MODEL_MATH_PLACEHOLDER, expand_placeholders

        with pytest.raises(ValueError, match="validate_problem_ir"):
            expand_placeholders(f"答案 {MODEL_MATH_PLACEHOLDER}", session)

    def test_unresolved_solve_result_fails_the_turn(self, session):
        from core.output_format import SOLVE_RESULT_PLACEHOLDER, expand_placeholders

        _validated_session(session)

        with pytest.raises(ValueError, match="solve_ir"):
            expand_placeholders(f"答案 {SOLVE_RESULT_PLACEHOLDER}", session)

    def test_result_from_another_ir_is_rejected(self, session):
        from core.output_format import SOLVE_RESULT_PLACEHOLDER, expand_placeholders

        ir = _validated_session(session)
        _save_solve_result(session, ir)

        # 模型随后被修正：solve_result.json 的指纹不再对应 model.json
        ir["parameters"]["p"] = 2
        write_model_of_record(
            session.model_file,
            {
                "valid": True,
                "normalized_ir": ir,
                "skeleton": {},
            },
        )

        with pytest.raises(ValueError, match="已变更"):
            expand_placeholders(SOLVE_RESULT_PLACEHOLDER, session)

    def test_answers_without_placeholders_pass_through(self, session):
        from core.output_format import expand_placeholders

        assert expand_placeholders("普通答复", session) == "普通答复"


# ---------------------------------------------------------------------------
# Artifact-backed placeholders and AnswerManifest
# ---------------------------------------------------------------------------


def _pmedian_report(distance: list[list[int]] | None = None) -> dict:
    ir = {
        "problem_families": [{"id": "p_median"}],
        "entities": {"I": {"size": 2}, "J": {"size": 2}},
        "parameters": {"p": 1, "distance": distance or [[1, 2], [2, 1]]},
        "constraint_blocks": [
            {"block_id": "assign_each_demand_once"},
            {"block_id": "link_assignment_to_open"},
            {"block_id": "cardinality_open_p_facilities"},
        ],
        "objective": {"block_id": "weighted_service_distance_objective"},
    }
    report = validate_problem_ir(ir)
    assert report["valid"], report["errors"]
    return report


def _baseline_artifacts(
    session,
) -> tuple[ArtifactStore, dict, ModelArtifact, SolveArtifact]:
    store = ArtifactStore(session)
    report = _pmedian_report()
    model = store.save_model_artifact(report, name="baseline", kind="baseline")
    solve = store.save_solve_artifact(
        report["normalized_ir"],
        status="Optimal",
        objective=2210,
        text="状态：最优\n[RESULT] Objective: 2210",
    )
    return store, report, model, solve


class TestExpandArtifactPlaceholders:
    def test_bare_placeholders_use_the_baseline(self, session):
        from core.output_format import expand_placeholders

        store, _, model, solve = _baseline_artifacts(session)
        manifest = AnswerManifest(session_id=session.session_id)

        text = expand_placeholders("[MODEL_MATH]\n[SOLVE_RESULT]", session, manifest)

        assert "## 数学模型" in text
        assert "Objective: 2210" in text
        assert manifest.model_refs["baseline"] == model.artifact_id
        assert manifest.solve_refs["baseline"] == solve.artifact_id

    def test_named_placeholders_resolve_the_named_artifacts(self, session):
        from core.output_format import expand_placeholders

        store = ArtifactStore(session)
        report1 = _pmedian_report()
        report2 = _pmedian_report([[1, 5], [5, 1]])
        store.save_model_artifact(report1, name="baseline", kind="baseline")
        scenario = store.save_model_artifact(report2, name="cap400")
        store.save_solve_artifact(
            report1["normalized_ir"],
            status="Optimal",
            objective=2210,
            text="baseline result",
        )
        solve2 = store.save_solve_artifact(
            report2["normalized_ir"],
            status="Optimal",
            objective=42,
            text="cap400 result",
        )

        manifest = AnswerManifest(session_id=session.session_id)
        text = expand_placeholders("[MODEL_MATH:cap400]\n[SOLVE_RESULT:cap400]", session, manifest)

        assert "cap400 result" in text
        assert manifest.model_refs["cap400"] == scenario.artifact_id
        assert manifest.solve_refs["cap400"] == solve2.artifact_id

    def test_named_solve_must_match_the_named_model(self, session):
        from core.output_format import expand_placeholders

        store = ArtifactStore(session)
        report1 = _pmedian_report()
        report2 = _pmedian_report([[1, 5], [5, 1]])
        store.save_model_artifact(report1, name="baseline", kind="baseline")
        store.save_model_artifact(report2, name="cap400")
        store.save_solve_artifact(
            report1["normalized_ir"],
            status="Optimal",
            objective=2210,
            text="baseline result",
            name="cap400",
        )

        with pytest.raises(ArtifactLinkError):
            expand_placeholders("[MODEL_MATH:cap400]\n[SOLVE_RESULT:cap400]", session)
        assert latest_answer_manifest(store) is None

    def test_missing_artifact_fails_loudly(self, session):
        from core.output_format import expand_placeholders

        store, _, _, _ = _baseline_artifacts(session)

        with pytest.raises(ArtifactNotFound, match="missing"):
            expand_placeholders("[MODEL_MATH:missing]", session)
        assert latest_answer_manifest(store) is None
