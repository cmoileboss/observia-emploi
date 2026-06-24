import json
import pytest
from pathlib import Path
from scripts.triage_free_work_matches import classify_triage

def test_triage_exact_fingerprint():
    fw_item = {"title": "Python Developer", "description": "Looking for Python dev", "company_name": "Acme", "location": {"postal_code": "75001"}}
    best_cand = {
        "preliminary_match_score": 90.0,
        "components": {},
        "company_comparison": {"match_type": "EXACT_NORMALIZED", "similarity": 1.0},
        "geography_comparison": {"result": "EXACT_POSTAL_CODE"},
        "title_comparison": {"sequence_similarity": 1.0},
        "candidate_blocks": ["EXACT_FINGERPRINT"]
    }
    category, reasons = classify_triage(fw_item, best_cand, None, 1, ["python", "developper"], "looking for python dev", "acme", "75001", "75", "paris", [])
    assert category == "DUPLICATE_HIGH_CONFIDENCE"
    assert "EXACT_FINGERPRINT" in reasons

def test_triage_exact_title_company_geography():
    fw_item = {"title": "Python Developer", "description": "Looking for Python dev", "company_name": "Acme", "location": {"postal_code": "75001"}}
    best_cand = {
        "preliminary_match_score": 85.0,
        "components": {},
        "company_comparison": {"match_type": "ALIAS_MATCH", "similarity": 1.0},
        "geography_comparison": {"result": "SAME_LOCALITY"},
        "title_comparison": {"sequence_similarity": 0.9},
        "candidate_blocks": ["COMPACT_TITLE_EXACT"]
    }
    category, reasons = classify_triage(fw_item, best_cand, None, 1, ["python", "developper"], "looking for python dev", "acme", "75001", "75", "paris", [])
    assert category == "DUPLICATE_HIGH_CONFIDENCE"
    assert "EXACT_TITLE_COMPANY_GEOGRAPHY" in reasons

def test_triage_postal_code_only_not_duplicate():
    fw_item = {"title": "Python Developer", "description": "Looking for Python dev", "company_name": "Acme", "location": {"postal_code": "75001"}}
    best_cand = {
        "preliminary_match_score": 25.0, # low title/company similarity
        "components": {},
        "company_comparison": {"match_type": "NO_MATCH", "similarity": 0.1},
        "geography_comparison": {"result": "EXACT_POSTAL_CODE"},
        "title_comparison": {"sequence_similarity": 0.2},
        "candidate_blocks": ["EXACT_POSTAL_CODE"]
    }
    category, reasons = classify_triage(fw_item, best_cand, None, 1, ["python", "developper"], "looking for python dev", "acme", "75001", "75", "paris", [])
    assert category == "PROBABLY_NEW"

def test_triage_rome_only_not_duplicate():
    fw_item = {"title": "Python Developer", "description": "Looking for Python dev", "company_name": "Acme", "location": {"postal_code": "75001"}}
    best_cand = {
        "preliminary_match_score": 20.0,
        "components": {},
        "company_comparison": {"match_type": "NO_MATCH", "similarity": 0.0},
        "geography_comparison": {"result": "DIFFERENT"},
        "title_comparison": {"sequence_similarity": 0.1},
        "candidate_blocks": ["ROME_QUERY_TITLE"]
    }
    category, reasons = classify_triage(fw_item, best_cand, None, 1, ["python", "developper"], "looking for python dev", "acme", "75001", "75", "paris", [])
    assert category == "PROBABLY_NEW"

def test_triage_probably_new():
    fw_item = {"title": "Python Developer", "description": "Looking for Python dev", "company_name": "Acme", "location": {"postal_code": "75001"}}
    best_cand = {
        "preliminary_match_score": 15.0,
        "components": {},
        "company_comparison": {"match_type": "NO_MATCH", "similarity": 0.0},
        "geography_comparison": {"result": "DIFFERENT"},
        "title_comparison": {"sequence_similarity": 0.1},
        "candidate_blocks": []
    }
    category, reasons = classify_triage(fw_item, best_cand, None, 1, ["python", "developper"], "looking for python dev", "acme", "75001", "75", "paris", [])
    assert category == "PROBABLY_NEW"
    assert "LOW_BEST_SCORE" in reasons

def test_triage_missing_data_human_review():
    # Missing description and metadata
    fw_item = {"title": "Python Developer", "description": None, "company_name": None, "location": None}
    category, reasons = classify_triage(fw_item, None, None, 0, ["python", "developper"], "", "", "", "", "", [])
    assert category == "HUMAN_REVIEW_REQUIRED"
    assert "MISSING_DESC_AND_META" in reasons

def test_triage_ambiguous_scores_human_review():
    fw_item = {"title": "Python Developer", "description": "Looking for Python dev", "company_name": "Acme", "location": {"postal_code": "75001"}}
    best_cand = {
        "preliminary_match_score": 65.0,
        "components": {},
        "company_comparison": {"match_type": "NO_MATCH", "similarity": 0.0},
        "geography_comparison": {"result": "EXACT_POSTAL_CODE"},
        "title_comparison": {"sequence_similarity": 0.6},
        "candidate_blocks": []
    }
    second_cand = {
        "preliminary_match_score": 62.0,
        "components": {},
        "company_comparison": {"match_type": "NO_MATCH", "similarity": 0.0},
        "geography_comparison": {"result": "EXACT_POSTAL_CODE"},
        "title_comparison": {"sequence_similarity": 0.5},
        "candidate_blocks": []
    }
    category, reasons = classify_triage(fw_item, best_cand, second_cand, 2, ["python", "developper"], "looking for python dev", "acme", "75001", "75", "paris", [])
    assert category == "HUMAN_REVIEW_REQUIRED"
    assert "AMBIGUOUS_SCORE_MARGIN" in reasons

def test_triage_company_match_geo_differs():
    fw_item = {"title": "Python Developer", "description": "Looking for Python dev", "company_name": "Acme", "location": {"postal_code": "75001"}}
    best_cand = {
        "preliminary_match_score": 55.0,
        "components": {},
        "company_comparison": {"match_type": "EXACT_NORMALIZED", "similarity": 1.0},
        "geography_comparison": {"result": "DIFFERENT"},
        "title_comparison": {"sequence_similarity": 0.5},
        "candidate_blocks": []
    }
    category, reasons = classify_triage(fw_item, best_cand, None, 1, ["python", "developper"], "looking for python dev", "acme", "75001", "75", "paris", [])
    assert category == "HUMAN_REVIEW_REQUIRED"
    assert "COMPANY_MATCH_GEO_DIFFERS" in reasons

def test_triage_non_regression_cases():
    # SAP / Signe+ -> EXACT_TITLE_COMPANY_LOCALITY or EXACT_FINGERPRINT
    fw_item = {"title": "Consultant fonctionnel SAP SD/MM", "description": "SAP", "company_name": "Signe +", "location": {"postal_code": "69000"}}
    best_cand = {
        "preliminary_match_score": 85.14,
        "components": {"title_sequence_similarity": 1.0},
        "company_comparison": {"match_type": "EXACT_NORMALIZED", "similarity": 1.0},
        "geography_comparison": {"result": "SAME_LOCALITY"},
        "title_comparison": {"sequence_similarity": 1.0},
        "candidate_blocks": ["COMPACT_TITLE_EXACT"]
    }
    category, reasons = classify_triage(fw_item, best_cand, None, 1, ["consultant", "fonctionnel", "sap", "sd", "mm"], "sap", "signe", "69000", "69", "lyon", [])
    assert category == "DUPLICATE_HIGH_CONFIDENCE"

    # IAM / comptabilité -> Never high confidence duplicate
    fw_item_iam = {"title": "Consultant IAM", "description": "IAM", "company_name": "EMGS GROUP", "location": {"postal_code": "92400"}}
    best_cand_iam = {
        "preliminary_match_score": 37.05,
        "components": {"title_sequence_similarity": 0.1},
        "company_comparison": {"match_type": "NO_MATCH", "similarity": 0.0},
        "geography_comparison": {"result": "EXACT_POSTAL_CODE"},
        "title_comparison": {"sequence_similarity": 0.1},
        "candidate_blocks": ["SAME_DEPARTMENT_TITLE"]
    }
    category_iam, reasons_iam = classify_triage(fw_item_iam, best_cand_iam, None, 1, ["consultant", "iam"], "iam", "emgs group", "92400", "92", "courbevoie", [])
    assert category_iam == "HUMAN_REVIEW_REQUIRED" or category_iam == "PROBABLY_NEW"
    assert category_iam != "DUPLICATE_HIGH_CONFIDENCE"
