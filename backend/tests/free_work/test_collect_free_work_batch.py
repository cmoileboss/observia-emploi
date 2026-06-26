import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

import backend.scripts.collect_free_work_batch as collect_batch_module
from backend.scripts.collect_free_work_batch import charger_selection_rome, orchestrer_batch


@pytest.fixture(autouse=True)
def isolate_backend_data_roots(tmp_path, monkeypatch):
    data_root = tmp_path / "backend" / "data"
    monkeypatch.setattr(collect_batch_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(collect_batch_module, "RAW_DATA_ROOT", data_root / "raw")
    monkeypatch.setattr(collect_batch_module, "PROCESSED_DATA_ROOT", data_root / "processed")
    yield
    assert not (tmp_path / "data").exists()


def test_charger_selection_rome_valid(tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Études et développement informatique\nM1802;Expertise et support\n"
    csv_file = tmp_path / "valid.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    res = charger_selection_rome(csv_file)
    assert res == {"M1805": "Études et développement informatique", "M1802": "Expertise et support"}


def test_charger_selection_rome_duplicate(tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Études et développement informatique\nM1805;Autre libellé\n"
    csv_file = tmp_path / "duplicate.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ValueError, match="le code ROME 'M1805' est associé à des intitulés différents"):
        charger_selection_rome(csv_file)


def test_charger_selection_rome_empty_label(tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;\n"
    csv_file = tmp_path / "empty.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ValueError, match="l'intitulé est vide"):
        charger_selection_rome(csv_file)


def test_charger_selection_rome_empty_code(tmp_path):
    csv_content = "code_rome;intitule_rome\n;Test\n"
    csv_file = tmp_path / "empty_code.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ValueError, match="le code ROME est vide"):
        charger_selection_rome(csv_file)


def test_orchestrer_batch_invalid_cli_code(tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Études et développement informatique\n"
    csv_file = tmp_path / "selection.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with pytest.raises(ValueError, match="Codes ROME demandés invalides"):
        orchestrer_batch(["INVALID_CODE"], 0.0, csv_file)


@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_orchestrer_batch_merging_deduplication(mock_collecter_offres, tmp_path):
    # Setup selection file
    csv_content = "code_rome;intitule_rome\nM1805;Dev\nM1802;Support\n"
    csv_file = tmp_path / "selection.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    # Run 1 directories
    run1_dir = tmp_path / "run1"
    run1_dir.mkdir()
    offer1 = {"id": 123, "title": "Dev Python"}
    offer2 = {"@id": 456, "title": "Dev JS"}  # test @id priority/fallback
    (run1_dir / "offers_merged_raw.json").write_text(json.dumps([offer1, offer2]), encoding="utf-8")

    # Run 2 directories
    run2_dir = tmp_path / "run2"
    run2_dir.mkdir()
    offer1_dup = {"id": 123, "title": "Dev Python"}  # same ID, same payload
    offer3 = {"id": 789, "title": "Support IT"}
    (run2_dir / "offers_merged_raw.json").write_text(json.dumps([offer1_dup, offer3]), encoding="utf-8")

    mock_collecter_offres.side_effect = [run1_dir, run2_dir]

    processed_dir = orchestrer_batch(["M1805", "M1802"], 0.0, csv_file)

    # Verify outputs exist
    assert (processed_dir / "offers_deduplicated.json").exists()
    assert (processed_dir / "batch_manifest.json").exists()

    with (processed_dir / "offers_deduplicated.json").open("r", encoding="utf-8") as f:
        dedup_offers = json.load(f)

    with (processed_dir / "batch_manifest.json").open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    # We collected:
    # M1805: 2 offers (123, 456)
    # M1802: 2 offers (123, 789)
    # Total before deduplication = 4
    # Unique offers = 3 (123, 456, 789)
    assert manifest["offers_before_global_deduplication"] == 4
    assert manifest["offers_after_global_deduplication"] == 3
    assert manifest["duplicates_removed"] == 1
    assert manifest["conflicting_duplicate_payloads"] == 0

    # Check that offer 123 has both matched_rome_queries
    offer_123_entry = next(o for o in dedup_offers if o["source_id"] == "123")
    assert len(offer_123_entry["matched_rome_queries"]) == 2
    assert {q["rome_code"] for q in offer_123_entry["matched_rome_queries"]} == {"M1805", "M1802"}

    # Check priority of id over @id
    offer_456_entry = next(o for o in dedup_offers if o["source_id"] == "456")
    assert offer_456_entry["offer"] == offer2


@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_orchestrer_batch_payload_conflict(mock_collecter_offres, tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Dev\nM1802;Support\n"
    csv_file = tmp_path / "selection.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    run1_dir = tmp_path / "run1"
    run1_dir.mkdir()
    offer1 = {"id": 123, "title": "Dev Python"}
    (run1_dir / "offers_merged_raw.json").write_text(json.dumps([offer1]), encoding="utf-8")

    run2_dir = tmp_path / "run2"
    run2_dir.mkdir()
    offer1_conflict = {"id": 123, "title": "Different Title"}  # same ID, different payload
    (run2_dir / "offers_merged_raw.json").write_text(json.dumps([offer1_conflict]), encoding="utf-8")

    mock_collecter_offres.side_effect = [run1_dir, run2_dir]

    processed_dir = orchestrer_batch(["M1805", "M1802"], 0.0, csv_file)

    with (processed_dir / "batch_manifest.json").open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["conflicting_duplicate_payloads"] == 1


@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_orchestrer_batch_no_id_error(mock_collecter_offres, tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Dev\n"
    csv_file = tmp_path / "selection.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    run1_dir = tmp_path / "run1"
    run1_dir.mkdir()
    offer_no_id = {"title": "No ID Offer"}  # neither id nor @id
    (run1_dir / "offers_merged_raw.json").write_text(json.dumps([offer_no_id]), encoding="utf-8")

    mock_collecter_offres.side_effect = [run1_dir]

    with pytest.raises(ValueError, match="l'offre ne possède ni 'id' ni '@id'"):
        orchestrer_batch(["M1805"], 0.0, csv_file)


def test_valider_delai():
    from backend.scripts.collect_free_work_batch import valider_delai
    import argparse
    assert valider_delai("1.5") == 1.5
    assert valider_delai("0") == 0.0
    with pytest.raises(argparse.ArgumentTypeError, match="n'est pas un nombre valide"):
        valider_delai("invalid")
    with pytest.raises(argparse.ArgumentTypeError, match="erreur : --delay-seconds doit être supérieur ou égal à 0"):
        valider_delai("-1")


@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_cli_negative_delay_exits(mock_collecter_offres):
    import sys
    from backend.scripts.collect_free_work_batch import lire_arguments
    test_args = ["backend/scripts/collect_free_work_batch.py", "--delay-seconds", "-1"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit):
            lire_arguments()
    mock_collecter_offres.assert_not_called()


@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_orchestrer_batch_continuation_on_failure(mock_collecter_offres, tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Dev\nM1802;Support\n"
    csv_file = tmp_path / "selection.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    import requests
    mock_collecter_offres.side_effect = [
        requests.RequestException("HTTP Error"),
        tmp_path / "run2"
    ]

    run2_dir = tmp_path / "run2"
    run2_dir.mkdir()
    offer = {"id": 123, "title": "Dev Python"}
    (run2_dir / "offers_merged_raw.json").write_text(json.dumps([offer]), encoding="utf-8")

    processed_dir = orchestrer_batch(["M1805", "M1802"], 0.0, csv_file)

    with (processed_dir / "batch_manifest.json").open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["queries_attempted"] == 2
    assert manifest["queries_succeeded"] == 1
    assert manifest["queries_failed"] == 1

    q1 = manifest["queries"][0]
    assert q1["status"] == "failed"
    assert "HTTP Error" in q1["error"]

    q2 = manifest["queries"][1]
    assert q2["status"] == "success"

    with (processed_dir / "offers_deduplicated.json").open("r", encoding="utf-8") as f:
        offers = json.load(f)
    assert len(offers) == 1
    assert offers[0]["source_id"] == "123"


@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_orchestrer_batch_canonicalisation(mock_collecter_offres, tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Dev\n"
    csv_file = tmp_path / "selection.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    offer1 = {"id": 639194, "title": "Dev Python"}
    offer2 = {"id": "639194", "title": "Dev Python"}
    (run_dir / "offers_merged_raw.json").write_text(json.dumps([offer1, offer2]), encoding="utf-8")

    mock_collecter_offres.side_effect = [run_dir]

    processed_dir = orchestrer_batch(["M1805"], 0.0, csv_file)

    with (processed_dir / "offers_deduplicated.json").open("r", encoding="utf-8") as f:
        offers = json.load(f)

    assert len(offers) == 1
    assert offers[0]["source_id"] == "639194"


def test_valider_batch_parent_failures(tmp_path):
    from backend.scripts.collect_free_work_batch import valider_batch_parent

    # Patch PROJECT_ROOT inside scripts.collect_free_work_batch
    with patch("backend.scripts.collect_free_work_batch.PROJECT_ROOT", tmp_path):
        # Missing directory
        missing_dir = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError, match="Dossier parent introuvable"):
            valider_batch_parent(missing_dir)

        # Missing manifest
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        (empty_dir / "offers_deduplicated.json").write_text("[]", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="batch_manifest.json introuvable"):
            valider_batch_parent(empty_dir)

        # Missing offers file
        manifest_only_dir = tmp_path / "manifest_only"
        manifest_only_dir.mkdir()
        (manifest_only_dir / "batch_manifest.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="offers_deduplicated.json introuvable"):
            valider_batch_parent(manifest_only_dir)

        # Invalid manifest JSON
        invalid_json_dir = tmp_path / "invalid_json"
        invalid_json_dir.mkdir()
        (invalid_json_dir / "batch_manifest.json").write_text("{invalid", encoding="utf-8")
        (invalid_json_dir / "offers_deduplicated.json").write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="Fichier batch_manifest.json parent invalide"):
            valider_batch_parent(invalid_json_dir)

        # Source not free_work
        wrong_source_dir = tmp_path / "wrong_source"
        wrong_source_dir.mkdir()
        (wrong_source_dir / "batch_manifest.json").write_text(json.dumps({"source": "other"}), encoding="utf-8")
        (wrong_source_dir / "offers_deduplicated.json").write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="Source invalide dans le manifeste parent"):
            valider_batch_parent(wrong_source_dir)

        # Missing queries
        no_queries_dir = tmp_path / "no_queries"
        no_queries_dir.mkdir()
        (no_queries_dir / "batch_manifest.json").write_text(json.dumps({"source": "free_work"}), encoding="utf-8")
        (no_queries_dir / "offers_deduplicated.json").write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="Clé 'queries' absente ou invalide"):
            valider_batch_parent(no_queries_dir)

        # Duplicate ROME codes in manifest
        dup_romes_dir = tmp_path / "dup_romes"
        dup_romes_dir.mkdir()
        manifest_data = {
            "source": "free_work",
            "queries": [
                {"rome_code": "M1805", "status": "success", "raw_run_directory": "dir1"},
                {"rome_code": "M1805", "status": "failed"}
            ],
            "queries_attempted": 2,
            "queries_succeeded": 1,
            "queries_failed": 1
        }
        (dup_romes_dir / "batch_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
        (dup_romes_dir / "offers_deduplicated.json").write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="Code ROME dupliqué dans le manifeste parent"):
            valider_batch_parent(dup_romes_dir)

        # No failed queries (nothing to resume)
        no_fail_dir = tmp_path / "no_fail"
        no_fail_dir.mkdir()
        success_dir = no_fail_dir / "success_dir"
        success_dir.mkdir()
        (success_dir / "offers_merged_raw.json").write_text("[]", encoding="utf-8")
        manifest_data = {
            "source": "free_work",
            "queries": [
                {"rome_code": "M1805", "status": "success", "raw_run_directory": "no_fail/success_dir"}
            ],
            "queries_attempted": 1,
            "queries_succeeded": 1,
            "queries_failed": 0
        }
        (no_fail_dir / "batch_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
        (no_fail_dir / "offers_deduplicated.json").write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="Le batch parent ne contient aucune requête en échec"):
            valider_batch_parent(no_fail_dir)


def test_should_retry_exception():
    from backend.scripts.collect_free_work_batch import should_retry_exception
    import requests

    # Not a RequestException
    assert should_retry_exception(ValueError("test")) is False

    # RequestException with 502 response
    response_502 = requests.Response()
    response_502.status_code = 502
    exc_502 = requests.RequestException(response=response_502)
    assert should_retry_exception(exc_502) is True

    # RequestException with 400 response
    response_400 = requests.Response()
    response_400.status_code = 400
    exc_400 = requests.RequestException(response=response_400)
    assert should_retry_exception(exc_400) is False

    # RequestException wrapping 502 string message (fallback)
    exc_fallback = requests.RequestException("502 Server Error: Bad Gateway")
    assert should_retry_exception(exc_fallback) is True


@patch("backend.scripts.collect_free_work_batch.time.sleep")
@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_collecter_avec_retry_success(mock_collecter, mock_sleep):
    from backend.scripts.collect_free_work_batch import collecter_avec_retry
    import requests

    mock_collecter.side_effect = [
        requests.RequestException("502 Bad Gateway"),
        Path("success_path")
    ]

    res_path, attempts = collecter_avec_retry("Dev", max_attempts=3)
    assert res_path == Path("success_path")
    assert attempts == 2
    mock_sleep.assert_called_once_with(5.0)


@patch("backend.scripts.collect_free_work_batch.time.sleep")
@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_collecter_avec_retry_persistent_failure(mock_collecter, mock_sleep):
    from backend.scripts.collect_free_work_batch import collecter_avec_retry
    import requests

    mock_collecter.side_effect = [
        requests.RequestException("502 Bad Gateway"),
        requests.RequestException("502 Bad Gateway"),
    ]

    with pytest.raises(requests.RequestException):
        collecter_avec_retry("Dev", max_attempts=2)
    assert mock_sleep.call_count == 1


@patch("backend.scripts.collect_free_work_batch.time.sleep")
@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_orchestrer_batch_resume_success(mock_collecter_offres, mock_sleep, tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Dev\nM1802;Support\n"
    csv_file = tmp_path / "selection.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    # Parent batch setups
    parent_dir = tmp_path / "parent_batch"
    parent_dir.mkdir()

    run_reused_dir = parent_dir / "run_reused"
    run_reused_dir.mkdir()
    (run_reused_dir / "offers_merged_raw.json").write_text(json.dumps([
        {"id": "1", "title": "Dev 1", "elasticHighlights": "Highlight 1"}
    ]), encoding="utf-8")

    manifest_data = {
        "source": "free_work",
        "batch_id": "parent_id",
        "queries": [
            {
                "rome_code": "M1805",
                "rome_label": "Dev",
                "query": "Dev",
                "status": "success",
                "raw_run_directory": str(run_reused_dir.relative_to(tmp_path)).replace("\\", "/")
            },
            {
                "rome_code": "M1802",
                "rome_label": "Support",
                "query": "Support",
                "status": "failed",
                "raw_run_directory": None
            }
        ],
        "queries_attempted": 2,
        "queries_succeeded": 1,
        "queries_failed": 1
    }
    (parent_dir / "batch_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    (parent_dir / "offers_deduplicated.json").write_text("[]", encoding="utf-8")

    # Mock new run directory for failed ROME (M1802)
    new_run_dir = tmp_path / "new_run"
    new_run_dir.mkdir()
    (new_run_dir / "offers_merged_raw.json").write_text(json.dumps([
        {"id": "2", "title": "Support 1"}
    ]), encoding="utf-8")

    mock_collecter_offres.side_effect = [new_run_dir]

    # Run resume orchestrator with patched PROJECT_ROOT
    with patch("backend.scripts.collect_free_work_batch.PROJECT_ROOT", tmp_path):
        new_batch_dir = orchestrer_batch(
            rome_codes_filter=None,
            delay_seconds=0.0,
            rome_csv_path=csv_file,
            resume_parent_path=parent_dir,
            max_attempts=2
        )

    assert new_batch_dir.exists()
    # Check parent batch is unmodified
    assert (parent_dir / "batch_manifest.json").exists()

    with (new_batch_dir / "batch_manifest.json").open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["batch_complete"] is True
    assert manifest["parent_batch_id"] == "parent_id"
    assert manifest["resume_mode"] is True
    assert manifest["queries_reused"] == 1
    assert manifest["queries_retried"] == 1
    assert manifest["retried_rome_codes"] == ["M1802"]
    assert manifest["remaining_failed_queries"] == 0

    with (new_batch_dir / "offers_deduplicated.json").open("r", encoding="utf-8") as f:
        offers = json.load(f)

    assert len(offers) == 2
    assert {o["source_id"] for o in offers} == {"1", "2"}


@patch("backend.scripts.collect_free_work_batch.time.sleep")
@patch("backend.scripts.collect_free_work_batch.collecter_offres")
def test_orchestrer_batch_payload_conflict_diagnostics(mock_collecter_offres, mock_sleep, tmp_path):
    csv_content = "code_rome;intitule_rome\nM1805;Dev\nM1802;Support\n"
    csv_file = tmp_path / "selection.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    run1_dir = tmp_path / "run1"
    run1_dir.mkdir()
    offer1 = {
        "id": "1",
        "title": "Title 1",
        "elasticHighlights": "Highlight A",
        "location": {"@id": "/.well-known/genid/abc", "locality": "Paris"}
    }
    (run1_dir / "offers_merged_raw.json").write_text(json.dumps([offer1]), encoding="utf-8")

    run2_dir = tmp_path / "run2"
    run2_dir.mkdir()
    # Context-only differences
    offer1_dup1 = {
        "id": "1",
        "title": "Title 1",
        "elasticHighlights": "Highlight B",
        "location": {"@id": "/.well-known/genid/xyz", "locality": "Paris"}
    }
    (run2_dir / "offers_merged_raw.json").write_text(json.dumps([offer1_dup1]), encoding="utf-8")

    mock_collecter_offres.side_effect = [run1_dir, run2_dir]

    processed_dir = orchestrer_batch(None, 0.0, csv_file)

    # Verify diagnostic file exists
    diag_file = processed_dir / "payload_conflict_diagnostics.json"
    assert diag_file.exists()

    with diag_file.open("r", encoding="utf-8") as f:
        diagnostics = json.load(f)

    assert len(diagnostics) == 1
    assert diagnostics[0]["source_id"] == "1"
    assert diagnostics[0]["only_search_context_fields_differ"] is True
    assert sorted(diagnostics[0]["differing_top_level_keys"]) == ["elasticHighlights", "location"]

    with (processed_dir / "batch_manifest.json").open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["duplicate_payloads_identical"] == 0
    assert manifest["duplicate_payloads_search_context_only"] == 1
    assert manifest["duplicate_payloads_business_fields_different"] == 0


def test_valider_max_attempts():
    from backend.scripts.collect_free_work_batch import valider_max_attempts
    import argparse
    assert valider_max_attempts("1") == 1
    assert valider_max_attempts("5") == 5
    with pytest.raises(argparse.ArgumentTypeError, match="n'est pas un entier valide"):
        valider_max_attempts("invalid")
    with pytest.raises(argparse.ArgumentTypeError, match="erreur : --max-attempts doit être supérieur ou égal à 1"):
        valider_max_attempts("0")
