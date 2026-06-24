import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_free_work_match_candidates import (
    normaliser_cle,
    normaliser_cle_compacte,
    extraire_tokens,
    generer_matching,
    charger_free_work,
    charger_france_travail,
    supprimer_diacritiques,
    write_progress,
    main
)


def test_supprimer_diacritiques():
    assert supprimer_diacritiques("éèàçûô") == "eeacuo"
    assert supprimer_diacritiques("Python") == "Python"


def test_normaliser_cle():
    # Title markers HF
    assert normaliser_cle("Développeur H/F/X", est_titre=True) == "developpeur"
    assert normaliser_cle("Ingénieur F/H", est_titre=True) == "ingenieur"
    assert normaliser_cle("Consultant hf", est_titre=True) == "consultant"
    # Company juridical forms
    assert normaliser_cle("Acme SAS", est_entreprise=True) == "acme"
    assert normaliser_cle("Tech SARL", est_entreprise=True) == "tech"
    # Group, conseil, services preserved
    assert normaliser_cle("Groupe Conseil SA", est_entreprise=True) == "groupe conseil"


def test_normaliser_cle_compacte():
    k1 = normaliser_cle("back-end", est_titre=True)
    k2 = normaliser_cle("back end", est_titre=True)
    k3 = normaliser_cle("backend", est_titre=True)

    assert normaliser_cle_compacte(k1) == "backend"
    assert normaliser_cle_compacte(k2) == "backend"
    assert normaliser_cle_compacte(k3) == "backend"

    assert normaliser_cle_compacte(normaliser_cle("Développeur Back-End", est_titre=True)) == "developpeurbackend"


def test_extraire_tokens():
    norm = normaliser_cle("développeur de python 500 par", est_titre=True)
    tokens = extraire_tokens(norm)
    # python and developpeur are kept
    assert "developpeur" in tokens
    assert "python" in tokens
    # stop words, numbers, short tokens ignored
    assert "de" not in tokens
    assert "500" not in tokens
    assert "par" not in tokens


def test_charger_free_work_validation(tmp_path):
    f_path = tmp_path / "fw.json"

    # Missing key
    f_path.write_text(json.dumps([{"source": "free_work", "source_id": "1"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="Clé 'title' manquante"):
        charger_free_work(f_path)

    # Wrong source
    f_path.write_text(json.dumps([{"source": "other", "source_id": "1", "title": "A", "location": {}, "matched_rome_queries": []}]), encoding="utf-8")
    with pytest.raises(ValueError, match="Source invalide"):
        charger_free_work(f_path)

    # Duplicate IDs
    item = {"source": "free_work", "source_id": "1", "title": "A", "location": {}, "matched_rome_queries": []}
    f_path.write_text(json.dumps([item, item]), encoding="utf-8")
    with pytest.raises(ValueError, match="dupliqué détecté"):
        charger_free_work(f_path)


def test_charger_france_travail_validation(tmp_path):
    f_path = tmp_path / "ft.json"

    # Missing key
    f_path.write_text(json.dumps([{"france_travail_id": "1"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="Clé 'title' manquante"):
        charger_france_travail(f_path)

    # Duplicate IDs
    item = {"france_travail_id": "1", "title": "A", "description": "B", "rome_code": "M1805"}
    f_path.write_text(json.dumps([item, item]), encoding="utf-8")
    with pytest.raises(ValueError, match="dupliqué détecté"):
        charger_france_travail(f_path)


def test_separation_identifiants(tmp_path):
    fw_file = tmp_path / "fw.json"
    ft_file = tmp_path / "ft.json"

    fw_data = [{
        "source": "free_work",
        "source_id": "SAME_ID_123",
        "title": "A",
        "location": {"postal_code": "31000"},
        "matched_rome_queries": [{"rome_code": "M1805", "query": "Dev"}]
    }]
    ft_data = [{
        "france_travail_id": "SAME_ID_123",
        "title": "Z",
        "description": "Desc Z",
        "rome_code": "M1802"
    }]

    fw_file.write_text(json.dumps(fw_data), encoding="utf-8")
    ft_file.write_text(json.dumps(ft_data), encoding="utf-8")

    with patch("scripts.generate_free_work_match_candidates.PROJECT_ROOT", tmp_path):
        generer_matching(fw_file, ft_file)

    matching_dirs = list((tmp_path / "data" / "processed" / "matching" / "free_work_vs_france_travail").iterdir())
    matches_file = matching_dirs[0] / "candidate_matches.json"
    matches = json.loads(matches_file.read_text(encoding="utf-8"))

    # Check that candidate score is low and not influenced by identical ID string
    cands = matches[0]["top_candidates"]
    if cands:
        assert cands[0]["preliminary_match_score"] < 10.0


def test_matching_idempotency(tmp_path, capsys):
    fw_file = tmp_path / "fw.json"
    ft_file = tmp_path / "ft.json"

    fw_data = [{
        "source": "free_work",
        "source_id": "1",
        "title": "Python Dev",
        "description": "Looking for a Python Developer in Paris.",
        "location": {"postal_code": "75001"},
        "matched_rome_queries": [{"rome_code": "M1805", "query": "Dev"}]
    }]
    ft_data = [{
        "france_travail_id": "FT1",
        "title": "Développeur Python H/F",
        "description": "Nous recherchons un Développeur Python.",
        "rome_code": "M1805",
        "postal_code": "75001"
    }]

    fw_file.write_text(json.dumps(fw_data), encoding="utf-8")
    ft_file.write_text(json.dumps(ft_data), encoding="utf-8")

    # Run 1
    with patch("scripts.generate_free_work_match_candidates.PROJECT_ROOT", tmp_path):
        generer_matching(fw_file, ft_file)
    captured = capsys.readouterr()
    assert "mis à jour" in captured.out

    # Run 2
    with patch("scripts.generate_free_work_match_candidates.PROJECT_ROOT", tmp_path):
        generer_matching(fw_file, ft_file)
    captured = capsys.readouterr()
    assert "inchangé" in captured.out


def test_descriptions_absentes_and_progress_json(tmp_path):
    fw_file = tmp_path / "fw.json"
    ft_file = tmp_path / "ft.json"

    fw_data = [{
        "source": "free_work",
        "source_id": "644334",
        "title": "Python Dev",
        "description": None, # missing description
        "candidate_profile": "Profile...",
        "location": {"postal_code": "75001"},
        "matched_rome_queries": [{"rome_code": "M1805"}]
    }]
    ft_data = [{
        "france_travail_id": "FT1",
        "title": "Développeur Python",
        "description": "Desc Python...",
        "rome_code": "M1805",
        "postal_code": "75001"
    }]

    fw_file.write_text(json.dumps(fw_data), encoding="utf-8")
    ft_file.write_text(json.dumps(ft_data), encoding="utf-8")

    with patch("scripts.generate_free_work_match_candidates.PROJECT_ROOT", tmp_path):
        generer_matching(fw_file, ft_file)

    # Check progress.json was created and is completed
    progress_file = tmp_path / "data" / "processed" / "matching" / "progress.json"
    assert progress_file.exists()
    progress_data = json.loads(progress_file.read_text(encoding="utf-8"))
    assert progress_data["status"] == "COMPLETED"
    assert progress_data["stage"] == "COMPLETED"

    # Read matches output
    matching_dirs = list((tmp_path / "data" / "processed" / "matching" / "free_work_vs_france_travail").iterdir())
    matches_file = matching_dirs[0] / "candidate_matches.json"
    matches = json.loads(matches_file.read_text(encoding="utf-8"))

    assert len(matches) == 1
    cands = matches[0]["top_candidates"]
    assert len(cands) == 1

    # Description missing checks
    assert cands[0]["components"]["description_source"] == "missing"
    assert cands[0]["components"]["description_token_jaccard"] is None
    assert cands[0]["components"]["description_weighted_token_similarity"] is None

    # Evidence coverage should be reduced (no description = -25)
    # Title (45) + PC (15) + ROME (5) = 65 (no company: 0)
    assert cands[0]["evidence_coverage"] == 65

    # Trigrams block is deleted
    assert "TITLE_TRIGRAMS" not in cands[0]["candidate_blocks"]


def test_stabilisation_engine_limits_and_priorities(tmp_path):
    fw_file = tmp_path / "fw.json"
    ft_file = tmp_path / "ft.json"

    # Create 30 FT offers so we can test limits and ordering
    ft_data = []
    for i in range(30):
        ft_data.append({
            "france_travail_id": f"FT{i:02d}",
            "title": f"Dev Python {i}",
            "description": f"Description Python {i}",
            "rome_code": "M1805",
            "postal_code": "75001"
        })

    # Offer with candidates
    fw_data = [
        {
            "source": "free_work",
            "source_id": "1",
            "title": "Dev Python 0",
            "location": {"postal_code": "75001"},
            "matched_rome_queries": [{"rome_code": "M1805"}]
        },
        # Offer without candidates (ROME does not match, title does not share token)
        {
            "source": "free_work",
            "source_id": "2",
            "title": "Java",
            "location": {},
            "matched_rome_queries": [{"rome_code": "M1206"}]
        }
    ]

    fw_file.write_text(json.dumps(fw_data), encoding="utf-8")
    ft_file.write_text(json.dumps(ft_data), encoding="utf-8")

    with patch("scripts.generate_free_work_match_candidates.PROJECT_ROOT", tmp_path):
        generer_matching(fw_file, ft_file)

    # Read matches output
    matching_dirs = list((tmp_path / "data" / "processed" / "matching" / "free_work_vs_france_travail").iterdir())
    matches_file = matching_dirs[0] / "candidate_matches.json"
    matches = json.loads(matches_file.read_text(encoding="utf-8"))

    # Assertions on limits and ordering
    match1 = next(m for m in matches if m["free_work_source_id"] == "1")
    assert len(match1["top_candidates"]) <= 20

    # Check score ordering (descending)
    scores = [c["preliminary_match_score"] for c in match1["top_candidates"]]
    assert scores == sorted(scores, reverse=True)

    # Check review sample prioritization
    review_file = matching_dirs[0] / "review_sample.json"
    review_sample = json.loads(review_file.read_text(encoding="utf-8"))
    # Offer 2 (NO_CANDIDATE) must be present in the review sample
    no_cand_in_review = any(r["free_work_source_id"] == "2" for r in review_sample)
    assert no_cand_in_review


def test_progress_write_robustness_success_after_retry(tmp_path):
    call_count = 0
    original_replace = Path.replace

    def mock_replace(self, target):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise PermissionError("Verrouillé par Windows")
        return original_replace(self, target)

    with patch("scripts.generate_free_work_match_candidates.PROJECT_ROOT", tmp_path), \
         patch("scripts.generate_free_work_match_candidates.time.sleep") as mock_sleep, \
         patch.object(Path, "replace", mock_replace):

        write_progress("TEST_STAGE", 1, 5, 10, "Test message", "RUNNING")

        progress_file = tmp_path / "data" / "processed" / "matching" / "progress.json"
        assert progress_file.exists()
        assert call_count == 3
        assert mock_sleep.call_count == 2


def test_progress_write_robustness_fail_ignored(tmp_path):
    def mock_replace(self, target):
        raise PermissionError("Verrouillé par Windows")

    with patch("scripts.generate_free_work_match_candidates.PROJECT_ROOT", tmp_path), \
         patch("scripts.generate_free_work_match_candidates.time.sleep"), \
         patch.object(Path, "replace", mock_replace):

        # Should not raise any exception, just ignore it and return
        write_progress("TEST_STAGE", 1, 5, 10, "Test message", "RUNNING")

        temp_files = list(tmp_path.glob("**/progress_*.tmp"))
        assert len(temp_files) == 0


def test_progress_write_failed_does_not_mask_original_exception(tmp_path):
    test_args = ["prog", "--free-work-input", str(tmp_path / "fw.json"), "--france-travail-input", str(tmp_path / "ft.json")]

    def mock_replace(self, target):
        raise PermissionError("Verrouillé par Windows")

    with patch("sys.argv", test_args), \
         patch("scripts.generate_free_work_match_candidates.PROJECT_ROOT", tmp_path), \
         patch("scripts.generate_free_work_match_candidates.generer_matching", side_effect=ValueError("Erreur métier")), \
         patch.object(Path, "replace", mock_replace), \
         pytest.raises(SystemExit) as sys_exit:

        main()

    assert sys_exit.value.code == 1
