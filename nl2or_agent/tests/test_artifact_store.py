"""Tests for the Phase 1 artifact store and AnswerManifest."""

from __future__ import annotations

import json

import pytest

from core.answer_manifest import AnswerManifest, latest_answer_manifest
from core.ir_validate import validate_problem_ir
from core.problem_ir import fingerprint
from utils.artifact_store import (
    ArtifactError,
    ArtifactLinkError,
    ArtifactNameConflict,
    ArtifactNotFound,
    ArtifactStore,
)

_DISTANCE = [[1, 2], [2, 1]]
_OTHER_DISTANCE = [[1, 5], [5, 1]]


def _pmedian_ir(distance: list[list[int]] | None = None) -> dict:
    return {
        "problem_families": [{"id": "p_median"}],
        "entities": {"I": {"size": 2}, "J": {"size": 2}},
        "parameters": {"p": 1, "distance": distance or _DISTANCE},
        "constraint_blocks": [
            {"block_id": "assign_each_demand_once"},
            {"block_id": "link_assignment_to_open"},
            {"block_id": "cardinality_open_p_facilities"},
        ],
        "objective": {"block_id": "weighted_service_distance_objective"},
    }


def _report(distance: list[list[int]] | None = None) -> dict:
    report = validate_problem_ir(_pmedian_ir(distance))
    assert report["valid"], report["errors"]
    return report


def _invalid_report() -> dict:
    ir = _pmedian_ir()
    ir["constraint_blocks"] = [{"block_id": "assign_each_demand_once"}]
    report = validate_problem_ir(ir)
    assert not report["valid"]
    return report


@pytest.fixture()
def session(tmp_path, monkeypatch):
    import utils.session as session_mod

    monkeypatch.setattr(session_mod, "_SESSIONS_ROOT", tmp_path / "sessions")
    return session_mod.Session(session_id="art01")


@pytest.fixture()
def store(session):
    return ArtifactStore(session)


# ---------------------------------------------------------------------------
# Model artifacts
# ---------------------------------------------------------------------------


class TestModelArtifacts:
    def test_save_creates_version_and_baseline(self, store):
        report = _report()

        artifact = store.save_model_artifact(report, name="baseline", kind="baseline")

        assert artifact.artifact_id.startswith("model_")
        assert artifact.revision == 1
        assert artifact.validation_status == "valid"
        assert store.model_version_file(artifact.artifact_id).is_file()
        assert store.model_pointer_file("baseline").is_file()
        index = store.load_index()
        assert index.models["baseline"]["current"] == artifact.artifact_id
        assert index.baseline_model == artifact.artifact_id

    def test_same_name_same_fingerprint_is_idempotent(self, store):
        first = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        second = store.save_model_artifact(_report(), name="baseline", kind="baseline")

        assert second.artifact_id == first.artifact_id
        index = store.load_index()
        assert len(index.models["baseline"]["versions"]) == 1

    def test_same_name_different_fingerprint_requires_revise(self, store):
        store.save_model_artifact(_report(), name="cap400")

        with pytest.raises(ArtifactNameConflict, match="revise=True"):
            store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400")

    def test_revise_keeps_history(self, store):
        first = store.save_model_artifact(_report(), name="cap400")
        second = store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", revise=True)

        assert second.revision == 2
        index = store.load_index()
        assert index.models["cap400"]["versions"] == [
            first.artifact_id,
            second.artifact_id,
        ]
        assert store.load_model_artifact(first.artifact_id).fingerprint != second.fingerprint

    def test_overwrite_is_an_alias_for_revise(self, store):
        first = store.save_model_artifact(_report(), name="cap400")
        second = store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", overwrite=True)

        assert second.revision == 2
        assert store.load_model_artifact(first.artifact_id).fingerprint != second.fingerprint

    def test_invalid_model_not_baseline(self, store):
        artifact = store.save_model_artifact(_invalid_report(), name="broken")

        assert artifact.validation_status == "invalid"
        assert store.load_index().baseline_model is None
        with pytest.raises(ArtifactError, match="baseline"):
            store.save_model_artifact(_invalid_report(), name="broken2", baseline=True)

    def test_explicit_baseline_updates_pointer(self, store):
        baseline = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        scenario = store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", baseline=True)

        index = store.load_index()
        assert index.baseline_model == scenario.artifact_id
        assert index.baseline_model != baseline.artifact_id
        assert index.baseline_solve is None

    def test_auto_name_uses_baseline_first(self, store):
        first = store.save_model_artifact(_report())
        second = store.save_model_artifact(_report(_OTHER_DISTANCE))

        assert first.name == "baseline"
        assert second.name == "scenario"

    def test_model_artifacts_list_current_and_history(self, store):
        first = store.save_model_artifact(_report(), name="cap400")
        second = store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", revise=True)

        current = store.list_model_artifacts(current_only=True)
        all_items = store.list_model_artifacts()
        assert [item.artifact_id for item in current] == [second.artifact_id]
        assert {item.artifact_id for item in all_items} >= {
            first.artifact_id,
            second.artifact_id,
        }

    def test_version_file_does_not_persist_a_baseline_flag(self, store):
        artifact = store.save_model_artifact(_report(), name="baseline", kind="baseline")

        payload = json.loads(store.model_version_file(artifact.artifact_id).read_text())

        assert "is_baseline" not in payload


# ---------------------------------------------------------------------------
# Solve artifacts and association
# ---------------------------------------------------------------------------


class TestSolveArtifacts:
    def test_solve_links_by_fingerprint(self, store):
        report = _report()
        model = store.save_model_artifact(report, name="baseline", kind="baseline")

        solve = store.save_solve_artifact(
            report["normalized_ir"], status="Optimal", objective=10, text="ok"
        )

        assert solve.association_status == "linked"
        assert solve.model_ref is not None
        assert solve.model_ref.artifact_id == model.artifact_id
        assert solve.name == "baseline"
        assert store.load_index().baseline_solve == solve.artifact_id

    def test_solve_explicit_model_id(self, store):
        report = _report()
        model = store.save_model_artifact(report, name="cap400")

        solve = store.save_solve_artifact(
            report["normalized_ir"],
            status="Optimal",
            objective=10,
            model_artifact_id=model.artifact_id,
        )

        assert solve.model_ref is not None
        assert solve.model_ref.artifact_id == model.artifact_id

    def test_solve_fingerprint_mismatch_raises(self, store):
        report = _report()
        model = store.save_model_artifact(report, name="cap400")
        other = _report(_OTHER_DISTANCE)

        with pytest.raises(ArtifactLinkError, match="指纹"):
            store.save_solve_artifact(
                other["normalized_ir"],
                status="Optimal",
                objective=10,
                model_artifact_id=model.artifact_id,
            )

    def test_solve_does_not_link_to_an_invalid_model(self, store):
        report = _invalid_report()
        model = store.save_model_artifact(report, name="broken")

        solve = store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)

        assert solve.association_status == "unassociated"
        assert solve.model_ref is None
        with pytest.raises(ArtifactLinkError, match="未通过校验"):
            store.save_solve_artifact(
                report["normalized_ir"],
                status="Optimal",
                objective=10,
                model_artifact_id=model.artifact_id,
            )

    def test_solve_ambiguous_when_multiple_same_fingerprint(self, store):
        store.save_model_artifact(_report(), name="baseline", kind="baseline")
        report = _report(_OTHER_DISTANCE)
        store.save_model_artifact(report, name="a")
        store.save_model_artifact(report, name="b")

        solve = store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)

        assert solve.association_status == "ambiguous"
        assert solve.model_ref is None

    def test_same_name_versions_do_not_cross_results(self, store):
        report1 = _report()
        model1 = store.save_model_artifact(report1, name="cap400")
        solve1 = store.save_solve_artifact(report1["normalized_ir"], status="Optimal", objective=1)

        report2 = _report(_OTHER_DISTANCE)
        model2 = store.save_model_artifact(report2, name="cap400", revise=True)
        solve2 = store.save_solve_artifact(report2["normalized_ir"], status="Optimal", objective=2)

        assert solve1.model_ref is not None
        assert solve2.model_ref is not None
        assert solve1.model_ref.artifact_id == model1.artifact_id
        assert solve2.model_ref.artifact_id == model2.artifact_id
        assert solve1.model_ref.artifact_id != solve2.model_ref.artifact_id

    def test_unassociated_solve_is_kept(self, store):
        report = _report()

        solve = store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)

        assert solve.association_status == "unassociated"
        assert solve.model_ref is None
        assert store.list_solve_artifacts()

    def test_solve_failure_status_is_stored(self, store):
        report = _report()
        store.save_model_artifact(report, name="cap400")

        solve = store.save_solve_artifact(
            report["normalized_ir"], status="Infeasible", objective=None, text="不可行"
        )

        assert solve.status == "Infeasible"
        assert solve.objective is None
        assert store.find_solves_by_model(solve.model_ref.artifact_id) == [solve]


# ---------------------------------------------------------------------------
# Index, baseline and legacy
# ---------------------------------------------------------------------------


class TestIndexAndLegacy:
    def test_index_rebuild_after_delete(self, store):
        report = _report()
        model = store.save_model_artifact(report, name="baseline", kind="baseline")
        solve = store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)
        store.index_file.unlink()

        index = store.load_index()

        assert index.models["baseline"]["current"] == model.artifact_id
        assert index.solves["baseline"]["current"] == solve.artifact_id
        assert index.baseline_model == model.artifact_id
        assert index.baseline_solve == solve.artifact_id

    def test_baseline_pointer_survives_index_rebuild(self, store):
        store.save_model_artifact(_report(), name="baseline", kind="baseline")
        scenario = store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", baseline=True)
        store.index_file.unlink()

        index = store.load_index()

        assert index.baseline_model == scenario.artifact_id

    def test_invalid_baseline_pointer_falls_back_to_a_valid_model(self, store):
        valid = store.save_model_artifact(_report(), name="baseline", kind="baseline")
        invalid = store.save_model_artifact(_invalid_report(), name="broken")
        store.baseline_file.write_text(
            json.dumps({"baseline_model": invalid.artifact_id}), encoding="utf-8"
        )
        store.index_file.unlink()

        index = store.load_index()

        assert index.baseline_model == valid.artifact_id

    def test_baseline_solve_pointer_must_match_the_baseline_model(self, store):
        report1 = _report()
        report2 = _report(_OTHER_DISTANCE)
        model1 = store.save_model_artifact(report1, name="baseline", kind="baseline")
        model2 = store.save_model_artifact(report2, name="cap400")
        solve1 = store.save_solve_artifact(report1["normalized_ir"], status="Optimal", objective=1)
        solve2 = store.save_solve_artifact(report2["normalized_ir"], status="Optimal", objective=2)
        store.baseline_file.write_text(
            json.dumps(
                {
                    "baseline_model": model1.artifact_id,
                    "baseline_solve": solve2.artifact_id,
                }
            ),
            encoding="utf-8",
        )
        store.index_file.unlink()

        index = store.load_index()

        assert model2.artifact_id != model1.artifact_id
        assert index.baseline_solve == solve1.artifact_id

    def test_legacy_files_are_deduplicated_against_equivalent_artifacts(self, session):
        store = ArtifactStore(session)
        report = _report()
        store.save_model_artifact(report, name="cflp")
        store.save_solve_artifact(
            report["normalized_ir"], status="Optimal", objective=10, text="ok"
        )
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

        models = ArtifactStore(session).list_model_artifacts()
        solves = ArtifactStore(session).list_solve_artifacts()

        assert len(models) == 1
        assert len(solves) == 1
        assert all(item.source.get("type") != "legacy" for item in models)
        assert all(item.source.get("type") != "legacy" for item in solves)

    def test_legacy_model_and_solve_are_imported(self, session):
        store = ArtifactStore(session)
        report = _report()
        model_payload = {"saved_at": "2026-01-01T00:00:00+00:00", "report": report}
        session.model_file.write_text(
            json.dumps(model_payload, ensure_ascii=False), encoding="utf-8"
        )
        solve_payload = {
            "ir_fingerprint": fingerprint(report["normalized_ir"]),
            "text": "状态：最优\n[RESULT] Objective: 10",
        }
        session.solve_result_file.write_text(
            json.dumps(solve_payload, ensure_ascii=False), encoding="utf-8"
        )

        models = store.list_model_artifacts()
        legacy = [item for item in models if item.source.get("type") == "legacy"]

        assert len(legacy) == 1
        assert legacy[0].name == "baseline"
        assert legacy[0].validation_status == "valid"
        solve = store.get_baseline_solve()
        assert solve is not None
        assert solve.model_ref is not None
        assert solve.model_ref.artifact_id == legacy[0].artifact_id
        assert solve.objective == 10

    def test_imported_direct_file_is_unvalidated(self, store):
        store.imports_dir.mkdir(parents=True, exist_ok=True)
        (store.imports_dir / "custom.json").write_text(json.dumps(_pmedian_ir()), encoding="utf-8")

        items = store.list_model_artifacts(include_imports=True)
        imported = [item for item in items if item.name == "custom"]

        assert len(imported) == 1
        assert imported[0].validation_status == "unvalidated"
        assert imported[0].source["tool_generated"] is False
        assert store.resolve_model("custom").artifact_id == imported[0].artifact_id


# ---------------------------------------------------------------------------
# AnswerManifest
# ---------------------------------------------------------------------------


class TestAnswerManifest:
    def test_resolves_and_persists(self, store, session):
        report = _report()
        model = store.save_model_artifact(report, name="baseline", kind="baseline")
        solve = store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)
        manifest = AnswerManifest(session_id=session.session_id)

        manifest.resolve_model(store, "baseline")
        manifest.resolve_solve(store, "baseline")
        manifest.save(store, text="answer")

        loaded = AnswerManifest.load(store, manifest.answer_id)
        assert loaded.model_refs["baseline"] == model.artifact_id
        assert loaded.solve_refs["baseline"] == solve.artifact_id
        assert latest_answer_manifest(store) is not None

    def test_pins_current_version(self, store):
        first = store.save_model_artifact(_report(), name="cap400")
        manifest = AnswerManifest()
        manifest.resolve_model(store, "cap400")
        store.save_model_artifact(_report(_OTHER_DISTANCE), name="cap400", revise=True)

        assert manifest.model_refs["cap400"] == first.artifact_id
        assert store.resolve_model("cap400").artifact_id != first.artifact_id

    def test_rejects_a_solve_from_another_model(self, store):
        report1 = _report()
        report2 = _report(_OTHER_DISTANCE)
        model1 = store.save_model_artifact(report1, name="a")
        model2 = store.save_model_artifact(report2, name="b")
        solve = store.save_solve_artifact(report1["normalized_ir"], status="Optimal", objective=1)
        manifest = AnswerManifest()

        with pytest.raises(ArtifactLinkError):
            manifest.resolve_solve(store, solve.artifact_id, model_artifact_id=model2.artifact_id)
        assert manifest.solve_refs == {}
        assert model1.artifact_id != model2.artifact_id

    def test_not_saved_until_commit(self, store):
        report = _report()
        store.save_model_artifact(report, name="baseline", kind="baseline")
        store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)
        manifest = AnswerManifest()
        manifest.resolve_model(store)
        manifest.resolve_solve(store)

        assert list(store.answers_dir.glob("*.json")) == []
        manifest.save(store, text="done")
        assert len(list(store.answers_dir.glob("*.json"))) == 1

    def test_load_missing_manifest_raises(self, store):
        with pytest.raises(ArtifactNotFound):
            AnswerManifest.load(store, "answer_missing")

    def test_baseline_solve_resolution_requires_a_baseline(self, store):
        manifest = AnswerManifest()
        with pytest.raises(ArtifactNotFound, match="baseline"):
            manifest.resolve_solve(store)

    def test_baseline_alias_resolves_the_pointer(self, store):
        report = _report()
        model = store.save_model_artifact(report, name="cflp_base")
        solve = store.save_solve_artifact(report["normalized_ir"], status="Optimal", objective=10)
        manifest = AnswerManifest()

        assert manifest.resolve_model(store, "baseline").artifact_id == model.artifact_id
        assert manifest.resolve_solve(store, "baseline").artifact_id == solve.artifact_id
