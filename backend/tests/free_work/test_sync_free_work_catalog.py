import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

import backend.scripts.sync_free_work_catalog as sync_module
from backend.scripts.sync_free_work_catalog import business_hash, sync_catalog


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_offer(source_id, title="Developpeur Python", skills=None, raw_hash="raw-1", source_url="https://example.test/a"):
    return {
        "source": "free_work",
        "source_id": str(source_id),
        "source_url": source_url,
        "source_url_raw": source_url,
        "source_url_resolution_method": "absolute",
        "matched_rome_queries": [{"rome_code": "M1805", "query": "python"}],
        "title": title,
        "description": "Mission backend Python.",
        "candidate_profile": "Profil autonome.",
        "company_description": "Editeur logiciel.",
        "company_name": "ObservIA",
        "location": {"locality": "Lille", "postal_code": "59000", "region": "Hauts-de-France", "country": "France"},
        "contracts": ["permanent"],
        "skills": skills
        if skills is not None
        else [
            {
                "source_skill_id": "2",
                "source_ref": "/skills/2",
                "name": "Django",
                "name_normalized": "django",
                "slug": "django",
                "displayed": True,
            },
            {
                "source_skill_id": "1",
                "source_ref": "/skills/1",
                "name": "Python",
                "name_normalized": "python",
                "slug": "python",
                "displayed": True,
            },
        ],
        "soft_skills": [],
        "remote_mode": "partial",
        "experience_level": "intermediate",
        "salary": {"annual_min": 45000, "annual_max": 50000, "daily_min": None, "daily_max": None, "currency": "EUR"},
        "published_at": "2026-01-01T00:00:00+01:00",
        "updated_at": "2026-01-02T00:00:00+01:00",
        "expires_at": "2026-03-01T00:00:00+01:00",
        "raw_payload_sha256": raw_hash,
    }


def make_batch(tmp_path, name="batch_a", complete=True):
    batch_dir = tmp_path / "raw" / name
    batch_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        batch_dir / "collection_manifest.json",
        {
            "batch_id": name,
            "status": "COMPLETED" if complete else "PARTIAL",
            "pages_failed": 0 if complete else 1,
            "pages_requested": 2,
            "pages_succeeded": 2 if complete else 1,
        },
    )
    write_json(batch_dir / "failed_pages.json", [] if complete else [{"page": 2}])
    write_json(batch_dir / "resume_state.json", {"batch_id": name, "next_page_url": None if complete else "https://next"})
    return batch_dir


def write_snapshot(tmp_path, offers, name):
    path = tmp_path / "snapshots" / name / "offers_normalized.json"
    write_json(path, offers)
    return path


def run_sync(tmp_path, catalog_root, offers, run_id, batch_dir=None):
    input_path = write_snapshot(tmp_path, offers, run_id)
    return sync_catalog(
        normalized_input=input_path,
        collection_batch_dir=batch_dir or make_batch(tmp_path, run_id),
        catalog_root=catalog_root,
        run_id=run_id,
    )


def assert_counts(manifest, **expected):
    counts = manifest["counts"]
    for key, value in expected.items():
        assert counts[key] == value


def test_bootstrap_marks_all_offers_new(tmp_path):
    catalog_root = tmp_path / "catalog"
    manifest = run_sync(tmp_path, catalog_root, [make_offer("1"), make_offer("2")], "run_1")

    assert_counts(manifest, NEW=2, UPDATED=0, UNCHANGED=0, REACTIVATED=0, INACTIVATED=0)
    assert len(read_json(catalog_root / "current" / "catalog_state.json")) == 2
    assert len(read_json(catalog_root / "current" / "offers_active.json")) == 2
    assert len(read_json(catalog_root / "runs" / "run_1" / "new_offers.json")) == 2


def test_second_identical_snapshot_is_unchanged(tmp_path):
    catalog_root = tmp_path / "catalog"
    offers = [make_offer("1"), make_offer("2")]
    run_sync(tmp_path, catalog_root, offers, "run_1")
    manifest = run_sync(tmp_path, catalog_root, offers, "run_2")

    assert_counts(manifest, NEW=0, UPDATED=0, UNCHANGED=2, REACTIVATED=0, INACTIVATED=0)
    assert read_json(catalog_root / "runs" / "run_2" / "unchanged_offer_ids.json") == ["1", "2"]
    assert (catalog_root / "runs" / "run_2" / "change_log.jsonl").read_text(encoding="utf-8") == ""


def test_adding_offer_is_new(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1")], "run_1")
    manifest = run_sync(tmp_path, catalog_root, [make_offer("1"), make_offer("2")], "run_2")

    assert_counts(manifest, NEW=1, UPDATED=0, UNCHANGED=1, REACTIVATED=0, INACTIVATED=0)


def test_business_modification_is_updated_with_changed_fields(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1")], "run_1")
    changed = make_offer("1", title="Lead Python")
    manifest = run_sync(tmp_path, catalog_root, [changed], "run_2")

    assert_counts(manifest, NEW=0, UPDATED=1, UNCHANGED=0, REACTIVATED=0, INACTIVATED=0)
    updated = read_json(catalog_root / "runs" / "run_2" / "updated_offers.json")
    assert updated[0]["changed_fields"] == ["title"]
    log_line = (catalog_root / "runs" / "run_2" / "change_log.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(log_line)["changed_fields"] == ["title"]


def test_skill_order_does_not_update(tmp_path):
    catalog_root = tmp_path / "catalog"
    offer = make_offer("1")
    run_sync(tmp_path, catalog_root, [offer], "run_1")
    reordered = make_offer("1", skills=list(reversed(offer["skills"])))
    manifest = run_sync(tmp_path, catalog_root, [reordered], "run_2")

    assert_counts(manifest, NEW=0, UPDATED=0, UNCHANGED=1, REACTIVATED=0, INACTIVATED=0)
    assert business_hash(offer) == business_hash(reordered)


def test_technical_metadata_is_ignored_by_hash(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1")], "run_1")
    technical_change = make_offer("1", raw_hash="raw-2", source_url="https://example.test/other")
    technical_change["matched_rome_queries"] = [{"rome_code": "M1802", "query": "other"}]
    manifest = run_sync(tmp_path, catalog_root, [technical_change], "run_2")

    assert_counts(manifest, NEW=0, UPDATED=0, UNCHANGED=1, REACTIVATED=0, INACTIVATED=0)


def test_disappearance_inactivates_only_when_collection_complete(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1"), make_offer("2")], "run_1")
    manifest = run_sync(tmp_path, catalog_root, [make_offer("1")], "run_2")

    assert_counts(manifest, NEW=0, UPDATED=0, UNCHANGED=1, REACTIVATED=0, INACTIVATED=1)
    inactive = read_json(catalog_root / "runs" / "run_2" / "offers_to_deactivate.json")
    assert inactive[0]["free_work_id"] == "2"
    state = read_json(catalog_root / "current" / "catalog_state.json")
    assert [entry for entry in state if entry["free_work_id"] == "2"][0]["is_active"] is False


def test_incomplete_collection_refuses_inactivation_and_keeps_current_unchanged(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1"), make_offer("2")], "run_1")
    before = read_json(catalog_root / "current" / "catalog_state.json")
    incomplete_batch = make_batch(tmp_path, "incomplete", complete=False)
    input_path = write_snapshot(tmp_path, [make_offer("1")], "run_2")

    with pytest.raises(ValueError, match="Collection is not complete"):
        sync_catalog(input_path, incomplete_batch, catalog_root, "run_2")

    after = read_json(catalog_root / "current" / "catalog_state.json")
    assert after == before
    assert read_json(catalog_root / "runs" / "run_2" / "sync_progress.json")["status"] == "FAILED"


def test_reactivated_offer_returns_to_active(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1")], "run_1")
    run_sync(tmp_path, catalog_root, [], "run_2")
    manifest = run_sync(tmp_path, catalog_root, [make_offer("1")], "run_3")

    assert_counts(manifest, NEW=0, UPDATED=0, UNCHANGED=0, REACTIVATED=1, INACTIVATED=0)
    state = read_json(catalog_root / "current" / "catalog_state.json")
    assert state[0]["is_active"] is True
    assert state[0]["inactive_since"] is None


def test_reactivated_with_content_changed_records_fields(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1")], "run_1")
    run_sync(tmp_path, catalog_root, [], "run_2")
    manifest = run_sync(tmp_path, catalog_root, [make_offer("1", title="Lead Python")], "run_3")

    assert_counts(manifest, NEW=0, UPDATED=0, UNCHANGED=0, REACTIVATED=1, INACTIVATED=0)
    reactivated = read_json(catalog_root / "runs" / "run_3" / "reactivated_offers.json")
    assert reactivated[0]["content_changed_on_reactivation"] is True
    assert reactivated[0]["changed_fields_on_reactivation"] == ["title"]


def test_duplicate_ids_are_refused(tmp_path):
    catalog_root = tmp_path / "catalog"
    input_path = write_snapshot(tmp_path, [make_offer("1"), make_offer("1")], "run_1")

    with pytest.raises(ValueError, match="Duplicate Free-Work source_id"):
        sync_catalog(input_path, make_batch(tmp_path, "run_1"), catalog_root, "run_1")


def test_invalid_json_is_refused(tmp_path):
    catalog_root = tmp_path / "catalog"
    input_path = tmp_path / "bad.json"
    input_path.write_text("{bad", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON file"):
        sync_catalog(input_path, make_batch(tmp_path, "run_1"), catalog_root, "run_1")


def test_non_empty_run_directory_is_refused(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_dir = catalog_root / "runs" / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "existing.txt").write_text("x", encoding="utf-8")
    input_path = write_snapshot(tmp_path, [make_offer("1")], "run_1")

    with pytest.raises(ValueError, match="Run directory already exists"):
        sync_catalog(input_path, make_batch(tmp_path, "run_1"), catalog_root, "run_1")


def test_current_catalog_unchanged_when_invariant_error_occurs_before_promotion(tmp_path, monkeypatch):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1")], "run_1")
    before = read_json(catalog_root / "current" / "catalog_state.json")

    def fail_invariants(next_state, buckets, next_offers):
        raise ValueError("forced invariant failure")

    monkeypatch.setattr(sync_module, "validate_invariants", fail_invariants)
    with pytest.raises(ValueError, match="forced invariant failure"):
        run_sync(tmp_path, catalog_root, [make_offer("1", title="Lead Python")], "run_2")

    after = read_json(catalog_root / "current" / "catalog_state.json")
    assert after == before


def test_counters_worksets_active_uniqueness_and_hash_determinism(tmp_path):
    catalog_root = tmp_path / "catalog"
    run_sync(tmp_path, catalog_root, [make_offer("1"), make_offer("2")], "run_1")
    manifest = run_sync(tmp_path, catalog_root, [make_offer("1", title="Lead Python"), make_offer("3")], "run_2")

    assert_counts(manifest, NEW=1, UPDATED=1, UNCHANGED=0, REACTIVATED=0, INACTIVATED=1)
    assert manifest["offers_to_process"] == 2
    assert manifest["offers_to_deactivate"] == 1

    active = read_json(catalog_root / "current" / "offers_active.json")
    active_ids = [offer["source_id"] for offer in active]
    assert active_ids == ["1", "3"]
    assert len(active_ids) == len(set(active_ids))
    assert business_hash(make_offer("1")) == business_hash(make_offer("1"))


def test_sync_is_deterministic_for_same_business_snapshot(tmp_path):
    catalog_a = tmp_path / "catalog_a"
    catalog_b = tmp_path / "catalog_b"
    offers = [make_offer("2"), make_offer("1")]
    manifest_a = run_sync(tmp_path, catalog_a, offers, "run_1")
    manifest_b = run_sync(tmp_path, catalog_b, list(reversed(offers)), "run_1")

    assert manifest_a["counts"] == manifest_b["counts"]
    state_a = read_json(catalog_a / "current" / "catalog_state.json")
    state_b = read_json(catalog_b / "current" / "catalog_state.json")
    assert [entry["free_work_id"] for entry in state_a] == [entry["free_work_id"] for entry in state_b]
    assert [entry["content_hash"] for entry in state_a] == [entry["content_hash"] for entry in state_b]


def test_script_uses_no_network_or_database_imports():
    source = Path(sync_module.__file__).read_text(encoding="utf-8")
    forbidden_tokens = ["requests", "psycopg", "sqlalchemy", "create_engine", "Session"]
    for token in forbidden_tokens:
        assert token not in source


def test_small_integration_three_snapshots(tmp_path):
    catalog_root = tmp_path / "catalog"
    first = run_sync(tmp_path, catalog_root, [make_offer("1"), make_offer("2")], "run_1")
    second = run_sync(tmp_path, catalog_root, [make_offer("1", title="Lead Python"), make_offer("3")], "run_2")
    third = run_sync(tmp_path, catalog_root, [make_offer("1", title="Lead Python"), make_offer("2"), make_offer("3")], "run_3")

    assert_counts(first, NEW=2, UPDATED=0, UNCHANGED=0, REACTIVATED=0, INACTIVATED=0)
    assert_counts(second, NEW=1, UPDATED=1, UNCHANGED=0, REACTIVATED=0, INACTIVATED=1)
    assert_counts(third, NEW=0, UPDATED=0, UNCHANGED=2, REACTIVATED=1, INACTIVATED=0)
    assert len(read_json(catalog_root / "current" / "offers_active.json")) == 3


def test_new_manifest_fields_and_modes(tmp_path):
    catalog_root = tmp_path / "catalog"

    # 1. First run: BOOTSTRAP
    offers_1 = [make_offer("1"), make_offer("2")]
    batch_dir_1 = make_batch(tmp_path, "run_1")
    # write a mock normalization_manifest.json in the parent directory of normalized input
    input_path_1 = write_snapshot(tmp_path, offers_1, "run_1")
    write_json(input_path_1.parent / "normalization_manifest.json", {"normalization_schema_version": 1})

    manifest_1 = sync_catalog(
        normalized_input=input_path_1,
        collection_batch_dir=batch_dir_1,
        catalog_root=catalog_root,
        run_id="run_1",
    )

    assert manifest_1["sync_schema_version"] == 1
    assert manifest_1["schema_version"] == 1
    assert manifest_1["mode"] == "BOOTSTRAP"
    assert manifest_1["status"] == "COMPLETED"
    assert isinstance(manifest_1["duration_seconds"], float)
    assert manifest_1["duration_seconds"] >= 0.0
    assert manifest_1["generation_id"] == "run_1"

    # Check input hashes
    input_hashes = manifest_1["collection_input_hashes"]
    assert "collection_manifest.json" in input_hashes
    assert "failed_pages.json" in input_hashes
    assert "resume_state.json" in input_hashes
    assert "normalization_manifest.json" in input_hashes

    # Check counters
    assert manifest_1["active_offers_before"] == 0
    assert manifest_1["active_offers_after"] == 2
    assert manifest_1["known_offers_before"] == 0
    assert manifest_1["known_offers_after"] == 2
    assert manifest_1["inactive_offers_after"] == 0
    assert manifest_1["unique_active_offer_ids"] == 2

    # 2. Second run: INCREMENTAL
    # Inactivate offer 2, keep offer 1, add offer 3
    offers_2 = [make_offer("1"), make_offer("3")]
    batch_dir_2 = make_batch(tmp_path, "run_2")
    input_path_2 = write_snapshot(tmp_path, offers_2, "run_2")

    manifest_2 = sync_catalog(
        normalized_input=input_path_2,
        collection_batch_dir=batch_dir_2,
        catalog_root=catalog_root,
        run_id="run_2",
    )

    assert manifest_2["mode"] == "INCREMENTAL"
    assert manifest_2["active_offers_before"] == 2
    assert manifest_2["active_offers_after"] == 2
    assert manifest_2["known_offers_before"] == 2
    assert manifest_2["known_offers_after"] == 3 # 1 and 3 active, 2 inactive
    assert manifest_2["inactive_offers_after"] == 1
    assert manifest_2["unique_active_offer_ids"] == 2


def test_catalog_incoherence_detection(tmp_path):
    catalog_root = tmp_path / "catalog"
    offers = [make_offer("1")]
    run_sync(tmp_path, catalog_root, offers, "run_1")

    # Verify everything starts coherent
    assert sync_module.load_current_state(catalog_root) is not None

    # 1. Test missing file
    (catalog_root / "current" / "offers_active.json").unlink()
    with pytest.raises(ValueError, match="Incoherent catalog state: one or more current files are missing"):
        sync_module.load_current_state(catalog_root)

    # Recreate catalog for the next test
    import shutil
    shutil.rmtree(catalog_root / "current")
    run_sync(tmp_path, catalog_root, offers, "run_2")

    # 2. Test hash mismatch in catalog_state.json
    state_file = catalog_root / "current" / "catalog_state.json"
    state_data = read_json(state_file)
    state_data[0]["is_active"] = False # Mutate without updating manifest
    write_json(state_file, state_data)

    with pytest.raises(ValueError, match="Incoherent catalog state: catalog_state.json hash mismatch"):
        sync_module.load_current_state(catalog_root)
