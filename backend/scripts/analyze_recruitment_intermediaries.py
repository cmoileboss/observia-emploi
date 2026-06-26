import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"

from backend.scripts.free_work_triage_v2 import (
    compare_companies_with_advertiser_role,
    candidate_score,
    detect_advertiser_role,
    description_similarity,
    geography_is_compatible,
    strong_match_via_intermediary,
    title_similarity,
)


V1_RUN_ID = "run_triage_full_20260624"
V2_RUN_ID = "run_triage_v2_preview_20260624"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_jsonl_by_id(path: Path):
    rows = {}
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            rows[str(record["free_work"]["source_id"])] = record
    return rows


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def band(score):
    if score is None:
        return "NONE"
    start = int(score // 10) * 10
    return f"{start}-{start + 9}"


def analyze_intermediaries(base_dir: Path, fw_path: Path, ft_path: Path, v1_run_id: str = V1_RUN_ID, v2_run_id: str = V2_RUN_ID):
    v1_dir = base_dir / v1_run_id
    v2_dir = base_dir / v2_run_id
    candidate_matches = load_json(v1_dir / "candidate_matches.json")
    v1_by_id = {str(row["free_work_source_id"]): row for row in load_json(v1_dir / "triage_results.json")}
    v2_by_id = load_jsonl_by_id(v2_dir / "triage_decisions.jsonl")
    fw_by_id = {str(row["source_id"]): row for row in load_json(fw_path)}
    ft_by_id = {str(row["france_travail_id"]): row for row in load_json(ft_path)}

    counters = Counter()
    score_bands = Counter()
    v1_classes = Counter()
    v2_classes = Counter()
    expressions = Counter()
    zone_50_75 = []
    simulated_present = []
    possible_only = []
    detected = []

    for match in candidate_matches:
        source_id = str(match["free_work_source_id"])
        candidates = match.get("top_candidates") or []
        if not candidates:
            continue
        best = candidates[0]
        ft = ft_by_id.get(str(best.get("france_travail_id")), {})
        fw = fw_by_id.get(source_id, {})
        role = detect_advertiser_role(
            fw.get("description"),
            fw.get("candidate_profile"),
            fw.get("company_description"),
            ft.get("description"),
        )
        comp = compare_companies_with_advertiser_role(
            match.get("free_work_company"),
            best.get("company_name"),
            ((best.get("company_comparison") or {}).get("match_type") or "UNKNOWN"),
            role,
        )
        if role.advertiser_role == "UNKNOWN" or role.advertiser_role == "DIRECT_EMPLOYER":
            continue
        counters[role.advertiser_role] += 1
        for evidence in role.advertiser_role_evidence:
            expressions[evidence] += 1
        score = candidate_score(best)
        score_bands[band(score)] += 1
        v1_classes[v1_by_id[source_id]["triage_category"]] += 1
        v2_classes[v2_by_id[source_id]["decision"]] += 1
        if role.advertiser_role == "POSSIBLE_INTERMEDIARY":
            possible_only.append(source_id)
        item = {
            "free_work_source_id": source_id,
            "free_work_title": match.get("free_work_title"),
            "free_work_company": match.get("free_work_company"),
            "france_travail_id": best.get("france_travail_id"),
            "france_travail_title": best.get("title"),
            "france_travail_company": best.get("company_name"),
            "score": score,
            "title_similarity": title_similarity(best),
            "description_similarity": description_similarity(best),
            "geography": (best.get("geography_comparison") or {}).get("result"),
            "v1_decision": v1_by_id[source_id]["triage_category"],
            "v2_decision": v2_by_id[source_id]["decision"],
            "advertiser_role": role.advertiser_role,
            "advertiser_role_evidence": role.advertiser_role_evidence,
            "company_comparison_human": {
                "result": comp.result,
                "free_work_company": comp.free_work_company,
                "france_travail_company": comp.france_travail_company,
                "message": comp.message,
                "advertiser_role": comp.advertiser_role,
                "advertiser_role_evidence": comp.advertiser_role_evidence,
            },
            "simulated_reason": "STRONG_MATCH_VIA_RECRUITMENT_INTERMEDIARY" if strong_match_via_intermediary(best, role) else None,
        }
        detected.append(item)
        if score is not None and 50 <= score < 75:
            zone_50_75.append(item)
        if v2_by_id[source_id]["decision"] != "PRESENT_IN_FT_SNAPSHOT" and strong_match_via_intermediary(best, role):
            simulated_present.append(item)

    payload = {
        "summary": {
            "explicit_intermediary_detected": counters["RECRUITMENT_INTERMEDIARY"],
            "possible_intermediary_not_proven": counters["POSSIBLE_INTERMEDIARY"],
            "currently_uncertain": v2_classes["UNCERTAIN"],
            "currently_not_found": v2_classes["NOT_FOUND_IN_FT_SNAPSHOT"],
            "zone_50_75": len(zone_50_75),
            "potentially_reclassable_present": len(simulated_present),
            "historical_public_url_recoverable": False,
            "future_public_url_preservable": True,
        },
        "v1_distribution": dict(v1_classes),
        "v2_distribution": dict(v2_classes),
        "score_bands": dict(sorted(score_bands.items())),
        "expressions_detected": dict(expressions.most_common()),
        "potentially_reclassable_cases": simulated_present,
        "possible_only_ids": possible_only[:200],
        "detected_cases_sample": detected[:200],
    }
    write_json(v2_dir / "recruitment_intermediary_analysis.json", payload)
    md_lines = [
        "# Analyse cabinets de recrutement / clients finaux",
        "",
        f"- Preuve explicite d'intermédiation: {payload['summary']['explicit_intermediary_detected']}",
        f"- Intermédiation possible mais non prouvée: {payload['summary']['possible_intermediary_not_proven']}",
        f"- Actuellement UNCERTAIN: {payload['summary']['currently_uncertain']}",
        f"- Actuellement NOT_FOUND_IN_FT_SNAPSHOT: {payload['summary']['currently_not_found']}",
        f"- Zone 50-75: {payload['summary']['zone_50_75']}",
        f"- Potentiellement reclassables PRESENT: {payload['summary']['potentially_reclassable_present']}",
        "",
        "## Expressions détectées",
    ]
    for expression, count in payload["expressions_detected"].items():
        md_lines.append(f"- {expression}: {count}")
    md_lines.extend(["", "## Risques", "- Faux rapprochement si la mention client est générique et que plusieurs clients finaux sont plausibles.", "- Les ESN ne sont pas considérées comme intermédiaires sans preuve textuelle explicite."])
    (v2_dir / "recruitment_intermediary_analysis.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Analyse hors ligne les intermédiaires de recrutement dans les matches Free-Work / France Travail.")
    parser.add_argument("--v1-run-id", default=V1_RUN_ID)
    parser.add_argument("--v2-run-id", default=V2_RUN_ID)
    args = parser.parse_args()
    base = PROCESSED_DATA_ROOT / "matching" / "free_work_vs_france_travail"
    payload = analyze_intermediaries(
        base,
        PROCESSED_DATA_ROOT / "free_work" / "full_catalog" / "20260624_081715" / "offers_normalized.json",
        PROCESSED_DATA_ROOT / "france_travail" / "snapshots" / "current" / "france_travail_offers_snapshot.json",
        args.v1_run_id,
        args.v2_run_id,
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
