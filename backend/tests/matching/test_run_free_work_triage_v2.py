import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from backend.scripts.run_free_work_triage_v2 import run_fresh_triage_v2


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def fw_offer(source_id="1", title="Développeur Java", description="Mission Java détaillée"):
    return {
        "source": "free_work",
        "source_id": source_id,
        "title": title,
        "description": description,
        "company_name": "ACME",
        "location": {"locality": "Lyon", "postal_code": "69000", "department_code": "69"},
        "skills": [{"name": "Java", "name_normalized": "java", "slug": "java"}],
        "soft_skills": [],
        "source_url": "/fr/jobs/java",
    }


def ft_offer(france_travail_id="FT1"):
    return {
        "france_travail_id": france_travail_id,
        "title": "Développeur Java",
        "description": "Mission Java détaillée",
        "company_name": "ACME",
        "postal_code": "69000",
        "rome_code": "M1805",
    }


def candidate(score=88, ft_id="FT1", company_match="EXACT_NORMALIZED", geography="EXACT_POSTAL_CODE", blocks=None):
    return {
        "france_travail_id": ft_id,
        "title": "Développeur Java",
        "company_name": "ACME",
        "postal_code": "69000",
        "rome_code": "M1805",
        "preliminary_match_score": score,
        "evidence_coverage": 95,
        "components": {"description_token_jaccard": 0.7, "rome_query_match": False},
        "company_comparison": {"match_type": company_match},
        "geography_comparison": {"result": geography},
        "title_comparison": {
            "sequence_similarity": 0.95,
            "free_work_normalized": "developpeur java",
            "shared_significant_tokens": ["java"],
        },
        "candidate_blocks": ["EXACT_FINGERPRINT"] if blocks is None else blocks,
    }


def match_entry(source_id="1", candidates=None, description="Mission Java détaillée"):
    return {
        "free_work_source_id": source_id,
        "free_work_title": "Développeur Java",
        "free_work_title_normalized": "developpeur java",
        "free_work_company": "ACME",
        "free_work_company_normalized": "acme",
        "free_work_location": {"locality": "Lyon", "postal_code": "69000", "department_code": "69"},
        "free_work_source_url": "/fr/jobs/java",
        "free_work_description_excerpt": description,
        "top_candidates": candidates if candidates is not None else [candidate()],
    }


@pytest.fixture()
def valid_inputs(tmp_path):
    fw = tmp_path / "offers_normalized.json"
    ft = tmp_path / "france_travail.json"
    matches = tmp_path / "candidate_matches.json"
    write_json(fw, [fw_offer("1"), fw_offer("2", title="Consultant Data", description="")])
    write_json(ft, [ft_offer("FT1")])
    write_json(
        matches,
        [
            match_entry("1", [candidate()]),
            match_entry("2", [], description=""),
        ],
    )
    return fw, ft, matches


def test_fresh_triage_cli_with_explicit_paths(valid_inputs, tmp_path):
    fw, ft, matches = valid_inputs
    out = tmp_path / "out_cli"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.scripts.run_free_work_triage_v2",
            "--free-work-input",
            str(fw),
            "--france-travail-input",
            str(ft),
            "--candidate-matches-input",
            str(matches),
            "--output-dir",
            str(out),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Triage V2 frais terminé" in completed.stdout
    assert (out / "run_manifest.json").exists()


def test_fresh_triage_produces_four_main_artifacts_and_progress(valid_inputs, tmp_path):
    fw, ft, matches = valid_inputs
    out = tmp_path / "out"
    manifest = run_fresh_triage_v2(fw, ft, matches, out)

    assert {"run_manifest.json", "triage_decisions.jsonl", "import_candidates.json", "review_queue.csv"}.issubset(
        {path.name for path in out.iterdir()}
    )
    assert (out / "triage_progress.json").exists()
    assert manifest["counts"]["decisions"] == 2
    assert manifest["counts"]["unique_free_work_ids"] == 2


def test_fresh_triage_refuses_non_empty_output(valid_inputs, tmp_path):
    fw, ft, matches = valid_inputs
    out = tmp_path / "out"
    out.mkdir()
    (out / "existing.txt").write_text("x", encoding="utf-8")

    with pytest.raises(FileExistsError):
        run_fresh_triage_v2(fw, ft, matches, out)


def test_fresh_triage_missing_file_fails(valid_inputs, tmp_path):
    _, ft, matches = valid_inputs
    with pytest.raises(FileNotFoundError):
        run_fresh_triage_v2(tmp_path / "missing.json", ft, matches, tmp_path / "out")


def test_fresh_triage_invalid_json_fails(valid_inputs, tmp_path):
    fw, ft, _ = valid_inputs
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON invalide"):
        run_fresh_triage_v2(fw, ft, bad, tmp_path / "out")


def test_fresh_triage_duplicate_ids_fail(valid_inputs, tmp_path):
    fw, ft, matches = valid_inputs
    write_json(fw, [fw_offer("1"), fw_offer("1")])

    with pytest.raises(ValueError, match="dupliqué"):
        run_fresh_triage_v2(fw, ft, matches, tmp_path / "out")


def test_fresh_triage_missing_candidate_match_fails(valid_inputs, tmp_path):
    fw, ft, matches = valid_inputs
    write_json(matches, [match_entry("1")])

    with pytest.raises(ValueError, match="offres normalisées sans candidate_matches"):
        run_fresh_triage_v2(fw, ft, matches, tmp_path / "out")


def test_fresh_triage_preserves_skills_and_unique_decisions(valid_inputs, tmp_path):
    fw, ft, matches = valid_inputs
    out = tmp_path / "out"
    run_fresh_triage_v2(fw, ft, matches, out)

    decisions = [json.loads(line) for line in (out / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(decisions) == len({row["free_work"]["source_id"] for row in decisions})
    assert decisions[0]["free_work"]["skills"][0]["name_normalized"] == "java"


def test_fresh_triage_review_now_and_defer_actions(tmp_path):
    fw = tmp_path / "offers_normalized.json"
    ft = tmp_path / "france_travail.json"
    matches = tmp_path / "candidate_matches.json"
    write_json(
        fw,
        [
            fw_offer("review", description=""),
            fw_offer("defer", description=""),
        ],
    )
    write_json(ft, [ft_offer("FT1"), ft_offer("FT2")])
    review_candidate = candidate(score=52, blocks=[], company_match="NO_MATCH", geography="DIFFERENT")
    review_candidate["title_comparison"]["sequence_similarity"] = 0.2
    defer_candidate = candidate(score=35, ft_id="FT2", blocks=[], company_match="NO_MATCH", geography="DIFFERENT")
    defer_candidate["title_comparison"]["sequence_similarity"] = 0.2
    write_json(
        matches,
        [
            match_entry("review", [review_candidate], description=""),
            match_entry("defer", [defer_candidate], description=""),
        ],
    )
    manifest = run_fresh_triage_v2(fw, ft, matches, tmp_path / "out")

    actions = manifest["counters"]["review_actions"]
    assert actions["REVIEW_NOW"] == 1
    assert actions["DEFER_DATA_INCOMPLETE"] == 1


def test_fresh_triage_is_deterministic(valid_inputs, tmp_path):
    fw, ft, matches = valid_inputs
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    run_fresh_triage_v2(fw, ft, matches, out1)
    run_fresh_triage_v2(fw, ft, matches, out2)

    assert (out1 / "triage_decisions.jsonl").read_text(encoding="utf-8") == (
        out2 / "triage_decisions.jsonl"
    ).read_text(encoding="utf-8")


def test_no_historical_paths_in_new_script():
    text = (PROJECT_ROOT / "backend" / "scripts" / "run_free_work_triage_v2.py").read_text(encoding="utf-8")
    assert "20260624_081715" not in text
    assert "run_triage_full_20260624" not in text
    assert "run_triage_v2_handoff_20260624" not in text
