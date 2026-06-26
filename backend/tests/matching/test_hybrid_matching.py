import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from backend.scripts.matching_normalization import (
    normaliser_entreprise,
    normaliser_localite,
    extraire_departement,
    normaliser_titre
)

from backend.scripts.generate_free_work_match_candidates import (
    match_entreprises,
    match_geographie,
    generer_matching
)


def test_company_normalization():
    # minuscules, accent, legal form, punctuation
    comp1 = normaliser_entreprise("Signe +")
    comp2 = normaliser_entreprise("Signe+")
    assert comp1 == "signe"
    assert comp2 == "signe"

    res, sim = match_entreprises(comp1, comp2)
    assert res == "EXACT_NORMALIZED"

    # Econocom alias (without config aliases)
    c_fw = normaliser_entreprise("ECONOCOM INFOGERANCE ET SYSTEME")
    c_ft = normaliser_entreprise("Econocom")
    res_eco, sim_eco = match_entreprises(c_fw, c_ft)
    assert res_eco == "CONTAINMENT_MATCH"
    assert sim_eco == 0.95

    # Different
    res_diff, sim_diff = match_entreprises("capgemini", "sopra steria")
    assert res_diff == "NO_MATCH"
    assert sim_diff < 0.5


def test_geography_cascade():
    # Exact postal code
    res, _ = match_geographie("92400", "courbevoie", "92", "92400", "courbevoie", "92")
    assert res == "EXACT_POSTAL_CODE"

    # Same locality
    res, _ = match_geographie("92400", "courbevoie", "92", "92300", "courbevoie", "92")
    assert res == "SAME_LOCALITY"

    # Same department
    res, _ = match_geographie("92400", "courbevoie", "92", "92100", "boulogne", "92")
    assert res == "SAME_DEPARTMENT"

    # Different
    res, _ = match_geographie("92400", "courbevoie", "92", "75001", "paris", "75")
    assert res == "DIFFERENT"

    # Unknown
    res, _ = match_geographie("", "", "", "92400", "courbevoie", "92")
    assert res == "UNKNOWN"


def test_hybrid_matching_cascade_sap(tmp_path):
    fw_offer = {
        "source": "free_work",
        "source_id": "606592",
        "title": "Consultant fonctionnel SAP SD/MM",
        "company_name": "Signe +",
        "location": {"postal_code": "69000", "locality": "Lyon"},
        "matched_rome_queries": [{"rome_code": "M1805", "rome_label": "IT", "query": "IT"}],
        "description": "Besoin de consultant fonctionnel SAP SD/MM pour notre équipe."
    }
    ft_candidate = {
        "france_travail_id": "4120490",
        "title": "Consultant fonctionnel SAP SD/MM",
        "company_name": "Signe+",
        "postal_code": "69009",
        "rome_code": "M1805",
        "description": "Nous recrutons un Consultant fonctionnel SAP SD/MM.",
        "work_place_name": "Lyon"
    }

    fw_file = tmp_path / "fw.json"
    ft_file = tmp_path / "ft.json"

    fw_file.write_text(json.dumps([fw_offer]), encoding="utf-8")
    ft_file.write_text(json.dumps([ft_candidate]), encoding="utf-8")

    with patch("backend.scripts.generate_free_work_match_candidates.PROCESSED_DATA_ROOT", tmp_path / "backend" / "data" / "processed"), \
         patch("backend.scripts.generate_free_work_match_candidates.time.sleep"):
        generer_matching(fw_file, ft_file, strategy="hybrid_cascade", use_aliases=False)

    # Let's inspect output candidate_matches.json
    matching_dirs = list((tmp_path / "backend" / "data" / "processed" / "matching" / "free_work_vs_france_travail").glob("*_hybrid_cascade"))
    assert not (tmp_path / "data").exists()
    assert len(matching_dirs) == 1

    matches_file = matching_dirs[0] / "candidate_matches.json"
    assert matches_file.exists()
    matches_data = json.loads(matches_file.read_text(encoding="utf-8"))

    assert len(matches_data) == 1
    offer_match = matches_data[0]
    assert offer_match["free_work_source_id"] == "606592"
    assert len(offer_match["top_candidates"]) == 1

    best_cand = offer_match["top_candidates"][0]
    assert best_cand["france_travail_id"] == "4120490"
    assert best_cand["company_comparison"]["match_type"] == "EXACT_NORMALIZED"
    assert best_cand["geography_comparison"]["result"] == "SAME_LOCALITY"
    assert "PRIMARY_CHAIN" in best_cand["candidate_generation_paths"]
