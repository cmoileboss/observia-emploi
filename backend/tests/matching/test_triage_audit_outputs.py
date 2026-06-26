import json
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = PROJECT_ROOT / "backend" / "data" / "processed" / "matching" / "free_work_vs_france_travail" / "run_triage_full_20260624"

@pytest.fixture(scope="module")
def audit_data():
    master_path = RUN_DIR / "audit_results.json"
    assert master_path.exists(), "master file audit_results.json must exist"
    with master_path.open("r", encoding="utf-8") as f:
        return json.load(f)

def test_master_structure(audit_data):
    # Check structure of the first entry
    assert len(audit_data) > 0
    entry = audit_data[0]
    
    assert "free_work" in entry
    fw = entry["free_work"]
    assert "source_id" in fw
    assert "source_url" in fw
    assert "title_raw" in fw
    assert "title_normalized" in fw
    assert "company_raw" in fw
    assert "company_normalized" in fw
    assert "location_raw" in fw
    assert "locality_normalized" in fw
    assert "postal_code" in fw
    assert "department_code" in fw
    assert "published_at" in fw
    assert "description_excerpt" in fw
    assert "description_length" in fw
    
    assert "triage" in entry
    tr = entry["triage"]
    assert "category" in tr
    assert "reason_codes" in tr
    assert "rule_version" in tr
    assert "data_coverage" in tr
    assert "human_explanation" in tr
    
    assert "human_review" in entry
    hr = entry["human_review"]
    assert hr["decision"] == ""
    assert hr["selected_france_travail_id"] == ""
    assert hr["comment"] == ""
    assert hr["reviewed_at"] == ""
    
    assert "source_trace" in entry
    st = entry["source_trace"]
    assert st["triage_run_id"] == "run_triage_full_20260624"
    assert st["matching_run_id"] == "run_triage_full_20260624"

def test_counters_coherence(audit_data):
    total = len(audit_data)
    assert total == 8457
    
    counters = {
        "DUPLICATE_HIGH_CONFIDENCE": 0,
        "PROBABLY_NEW": 0,
        "HUMAN_REVIEW_REQUIRED": 0,
        "PROCESSING_ERROR": 0
    }
    
    for x in audit_data:
        counters[x["triage"]["category"]] += 1
        
    assert counters["DUPLICATE_HIGH_CONFIDENCE"] == 229
    assert counters["PROBABLY_NEW"] == 1831
    assert counters["HUMAN_REVIEW_REQUIRED"] == 6397
    assert counters["PROCESSING_ERROR"] == 0

def test_uniqueness_and_no_double_categorization(audit_data):
    fw_ids = [x["free_work"]["source_id"] for x in audit_data]
    assert len(fw_ids) == 8457
    assert len(set(fw_ids)) == 8457

def test_champs_humains_vides(audit_data):
    for x in audit_data:
        hr = x["human_review"]
        assert hr["decision"] == ""
        assert hr["selected_france_travail_id"] == ""
        assert hr["comment"] == ""
        assert hr["reviewed_at"] == ""

def test_prioritized_queue_structure():
    pq_path = RUN_DIR / "human_review_queue_prioritized.json"
    assert pq_path.exists()
    with pq_path.open("r", encoding="utf-8") as f:
        pq = json.load(f)
        
    assert len(pq) == 6397
    
    # Check sorting order: HIGH -> MEDIUM -> LOW
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    current_priority_val = 0
    
    for idx, item in enumerate(pq):
        p = item["triage"]["priority"]
        assert p in ["HIGH", "MEDIUM", "LOW"]
        p_val = priority_order[p]
        assert p_val >= current_priority_val, "Queue must be sorted by priority HIGH -> MEDIUM -> LOW"
        current_priority_val = p_val
        
        # Check that top_candidates counts are correct
        assert item["triage"]["category"] == "HUMAN_REVIEW_REQUIRED"
        cands_count = len(item["alternative_candidates"]) + (1 if item["best_france_travail_candidate"] else 0)
        assert cands_count <= 5

def test_no_invented_urls(audit_data):
    # Verify that we do not generate artificial urls (they must either be present from the inputs or null)
    # France Travail url should only be present if source_url was provided
    for x in audit_data:
        best = x["best_france_travail_candidate"]
        if best:
            url = best["source_url"]
            if url is not None:
                assert url.startswith("http") or url == ""
        for alt in x["alternative_candidates"]:
            url = alt["source_url"]
            if url is not None:
                assert url.startswith("http") or url == ""

def test_determinism(audit_data):
    # Running sorting or retrieval must be deterministic
    fw_ids = [x["free_work"]["source_id"] for x in audit_data]
    # Check that it's sorted or matching order
    # Our master file lists them in order of the input offers (which was sorted by source_id)
    assert fw_ids == sorted(fw_ids, key=lambda x: str(x))

def test_utf8_encoding():
    # Verify all generated json files can be parsed as UTF-8
    files = [
        "audit_results.json",
        "audit_duplicates_high_confidence.json",
        "audit_probably_new.json",
        "audit_human_review_required.json",
        "audit_processing_errors.json",
        "human_review_queue_prioritized.json",
        "manual_check_sample.json",
        "audit_manifest.json"
    ]
    for filename in files:
        filepath = RUN_DIR / filename
        assert filepath.exists()
        # Should load without UnicodeDecodeError
        with filepath.open("r", encoding="utf-8") as f:
            json.load(f)
