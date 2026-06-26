import pytest

from backend.scripts.analyze_free_work_ambiguities import (
    AnalysisError,
    build_case_metrics,
    build_clusters,
    build_simulated_probably_new,
    is_simulated_probably_new,
    select_calibration_sample,
    validate_inputs,
)


def make_audit_item(source_id, priority="LOW", reason_codes=None, score=34.0):
    return {
        "free_work": {
            "source_id": str(source_id),
            "source_url": f"https://example.test/fw/{source_id}",
            "title_raw": "Développeur Python confirmé",
            "title_normalized": "developpeur python confirme",
            "company_raw": "Acme",
            "company_normalized": "acme",
            "location_raw": "Paris",
            "postal_code": "75001",
            "published_at": "2026-06-01",
            "description_excerpt": "Mission Python et API.",
            "description_length": 120,
        },
        "triage": {
            "category": "HUMAN_REVIEW_REQUIRED",
            "reason_codes": reason_codes or ["INTERMEDIATE_SCORE"],
            "rule_version": "CONSERVATIVE_RULESET_V1",
            "data_coverage": 95,
            "priority": priority,
        },
        "best_france_travail_candidate": {
            "source_id": "FT-1",
            "source_url": None,
            "title_raw": "Développeur Java",
            "company_raw": "Other",
            "location_raw": "Lyon",
            "postal_code": "69000",
            "published_at": "2026-06-01",
            "description_excerpt": "Mission Java.",
            "score_total": score,
            "score_breakdown": {"title": 10, "description": 2, "company": 0, "geography": 0, "other": 0},
            "evidence": ["Company Match: NO_MATCH", "Geography Match: DIFFERENT"],
            "rank": 1,
        },
        "alternative_candidates": [],
        "human_review": {"decision": "", "selected_france_travail_id": "", "comment": "", "reviewed_at": ""},
        "source_trace": {},
    }


def make_raw_match(source_id, score=34.0, second_score=29.0):
    return {
        "free_work_source_id": str(source_id),
        "top_candidates": [
            {
                "france_travail_id": "FT-1",
                "preliminary_match_score": score,
                "components": {
                    "title_sequence_similarity": 0.3,
                    "description_token_jaccard": 0.1,
                    "description_source": "description",
                },
                "company_comparison": {"match_type": "NO_MATCH"},
                "geography_comparison": {"result": "DIFFERENT"},
                "title_comparison": {"sequence_similarity": 0.3},
                "candidate_blocks": ["SAME_DEPARTMENT_TITLE"],
            },
            {
                "france_travail_id": "FT-2",
                "preliminary_match_score": second_score,
                "components": {"description_source": "description"},
                "company_comparison": {"match_type": "NO_MATCH"},
                "geography_comparison": {"result": "DIFFERENT"},
                "title_comparison": {"sequence_similarity": 0.2},
                "candidate_blocks": [],
            },
        ],
    }


def test_validate_inputs_rejects_duplicate_ids(monkeypatch):
    monkeypatch.setattr("backend.scripts.analyze_free_work_ambiguities.EXPECTED_HUMAN_REVIEW_COUNT", 2)
    monkeypatch.setattr("backend.scripts.analyze_free_work_ambiguities.EXPECTED_PRIORITIES", {"LOW": 2})
    audit = [make_audit_item("1"), make_audit_item("1")]
    prioritized = [make_audit_item("1"), make_audit_item("1")]
    triage = [
        {"free_work_source_id": "1", "triage_category": "HUMAN_REVIEW_REQUIRED"},
        {"free_work_source_id": "1", "triage_category": "HUMAN_REVIEW_REQUIRED"},
    ]

    with pytest.raises(AnalysisError):
        validate_inputs(audit, prioritized, triage)


def test_build_case_metrics_detects_low_signal_probably_new_candidate():
    item = make_audit_item("42")
    case = build_case_metrics(item, make_raw_match("42"))

    assert case["free_work_id"] == "42"
    assert case["best_score"] == 34.0
    assert case["top1_top2_margin"] == 5.0
    assert case["evidence"]["company_incompatible_or_missing"] is True
    assert is_simulated_probably_new(case, "BALANCED") is True
    assert is_simulated_probably_new(case, "CONSERVATIVE") is True


def test_simulated_probably_new_does_not_prefill_human_decision():
    item = make_audit_item("42")
    case = build_case_metrics(item, make_raw_match("42"))
    simulated = build_simulated_probably_new({"42": item}, {"42": make_raw_match("42")}, [case])

    assert len(simulated) == 1
    assert simulated[0]["current_category"] == "HUMAN_REVIEW_REQUIRED"
    assert simulated[0]["simulated_category"] == "PROBABLY_NEW"
    assert "human_decision" not in simulated[0]


def test_clusters_are_deterministic_and_marked_safe_only_when_identical():
    items = {
        "1": make_audit_item("1", score=35.0),
        "2": make_audit_item("2", score=35.5),
        "3": make_audit_item("3", priority="MEDIUM", score=36.0),
    }
    cases = [
        build_case_metrics(items["1"], make_raw_match("1", score=35.0, second_score=30.0)),
        build_case_metrics(items["2"], make_raw_match("2", score=35.5, second_score=30.5)),
        build_case_metrics(items["3"], make_raw_match("3", score=36.0, second_score=31.0)),
    ]

    clusters = build_clusters(items, cases)

    assert clusters["summary"]["group_count"] == 1
    cluster = clusters["clusters"][0]
    assert cluster["member_free_work_ids"] == ["1", "2", "3"]
    assert cluster["safe_for_bulk_review"] is False


def test_calibration_sample_keeps_human_fields_empty():
    item = make_audit_item("42")
    case = build_case_metrics(item, make_raw_match("42"))
    clusters = {"clusters": []}

    sample = select_calibration_sample({"42": item}, [case], clusters, max_size=1)

    assert len(sample) == 1
    assert sample[0]["human_decision"] == ""
    assert sample[0]["human_selected_france_travail_id"] == ""
    assert sample[0]["human_comment"] == ""
    assert sample[0]["reviewed_at"] == ""
    assert sample[0]["reviewer"] == ""
