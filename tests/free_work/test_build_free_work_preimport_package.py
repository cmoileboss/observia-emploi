import json
import pytest
import hashlib
from pathlib import Path
from scripts.build_free_work_preimport_package import main as preimport_main


@pytest.fixture
def tmp_run_dirs(tmp_path):
    sync_dir = tmp_path / "sync_run"
    sync_dir.mkdir()
    triage_dir = tmp_path / "triage_run"
    triage_dir.mkdir()
    rome_dir = tmp_path / "rome_run"
    rome_dir.mkdir()
    output_dir = tmp_path / "output_run"

    return {
        "sync": sync_dir,
        "triage": triage_dir,
        "rome": rome_dir,
        "output": output_dir,
        "normalized": tmp_path / "offers_normalized.json"
    }


def helper_setup_files(tmp_run_dirs, normalized_data, sync_manifest, offers_to_process, offers_to_deactivate, unchanged_offer_ids, triage_decisions, rome_assignments):
    # 1. Écrire offers_normalized.json
    normalized_content = json.dumps(normalized_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp_run_dirs["normalized"].write_text(normalized_content, encoding="utf-8")

    # Calculer le hash
    digest = hashlib.sha256()
    with tmp_run_dirs["normalized"].open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    sync_manifest["normalized_input_sha256"] = digest.hexdigest()

    # 2. Écrire les fichiers de synchro
    with (tmp_run_dirs["sync"] / "sync_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(sync_manifest, f)
    with (tmp_run_dirs["sync"] / "offers_to_process.json").open("w", encoding="utf-8") as f:
        json.dump(offers_to_process, f)
    with (tmp_run_dirs["sync"] / "offers_to_deactivate.json").open("w", encoding="utf-8") as f:
        json.dump(offers_to_deactivate, f)
    with (tmp_run_dirs["sync"] / "unchanged_offer_ids.json").open("w", encoding="utf-8") as f:
        json.dump(unchanged_offer_ids, f)

    # 3. Écrire triage manifest et decisions.jsonl
    triage_manifest = {
        "run_id": "triage_test",
        "input_files": {
            "free_work_input": "data/processed/free_work/full_catalog/20260624_test/offers_normalized.json"
        }
    }
    with (tmp_run_dirs["triage"] / "run_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(triage_manifest, f)
    with (tmp_run_dirs["triage"] / "triage_decisions.jsonl").open("w", encoding="utf-8") as f:
        for d in triage_decisions:
            f.write(json.dumps(d) + "\n")

    # 4. Écrire ROME assignments and manifest
    rome_manifest = {
        "classifier_version": "rome_test",
        "input_files": {},
        "rome_assignments": {}
    }
    with (tmp_run_dirs["rome"] / "rome_classification_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(rome_manifest, f)
    with (tmp_run_dirs["rome"] / "rome_assignments_deterministic_v1.jsonl").open("w", encoding="utf-8") as f:
        for r in rome_assignments:
            f.write(json.dumps(r) + "\n")


def test_build_preimport_nominal(tmp_run_dirs, monkeypatch):
    normalized_data = [
        {"source": "free_work", "source_id": "1", "title": "Dev Java", "skills": [{"name": "Java"}], "soft_skills": [{"name": "Communication"}]},
        {"source": "free_work", "source_id": "2", "title": "Dev Python", "skills": [], "soft_skills": []},
        {"source": "free_work", "source_id": "3", "title": "Dev Angular", "skills": [], "soft_skills": []},
        {"source": "free_work", "source_id": "4", "title": "Dev React", "skills": [], "soft_skills": []}
    ]
    sync_manifest = {
        "run_id": "sync_test",
        "mode": "BOOTSTRAP",
        "source_batch_id": "20260624_test"
    }
    offers_to_process = [
        {"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"},
        {"free_work_id": "2", "last_change_type": "UPDATED", "source_batch_id": "20260624_test"},
        {"free_work_id": "3", "last_change_type": "NEW", "source_batch_id": "20260624_test"},
        {"free_work_id": "4", "last_change_type": "NEW", "source_batch_id": "20260624_test"},
    ]
    triage_decisions = [
        {"free_work": {"source_id": "1"}, "decision": "PRESENT_IN_FT_SNAPSHOT", "best_candidate": {"france_travail_id": "FT_1"}},
        {"free_work": {"source_id": "2"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT", "review_action": "NO_MANUAL_REVIEW"},
        {"free_work": {"source_id": "3"}, "decision": "UNCERTAIN", "review_action": "REVIEW_NOW"},
        {"free_work": {"source_id": "4"}, "decision": "UNCERTAIN", "review_action": "DEFER_DATA_INCOMPLETE"}
    ]
    rome_assignments = [
        {"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "CONFIRMED_FROM_FT_MATCH"},
        {"free_work_id": "2", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"},
        {"free_work_id": "3", "assigned_rome_code": None, "assignment_status": "UNASSIGNED_AMBIGUOUS"},
        {"free_work_id": "4", "assigned_rome_code": None, "assignment_status": "UNASSIGNED_INSUFFICIENT_SIGNAL"},
    ]
    helper_setup_files(tmp_run_dirs, normalized_data, sync_manifest, offers_to_process, [], [], triage_decisions, rome_assignments)

    args = [
        "build_free_work_preimport_package.py",
        "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]),
        "--triage-run-dir", str(tmp_run_dirs["triage"]),
        "--rome-run-dir", str(tmp_run_dirs["rome"]),
        "--normalized-input", str(tmp_run_dirs["normalized"]),
        "--output-dir", str(tmp_run_dirs["output"]),
        "--run-id", "preimport_test_run"
    ]
    monkeypatch.setattr("sys.argv", args)
    preimport_main()

    assert tmp_run_dirs["output"].exists()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED"
    assert manifest["counts"]["ENRICH_EXISTING_FT"] == 1
    assert manifest["counts"]["CREATE_FREE_WORK"] == 1
    assert manifest["counts"]["UPDATE_FREE_WORK"] == 1
    assert manifest["counts"]["DEFER"] == 1


def test_transition_new_not_found(tmp_run_dirs, monkeypatch):
    # 1. NEW + NOT_FOUND -> CREATE_FREE_WORK
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["CREATE_FREE_WORK"] == 1
    assert manifest["counts"]["NO_ACTION"] == 0


def test_transition_updated_not_found(tmp_run_dirs, monkeypatch):
    # 2. UPDATED + NOT_FOUND -> UPDATE_FREE_WORK
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "INCREMENTAL", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "UPDATED", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["UPDATE_FREE_WORK"] == 1


def test_transition_reactivated_not_found(tmp_run_dirs, monkeypatch):
    # 3. REACTIVATED + NOT_FOUND -> REACTIVATE_FREE_WORK
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "INCREMENTAL", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "REACTIVATED", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["REACTIVATE_FREE_WORK"] == 1


def test_transition_present(tmp_run_dirs, monkeypatch):
    # 4. PRESENT -> ENRICH_EXISTING_FT
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "PRESENT_IN_FT_SNAPSHOT", "best_candidate": {"france_travail_id": "FT_123"}}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "CONFIRMED_FROM_FT_MATCH"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["ENRICH_EXISTING_FT"] == 1


def test_transition_uncertain_review_now(tmp_run_dirs, monkeypatch):
    # 5. UNCERTAIN + REVIEW_NOW + NEW -> CREATE_FREE_WORK
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "UNCERTAIN", "review_action": "REVIEW_NOW"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "UNASSIGNED_AMBIGUOUS"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["CREATE_FREE_WORK"] == 1


def test_transition_uncertain_defer(tmp_run_dirs, monkeypatch):
    # 6. UNCERTAIN + DEFER -> DEFER
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "UNCERTAIN", "review_action": "DEFER_DATA_INCOMPLETE"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": None, "assignment_status": "UNASSIGNED_INSUFFICIENT_SIGNAL"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["DEFER"] == 1


def test_transition_processing_error(tmp_run_dirs, monkeypatch):
    # 7. PROCESSING_ERROR -> REJECT
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "PROCESSING_ERROR"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": None, "assignment_status": "PROCESSING_ERROR"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["REJECT"] == 1


def test_unchanged_no_action(tmp_run_dirs, monkeypatch):
    # 8. UNCHANGED -> NO_ACTION
    # 9. UNCHANGED absent des fichiers d'écriture métier
    # 10. UNCHANGED présent dans unchanged_offer_ids.json
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[
            {"source": "free_work", "source_id": "1", "title": "Dev 1"},
            {"source": "free_work", "source_id": "2", "title": "Dev 2"}
        ],
        sync_manifest={"run_id": "sync_test", "mode": "INCREMENTAL", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=["2"],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["CREATE_FREE_WORK"] == 1
    assert manifest["counts"]["NO_ACTION"] == 1

    # Vérifier que "2" n'est présent dans aucune écriture métier, mais dans unchanged_offer_ids.json
    with (tmp_run_dirs["output"] / "unchanged_offer_ids.json").open("r") as f:
        unchanged_ids_written = json.load(f)
    assert unchanged_ids_written == ["2"]

    with (tmp_run_dirs["output"] / "offers_to_create.json").open("r") as f:
        created = json.load(f)
    assert len(created) == 1
    assert created[0]["source_id"] == "1"


def test_inactivated_deactivate_free_work(tmp_run_dirs, monkeypatch):
    # 11. INACTIVATED -> DEACTIVATE_FREE_WORK
    # 12. offre INACTIVATED absente de offers_normalized.json
    # 13. aucun triage exigé pour INACTIVATED
    # 14. aucun ROME exigé pour INACTIVATED
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev 1"}],
        sync_manifest={"run_id": "sync_test", "mode": "INCREMENTAL", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[{"free_work_id": "99", "source_batch_id": "20260624_test"}],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["DEACTIVATE_FREE_WORK"] == 1

    with (tmp_run_dirs["output"] / "offers_to_deactivate.json").open("r") as f:
        deac = json.load(f)
    assert len(deac) == 1
    assert deac[0]["source_id"] == "99"


def test_triage_rome_superset(tmp_run_dirs, monkeypatch):
    # 15. triage couvrant un superset valide de process_ids
    # 16. ROME couvrant un superset valide de process_ids
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[
            {"source": "free_work", "source_id": "1", "title": "Dev 1"},
            {"source": "free_work", "source_id": "2", "title": "Dev 2"}
        ],
        sync_manifest={"run_id": "sync_test", "mode": "INCREMENTAL", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=["2"],
        triage_decisions=[
            {"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"},
            {"free_work": {"source_id": "2"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"} # triage contient "2" qui est inchangé
        ],
        rome_assignments=[
            {"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"},
            {"free_work_id": "2", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"} # ROME contient "2"
        ]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    manifest = json.loads((tmp_run_dirs["output"] / "preimport_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED"


def test_triage_outside_snapshot_refused(tmp_run_dirs, monkeypatch):
    # 17. rejet d'un triage extérieur au snapshot actif
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[
            {"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"},
            {"free_work": {"source_id": "999"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"} # hors snapshot actif !
        ],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1


def test_rome_outside_snapshot_refused(tmp_run_dirs, monkeypatch):
    # 18. rejet d'un ROME extérieur au snapshot actif
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[
            {"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"},
            {"free_work_id": "999", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"} # hors snapshot !
        ]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1


def test_triage_missing_fails(tmp_run_dirs, monkeypatch):
    # 19. triage manquant pour un process_id
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[], # vide !
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1


def test_rome_missing_fails(tmp_run_dirs, monkeypatch):
    # 20. ROME manquant pour un process_id
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[{"source": "free_work", "source_id": "1", "title": "Dev"}],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[] # vide !
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1


def test_duplicate_identifiers_fails(tmp_run_dirs, monkeypatch):
    # 21. identifiants dupliqués dans normalized_input
    normalized_data = [
        {"source": "free_work", "source_id": "1", "title": "Dev 1"},
        {"source": "free_work", "source_id": "1", "title": "Dev 1 bis"} # doublon
    ]
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=normalized_data,
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1


def test_partition_overlap_fails(tmp_run_dirs, monkeypatch):
    # 22. partitions non disjointes (ex: process et unchanged partagent un ID)
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[
            {"source": "free_work", "source_id": "1", "title": "Dev 1"},
            {"source": "free_work", "source_id": "2", "title": "Dev 2"}
        ],
        sync_manifest={"run_id": "sync_test", "mode": "INCREMENTAL", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=["1"], # ID 1 est aussi dans process !
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1


def test_skills_soft_skills_separated(tmp_run_dirs, monkeypatch):
    # 24. compétences et soft skills propagées séparément
    helper_setup_files(
        tmp_run_dirs,
        normalized_data=[
            {
                "source": "free_work",
                "source_id": "1",
                "title": "Dev 1",
                "skills": [{"name": "Python", "name_normalized": "python"}],
                "soft_skills": [{"name": "Leadership", "name_normalized": "leadership"}]
            }
        ],
        sync_manifest={"run_id": "sync_test", "mode": "BOOTSTRAP", "source_batch_id": "20260624_test"},
        offers_to_process=[{"free_work_id": "1", "last_change_type": "NEW", "source_batch_id": "20260624_test"}],
        offers_to_deactivate=[],
        unchanged_offer_ids=[],
        triage_decisions=[{"free_work": {"source_id": "1"}, "decision": "NOT_FOUND_IN_FT_SNAPSHOT"}],
        rome_assignments=[{"free_work_id": "1", "assigned_rome_code": "M1805", "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE"}]
    )
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    preimport_main()
    with (tmp_run_dirs["output"] / "offers_to_create.json").open("r") as f:
        created = json.load(f)
    assert len(created) == 1
    assert created[0]["skills"] == [{"name": "Python", "name_normalized": "python"}]
    assert created[0]["soft_skills"] == [{"name": "Leadership", "name_normalized": "leadership"}]


def test_progress_failed_on_error(tmp_run_dirs, monkeypatch):
    # 25. progression FAILED en cas d'erreur
    # dossier sync vide provoquera une exception
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1
    progress_file = tmp_run_dirs["output"] / "preimport_progress.json"
    assert progress_file.exists()
    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    assert progress["status"] == "FAILED"
    assert progress["error"] is not None


def test_output_not_empty_refused(tmp_run_dirs, monkeypatch):
    # 26. dossier de sortie non vide refusé
    tmp_run_dirs["output"].mkdir(parents=True, exist_ok=True)
    (tmp_run_dirs["output"] / "some_file.txt").write_text("not empty")
    monkeypatch.setattr("sys.argv", ["build_free_work_preimport_package.py", "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]), "--triage-run-dir", str(tmp_run_dirs["triage"]), "--rome-run-dir", str(tmp_run_dirs["rome"]), "--normalized-input", str(tmp_run_dirs["normalized"]), "--output-dir", str(tmp_run_dirs["output"]), "--run-id", "test_run"])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1


def test_build_preimport_failures(tmp_run_dirs, monkeypatch):
    monkeypatch.setattr("sys.argv", [
        "build_free_work_preimport_package.py",
        "--catalog-sync-run-dir", str(tmp_run_dirs["sync"]),
        "--triage-run-dir", str(tmp_run_dirs["triage"]),
        "--rome-run-dir", str(tmp_run_dirs["rome"]),
        "--normalized-input", str(tmp_run_dirs["normalized"]),
        "--output-dir", str(tmp_run_dirs["output"]),
        "--run-id", "preimport_test_run"
    ])
    with pytest.raises(SystemExit) as excinfo:
        preimport_main()
    assert excinfo.value.code == 1
