"""Tests for the minimal flat artifact store and AnswerManifest."""

from __future__ import annotations

import json

import pytest

from core.answer_manifest import AnswerManifest
from core.ir_validate import validate_problem_ir
from core.problem_ir import fingerprint
from utils.artifact_store import (
    ArtifactError,
    ArtifactLinkError,
    ArtifactNameConflict,
    ArtifactStore,
)

_DISTANCE = [[1, 2], [2, 1]]
_OTHER_DISTANCE = [[1, 5], [5, 1]]


def _pmedian_ir(distance: list[list[int]] | None = None, p: int = 1) -> dict:
    return {
        "problem_families": [{"id": "p_median"}],
        "entities": {"I": {"size": 2}, "J": {"size": 2}},
        "parameters": {"p": p, "distance": distance or _DISTANCE},
        "constraint_blocks": [
            {"block_id": "assign_each_demand_once"},
            {"block_id": "link_assignment_to_open"},
            {"block_id": "cardinality_open_p_facilities"},
        ],
        "objective": {"block_id": "weighted_service_distance_objective"},
    }


def _report(distance: list[list[int]] | None = None, p: int = 1) -> dict:
    report = validate_problem_ir(_pmedian_ir(distance, p))
    assert report["valid"], report["errors"]
    return report


def _invalid_report() -> dict:
    ir = _pmedian_ir()
    ir["constraint_blocks"] = [{"block_id": "assign_each_demand_once"}]
    report = validate_problem_ir(ir)
    assert not report["valid"]
    return report


def _cflp_report() -> dict:
    ir = {
        "problem_families": [{"id": "capacitated_facility_location"}],
        "entities": {
            "I": {"size": 4, "ids": ["C1", "C2", "C3", "C4"]},
            "J": {"size": 3, "ids": ["W1", "W2", "W3"]},
        },
        "parameters": {
            "fixed_cost": [100, 120, 90],
            "unit_service_cost": [
                [1, 4, 6],
                [4, 1, 2],
                [6, 3, 1],
                [3, 5, 2],
            ],
            "facility_capacity": [8, 8, 8],
            "demand": [4, 3, 3, 2],
        },
        "constraint_blocks": [
            {"block_id": "assign_each_demand_once"},
            {"block_id": "link_assignment_to_open"},
            {"block_id": "facility_capacity"},
        ],
        "objective": {"block_id": "fixed_plus_unit_service_cost_objective", "sense": "minimize"},
    }
    report = validate_problem_ir(ir)
    assert report["valid"], report["errors"]
    return report


@pytest.fixture()
def session(tmp_path, monkeypatch):
    import utils.session as session_mod

    monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
    return session_mod.Session(session_id="art01")


@pytest.fixture()
def store(session):
    return ArtifactStore(session)


class TestModelArtifacts:
    def test_save_writes_flat_model_file_and_baseline_state(self, store):
        artifact = store.save_model_artifact(_report(), name="baseline", kind="baseline")

        assert artifact.artifact_id.startswith("model_")
        assert (store.root / f"{artifact.artifact_id}.json").is_file()
        assert store.load_state()["baseline_model"] == artifact.artifact_id
        assert store.get_baseline_model().artifact_id == artifact.artifact_id

    def test_no_index_or_pointer_directories_are_created(self, store):
        store.save_model_artifact(_report(), name="baseline", kind="baseline")

        assert not (store.root / "index.json").exists()
        assert not (store.root / "models").exists()
        assert not (store.root / "model_versions").exists()

    def test_full_model_stores_compact_ir_without_validation(self, store):
        from core.model_document import render_model_document

        artifact = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        payload = json.loads((store.root / f"{artifact.artifact_id}.json").read_text())

        assert "validation" not in payload
        stored_ir = payload["report"]["normalized_ir"]
        assert fingerprint(stored_ir) == artifact.fingerprint
        for block in stored_ir["constraint_blocks"]:
            assert "name" not in block
            assert "category" not in block
            assert "natural_language" not in block
            assert "status" not in block
        assert "natural_language" not in stored_ir["objective"]
        assert render_model_document(stored_ir).startswith("## 数学模型")

    def test_same_name_same_fingerprint_is_idempotent(self, store):
        first = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        second = store.save_model_artifact(_report(), name="baseline", kind="baseline")

        assert second.artifact_id == first.artifact_id

    def test_same_content_under_a_new_name_reuses_the_existing_model(self, store):
        first = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        second = store.save_model_artifact(_report(), name="scenario")

        assert second.artifact_id == first.artifact_id

    def test_same_name_different_content_requires_revise(self, store):
        store.save_model_artifact(_report(), name="cap400")

        with pytest.raises(ArtifactNameConflict, match="revise=True"):
            store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400")

        second = store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", revise=True)
        assert second.revision == 2

    def test_kind_cannot_change_under_the_same_name(self, store):
        store.save_model_artifact(_report(), name="cap400", kind="scenario")

        with pytest.raises(ArtifactNameConflict, match="不允许"):
            store.save_model_artifact(
                _report(_OTHER_DISTANCE), name="cap400", kind="baseline", revise=True
            )

    def test_invalid_model_not_baseline(self, store):
        artifact = store.save_model_artifact(_invalid_report(), name="broken")

        assert artifact.validation_status == "invalid"
        with pytest.raises(ArtifactError, match="baseline"):
            store.save_model_artifact(_invalid_report(), name="broken2", baseline=True)

    def test_baseline_changes_clear_the_baseline_solve(self, store):
        store.save_model_artifact(_report(), name="baseline", kind="baseline")
        solve = store.save_solve_artifact(
            _report()["normalized_ir"], status="Optimal", objective=10
        )
        assert store.load_state()["baseline_solve"] == solve.artifact_id

        scenario = store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", baseline=True)
        assert store.get_baseline_model().artifact_id == scenario.artifact_id
        assert store.load_state()["baseline_solve"] is None


class TestParameterPatch:
    def test_patch_stores_base_and_overrides_without_full_ir(self, store):
        base = store.save_model_artifact(_report(), name="baseline", kind="baseline")

        patch = store.save_model_patch(base.artifact_id, {"p": 2}, name="p2")

        payload = json.loads((store.root / f"{patch.artifact_id}.json").read_text())
        assert payload["kind"] == "parameter_patch"
        assert payload["base_model_ref"]["artifact_id"] == base.artifact_id
        assert payload["overrides"] == {"p": 2}
        assert "report" not in payload or payload["report"] is None
        assert store.effective_ir(patch)["parameters"]["p"] == 2

    def test_patch_same_name_same_content_is_idempotent(self, store):
        base = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        first = store.save_model_patch(base.artifact_id, {"p": 2}, name="p2")
        second = store.save_model_patch(base.artifact_id, {"p": 2}, name="p2")

        assert second.artifact_id == first.artifact_id

    def test_same_patch_content_under_a_new_name_reuses_the_existing_patch(self, store):
        base = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        first = store.save_model_patch(base.artifact_id, {"p": 2}, name="p2")
        second = store.save_model_patch(base.artifact_id, {"p": 2}, name="p2b")

        assert second.artifact_id == first.artifact_id

    def test_patch_requires_revise_for_different_overrides(self, store):
        base = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        store.save_model_patch(base.artifact_id, {"p": 2}, name="p2")

        with pytest.raises(ArtifactNameConflict, match="revise=True"):
            store.save_model_patch(base.artifact_id, {"p": 1}, name="p2")

    def test_patch_chain_resolves_recursively(self, store):
        base = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        first = store.save_model_patch(base.artifact_id, {"p": 2}, name="p2")
        second = store.save_model_patch(
            first.artifact_id, {"distance": _OTHER_DISTANCE}, name="p2b"
        )

        assert store.effective_ir(second)["parameters"]["p"] == 2
        assert store.effective_ir(second)["parameters"]["distance"] == _OTHER_DISTANCE

    def test_compact_cflp_patch_keeps_fingerprint_and_links_solve(self, store):
        report = _cflp_report()
        base = store.save_model_artifact(report, name="cflp", kind="baseline")
        patch = store.save_model_patch(base.artifact_id, {"demand": [5, 3, 3, 2]}, name="d1")

        patched_ir = store.effective_ir(patch)
        assert fingerprint(patched_ir) == patch.fingerprint
        solve = store.save_solve_artifact(
            patched_ir, status="Optimal", objective=42, model_artifact_id=patch.artifact_id
        )
        assert solve.model_ref is not None
        assert solve.model_ref.artifact_id == patch.artifact_id

    def test_patch_cannot_be_baseline(self, store):
        base = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        patch = store.save_model_patch(base.artifact_id, {"p": 2}, name="p2")

        assert store.get_baseline_model().artifact_id == base.artifact_id
        assert patch.artifact_id != store.get_baseline_model().artifact_id


class TestSolveArtifacts:
    def test_solve_links_by_fingerprint(self, store):
        report = _report()
        model = store.save_model_artifact(report, name="baseline", kind="baseline")

        solve = store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)

        assert solve.association_status == "linked"
        assert solve.model_ref is not None
        assert solve.model_ref.artifact_id == model.artifact_id
        assert store.load_state()["baseline_solve"] == solve.artifact_id

    def test_solve_links_to_patch(self, store):
        base = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        patch = store.save_model_patch(base.artifact_id, {"p": 2}, name="p2")
        patched_ir = store.effective_ir(patch)

        solve = store.save_solve_artifact(
            patched_ir, status="Optimal", objective=42, model_artifact_id=patch.artifact_id
        )

        assert solve.model_ref is not None
        assert solve.model_ref.artifact_id == patch.artifact_id

    def test_solve_fingerprint_mismatch_raises(self, store):
        base = store.save_model_artifact(_report(), name="baseline", kind="baseline")

        with pytest.raises(ArtifactLinkError, match="指纹"):
            store.save_solve_artifact(
                _report(_OTHER_DISTANCE)["normalized_ir"],
                status="Optimal",
                model_artifact_id=base.artifact_id,
            )

    def test_unassociated_solve_records_overrides(self, store):
        report = _report()
        solve = store.save_solve_artifact(
            report["normalized_ir"],
            status="Optimal",
            objective=10,
            overrides={"p": 1},
        )

        assert solve.association_status == "unassociated"
        assert solve.model_ref is None
        assert solve.overrides == {"p": 1}


class TestLegacy:
    def test_legacy_files_are_read_as_synthetic_artifacts(self, session):
        store = ArtifactStore(session)
        report = _report()
        session.model_file.write_text(
            json.dumps({"report": report}, ensure_ascii=False), encoding="utf-8"
        )
        session.solve_result_file.write_text(
            json.dumps(
                {
                    "ir_fingerprint": fingerprint(report["normalized_ir"]),
                    "text": "状态：最优\n[RESULT] Objective: 10",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        model = store.resolve_model("baseline")
        solve = store.get_baseline_solve()

        assert model.kind == "legacy"
        assert solve is not None
        assert solve.model_ref is not None
        assert solve.objective == 10
        assert not store.has_artifacts()  # read-only: nothing was written

    def test_legacy_solve_does_not_create_artifacts(self, session):
        store = ArtifactStore(session)
        report = _report()
        session.model_file.write_text(
            json.dumps({"report": report}, ensure_ascii=False), encoding="utf-8"
        )

        store.get_baseline_model()

        assert not (session.workspace / "artifacts").exists()


class TestAnswerManifest:
    def test_resolves_and_records(self, store, session):
        report = _report()
        model = store.save_model_artifact(report, name="baseline", kind="baseline")
        solve = store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)
        manifest = AnswerManifest(session_id=session.session_id)

        manifest.resolve_model(store, "baseline")
        manifest.resolve_solve(store, "baseline")

        assert manifest.model_refs["baseline"] == model.artifact_id
        assert manifest.solve_refs["baseline"] == solve.artifact_id
        assert manifest.entry_extra()["answer_id"].startswith("answer_")

    def test_pins_current_version(self, store):
        first = store.save_model_artifact(_report(), name="cap400")
        manifest = AnswerManifest()
        manifest.resolve_model(store, "cap400")
        store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", revise=True)

        assert manifest.model_refs["cap400"] == first.artifact_id

    def test_rejects_solve_from_another_model(self, store):
        report1 = _report()
        report2 = _report(_OTHER_DISTANCE)
        model2 = store.save_model_artifact(report2, name="b")
        solve = store.save_solve_artifact(report1["normalized_ir"], status="Optimal", objective=1)
        manifest = AnswerManifest()

        with pytest.raises(ArtifactLinkError):
            manifest.resolve_solve(store, solve.artifact_id, model_artifact_id=model2.artifact_id)

    def test_missing_manifest_returns_none(self, session):
        from core.answer_manifest import latest_answer_manifest

        assert latest_answer_manifest(session) is None
