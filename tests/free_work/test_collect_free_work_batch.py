import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_free_work_batch import charger_selection_rome, orchestrer_batch


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


@patch("scripts.collect_free_work_batch.collecter_offres")
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


@patch("scripts.collect_free_work_batch.collecter_offres")
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


@patch("scripts.collect_free_work_batch.collecter_offres")
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
    from scripts.collect_free_work_batch import valider_delai
    import argparse
    assert valider_delai("1.5") == 1.5
    assert valider_delai("0") == 0.0
    with pytest.raises(argparse.ArgumentTypeError, match="n'est pas un nombre valide"):
        valider_delai("invalid")
    with pytest.raises(argparse.ArgumentTypeError, match="erreur : --delay-seconds doit être supérieur ou égal à 0"):
        valider_delai("-1")


@patch("scripts.collect_free_work_batch.collecter_offres")
def test_cli_negative_delay_exits(mock_collecter_offres):
    import sys
    from scripts.collect_free_work_batch import lire_arguments
    test_args = ["scripts/collect_free_work_batch.py", "--delay-seconds", "-1"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit):
            lire_arguments()
    mock_collecter_offres.assert_not_called()


@patch("scripts.collect_free_work_batch.collecter_offres")
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


@patch("scripts.collect_free_work_batch.collecter_offres")
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
