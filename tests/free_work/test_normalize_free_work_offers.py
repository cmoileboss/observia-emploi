import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.normalize_free_work_offers as normalize_module
from scripts.normalize_free_work_offers import normaliser_competences, normaliser_offres


def test_normaliser_competences_complete_and_deterministic():
    raw = [
        {"@id": "/skills/152", "id": 152, "displayed": True, "name": "Python", "slug": "python", "skillJobs": [{"x": 1}]},
        {"@id": "/skills/152", "id": 152, "displayed": True, "name": " PYTHON ", "slug": "python"},
        {"name": "Écoute active", "displayed": False},
        {},
        {"skillJobs": []},
    ]

    normalized = normaliser_competences(raw)

    assert normalized == [
        {
            "source_skill_id": None,
            "source_ref": None,
            "name": "Écoute active",
            "name_normalized": "ecoute active",
            "slug": None,
            "displayed": False,
        },
        {
            "source_skill_id": "152",
            "source_ref": "/skills/152",
            "name": "Python",
            "name_normalized": "python",
            "slug": "python",
            "displayed": True,
        },
    ]
    assert "skillJobs" not in normalized[1]


def test_normaliser_competences_missing_optional_fields_and_empty_array():
    assert normaliser_competences([]) == []
    assert normaliser_competences(None) == []

    normalized = normaliser_competences([{"id": 7, "name": "SAS"}])

    assert normalized[0]["source_skill_id"] == "7"
    assert normalized[0]["source_ref"] is None
    assert normalized[0]["slug"] is None
    assert normalized[0]["displayed"] is None


def test_normalize_root_not_list(tmp_path):
    input_file = tmp_path / "dedup" / "offers_deduplicated.json"
    input_file.parent.mkdir()
    input_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

    with pytest.raises(ValueError, match="La racine du fichier JSON d'entrée doit être une liste"):
        normaliser_offres(input_file)


def test_normalize_element_not_dict(tmp_path):
    input_file = tmp_path / "dedup" / "offers_deduplicated.json"
    input_file.parent.mkdir()
    input_file.write_text(json.dumps(["not a dict"]), encoding="utf-8")

    with pytest.raises(ValueError, match="n'est pas un dictionnaire"):
        normaliser_offres(input_file)


def test_normalize_missing_keys(tmp_path):
    input_file = tmp_path / "dedup" / "offers_deduplicated.json"
    input_file.parent.mkdir()
    item = {"source": "free_work", "source_id": "123"}  # missing matched_rome_queries & offer
    input_file.write_text(json.dumps([item]), encoding="utf-8")

    with pytest.raises(ValueError, match="Clé 'matched_rome_queries' manquante"):
        normaliser_offres(input_file)


def test_normalize_invalid_source(tmp_path):
    input_file = tmp_path / "dedup" / "offers_deduplicated.json"
    input_file.parent.mkdir()
    item = {
        "source": "other",
        "source_id": "123",
        "matched_rome_queries": [],
        "offer": {}
    }
    input_file.write_text(json.dumps([item]), encoding="utf-8")

    with pytest.raises(ValueError, match="Source invalide"):
        normaliser_offres(input_file)


def test_normalize_empty_source_id(tmp_path):
    input_file = tmp_path / "dedup" / "offers_deduplicated.json"
    input_file.parent.mkdir()
    item = {
        "source": "free_work",
        "source_id": "   ",
        "matched_rome_queries": [],
        "offer": {}
    }
    input_file.write_text(json.dumps([item]), encoding="utf-8")

    with pytest.raises(ValueError, match="source_id invalide ou vide"):
        normaliser_offres(input_file)


def test_normalize_duplicate_source_id(tmp_path):
    input_file = tmp_path / "dedup" / "offers_deduplicated.json"
    input_file.parent.mkdir()
    item = {
        "source": "free_work",
        "source_id": "123",
        "matched_rome_queries": [],
        "offer": {"id": 123, "title": "Title"}
    }
    input_file.write_text(json.dumps([item, item]), encoding="utf-8")

    with pytest.raises(ValueError, match="source_id dupliqué détecté"):
        normaliser_offres(input_file)


def test_normalize_id_mismatch(tmp_path):
    input_file = tmp_path / "dedup" / "offers_deduplicated.json"
    input_file.parent.mkdir()
    item = {
        "source": "free_work",
        "source_id": "123",
        "matched_rome_queries": [],
        "offer": {"id": 456, "title": "Title"}
    }
    input_file.write_text(json.dumps([item]), encoding="utf-8")

    with pytest.raises(ValueError, match="Incohérence d'identifiant"):
        normaliser_offres(input_file)


def test_normalize_missing_title(tmp_path):
    input_file = tmp_path / "dedup" / "offers_deduplicated.json"
    input_file.parent.mkdir()
    item = {
        "source": "free_work",
        "source_id": "123",
        "matched_rome_queries": [],
        "offer": {"id": 123, "title": "   "}
    }
    input_file.write_text(json.dumps([item]), encoding="utf-8")

    with pytest.raises(ValueError, match="Titre manquant ou vide"):
        normaliser_offres(input_file)


def test_normalize_nominal_and_idempotence(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(normalize_module, "PROJECT_ROOT", tmp_path)
    input_file = tmp_path / "batches" / "batch_test" / "offers_deduplicated.json"
    input_file.parent.mkdir(parents=True)

    offer_raw1 = {
        "id": 123,
        "title": "Développeur Python & Django",
        "description": "<p>Super mission pour développeur.</p><br/>Venez nombreux &amp; motivés !",
        "candidateProfile": "<div>Expérience de 3 ans.</div>",
        "companyDescription": "Une ESN innovante.",
        "company": {"name": "  ObservIA  "},
        "location": {
            "locality": "Lille",
            "postalCode": "59000",
            "adminLevel1": "Nord",
            "country": "France"
        },
        "contracts": ["permanent", "permanent", "fixed-term"],
        "remoteMode": "partial",
        "experienceLevel": "intermediate",
        "minAnnualSalary": 45000,
        "maxAnnualSalary": 50000,
        "minDailySalary": None,
        "maxDailySalary": None,
        "currency": "EUR",
        "publishedAt": "2026-05-29T09:43:26+02:00",
        "updatedAt": "2026-05-29T09:43:26+02:00",
        "expiredAt": "2026-07-28T09:43:26+02:00",
        "@id": "/job_postings/developpeur-python-django-123",
        "skills": [
            {"@id": "/skills/152", "id": 152, "displayed": True, "name": "Python", "slug": "python", "skillJobs": [{"ignored": True}]}
        ],
        "softSkills": [
            {"@id": "/skills/900", "id": 900, "displayed": True, "name": "Communication", "slug": "communication"}
        ]
    }

    offer_raw2 = {
        "id": 99,
        "title": "Ingénieur Support Électronique",
        "contracts": ["contractor"],
        "@id": "/job_postings/support-99"
    }

    item1 = {
        "source": "free_work",
        "source_id": "123",
        "matched_rome_queries": [
            {"rome_code": "M1805", "rome_label": "Dev", "query": "Python"},
            {"rome_code": "M1805", "rome_label": "Dev", "query": "Python"}  # duplicate query entry
        ],
        "offer": offer_raw1
    }

    item2 = {
        "source": "free_work",
        "source_id": "99",
        "matched_rome_queries": [
            {"rome_code": "I1401", "rome_label": "Support", "query": "Support"}
        ],
        "offer": offer_raw2
    }

    input_file.write_text(json.dumps([item1, item2]), encoding="utf-8")

    # First run (should output 'mis à jour')
    capsys.readouterr()
    output_dir = normaliser_offres(input_file)
    stdout_run1 = capsys.readouterr().out.strip()
    assert stdout_run1 == "mis à jour"

    # Verify output contents
    offers_file = output_dir / "offers_normalized.json"
    manifest_file = output_dir / "normalization_manifest.json"

    assert offers_file.exists()
    assert manifest_file.exists()

    with offers_file.open("r", encoding="utf-8") as f:
        normalized = json.load(f)

    # Deterministic order test: "123" should be before "99" in alphabetical string sorting
    assert len(normalized) == 2
    assert normalized[0]["source_id"] == "123"
    assert normalized[1]["source_id"] == "99"

    # Test html stripping, entity decoding, space normalization, accent preservation
    o123 = normalized[0]
    assert o123["title"] == "Développeur Python & Django"
    assert o123["description"] == "Super mission pour développeur. Venez nombreux & motivés !"
    assert o123["candidate_profile"] == "Expérience de 3 ans."
    assert o123["company_description"] == "Une ESN innovante."
    assert o123["company_name"] == "ObservIA"
    assert o123["location"] == {
        "locality": "Lille",
        "postal_code": "59000",
        "region": "Nord",
        "country": "France"
    }
    # Contracts sorted and deduplicated
    assert o123["contracts"] == ["fixed-term", "permanent"]
    assert o123["remote_mode"] == "partial"
    assert o123["experience_level"] == "intermediate"
    # Salary values
    assert o123["salary"] == {
        "annual_min": 45000,
        "annual_max": 50000,
        "daily_min": None,
        "daily_max": None,
        "currency": "EUR"
    }
    # Dates
    assert o123["published_at"] == "2026-05-29T09:43:26+02:00"
    assert o123["raw_payload_sha256"] is not None
    assert o123["source_url"] is None
    assert o123["source_url_raw"] == "/job_postings/developpeur-python-django-123"
    assert o123["source_url_resolution_method"] == "LEGACY_URL_REBUILT"
    assert o123["skills"][0]["name"] == "Python"
    assert o123["skills"][0]["name_normalized"] == "python"
    assert "skillJobs" not in o123["skills"][0]
    assert o123["soft_skills"][0]["name_normalized"] == "communication"

    # matched_rome_queries deduplication
    assert len(o123["matched_rome_queries"]) == 1

    # Manifest checks
    with manifest_file.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["input_offers"] == 2
    assert manifest["output_offers"] == 2
    assert manifest["offers_with_missing_company"] == 1  # offer 99 has no company
    assert manifest["offers_with_missing_location"] == 1  # offer 99 has no location
    assert manifest["offers_with_missing_description"] == 1  # offer 99 has no description

    # Second run (should output 'inchangé' and not modify anything)
    capsys.readouterr()
    normaliser_offres(input_file)
    stdout_run2 = capsys.readouterr().out.strip()
    assert stdout_run2 == "inchangé"
