"""."""
from scripts.free_work_triage_v2 import (
    candidate_score,
    description_similarity,
    has_strong_fingerprint,
    human_explanation,
    is_generic_title,
    title_similarity,
)
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"


V1_RUN_ID = "run_triage_full_20260624"
V2_RUN_ID = "run_triage_v2_preview_20260624"
HISTORICAL_CASES = {
    "606592": "SAP SD/MM / Signe+",
    "621908": "Econocom",
    "637922": "Experis",
    "422864": "IAM / comptabilité",
}
HUMAN_FIELDS = [
    "human_decision",
    "human_selected_france_travail_id",
    "human_comment",
    "reviewed_at",
    "reviewer"]


def load_json(path: Path):
    """Load and parse JSON file."""
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_jsonl_by_id(path: Path) -> dict[str, dict]:
    """Load JSONL file indexed by source_id with duplicate detection."""
    rows = {}
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            source_id = str(item["free_work"]["source_id"])
            if source_id in rows:
                raise ValueError(f"Duplicate source_id {source_id} in {path} at line {line_number}")
            rows[source_id] = item
    return rows


def write_json(path: Path, payload) -> None:
    """Serialize object to JSON file."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reason_key(reasons) -> str:
    """Convert reason list to pipe-separated string for aggregation."""
    if not reasons:
        return ""
    return "|".join(str(reason) for reason in reasons)


def candidate_by_id(candidate_matches: list[dict]) -> dict[str, dict]:
    """Index candidate matches by Free-Work source_id."""
    rows = {}
    for item in candidate_matches:
        source_id = str(item["free_work_source_id"])
        if source_id in rows:
            raise ValueError(f"Duplicate source_id {source_id} in candidate_matches")
        rows[source_id] = item
    return rows


def build_transition_rows(
        v1_rows: list[dict], v2_by_id: dict[str, dict], matches_by_id: dict[str, dict]) -> list[dict]:  # pylint: disable=line-too-long
    """Build V1→V2 transition analysis rows with scoring."""
    rows = []
    seen = set()
    for v1 in v1_rows:
        source_id = str(v1["free_work_source_id"])
        if source_id in seen:
            raise ValueError(f"Duplicate source_id {source_id} in triage_results")
        seen.add(source_id)
        if source_id not in v2_by_id:
            raise ValueError(f"Missing source_id {source_id} in V2 decisions")
        match = matches_by_id.get(source_id, {})
        candidates = match.get("top_candidates") or []
        best = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        rows.append({"free_work_source_id": source_id,
                     "decision_v1": v1.get("triage_category"),
                     "decision_v2": v2_by_id[source_id]["decision"],
                     "score_top1": candidate_score(best),
                     "score_top2": candidate_score(second),
                     "evidence_coverage": (best or {}).get("evidence_coverage") or v1.get("data_coverage"),  # pylint: disable=line-too-long
                     "reason_v1": reason_key(v1.get("triage_reason_codes")),
                     "reason_v2": reason_key(v2_by_id[source_id].get("technical_reasons")),
                     })
    if len(rows) != 8457:
        raise ValueError(f"Expected 8457 transition rows, got {len(rows)}")
    if len({row["free_work_source_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate source_id found in transition rows")
    return sorted(rows, key=lambda row: row["free_work_source_id"])


def build_matrix(rows: list[dict]) -> dict:
    """Build V1→V2 decision transition contingency matrix."""
    matrix = defaultdict(Counter)
    for row in rows:
        matrix[row["decision_v1"]][row["decision_v2"]] += 1
    return {v1: dict(sorted(counter.items())) for v1, counter in sorted(matrix.items())}


def write_transition_csv(path: Path, rows: list[dict]) -> None:
    """Write transition rows to CSV with all fields."""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def candidate_details(candidate: dict | None) -> dict | None:
    """Extract candidate details for audit including scores and comparisons."""
    if not candidate:
        return None
    return {
        "france_travail_id": candidate.get("france_travail_id"),
        "title": candidate.get("title"),
        "company_name": candidate.get("company_name"),
        "postal_code": candidate.get("postal_code"),
        "rome_code": candidate.get("rome_code"),
        "score": candidate_score(candidate),
        "exact_fingerprint": has_strong_fingerprint(candidate),
        "title_similarity": title_similarity(candidate),
        "description_similarity": description_similarity(candidate),
        "company_comparison": candidate.get("company_comparison"),
        "geography_comparison": candidate.get("geography_comparison"),
        "rome_query_match": (candidate.get("components") or {}).get("rome_query_match"),
    }


def possible_regression_reasons(match: dict, best: dict | None, source_id: str) -> list[str]:
    """Identify potential V2 regression reasons for reclassified duplicates."""
    if not best:
        return []
    reasons = []
    if has_strong_fingerprint(best):
        reasons.append("EXACT_FINGERPRINT_LOST")
    company_type = ((best.get("company_comparison") or {}).get("match_type") or "")
    if company_type in {"EXACT_NORMALIZED", "ALIAS_MATCH"} and (
            title_similarity(best) or 0) >= 0.85:
        reasons.append("SAME_COMPANY_STRONG_TITLE")
    score = candidate_score(best) or 0
    if score >= 75 and not is_generic_title(match.get("free_work_title_normalized")):
        reasons.append("HIGH_SCORE_NON_GENERIC_TITLE")
    if source_id in {"606592", "621908", "637922"}:
        reasons.append("KNOWN_POSITIVE_HISTORICAL_CASE")
    return reasons


def audit_reclassified_duplicates(v1_rows, v2_by_id, matches_by_id) -> tuple[list[dict], dict]:
    """Audit V1 duplicates reclassified by V2 with regression detection."""
    audited = []
    summary = Counter()
    for v1 in v1_rows:
        source_id = str(v1["free_work_source_id"])
        if v1.get("triage_category") != "DUPLICATE_HIGH_CONFIDENCE":
            continue
        v2 = v2_by_id[source_id]
        if v2["decision"] == "PRESENT_IN_FT_SNAPSHOT":
            continue
        match = matches_by_id[source_id]
        best = (match.get("top_candidates") or [None])[0]
        regression_reasons = possible_regression_reasons(match, best, source_id)
        if regression_reasons:
            verdict = "regression_v2_possible"
        elif v2["decision"] == "UNCERTAIN":
            verdict = "verification_humaine_necessaire"
        else:
            verdict = "reclassification_probablement_justifiee"
        summary[verdict] += 1
        audited.append(
            {
                "free_work": {
                    "source_id": source_id,
                    "title": match.get("free_work_title"),
                    "company": match.get("free_work_company"),
                    "location": match.get("free_work_location"),
                    "url": v2["free_work"].get("url"),
                    "url_resolution_method": v2["free_work"].get("url_resolution_method"),
                },
                "best_france_travail_candidate": candidate_details(best),
                "score": candidate_score(best),
                "v1_reason": v1.get("triage_reason_codes"),
                "v2_reason": v2.get("technical_reasons"),
                "v2_decision": v2["decision"],
                "human_explanation": v2.get("human_explanation"),
                "possible_v2_regression": bool(regression_reasons),
                "possible_v2_regression_reasons": regression_reasons,
                "audit_verdict": verdict,
            }
        )
    return sorted(audited, key=lambda item: item["free_work"]["source_id"]), dict(summary)


def write_reclassified_csv(path: Path, rows: list[dict]) -> None:
    """Write reclassified audit data to CSV."""
    fields = [
        "free_work_source_id",
        "free_work_title",
        "free_work_company",
        "v2_decision",
        "score",
        "exact_fingerprint",
        "v1_reason",
        "v2_reason",
        "possible_v2_regression",
        "possible_v2_regression_reasons",
        "audit_verdict",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            best = row["best_france_travail_candidate"] or {}
            writer.writerow(
                {
                    "free_work_source_id": row["free_work"]["source_id"],
                    "free_work_title": row["free_work"]["title"],
                    "free_work_company": row["free_work"]["company"],
                    "v2_decision": row["v2_decision"],
                    "score": row["score"],
                    "exact_fingerprint": best.get("exact_fingerprint"),
                    "v1_reason": reason_key(
                        row["v1_reason"]),
                    "v2_reason": reason_key(
                        row["v2_reason"]),
                    "possible_v2_regression": row["possible_v2_regression"],
                    "possible_v2_regression_reasons": reason_key(
                        row["possible_v2_regression_reasons"]),
                    "audit_verdict": row["audit_verdict"],
                })


def uncertainty_bucket(record: dict, match: dict) -> str:
    """Categorize UNCERTAIN cases by technical reason."""
    reasons = set(record.get("technical_reasons") or [])
    if "INSUFFICIENT_FREE_WORK_DATA" in reasons:
        return "UNCERTAIN_DATA_INSUFFICIENT"
    if reasons & {
        "COMPANY_MATCH_GEO_DIFFERS",
        "HIGH_SCORE_COMPANY_DIFFERS",
        "STRONG_TITLE_COMPANY_DIFFERS",
            "COMPANY_MATCH_TITLE_WEAK"}:
        return "UNCERTAIN_CONTRADICTORY_SIGNALS"
    if "MULTIPLE_CREDIBLE_CLOSE_CANDIDATES" in reasons:
        return "UNCERTAIN_MULTIPLE_CREDIBLE_CANDIDATES"
    if "INTERMEDIATE_SCORE" in reasons:
        return "UNCERTAIN_INTERMEDIATE_SCORE"
    return "UNCERTAIN_OTHER"


def band(value, size=10):
    """Group value into equal-width bands (default 10-point)."""
    if value is None:
        return "NONE"
    start = int(value // size) * size
    return f"{start}-{start + size - 1}"


def margin_band(best, second):
    """Categorize score margin between top2 candidates."""
    if best is None or second is None:
        return "NO_SECOND"
    margin = best - second
    if margin < 2:
        return "0-1"
    if margin < 5:
        return "2-4"
    if margin < 10:
        return "5-9"
    return "10_PLUS"


def analyze_uncertainties(v2_by_id, matches_by_id) -> dict:
    """Analyze V2 UNCERTAIN cases by reason, score, and potential solutions."""
    summary = Counter()
    score_bands = Counter()
    margin_bands = Counter()
    coverage_bands = Counter()
    reasons = Counter()
    reducible = Counter()
    examples = defaultdict(list)
    for source_id, record in v2_by_id.items():
        if record["decision"] != "UNCERTAIN":
            continue
        match = matches_by_id[source_id]
        candidates = match.get("top_candidates") or []
        best = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        best_score = candidate_score(best)
        second_score = candidate_score(second)
        bucket = uncertainty_bucket(record, match)
        summary[bucket] += 1
        score_bands[band(best_score)] += 1
        margin_bands[margin_band(best_score, second_score)] += 1
        coverage_bands[band((best or {}).get("evidence_coverage"), 20)] += 1
        reasons.update(record.get("technical_reasons") or [])
        if "INSUFFICIENT_FREE_WORK_DATA" in (record.get("technical_reasons") or []):
            reducible["meilleure_qualite_description"] += 1
        if any(r in (record.get("technical_reasons") or []) for r in ["COMPANY_MATCH_GEO_DIFFERS"]):
            reducible["meilleure_geographie"] += 1
        if any(r in (record.get("technical_reasons") or [])
               for r in ["HIGH_SCORE_COMPANY_DIFFERS", "STRONG_TITLE_COMPANY_DIFFERS"]):
            reducible["alias_entreprises"] += 1
        if bucket == "UNCERTAIN_INTERMEDIATE_SCORE":
            reducible["nouvelle_regle_metier"] += 1
        if bucket == "UNCERTAIN_MULTIPLE_CREDIBLE_CANDIDATES":
            reducible["aucune_automatisation_sure"] += 1
        if is_generic_title(match.get("free_work_title_normalized")):
            reducible["meilleure_normalisation"] += 1
        if len(examples[bucket]) < 5:
            examples[bucket].append(source_id)
    total = sum(summary.values())
    return {
        "total_uncertain": total,
        "buckets": dict(summary),
        "score_top1_bands": dict(sorted(score_bands.items())),
        "top1_top2_margin_bands": dict(sorted(margin_bands.items())),
        "coverage_bands": dict(sorted(coverage_bands.items())),
        "reason_counts": dict(reasons.most_common()),
        "potentially_reducible_by": dict(reducible),
        "examples_by_bucket": dict(examples),
    }


def top3_for_pilot(match: dict) -> list[dict]:
    """Extract top3 candidates with scores for pilot review."""
    rows = []
    for candidate in (match.get("top_candidates") or [])[:3]:
        rows.append({"id": candidate.get("france_travail_id"),
                     "title": candidate.get("title"),
                     "company": candidate.get("company_name"),
                     "location": candidate.get("postal_code"),
                     "score": candidate_score(candidate),
                     "human_explanation": human_explanation(match,
                                                            candidate,
                                                            "UNCERTAIN",
                                                            ["PILOT_CONTEXT"]),
                     })
    return rows


def pilot_entry(group, source_id, v1_by_id, v2_by_id, matches_by_id):
    """Build pilot review entry for human validation."""
    match = matches_by_id[source_id]
    v1 = v1_by_id[source_id]
    v2 = v2_by_id[source_id]
    return {
        "pilot_group": group,
        "free_work_id": source_id,
        "free_work_url": v2["free_work"].get("url"),
        "free_work_title": match.get("free_work_title"),
        "free_work_company": match.get("free_work_company"),
        "free_work_location": match.get("free_work_location"),
        "free_work_description_excerpt": match.get("free_work_description_excerpt"),
        "v1_decision": v1.get("triage_category"),
        "v2_decision": v2.get("decision"),
        "v1_reason": v1.get("triage_reason_codes"),
        "v2_reason": v2.get("technical_reasons"),
        "top_france_travail_candidates": top3_for_pilot(match),
        "human_decision": "",
        "human_selected_france_travail_id": "",
        "human_comment": "",
        "reviewed_at": "",
        "reviewer": "",
    }


def build_pilot(v1_by_id, v2_by_id, matches_by_id, reclassified):
    """Build 60-case pilot for human validation across 3 groups."""
    not_found_ids = [
        source_id for source_id, record in v2_by_id.items()
        if record["decision"] == "NOT_FOUND_IN_FT_SNAPSHOT"
    ]

    def nf_key(source_id):
        """Build NOT_FOUND case key from source_id and best FT candidate."""
        match = matches_by_id[source_id]
        best = (match.get("top_candidates") or [None])[0]
        return (candidate_score(best) or 0, -
                ((best or {}).get("evidence_coverage") or 0), source_id)
    group_a = sorted(not_found_ids, key=nf_key)[:20]
    group_b = [
        row["free_work"]["source_id"] for row in sorted(
            reclassified,
            key=lambda row: (
                not row["possible_v2_regression"],
                row["free_work"]["source_id"]))[
            :20]]
    uncertain_by_bucket = defaultdict(list)
    for source_id, record in v2_by_id.items():
        if record["decision"] == "UNCERTAIN":
            uncertain_by_bucket[uncertainty_bucket(
                record, matches_by_id[source_id])].append(source_id)
    group_c = []
    for bucket in [
        "UNCERTAIN_DATA_INSUFFICIENT",
        "UNCERTAIN_CONTRADICTORY_SIGNALS",
        "UNCERTAIN_MULTIPLE_CREDIBLE_CANDIDATES",
        "UNCERTAIN_INTERMEDIATE_SCORE",
        "UNCERTAIN_OTHER",
    ]:
        group_c.extend(sorted(uncertain_by_bucket[bucket])[:4])
    if len(group_c) < 20:
        remaining = sorted([sid for sid, rec in v2_by_id.items()
                           if rec["decision"] == "UNCERTAIN" and sid not in group_c])
        group_c.extend(remaining[:20 - len(group_c)])
    group_c = group_c[:20]

    pilot = []
    pilot.extend(
        pilot_entry(
            "A_NOT_FOUND_CONTROL",
            sid,
            v1_by_id,
            v2_by_id,
            matches_by_id) for sid in group_a)
    pilot.extend(
        pilot_entry(
            "B_V1_DUPLICATE_RECLASSIFIED",
            sid,
            v1_by_id,
            v2_by_id,
            matches_by_id) for sid in group_b)
    pilot.extend(pilot_entry("C_V2_UNCERTAIN", sid, v1_by_id, v2_by_id, matches_by_id)
                 for sid in group_c)
    if len(pilot) != 60:
        raise ValueError(f"Expected 60 pilot cases, got {len(pilot)}")
    if Counter(item["pilot_group"] for item in pilot) != {
        "A_NOT_FOUND_CONTROL": 20,
        "B_V1_DUPLICATE_RECLASSIFIED": 20,
        "C_V2_UNCERTAIN": 20,
    }:
        raise ValueError("Pilot group distribution mismatch")
    return pilot


def write_pilot_csv(path: Path, pilot: list[dict]) -> None:
    """Write pilot cases to CSV with candidate details."""
    fields = [
        "pilot_group", "free_work_id", "free_work_url", "free_work_title", "free_work_company",
        "free_work_location", "free_work_description_excerpt", "v1_decision", "v2_decision",
        "v1_reason", "v2_reason",
    ]
    for index in range(1, 4):
        fields += [f"ft_{index}_id",
                   f"ft_{index}_title",
                   f"ft_{index}_company",
                   f"ft_{index}_location",
                   f"ft_{index}_score",
                   f"ft_{index}_human_explanation"]
    fields += HUMAN_FIELDS
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for item in pilot:
            row = {field: "" for field in fields}
            for field in fields[:11]:
                value = item.get(field)
                row[field] = json.dumps(
                    value, ensure_ascii=False) if isinstance(
                    value, (dict, list)) else value
            for idx, candidate in enumerate(item["top_france_travail_candidates"], start=1):
                row[f"ft_{idx}_id"] = candidate["id"]
                row[f"ft_{idx}_title"] = candidate["title"]
                row[f"ft_{idx}_company"] = candidate["company"]
                row[f"ft_{idx}_location"] = candidate["location"]
                row[f"ft_{idx}_score"] = candidate["score"]
                row[f"ft_{idx}_human_explanation"] = json.dumps(
                    candidate["human_explanation"], ensure_ascii=False)
            writer.writerow(row)


def write_markdown(path: Path, matrix, reclassified_summary, historical, uncertainty, pilot_counts):
    """Write V1→V2 analysis summary to Markdown."""
    lines = ["# Analyse de transition V1 vers V2", ""]
    lines.append("## Matrice V1 -> V2")
    for source, dests in matrix.items():
        lines.append(f"- {source}")
        for dest, count in dests.items():
            lines.append(f"  - {dest}: {count}")
    lines.extend(["", "## Anciens doublons V1 reclassés"])
    for key in [
        "reclassification_probablement_justifiee",
        "regression_v2_possible",
            "verification_humaine_necessaire"]:
        lines.append(f"- {key}: {reclassified_summary.get(key, 0)}")
    lines.extend(["", "## Cas historiques"])
    for case in historical:
        lines.append(
            f"- {
                case['label']} ({
                case['source_id']}): V1={
                case['decision_v1']} ; V2={
                    case['decision_v2']} ; score={
                        case['score_top1']}")
    lines.extend(["", "## Incertitudes V2"])
    lines.append(f"- Total: {uncertainty['total_uncertain']}")
    for key, count in uncertainty["buckets"].items():
        lines.append(f"- {key}: {count}")
    lines.extend(["", "## Pilote humain V2"])
    for group, count in pilot_counts.items():
        lines.append(f"- {group}: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_analysis(v1_dir: Path, v2_dir: Path):
    """Run full V1→V2 transition analysis generating all reports."""
    v1_rows = load_json(v1_dir / "triage_results.json")
    matches = load_json(v1_dir / "candidate_matches.json")
    v2_by_id = load_jsonl_by_id(v2_dir / "triage_decisions.jsonl")
    matches_by_id = candidate_by_id(matches)
    v1_by_id = {str(row["free_work_source_id"]): row for row in v1_rows}

    transition_rows = build_transition_rows(v1_rows, v2_by_id, matches_by_id)
    matrix = build_matrix(transition_rows)
    reclassified, reclassified_summary = audit_reclassified_duplicates(
        v1_rows, v2_by_id, matches_by_id)
    uncertainty = analyze_uncertainties(v2_by_id, matches_by_id)
    historical = []
    for source_id, label in HISTORICAL_CASES.items():
        row = next(row for row in transition_rows if row["free_work_source_id"] == source_id)
        historical.append({"source_id": source_id, "label": label, **row})
    pilot = build_pilot(v1_by_id, v2_by_id, matches_by_id, reclassified)
    pilot_counts = dict(Counter(item["pilot_group"] for item in pilot))

    transition_payload = {
        "total_offers": len(transition_rows),
        "matrix": matrix,
        "historical_cases": historical,
        "rows": transition_rows,
    }
    write_json(v2_dir / "v1_v2_transition_analysis.json", transition_payload)
    write_transition_csv(v2_dir / "v1_v2_transition_analysis.csv", transition_rows)
    write_markdown(
        v2_dir /
        "v1_v2_transition_analysis.md",
        matrix,
        reclassified_summary,
        historical,
        uncertainty,
        pilot_counts)
    write_json(v2_dir / "v1_duplicates_reclassified_by_v2.json",
               {"summary": reclassified_summary, "cases": reclassified})
    write_reclassified_csv(v2_dir / "v1_duplicates_reclassified_by_v2.csv", reclassified)
    write_json(v2_dir / "v2_uncertainty_analysis.json", uncertainty)
    uncertainty_md = [
        "# Analyse des incertitudes V2",
        "",
        f"Total UNCERTAIN: {uncertainty['total_uncertain']}",
        "",
        "## Catégories",
    ]
    for key, count in uncertainty["buckets"].items():
        uncertainty_md.append(f"- {key}: {count}")
    uncertainty_md.extend(["", "## Réductibilité potentielle"])
    for key, count in uncertainty["potentially_reducible_by"].items():
        uncertainty_md.append(f"- {key}: {count}")
    (v2_dir / "v2_uncertainty_analysis.md").write_text("\n".join(uncertainty_md) + "\n", encoding="utf-8")  # pylint: disable=line-too-long
    write_json(v2_dir / "v2_calibration_pilot_60.json", pilot)
    write_pilot_csv(v2_dir / "v2_calibration_pilot_60.csv", pilot)
    (v2_dir / "v2_calibration_pilot_60_instructions.md").write_text(
        """# Instructions pilote humain V2

Annoter chaque ligne avec une des valeurs suivantes :

- PRESENT_CONFIRMED
- NOT_FOUND_CONFIRMED
- STILL_UNCERTAIN
- INVALID_DATA

Ne pas modifier les champs techniques. Le groupe A vérifie les offres classées non retrouvées, le groupe B cible les anciens doublons V1 reclassés par V2, le groupe C vérifie l'incertitude résiduelle.  # pylint: disable=line-too-long
""",
        encoding="utf-8",
    )
    return {
        "matrix": matrix,
        "reclassified_summary": reclassified_summary,
        "reclassified_count": len(reclassified),
        "uncertainty": uncertainty,
        "historical": historical,
        "pilot_counts": pilot_counts,
    }


def main():
    """Main entry point to analyze V1 to V2 transition."""
    parser = argparse.ArgumentParser(description="Analyse la transition Free-Work V1 vers V2.")
    parser.add_argument("--v1-run-id", default=V1_RUN_ID)
    parser.add_argument("--v2-run-id", default=V2_RUN_ID)
    args = parser.parse_args()
    base = PROCESSED_DATA_ROOT / "matching" / "free_work_vs_france_travail"
    result = run_analysis(base / args.v1_run_id, base / args.v2_run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
