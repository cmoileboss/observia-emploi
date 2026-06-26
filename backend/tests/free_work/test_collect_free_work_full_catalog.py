import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from backend.scripts.collect_free_work_full_catalog import collecter_exhaustive


@pytest.fixture
def mock_requests_get():
    with patch("requests.get") as mock_get:
        yield mock_get


def test_collect_full_catalog_max_pages(tmp_path, mock_requests_get):
    # Mock three successful pages and then stop
    page1 = {
        "hydra:totalItems": 25,
        "hydra:member": [
            {"id": "fw1", "title": "Job 1", "updatedAt": "2026-01-01"},
            {"id": "fw2", "title": "Job 2", "updatedAt": "2026-01-01"}
        ],
        "hydra:view": {
            "hydra:next": "/job_postings?page=2&itemsPerPage=10"
        }
    }
    page2 = {
        "hydra:totalItems": 25,
        "hydra:member": [
            {"id": "fw3", "title": "Job 3", "updatedAt": "2026-01-01"}
        ],
        "hydra:view": {
            "hydra:next": "/job_postings?page=3&itemsPerPage=10"
        }
    }

    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = page1
    mock_resp1.content = json.dumps(page1).encode("utf-8")

    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = page2
    mock_resp2.content = json.dumps(page2).encode("utf-8")

    mock_requests_get.side_effect = [mock_resp1, mock_resp1, mock_resp2]  # First call is for robots.txt

    data_root = tmp_path / "backend" / "data"
    with patch("backend.scripts.collect_free_work_full_catalog.RAW_DATA_ROOT", data_root / "raw"), \
         patch("backend.scripts.collect_free_work_full_catalog.PROCESSED_DATA_ROOT", data_root / "processed"), \
         patch("backend.scripts.collect_free_work_full_catalog.time.sleep"):
        batch_id = collecter_exhaustive(
            delay_seconds=0.0,
            timeout_seconds=5,
            max_retries=1,
            max_pages=2,
            resume_batch_id=None
        )

    assert batch_id is not None
    batch_dir = data_root / "raw" / "free_work" / "full_catalog" / "batches" / batch_id
    assert not (tmp_path / "data").exists()

    # Check that output raw and deduplicated files were written
    raw_file = batch_dir / "offers_raw.json"
    assert raw_file.exists()
    raw_data = json.loads(raw_file.read_text(encoding="utf-8"))
    assert len(raw_data) == 3

    dedup_file = batch_dir / "offers_deduplicated.json"
    assert dedup_file.exists()

    manifest_file = batch_dir / "collection_manifest.json"
    assert manifest_file.exists()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["unique_source_offers"] == 3


def test_collect_full_catalog_resume(tmp_path, mock_requests_get):
    # Setup a state that is partially completed (page 1 done, needs page 2)
    batch_id = "test_batch_123"
    data_root = tmp_path / "backend" / "data"
    batch_dir = data_root / "raw" / "free_work" / "full_catalog" / "batches" / batch_id
    batch_dir.mkdir(parents=True)

    import hashlib
    config_hash = hashlib.sha256(
        "https://www.free-work.com/api/job_postings|ObservIA-Emploi/1.0 (projet pédagogique)".encode("utf-8")
    ).hexdigest()
    state = {
        "batch_id": batch_id,
        "endpoint_initial": "https://www.free-work.com/api/job_postings",
        "next_page_url": "https://www.free-work.com/api/job_postings?page=2&itemsPerPage=100&locationKeys=fr~~~",
        "visited_page_urls": ["https://www.free-work.com/api/job_postings?page=1&itemsPerPage=100&locationKeys=fr~~~"],
        "pages_succeeded": [1],
        "pages_failed": {},
        "raw_offer_occurrences": 1,
        "unique_source_ids": ["fw1"],
        "total_items_announced": 2,
        "input_configuration_hash": config_hash,
        "collector_version": "1.0",
        "updated_at": "2026-06-24T00:00:00Z",
        "status": "RUNNING"
    }
    (batch_dir / "resume_state.json").write_text(json.dumps(state))
    (batch_dir / "offers_raw.json").write_text(json.dumps([{
        "source": "free_work",
        "source_id": "fw1",
        "matched_rome_queries": [],
        "collection_mode": "FULL_CATALOG",
        "offer": {"id": "fw1", "title": "Job 1"}
    }]))

    page2 = {
        "hydra:totalItems": 2,
        "hydra:member": [
            {"id": "fw2", "title": "Job 2", "updatedAt": "2026-01-01"}
        ],
        "hydra:view": {
            "hydra:next": None
        }
    }

    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = page2
    mock_resp2.content = json.dumps(page2).encode("utf-8")

    mock_requests_get.side_effect = [mock_resp2, mock_resp2]  # robots, page2

    with patch("backend.scripts.collect_free_work_full_catalog.RAW_DATA_ROOT", data_root / "raw"), \
         patch("backend.scripts.collect_free_work_full_catalog.PROCESSED_DATA_ROOT", data_root / "processed"), \
         patch("backend.scripts.collect_free_work_full_catalog.time.sleep"):
        res_batch_id = collecter_exhaustive(
            delay_seconds=0.0,
            timeout_seconds=5,
            max_retries=1,
            max_pages=None,
            resume_batch_id=batch_id
        )

    assert res_batch_id == batch_id
    assert not (tmp_path / "data").exists()

    raw_data = json.loads((batch_dir / "offers_raw.json").read_text(encoding="utf-8"))
    assert len(raw_data) == 2  # fw1 + fw2
