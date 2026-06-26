import argparse
import csv
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path


from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"
DEFAULT_RUN_ID = "run_triage_full_20260624"
EXPECTED_HUMAN_REVIEW_COUNT = 6397
EXPECTED_PRIORITIES = {"HIGH": 916, "MEDIUM": 1565, "LOW": 3916}
HUMAN_FIELDS = [
    "human_decision",
    "human_selected_france_travail_id",
    "human_comment",
    "reviewed_at",
    "reviewer",
]


class AnalysisError(RuntimeError):
    pass


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def score_band(score):
    if score is None:
        return "NO_SCORE"
    if score < 30:
        return "00_29"
    if score < 40:
        return "30_39"
    if score < 50:
        return "40_49"
    if score < 60:
        return "50_59"
    if score < 70:
        return "60_69"
    if score < 80:
        return "70_79"
    return "80_PLUS"


def margin_band(margin):
    if margin is None:
        return "NO_SECOND_CANDIDATE"
    if margin < 2:
        return "00_01"
    if margin < 5:
        return "02_04"
    if margin < 10:
        return "05_09"
    if margin < 20:
        return "10_19"
    return "20_PLUS"


def coverage_band(coverage):
    if coverage is None:
        return "UNKNOWN"
    if coverage < 55:
        return "LOW_LT_55"
    if coverage < 80:
        return "PARTIAL_55_79"
    if coverage < 95:
        return "GOOD_80_94"
    return "FULL_95_PLUS"


def get_score(candidate):
    if not candidate:
        return None
    if "preliminary_match_score" in candidate:
        return candidate.get("preliminary_match_score")
    return candidate.get("score_total")


def get_candidate_id(candidate):
    if not candidate:
        return None
    return str(candidate.get("france_travail_id") or candidate.get("source_id") or "")


def get_reason_key(reason_codes):
    if not reason_codes:
        return "NO_REASON"
    return "+".join(sorted(str(reason) for reason in reason_codes))


def is_company_compatible(raw_candidate):
    comparison = (raw_candidate or {}).get("company_comparison", {})
    return comparison.get("match_type") in {
        "EXACT_NORMALIZED",
        "ALIAS_MATCH",
        "CONTAINMENT_MATCH",
        "HIGH_SIMILARITY",
    }


def is_company_incompatible_or_missing(raw_candidate):
    comparison = (raw_candidate or {}).get("company_comparison", {})
    return comparison.get("match_type") in {"NO_MATCH", "MISSING", None, ""}


def is_geo_compatible(raw_candidate):
    comparison = (raw_candidate or {}).get("geography_comparison", {})
    return comparison.get("result") in {"EXACT_POSTAL_CODE", "SAME_LOCALITY", "SAME_DEPARTMENT"}


def is_geo_different(raw_candidate):
    comparison = (raw_candidate or {}).get("geography_comparison", {})
    return comparison.get("result") == "DIFFERENT"


def has_strong_fingerprint(raw_candidate):
    blocks = set((raw_candidate or {}).get("candidate_blocks", []))
    return bool(blocks & {"EXACT_FINGERPRINT", "FALLBACK_EXACT_FINGERPRINT"})


def title_similarity(raw_candidate):
    return ((raw_candidate or {}).get("title_comparison") or {}).get("sequence_similarity")


def description_similarity(raw_candidate):
    components = (raw_candidate or {}).get("components", {})
    return components.get("description_token_jaccard")


def candidate_set_signature(raw_candidates, limit=3):
    return tuple(get_candidate_id(candidate) for candidate in (raw_candidates or [])[:limit])


def validate_inputs(audit_hr, prioritized, triage_results):
    audit_ids = [str(item["free_work"]["source_id"]) for item in audit_hr]
    prioritized_ids = [str(item["free_work"]["source_id"]) for item in prioritized]
    triage_hr_ids = [
        str(item["free_work_source_id"])
        for item in triage_results
        if item.get("triage_category") == "HUMAN_REVIEW_REQUIRED"
    ]

    if len(audit_ids) != EXPECTED_HUMAN_REVIEW_COUNT:
        raise AnalysisError(f"Expected {EXPECTED_HUMAN_REVIEW_COUNT} audit HR cases, got {len(audit_ids)}")
    if len(set(audit_ids)) != len(audit_ids):
        duplicates = [item for item, count in Counter(audit_ids).items() if count > 1]
        raise AnalysisError(f"Duplicate Free-Work ids in audit HR file: {duplicates[:10]}")
    if set(audit_ids) != set(prioritized_ids):
        raise AnalysisError("Prioritized queue ids do not match audit_human_review_required ids")
    if set(audit_ids) != set(triage_hr_ids):
        raise AnalysisError("Triage HUMAN_REVIEW_REQUIRED ids do not match audit_human_review_required ids")

    bad_categories = [
        item["free_work"]["source_id"]
        for item in audit_hr
        if item.get("triage", {}).get("category") != "HUMAN_REVIEW_REQUIRED"
    ]
    if bad_categories:
        raise AnalysisError(f"Non HUMAN_REVIEW_REQUIRED category found in HR audit file: {bad_categories[:10]}")

    priority_counts = Counter(item.get("triage", {}).get("priority") for item in prioritized)
    if dict(priority_counts) != EXPECTED_PRIORITIES:
        raise AnalysisError(f"Priority counters mismatch: expected {EXPECTED_PRIORITIES}, got {dict(priority_counts)}")

    human_prefilled = []
    for item in prioritized:
        human_review = item.get("human_review", {})
        if any(human_review.get(key) for key in ("decision", "selected_france_travail_id", "comment", "reviewed_at")):
            human_prefilled.append(item["free_work"]["source_id"])
    if human_prefilled:
        raise AnalysisError(f"Human review fields are already filled for ids: {human_prefilled[:10]}")


def build_case_metrics(item, raw_match):
    raw_candidates = (raw_match or {}).get("top_candidates", [])
    best_raw = raw_candidates[0] if raw_candidates else None
    second_raw = raw_candidates[1] if len(raw_candidates) > 1 else None
    best_audit = item.get("best_france_travail_candidate")
    alternatives = item.get("alternative_candidates") or []
    best_score = get_score(best_raw) if best_raw else get_score(best_audit)
    second_score = get_score(second_raw) if second_raw else (alternatives[0].get("score_total") if alternatives else None)
    margin = round(best_score - second_score, 2) if best_score is not None and second_score is not None else None
    reason_codes = item.get("triage", {}).get("reason_codes", [])
    coverage = item.get("triage", {}).get("data_coverage")
    fw = item.get("free_work", {})
    title_sim = title_similarity(best_raw)
    desc_sim = description_similarity(best_raw)

    missing_data = []
    if not fw.get("title_raw"):
        missing_data.append("FREE_WORK_TITLE")
    if not fw.get("company_raw"):
        missing_data.append("FREE_WORK_COMPANY")
    if not fw.get("postal_code") and not fw.get("location_raw"):
        missing_data.append("FREE_WORK_LOCATION")
    if not fw.get("description_excerpt") and not fw.get("description_length"):
        missing_data.append("FREE_WORK_DESCRIPTION")
    if best_raw and ((best_raw.get("components") or {}).get("description_source") == "missing"):
        missing_data.append("COMPARABLE_DESCRIPTION")

    contradictions = []
    if best_raw and is_company_compatible(best_raw) and is_geo_different(best_raw):
        contradictions.append("COMPANY_COMPATIBLE_BUT_GEOGRAPHY_DIFFERENT")
    if best_raw and is_company_incompatible_or_missing(best_raw) and best_score is not None and best_score >= 60:
        contradictions.append("HIGH_SCORE_BUT_COMPANY_INCOMPATIBLE_OR_MISSING")
    if best_raw and is_geo_compatible(best_raw) and title_sim is not None and title_sim < 0.35:
        contradictions.append("GEOGRAPHY_COMPATIBLE_BUT_TITLE_WEAK")

    strong_fp = has_strong_fingerprint(best_raw)
    evidence = {
        "strong_fingerprint": strong_fp,
        "company_compatible": bool(best_raw and is_company_compatible(best_raw)),
        "company_incompatible_or_missing": bool(best_raw and is_company_incompatible_or_missing(best_raw)),
        "geography_compatible": bool(best_raw and is_geo_compatible(best_raw)),
        "geography_different": bool(best_raw and is_geo_different(best_raw)),
        "title_similarity": title_sim,
        "description_similarity": desc_sim,
    }
    weak_only = bool(raw_candidates) and all((get_score(candidate) or 0) < 40 for candidate in raw_candidates)
    close_candidates = bool(margin is not None and margin < 5 and best_score is not None and best_score >= 50)
    insufficient_data = bool(coverage is None or coverage < 80 or missing_data)

    return {
        "free_work_id": str(fw.get("source_id")),
        "priority": item.get("triage", {}).get("priority"),
        "reason_codes": reason_codes,
        "reason_key": get_reason_key(reason_codes),
        "best_score": best_score,
        "second_score": second_score,
        "top1_top2_margin": margin,
        "candidate_count": len(raw_candidates) if raw_candidates else len(alternatives) + (1 if best_audit else 0),
        "data_coverage": coverage,
        "title_similarity": title_sim,
        "description_similarity": desc_sim,
        "score_breakdown": (best_raw or best_audit or {}).get("score_breakdown") or (best_raw or {}).get("components"),
        "evidence": evidence,
        "missing_data": sorted(set(missing_data)),
        "contradictions": contradictions,
        "only_weak_candidates": weak_only,
        "multiple_close_candidates": close_candidates,
        "insufficient_data": insufficient_data,
        "best_candidate_id": get_candidate_id(best_raw) or get_candidate_id(best_audit),
        "top_candidate_ids": candidate_set_signature(raw_candidates),
    }


def add_counter(counter, *keys):
    cursor = counter
    for key in keys[:-1]:
        cursor = cursor.setdefault(str(key), {})
    last = str(keys[-1])
    cursor[last] = cursor.get(last, 0) + 1


def build_analysis(cases):
    priority_counts = Counter(case["priority"] for case in cases)
    reason_counts = Counter(case["reason_key"] for case in cases)
    score_distribution = Counter(score_band(case["best_score"]) for case in cases)
    margin_distribution = Counter(margin_band(case["top1_top2_margin"]) for case in cases)
    candidate_count_distribution = Counter(str(case["candidate_count"]) for case in cases)
    coverage_distribution = Counter(coverage_band(case["data_coverage"]) for case in cases)

    priority_by_score = {}
    priority_by_reason = {}
    coverage_by_score = {}
    for case in cases:
        add_counter(priority_by_score, case["priority"], score_band(case["best_score"]))
        add_counter(priority_by_reason, case["priority"], case["reason_key"])
        add_counter(coverage_by_score, coverage_band(case["data_coverage"]), score_band(case["best_score"]))

    return {
        "summary": {
            "analyzed_cases": len(cases),
            "priority_counts": dict(sorted(priority_counts.items())),
            "only_weak_candidates": sum(1 for case in cases if case["only_weak_candidates"]),
            "multiple_close_candidates": sum(1 for case in cases if case["multiple_close_candidates"]),
            "contradictory_evidence_cases": sum(1 for case in cases if case["contradictions"]),
            "insufficient_data_cases": sum(1 for case in cases if case["insufficient_data"]),
        },
        "distributions": {
            "reason_counts": dict(reason_counts.most_common()),
            "best_score_bands": dict(sorted(score_distribution.items())),
            "top1_top2_margin_bands": dict(sorted(margin_distribution.items())),
            "candidate_count": dict(sorted(candidate_count_distribution.items(), key=lambda item: int(item[0]))),
            "data_coverage_bands": dict(sorted(coverage_distribution.items())),
        },
        "cross_tabs": {
            "priority_by_score": priority_by_score,
            "priority_by_reason": priority_by_reason,
            "coverage_by_score": coverage_by_score,
        },
        "case_metrics": cases,
    }


def probably_new_explanation(case):
    return (
        "Simulation uniquement : le meilleur candidat France Travail reste faible, "
        "aucune empreinte forte n'est présente, les signaux de titre/description/entreprise "
        "ne convergent pas assez pour justifier une revue individuelle prioritaire."
    )


def is_simulated_probably_new(case, policy="BALANCED"):
    score_limits = {"CONSERVATIVE": 35, "BALANCED": 40, "AGGRESSIVE": 45}
    score_limit = score_limits[policy]
    evidence = case["evidence"]
    if case["best_score"] is None:
        return False
    if case["best_score"] >= score_limit:
        return False
    if case["data_coverage"] is None or case["data_coverage"] < 70:
        return False
    if evidence["strong_fingerprint"]:
        return False
    if case["contradictions"] and policy == "CONSERVATIVE":
        return False
    title_ok = evidence["title_similarity"] is None or evidence["title_similarity"] < 0.55
    desc_ok = evidence["description_similarity"] is None or evidence["description_similarity"] < 0.25
    no_convergence = not (
        evidence["company_compatible"]
        and evidence["geography_compatible"]
        and evidence["title_similarity"] is not None
        and evidence["title_similarity"] >= 0.55
    )
    return title_ok and desc_ok and evidence["company_incompatible_or_missing"] and no_convergence


def build_simulated_probably_new(prioritized_by_id, matches_by_id, cases):
    simulated = []
    for case in cases:
        if not is_simulated_probably_new(case, "BALANCED"):
            continue
        item = prioritized_by_id[case["free_work_id"]]
        raw_match = matches_by_id.get(case["free_work_id"], {})
        best_raw = (raw_match.get("top_candidates") or [None])[0]
        simulated.append(
            {
                "free_work_id": case["free_work_id"],
                "free_work": item["free_work"],
                "best_france_travail_candidate": item.get("best_france_travail_candidate"),
                "raw_best_candidate_score_detail": (best_raw or {}).get("components"),
                "score": case["best_score"],
                "evidence_present": {key: value for key, value in case["evidence"].items() if value},
                "evidence_absent": [key for key, value in case["evidence"].items() if not value],
                "current_category": "HUMAN_REVIEW_REQUIRED",
                "simulated_category": "PROBABLY_NEW",
                "simulated_rule": "BALANCED_LOW_SIGNAL_PROBABLY_NEW_SIMULATION",
                "human_explanation": probably_new_explanation(case),
            }
        )
    simulated.sort(key=lambda item: (item["score"], item["free_work_id"]))
    return simulated


GENERIC_TITLE_TOKENS = {
    "developpeur",
    "developer",
    "consultant",
    "ingenieur",
    "chef",
    "projet",
    "data",
    "technicien",
    "administrateur",
}


def is_generic_title(title_norm):
    tokens = set(str(title_norm or "").split())
    return len(tokens) < 3 or tokens.issubset(GENERIC_TITLE_TOKENS)


def cluster_key(item, case):
    fw = item.get("free_work", {})
    title_norm = fw.get("title_normalized")
    company_norm = fw.get("company_normalized")
    postal_code = fw.get("postal_code")
    if is_generic_title(title_norm):
        return None
    if not company_norm and not postal_code and not case["best_candidate_id"]:
        return None
    return (
        title_norm or "",
        company_norm or "",
        postal_code or "",
        case["best_candidate_id"] or "",
        case["reason_key"],
        score_band(case["best_score"]),
    )


def build_clusters(prioritized_by_id, cases):
    by_key = defaultdict(list)
    cases_by_id = {case["free_work_id"]: case for case in cases}
    for case in cases:
        item = prioritized_by_id[case["free_work_id"]]
        key = cluster_key(item, case)
        if key:
            by_key[key].append(case["free_work_id"])

    clusters = []
    clustered_ids = set()
    for index, (key, member_ids) in enumerate(sorted(by_key.items(), key=lambda entry: (-len(entry[1]), entry[0])), start=1):
        if len(member_ids) < 2:
            continue
        member_cases = [cases_by_id[member_id] for member_id in sorted(member_ids)]
        score_values = [case["best_score"] for case in member_cases if case["best_score"] is not None]
        coverages = {case["data_coverage"] for case in member_cases}
        candidate_sets = {case["top_candidate_ids"] for case in member_cases}
        priorities = {case["priority"] for case in member_cases}
        safe = (
            len(coverages) == 1
            and len(candidate_sets) == 1
            and len(priorities) == 1
            and score_values
            and max(score_values) - min(score_values) <= 2
        )
        title_norm, company_norm, postal_code, best_candidate_id, reason_key, score_range = key
        representative_id = sorted(member_ids)[0]
        clusters.append(
            {
                "cluster_id": f"AMB-{index:04d}",
                "cluster_size": len(member_ids),
                "grouping_reasons": [
                    "same_normalized_title",
                    "same_normalized_company" if company_norm else "company_missing_or_empty",
                    "same_postal_code" if postal_code else "postal_code_missing_or_empty",
                    "same_best_france_travail_candidate" if best_candidate_id else "best_candidate_missing",
                    "same_triage_reason",
                    "same_score_band",
                ],
                "shared_fields": {
                    "title_normalized": title_norm,
                    "company_normalized": company_norm,
                    "postal_code": postal_code,
                    "best_france_travail_candidate_id": best_candidate_id,
                    "reason_key": reason_key,
                    "score_band": score_range,
                },
                "differing_fields": {
                    "priorities": sorted(priorities),
                    "data_coverages": sorted(coverages),
                    "top_candidate_sets": [list(candidate_set) for candidate_set in sorted(candidate_sets)],
                    "score_min": min(score_values) if score_values else None,
                    "score_max": max(score_values) if score_values else None,
                },
                "representative_case": representative_id,
                "member_free_work_ids": sorted(member_ids),
                "top_france_travail_candidates": list(member_cases[0]["top_candidate_ids"]),
                "safe_for_bulk_review": safe,
            }
        )
        clustered_ids.update(member_ids)

    sizes = [cluster["cluster_size"] for cluster in clusters]
    safe_savings = sum(cluster["cluster_size"] - 1 for cluster in clusters if cluster["safe_for_bulk_review"])
    all_group_savings = sum(cluster["cluster_size"] - 1 for cluster in clusters)
    return {
        "summary": {
            "group_count": len(clusters),
            "clustered_case_count": len(clustered_ids),
            "isolated_case_count": len(cases) - len(clustered_ids),
            "average_cluster_size": round(statistics.mean(sizes), 2) if sizes else 0,
            "median_cluster_size": statistics.median(sizes) if sizes else 0,
            "largest_groups": sorted(
                [
                    {
                        "cluster_id": cluster["cluster_id"],
                        "cluster_size": cluster["cluster_size"],
                        "safe_for_bulk_review": cluster["safe_for_bulk_review"],
                    }
                    for cluster in clusters
                ],
                key=lambda item: (-item["cluster_size"], item["cluster_id"]),
            )[:10],
            "theoretical_decisions_saved_if_all_groups_reviewed_in_bulk": all_group_savings,
            "theoretical_decisions_saved_safe_bulk_only": safe_savings,
        },
        "clusters": clusters,
    }


def select_calibration_sample(prioritized_by_id, cases, clusters, max_size=180):
    cases_by_id = {case["free_work_id"]: case for case in cases}
    cluster_member_ids = {member_id for cluster in clusters["clusters"] for member_id in cluster["member_free_work_ids"]}

    buckets = defaultdict(list)
    for case in cases:
        bucket = (
            case["priority"],
            case["reason_key"],
            score_band(case["best_score"]),
            coverage_band(case["data_coverage"]),
            margin_band(case["top1_top2_margin"]),
            "GROUPED" if case["free_work_id"] in cluster_member_ids else "ISOLATED",
        )
        buckets[bucket].append(case["free_work_id"])

    selected = []
    seen = set()
    priorities = ["HIGH", "MEDIUM", "LOW"]
    base_quota = max_size // len(priorities)
    quotas = {priority: base_quota for priority in priorities}
    quotas["HIGH"] += max_size - sum(quotas.values())

    def take_from_priority(priority, quota):
        priority_buckets = [
            (bucket, ids)
            for bucket, ids in buckets.items()
            if bucket[0] == priority
        ]
        priority_buckets.sort(key=lambda item: (len(item[1]), item[0]))
        taken = []
        added = False
        while len(taken) < quota:
            added = False
            for _, ids in priority_buckets:
                ordered_ids = sorted(
                    ids,
                    key=lambda value: (
                        prioritized_by_id[value]["free_work"].get("title_normalized") or "",
                        prioritized_by_id[value]["free_work"].get("company_normalized") or "",
                        prioritized_by_id[value]["free_work"].get("postal_code") or "",
                        value,
                    ),
                )
                for fw_id in ordered_ids:
                    if fw_id not in seen:
                        seen.add(fw_id)
                        taken.append(fw_id)
                        added = True
                        break
                if len(taken) >= quota:
                    break
            if not added:
                break
        return taken

    for priority in priorities:
        selected.extend(take_from_priority(priority, quotas[priority]))

    if len(selected) < max_size:
        sorted_buckets = sorted(buckets.items(), key=lambda item: (item[0], len(item[1])))
        while len(selected) < max_size:
            added = False
            for _, ids in sorted_buckets:
                for fw_id in sorted(ids, key=lambda value: (prioritized_by_id[value]["free_work"].get("title_normalized") or "", value)):
                    if fw_id not in seen:
                        seen.add(fw_id)
                        selected.append(fw_id)
                        added = True
                        break
                if len(selected) >= max_size:
                    break
            if not added:
                break

    selected = selected[:max_size]

    sample = []
    for fw_id in selected:
        item = prioritized_by_id[fw_id]
        candidates = []
        best = item.get("best_france_travail_candidate")
        if best:
            candidates.append(best)
        candidates.extend(item.get("alternative_candidates") or [])
        formatted_candidates = []
        for rank, candidate in enumerate(candidates[:3], start=1):
            formatted_candidates.append(
                {
                    "france_travail_id": candidate.get("source_id"),
                    "source_url": candidate.get("source_url"),
                    "title": candidate.get("title_raw"),
                    "company": candidate.get("company_raw"),
                    "location": candidate.get("location_raw") or candidate.get("postal_code"),
                    "date": candidate.get("published_at"),
                    "description_excerpt": candidate.get("description_excerpt"),
                    "score_total": candidate.get("score_total"),
                    "score_detail": candidate.get("score_breakdown"),
                    "evidence": candidate.get("evidence"),
                    "rank": rank,
                }
            )
        case = cases_by_id[fw_id]
        entry = {
            "selection_context": {
                "priority": case["priority"],
                "reason_codes": case["reason_codes"],
                "score_band": score_band(case["best_score"]),
                "coverage_band": coverage_band(case["data_coverage"]),
                "margin_band": margin_band(case["top1_top2_margin"]),
                "clustered": fw_id in cluster_member_ids,
            },
            "free_work": {
                "source_id": item["free_work"].get("source_id"),
                "source_url": item["free_work"].get("source_url"),
                "title": item["free_work"].get("title_raw"),
                "company": item["free_work"].get("company_raw"),
                "location": item["free_work"].get("location_raw") or item["free_work"].get("postal_code"),
                "date": item["free_work"].get("published_at"),
                "description_excerpt": item["free_work"].get("description_excerpt"),
            },
            "top_france_travail_candidates": formatted_candidates,
            "human_decision": "",
            "human_selected_france_travail_id": "",
            "human_comment": "",
            "reviewed_at": "",
            "reviewer": "",
            "allowed_human_decisions": [
                "DUPLICATE_CONFIRMED",
                "NEW_CONFIRMED",
                "STILL_UNCERTAIN",
                "INVALID_DATA",
            ],
        }
        sample.append(entry)
    return sample


def write_sample_csv(path, sample):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "free_work_id",
                "priority",
                "reason_codes",
                "score_band",
                "coverage_band",
                "margin_band",
                "clustered",
                "free_work_url",
                "free_work_title",
                "free_work_company",
                "free_work_location",
                "best_france_travail_id",
                "best_score",
                *HUMAN_FIELDS,
            ],
        )
        writer.writeheader()
        for item in sample:
            best = item["top_france_travail_candidates"][0] if item["top_france_travail_candidates"] else {}
            context = item["selection_context"]
            writer.writerow(
                {
                    "free_work_id": item["free_work"]["source_id"],
                    "priority": context["priority"],
                    "reason_codes": "|".join(context["reason_codes"]),
                    "score_band": context["score_band"],
                    "coverage_band": context["coverage_band"],
                    "margin_band": context["margin_band"],
                    "clustered": context["clustered"],
                    "free_work_url": item["free_work"]["source_url"],
                    "free_work_title": item["free_work"]["title"],
                    "free_work_company": item["free_work"]["company"],
                    "free_work_location": item["free_work"]["location"],
                    "best_france_travail_id": best.get("france_travail_id"),
                    "best_score": best.get("score_total"),
                    "human_decision": "",
                    "human_selected_france_travail_id": "",
                    "human_comment": "",
                    "reviewed_at": "",
                    "reviewer": "",
                }
            )


def simulate_policies(cases, clusters):
    policies = {}
    duplicate_rules = {
        "CONSERVATIVE_REDUCTION": lambda case: False,
        "BALANCED_REDUCTION": lambda case: (
            case["best_score"] is not None
            and case["best_score"] >= 80
            and case["evidence"]["company_compatible"]
            and case["evidence"]["geography_compatible"]
            and case["evidence"]["title_similarity"] is not None
            and case["evidence"]["title_similarity"] >= 0.9
            and not case["contradictions"]
        ),
        "AGGRESSIVE_REDUCTION": lambda case: (
            case["best_score"] is not None
            and case["best_score"] >= 70
            and case["evidence"]["company_compatible"]
            and case["evidence"]["title_similarity"] is not None
            and case["evidence"]["title_similarity"] >= 0.8
            and case["top1_top2_margin"] is not None
            and case["top1_top2_margin"] >= 5
        ),
    }
    probably_new_policy = {
        "CONSERVATIVE_REDUCTION": "CONSERVATIVE",
        "BALANCED_REDUCTION": "BALANCED",
        "AGGRESSIVE_REDUCTION": "AGGRESSIVE",
    }
    grouped_ids = {
        member_id
        for cluster in clusters["clusters"]
        if cluster["safe_for_bulk_review"]
        for member_id in cluster["member_free_work_ids"]
    }
    for policy, pn_policy in probably_new_policy.items():
        moved_new = {case["free_work_id"] for case in cases if is_simulated_probably_new(case, pn_policy)}
        moved_duplicate = {
            case["free_work_id"]
            for case in cases
            if case["free_work_id"] not in moved_new and duplicate_rules[policy](case)
        }
        remaining = [
            case
            for case in cases
            if case["free_work_id"] not in moved_new and case["free_work_id"] not in moved_duplicate
        ]
        remaining_ids = {case["free_work_id"] for case in remaining}
        regroupable = len(grouped_ids & remaining_ids)
        safe_savings = sum(
            max(0, len(set(cluster["member_free_work_ids"]) & remaining_ids) - 1)
            for cluster in clusters["clusters"]
            if cluster["safe_for_bulk_review"]
        )
        policies[policy] = {
            "rules_simulated": {
                "probably_new": pn_policy,
                "duplicate": "NONE" if policy == "CONSERVATIVE_REDUCTION" else "strong score + compatible company/title/geography simulation",
                "bulk_review": "safe_for_bulk_review clusters only",
            },
            "moved_to_probably_new": len(moved_new),
            "moved_to_duplicate_high_confidence": len(moved_duplicate),
            "remaining_individual_review": len(remaining) - regroupable,
            "regroupable_cases": regroupable,
            "theoretical_human_decisions": len(remaining) - safe_savings,
            "risks": policy_risks(policy),
            "recommended_without_human_calibration": policy == "CONSERVATIVE_REDUCTION",
        }
    return policies


def policy_risks(policy):
    if policy == "CONSERVATIVE_REDUCTION":
        return [
            "Réduction limitée de charge.",
            "Seuils non validés statistiquement avant annotation humaine.",
        ]
    if policy == "BALANCED_REDUCTION":
        return [
            "Risque modéré de classer nouvelle une offre réellement dupliquée avec signaux faibles.",
            "Nécessite calibration humaine avant activation.",
        ]
    return [
        "Risque élevé de faux nouveaux et de faux doublons.",
        "Ne doit pas être recommandée sans validation humaine large.",
    ]


def write_markdown(path, analysis, simulated_count, clusters, policies):
    lines = [
        "# Analyse des ambiguïtés Free-Work / France Travail",
        "",
        "Cette analyse utilise uniquement les résultats déjà calculés du run `run_triage_full_20260624`.",
        "Elle ne modifie aucune catégorie officielle et ne remplit aucune décision humaine.",
        "",
        "## Synthèse",
        "",
        f"- Cas analysés : {analysis['summary']['analyzed_cases']}",
        f"- Candidats faibles uniquement : {analysis['summary']['only_weak_candidates']}",
        f"- Plusieurs candidats proches : {analysis['summary']['multiple_close_candidates']}",
        f"- Preuves contradictoires : {analysis['summary']['contradictory_evidence_cases']}",
        f"- Données insuffisantes : {analysis['summary']['insufficient_data_cases']}",
        f"- Cas simulés comme probablement nouveaux : {simulated_count}",
        f"- Groupes homogènes détectés : {clusters['summary']['group_count']}",
        f"- Cas isolés : {clusters['summary']['isolated_case_count']}",
        f"- Décisions économisées en revue groupée sûre : {clusters['summary']['theoretical_decisions_saved_safe_bulk_only']}",
        "",
        "## Priorités",
        "",
    ]
    for priority, count in analysis["summary"]["priority_counts"].items():
        lines.append(f"- {priority}: {count}")
    lines.extend(["", "## Raisons de triage principales", ""])
    for reason, count in list(analysis["distributions"]["reason_counts"].items())[:20]:
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "## Distribution des scores du meilleur candidat", ""])
    for band, count in analysis["distributions"]["best_score_bands"].items():
        lines.append(f"- {band}: {count}")
    lines.extend(["", "## Politiques simulées", ""])
    for name, policy in policies.items():
        lines.append(f"### {name}")
        lines.append(f"- Vers `PROBABLY_NEW`: {policy['moved_to_probably_new']}")
        lines.append(f"- Vers `DUPLICATE_HIGH_CONFIDENCE`: {policy['moved_to_duplicate_high_confidence']}")
        lines.append(f"- Revue individuelle restante: {policy['remaining_individual_review']}")
        lines.append(f"- Cas regroupables: {policy['regroupable_cases']}")
        lines.append(f"- Décisions humaines théoriques: {policy['theoretical_human_decisions']}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rules_proposal(path):
    path.write_text(
        """# Proposition non activée de règles de triage V2

Cette proposition est une base de discussion. Elle ne modifie pas `CONSERVATIVE_RULESET_V1` et ne doit pas être activée avant annotation de l'échantillon de calibration.

## 1. Doublons à preuves fortes

Classer automatiquement seulement lorsque plusieurs signaux forts convergent : score du meilleur candidat élevé, titre très similaire, entreprise compatible, géographie compatible, marge suffisante avec le deuxième candidat et absence de contradiction. Une empreinte forte reste un signal majeur, mais elle doit rester auditée.

## 2. Nouvelles offres à preuves faibles concordantes

Simuler `PROBABLY_NEW` lorsque la couverture Free-Work est suffisante, le meilleur score reste faible, aucune empreinte forte n'est présente, le titre et la description sont peu compatibles, l'entreprise est incompatible ou absente côté candidats, et aucun faisceau entreprise + titre + géographie ne converge.

## 3. Groupes homogènes pour revue commune

Regrouper les cas partageant titre normalisé, entreprise normalisée, localisation, meilleur candidat France Travail, raisons de triage, bande de score et ensemble de candidats proche. Un groupe ne doit pas reposer seulement sur un titre générique. `safe_for_bulk_review` doit rester faux dès qu'une différence de priorité, de couverture, de candidats ou de score est significative.

## 4. Noyau réellement ambigu pour revue individuelle

Conserver en revue individuelle les cas à score intermédiaire, marge Top 1 / Top 2 faible, signaux contradictoires, données insuffisantes ou candidats crédibles multiples. Ce noyau doit rester priorisé après calibration humaine.

## Garde-fous

- Aucun seuil proposé ici n'est validé sans annotation humaine.
- La politique agressive ne doit pas être recommandée sans validation humaine large.
- Les décisions humaines doivent rester vides dans les fichiers de préparation.
- Les sorties V2 doivent rester déterministes et traçables.
""",
        encoding="utf-8",
    )


def run_analysis(run_dir):
    start = time.time()
    print("[1/6] Chargement des fichiers existants")
    audit_hr = load_json(run_dir / "audit_human_review_required.json")
    prioritized = load_json(run_dir / "human_review_queue_prioritized.json")
    triage_results = load_json(run_dir / "triage_results.json")
    candidate_matches = load_json(run_dir / "candidate_matches.json")

    print("[2/6] Validation de cohérence")
    validate_inputs(audit_hr, prioritized, triage_results)
    prioritized_by_id = {str(item["free_work"]["source_id"]): item for item in prioritized}
    matches_by_id = {str(item["free_work_source_id"]): item for item in candidate_matches}

    print("[3/6] Extraction des métriques par cas")
    cases = []
    total = len(prioritized)
    last = time.time()
    for index, item in enumerate(prioritized, start=1):
        fw_id = str(item["free_work"]["source_id"])
        cases.append(build_case_metrics(item, matches_by_id.get(fw_id)))
        now = time.time()
        if index == total or index % 1000 == 0 or now - last >= 5:
            elapsed = now - start
            speed = index / elapsed if elapsed else 0
            eta = (total - index) / speed if speed else 0
            print(
                f"[3/6] {index}/{total} - {index / total * 100:.2f}% - "
                f"elapsed {elapsed:.1f}s - heartbeat {time.strftime('%H:%M:%S')} - "
                f"{speed:.1f} cas/s - ETA {eta:.1f}s"
            )
            last = now

    print("[4/6] Construction des analyses, simulations et groupes")
    analysis = build_analysis(cases)
    simulated_probably_new = build_simulated_probably_new(prioritized_by_id, matches_by_id, cases)
    clusters = build_clusters(prioritized_by_id, cases)
    sample = select_calibration_sample(prioritized_by_id, cases, clusters)
    policies = simulate_policies(cases, clusters)
    analysis["policy_simulations"] = policies
    analysis["cluster_summary"] = clusters["summary"]
    analysis["simulated_probably_new_count"] = len(simulated_probably_new)
    analysis["calibration_sample_summary"] = {
        "sample_size": len(sample),
        "priority_counts": dict(Counter(item["selection_context"]["priority"] for item in sample)),
        "grouped_cases": sum(1 for item in sample if item["selection_context"]["clustered"]),
        "isolated_cases": sum(1 for item in sample if not item["selection_context"]["clustered"]),
    }

    print("[5/6] Écriture des fichiers d'analyse")
    write_json(run_dir / "ambiguity_analysis.json", analysis)
    write_markdown(run_dir / "ambiguity_analysis.md", analysis, len(simulated_probably_new), clusters, policies)
    write_json(run_dir / "simulated_probably_new_candidates.json", simulated_probably_new)
    write_json(run_dir / "ambiguity_clusters.json", clusters)
    write_json(run_dir / "ambiguity_calibration_sample.json", sample)
    write_sample_csv(run_dir / "ambiguity_calibration_sample.csv", sample)
    write_json(run_dir / "reduction_policy_simulations.json", policies)
    write_rules_proposal(run_dir / "triage_rules_v2_proposal.md")

    print("[6/6] Contrôles finaux")
    if len(cases) != EXPECTED_HUMAN_REVIEW_COUNT:
        raise AnalysisError("Final analyzed case count mismatch")
    if len({case["free_work_id"] for case in cases}) != len(cases):
        raise AnalysisError("Duplicate analyzed case id detected")
    for item in sample:
        for field in HUMAN_FIELDS:
            if item.get(field) != "":
                raise AnalysisError(f"Human field {field} was prefilled")

    elapsed = time.time() - start
    print(f"Analyse terminée en {elapsed:.1f}s")
    return {
        "analysis": analysis,
        "clusters": clusters,
        "simulated_probably_new": simulated_probably_new,
        "sample": sample,
    }


def main():
    parser = argparse.ArgumentParser(description="Analyse hors ligne des ambiguïtés Free-Work / France Travail.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    args = parser.parse_args()
    run_dir = PROCESSED_DATA_ROOT / "matching" / "free_work_vs_france_travail" / args.run_id
    if not run_dir.exists():
        raise SystemExit(f"Run directory not found: {run_dir}")
    run_analysis(run_dir)


if __name__ == "__main__":
    main()
