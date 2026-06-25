import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.free_work.rome_classifier import (
    DEFAULT_CONFIG,
    assignment_metrics_for_rows,
    build_benchmark,
    build_calibrated_benchmark,
    build_leave_one_out_reference_predictions,
    build_rome_profiles,
    classify_independent,
    classify_offers,
    deterministic_reference_split,
    run_classification,
    sha256_file,
)


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


@pytest.fixture()
def rome_csv(tmp_path):
    path = tmp_path / "rome.csv"
    path.write_text(
        "\n".join(
            [
                "code_rome;intitule_rome;code_rncp;intitule_rncp;niveau_rncp",
                "M1805;Études et développement informatique;RNCP1;Développeur Python;NIV6",
                "M1802;Conseil et maîtrise d'ouvrage en systèmes d'information;RNCP2;Business analyst;NIV7",
                "M1806;Expertise et support technique en systèmes d'information;RNCP3;Administrateur systèmes;NIV6",
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def france_travail_rows():
    return [
        {
            "france_travail_id": "FT1",
            "title": "Développeur Python",
            "description": "Développement backend API Python Django",
            "rome_code": "M1805",
        },
        {
            "france_travail_id": "FT2",
            "title": "Business analyst maîtrise ouvrage",
            "description": "Recueil des besoins MOA processus métier",
            "rome_code": "M1802",
        },
        {
            "france_travail_id": "FT3",
            "title": "Administrateur systèmes Linux",
            "description": "Support technique infrastructure Linux",
            "rome_code": "M1806",
        },
    ]


def offer(source_id="1", title="Développeur Python", description="API Python", skills=None):
    return {
        "source": "free_work",
        "source_id": source_id,
        "title": title,
        "description": description,
        "candidate_profile": None,
        "skills": skills or [],
        "soft_skills": [],
    }


def test_exact_rome_label_match(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    prediction = classify_independent(offer(title="Études et développement informatique"), profiles)
    assert prediction["candidates"][0]["rome_code"] == "M1805"


def test_occupation_label_match(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    prediction = classify_independent(offer(title="Business analyst"), profiles)
    assert prediction["candidates"][0]["rome_code"] == "M1802"


def test_structured_skills_help_second_signal(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    skill = {"name": "Linux", "name_normalized": "linux", "slug": "linux"}
    prediction = classify_independent(offer(title="Technicien", description="", skills=[skill]), profiles)
    assert prediction["candidates"][0]["rome_code"] == "M1806"
    assert prediction["candidates"][0]["field_scores"]["skills"] > 0


def test_description_less_influential_than_title(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    prediction = classify_independent(
        offer(title="Développeur Python", description="support infrastructure linux " * 20),
        profiles,
    )
    assert prediction["candidates"][0]["rome_code"] == "M1805"


def test_close_candidates_trigger_review(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    rows = classify_offers([offer(title="Systèmes information", description="")], profiles)
    assert rows[0]["assignment_status"] == "UNASSIGNED_AMBIGUOUS"
    assert rows[0]["assigned_rome_code"] is None


def test_generic_title_unassigned(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    rows = classify_offers([offer(title="Consultant", description="", skills=[])], profiles)
    assert rows[0]["assignment_status"] == "UNASSIGNED_INSUFFICIENT_SIGNAL"
    assert rows[0]["assigned_rome_code"] is None


def test_missing_data_unassigned(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    rows = classify_offers([offer(title="", description="", skills=[])], profiles)
    assert rows[0]["assignment_status"] in {"UNASSIGNED_INSUFFICIENT_SIGNAL", "PROCESSING_ERROR"}
    assert rows[0]["assigned_rome_code"] is None


def test_stable_candidate_order_and_determinism(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    input_offer = offer(title="Développeur Python", skills=[{"name": "Python"}])
    first = classify_independent(input_offer, profiles)
    second = classify_independent(input_offer, profiles)
    assert first == second
    scores = [candidate["score"] for candidate in first["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_inputs_not_mutated(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    rows = [offer(skills=[{"name": "Python"}])]
    before = json.loads(json.dumps(rows))
    classify_offers(rows, profiles)
    assert rows == before


def test_confirmed_from_france_travail_keeps_independent_prediction(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    triage = [
        {
            "free_work": {"source_id": "1"},
            "decision": "PRESENT_IN_FT_SNAPSHOT",
            "best_candidate": {"rome_code": "M1802", "france_travail_id": "FT2"},
        }
    ]
    rows = classify_offers([offer(title="Développeur Python")], profiles, triage_rows=triage)
    assert rows[0]["assignment_status"] == "CONFIRMED_FROM_FT_MATCH"
    assert rows[0]["assigned_rome_code"] == "M1802"
    assert rows[0]["independent_prediction"]["rome_code"] == "M1805"


def test_schema_errors(rome_csv):
    with pytest.raises(ValueError, match="rome_code"):
        build_rome_profiles([{"france_travail_id": "FT1", "title": "A", "description": "B"}], rome_csv)


def test_manifest_hashes_and_benchmark(tmp_path, rome_csv, france_travail_rows):
    fw_path = tmp_path / "fw.json"
    ft_path = tmp_path / "ft.json"
    triage_path = tmp_path / "triage.jsonl"
    out = tmp_path / "out"
    write_json(fw_path, [offer("1", "Développeur Python")])
    write_json(ft_path, france_travail_rows)
    write_jsonl(
        triage_path,
        [{"free_work": {"source_id": "1"}, "decision": "PRESENT_IN_FT_SNAPSHOT", "best_candidate": {"rome_code": "M1805"}}],
    )
    result = run_classification(fw_path, ft_path, out, rome_csv, triage_input=triage_path)
    manifest = json.loads((out / "rome_classification_manifest.json").read_text(encoding="utf-8"))
    benchmark = json.loads((out / "rome_classification_benchmark.json").read_text(encoding="utf-8"))
    assert manifest["input_files"]["free_work_sha256"] == sha256_file(fw_path)
    assert benchmark["leave_one_out"]["sample_size"] == 1
    assert benchmark["leave_one_out"]["top1_correct"] == 1
    assert benchmark["leave_one_out"]["top3_correct"] == 1
    assert result["manifest"]["total_offers"] == 1
    assert (out / "rome_assignments_deterministic_v1.jsonl").exists()


def test_cli_without_fixed_batch_paths(tmp_path, rome_csv, france_travail_rows):
    fw_path = tmp_path / "custom_fw.json"
    ft_path = tmp_path / "custom_ft.json"
    out = tmp_path / "custom_out"
    write_json(fw_path, [offer("custom", "Développeur Python")])
    write_json(ft_path, france_travail_rows)
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "classify_free_work_rome.py"),
            "--free-work-input",
            str(fw_path),
            "--france-travail-input",
            str(ft_path),
            "--output-dir",
            str(out),
            "--rome-reference-csv",
            str(rome_csv),
            "--top-k",
            "3",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Classification ROME Free-Work terminée" in completed.stdout
    assert (out / "rome_classification_results.jsonl").exists()


def test_benchmark_top1_and_top3(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    triage = [
        {"free_work": {"source_id": "1"}, "decision": "PRESENT_IN_FT_SNAPSHOT", "best_candidate": {"rome_code": "M1805"}},
        {"free_work": {"source_id": "2"}, "decision": "PRESENT_IN_FT_SNAPSHOT", "best_candidate": {"rome_code": "M1802"}},
    ]
    results = classify_offers(
        [
            offer("1", "Développeur Python"),
            offer("2", "Business analyst"),
        ],
        profiles,
        triage_rows=triage,
    )
    benchmark = build_benchmark(results, triage)
    assert benchmark["sample_size"] == 2
    assert benchmark["top1_correct"] == 2
    assert benchmark["top3_correct"] == 2
    assert benchmark["threshold_analysis"]


def test_auto_assignment_when_score_and_margin_reach_thresholds(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    rows = classify_offers([offer(title="Développeur Python", skills=[{"name": "Python"}])], profiles)
    assert rows[0]["assignment_status"] == "AUTO_ASSIGNED_HIGH_CONFIDENCE"
    assert rows[0]["assigned_rome_code"] == "M1805"


def test_score_below_threshold_is_not_assigned(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    rows = classify_offers([offer(title="Produit", description="", skills=[])], profiles)
    assert rows[0]["assignment_status"] == "UNASSIGNED_INSUFFICIENT_SIGNAL"
    assert rows[0]["assigned_rome_code"] is None


def test_threshold_boundary_is_inclusive(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    base_offer = offer(title="Développeur Python", skills=[{"name": "Python"}])
    prediction = classify_independent(base_offer, profiles)
    boundary_config = DEFAULT_CONFIG.__class__(
        **{
            **DEFAULT_CONFIG.__dict__,
            "auto_score_threshold": prediction["top_score"],
            "auto_margin_threshold": prediction["margin"],
        }
    )
    rows = classify_offers([base_offer], profiles, config=boundary_config)
    assert rows[0]["assignment_status"] == "AUTO_ASSIGNED_HIGH_CONFIDENCE"


def test_one_result_per_free_work_id_and_candidates_kept_for_unassigned(rome_csv, france_travail_rows):
    profiles = build_rome_profiles(france_travail_rows, rome_csv)
    rows = classify_offers(
        [
            offer("2", "Systèmes information", ""),
            offer("1", "Consultant", ""),
        ],
        profiles,
    )
    assert [row["free_work_id"] for row in rows] == ["1", "2"]
    assert len({row["free_work_id"] for row in rows}) == 2
    assert all(row["candidates"] for row in rows if row["assigned_rome_code"] is None)


def test_leave_one_out_removes_matched_france_travail_offer(rome_csv):
    ft_rows = [
        {"france_travail_id": "FT_KEEP", "title": "Développeur Python", "description": "API", "rome_code": "M1805"},
        {"france_travail_id": "FT_MATCH", "title": "Architecte Dragon Rare", "description": "Dragon", "rome_code": "M1806"},
    ]
    triage = [
        {
            "free_work": {"source_id": "1"},
            "decision": "PRESENT_IN_FT_SNAPSHOT",
            "best_candidate": {"rome_code": "M1806", "france_travail_id": "FT_MATCH"},
        }
    ]
    rows = build_leave_one_out_reference_predictions(
        [offer("1", "Architecte Dragon Rare", "Dragon")],
        ft_rows,
        triage,
        rome_csv,
        DEFAULT_CONFIG,
        3,
    )
    assert rows[0]["reference_france_travail_id"] == "FT_MATCH"
    assert rows[0]["predicted_rome_code"] != "M1806"


def test_deterministic_calibration_validation_split():
    sample = [(str(index), "M1805" if index < 10 else "M1802", f"FT{index}") for index in range(20)]
    first = deterministic_reference_split(sample)
    second = deterministic_reference_split(sample)
    assert first == second
    assert set(first["calibration"]).isdisjoint(first["validation"])
    assert len(first["calibration"]) + len(first["validation"]) == 20


def test_precision_and_coverage_metrics():
    rows = [
        {"top_score": 80, "margin": 20, "predicted_rome_code": "A", "reference_rome_code": "A"},
        {"top_score": 80, "margin": 20, "predicted_rome_code": "A", "reference_rome_code": "B"},
        {"top_score": 40, "margin": 20, "predicted_rome_code": "A", "reference_rome_code": "A"},
    ]
    metrics = assignment_metrics_for_rows(rows, 60, 10)
    assert metrics["auto_assigned"] == 2
    assert metrics["observed_precision"] == 0.5
    assert metrics["coverage_rate"] == 0.6667


def test_calibrated_benchmark_contains_compared_configurations(rome_csv, france_travail_rows):
    triage = [
        {"free_work": {"source_id": "1"}, "decision": "PRESENT_IN_FT_SNAPSHOT", "best_candidate": {"rome_code": "M1805", "france_travail_id": "FT1"}},
        {"free_work": {"source_id": "2"}, "decision": "PRESENT_IN_FT_SNAPSHOT", "best_candidate": {"rome_code": "M1802", "france_travail_id": "FT2"}},
        {"free_work": {"source_id": "3"}, "decision": "PRESENT_IN_FT_SNAPSHOT", "best_candidate": {"rome_code": "M1806", "france_travail_id": "FT3"}},
    ]
    benchmark = build_calibrated_benchmark(
        [
            offer("1", "Développeur Python"),
            offer("2", "Business analyst"),
            offer("3", "Administrateur systèmes Linux"),
        ],
        france_travail_rows,
        triage,
        rome_csv,
        3,
    )
    assert {"BASELINE", "DETERMINISTIC_V1_A", "DETERMINISTIC_V1_B"}.issubset(benchmark["configuration_summaries"])
    assert benchmark["threshold_selection"]["calibration"]["sample_size"] > 0
