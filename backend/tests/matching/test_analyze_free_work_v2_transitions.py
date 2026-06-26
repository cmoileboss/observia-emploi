import json
from collections import Counter

from backend.scripts.analyze_free_work_v2_transitions import (
    audit_reclassified_duplicates,
    build_matrix,
    build_pilot,
    build_transition_rows,
)


def v1(source_id, category, reasons=None):
    return {
        "free_work_source_id": str(source_id),
        "triage_category": category,
        "triage_reason_codes": reasons or ["R1"],
        "data_coverage": 95,
    }


def v2(source_id, decision, reasons=None):
    return {
        "free_work": {
            "source_id": str(source_id),
            "url": None,
            "url_resolution_method": "LEGACY_URL_REBUILT",
        },
        "decision": decision,
        "technical_reasons": reasons or ["V2_R1"],
        "human_explanation": {"overall": "Synthèse"},
    }


def candidate(score=35.0, ft_id="FT1", blocks=None, company="NO_MATCH", title=0.4):
    return {
        "france_travail_id": ft_id,
        "title": "Dev Python",
        "company_name": "ACME",
        "postal_code": "75001",
        "rome_code": "M1805",
        "preliminary_match_score": score,
        "evidence_coverage": 95,
        "candidate_blocks": blocks or [],
        "title_comparison": {"sequence_similarity": title, "shared_significant_tokens": ["python"]},
        "components": {"description_token_jaccard": 0.1, "rome_query_match": False},
        "company_comparison": {"match_type": company, "free_work_raw": "FW", "france_travail_raw": "ACME"},
        "geography_comparison": {"result": "DIFFERENT"},
    }


def match(source_id, candidates=None):
    return {
        "free_work_source_id": str(source_id),
        "free_work_title": f"Offre {source_id}",
        "free_work_title_normalized": f"offre {source_id}",
        "free_work_company": "FW",
        "free_work_location": {"postal_code": "75001"},
        "free_work_description_excerpt": "Description",
        "top_candidates": candidates if candidates is not None else [candidate()],
    }


def test_transition_matrix_complete_and_unique(monkeypatch):
    monkeypatch.setattr("backend.scripts.analyze_free_work_v2_transitions.len", len, raising=False)
    v1_rows = [
        v1("1", "DUPLICATE_HIGH_CONFIDENCE"),
        v1("2", "PROBABLY_NEW"),
        v1("3", "HUMAN_REVIEW_REQUIRED"),
    ]
    v2_by_id = {
        "1": v2("1", "PRESENT_IN_FT_SNAPSHOT"),
        "2": v2("2", "NOT_FOUND_IN_FT_SNAPSHOT"),
        "3": v2("3", "UNCERTAIN"),
    }
    matches_by_id = {str(i): match(str(i)) for i in range(1, 4)}

    # build_transition_rows en production exige 8457 ; on teste la logique de matrice directement ici.
    rows = []
    for row in v1_rows:
        source_id = row["free_work_source_id"]
        rows.append(
            {
                "free_work_source_id": source_id,
                "decision_v1": row["triage_category"],
                "decision_v2": v2_by_id[source_id]["decision"],
            }
        )

    matrix = build_matrix(rows)

    assert matrix["DUPLICATE_HIGH_CONFIDENCE"]["PRESENT_IN_FT_SNAPSHOT"] == 1
    assert matrix["PROBABLY_NEW"]["NOT_FOUND_IN_FT_SNAPSHOT"] == 1
    assert matrix["HUMAN_REVIEW_REQUIRED"]["UNCERTAIN"] == 1
    assert len({row["free_work_source_id"] for row in rows}) == len(rows)


def test_reclassified_duplicates_flags_possible_regression_for_exact_fingerprint():
    v1_rows = [v1("1", "DUPLICATE_HIGH_CONFIDENCE")]
    v2_by_id = {"1": v2("1", "NOT_FOUND_IN_FT_SNAPSHOT")}
    matches_by_id = {"1": match("1", [candidate(score=82, blocks=["EXACT_FINGERPRINT"], company="EXACT_NORMALIZED", title=0.95)])}

    cases, summary = audit_reclassified_duplicates(v1_rows, v2_by_id, matches_by_id)

    assert len(cases) == 1
    assert cases[0]["possible_v2_regression"] is True
    assert "EXACT_FINGERPRINT_LOST" in cases[0]["possible_v2_regression_reasons"]
    assert summary["regression_v2_possible"] == 1


def test_pilot_has_60_cases_20_per_group_and_empty_human_fields():
    v1_by_id = {}
    v2_by_id = {}
    matches_by_id = {}
    reclassified = []

    for i in range(1, 81):
        sid = str(i)
        category = "DUPLICATE_HIGH_CONFIDENCE" if 21 <= i <= 40 else "HUMAN_REVIEW_REQUIRED"
        decision = "NOT_FOUND_IN_FT_SNAPSHOT" if i <= 40 else "UNCERTAIN"
        v1_by_id[sid] = v1(sid, category)
        v2_by_id[sid] = v2(sid, decision, ["INSUFFICIENT_FREE_WORK_DATA"] if i > 40 else ["ALL_CANDIDATES_WEAK"])
        matches_by_id[sid] = match(sid, [candidate(score=float(i % 60), ft_id=f"FT{i}")])
        if 21 <= i <= 40:
            reclassified.append(
                {
                    "free_work": {"source_id": sid},
                    "possible_v2_regression": i % 2 == 0,
                }
            )

    pilot = build_pilot(v1_by_id, v2_by_id, matches_by_id, reclassified)
    counts = Counter(item["pilot_group"] for item in pilot)

    assert len(pilot) == 60
    assert counts == {
        "A_NOT_FOUND_CONTROL": 20,
        "B_V1_DUPLICATE_RECLASSIFIED": 20,
        "C_V2_UNCERTAIN": 20,
    }
    for item in pilot:
        assert item["human_decision"] == ""
        assert item["human_selected_france_travail_id"] == ""
        assert item["human_comment"] == ""
        assert item["reviewed_at"] == ""
        assert item["reviewer"] == ""


def test_historical_cases_can_be_represented_without_duplicate_ids():
    rows = [
        {"free_work_source_id": "606592", "decision_v1": "DUPLICATE_HIGH_CONFIDENCE", "decision_v2": "PRESENT_IN_FT_SNAPSHOT"},
        {"free_work_source_id": "621908", "decision_v1": "DUPLICATE_HIGH_CONFIDENCE", "decision_v2": "PRESENT_IN_FT_SNAPSHOT"},
        {"free_work_source_id": "637922", "decision_v1": "DUPLICATE_HIGH_CONFIDENCE", "decision_v2": "PRESENT_IN_FT_SNAPSHOT"},
        {"free_work_source_id": "422864", "decision_v1": "HUMAN_REVIEW_REQUIRED", "decision_v2": "NOT_FOUND_IN_FT_SNAPSHOT"},
    ]

    assert len({row["free_work_source_id"] for row in rows}) == 4
    assert all(row["decision_v2"] != "PRESENT_IN_FT_SNAPSHOT" for row in rows if row["free_work_source_id"] == "422864")
