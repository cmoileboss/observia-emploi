"""."""
import json
import hashlib
import csv
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"


def get_sha256(file_path: Path) -> str:
    """."""
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_description_excerpt(desc: str, length: int = 150) -> str:
    """."""
    if not desc:
        return ""
    desc_str = str(desc).strip()
    if len(desc_str) > length:
        return desc_str[:length] + "..."
    return desc_str


def generate_explanation(category: str, reason_codes: list, best_cand: dict) -> str:
    """."""
    if category == "DUPLICATE_HIGH_CONFIDENCE":
        if "EXACT_FINGERPRINT" in reason_codes:
            return "Doublon à forte confiance détecté par concordance exacte d'une empreinte (soit Titre + Entreprise + Code Postal, soit Titre + Code Postal, soit Titre + Entreprise, soit Titre + Description)."  # pylint: disable=line-too-long
        return "Titre presque identique, entreprise compatible et même code postal. La description présente également une forte similarité."  # pylint: disable=line-too-long
    elif category == "PROBABLY_NEW":
        if not best_cand:
            return "Aucun candidat France Travail crédible n’a été identifié pour considérer l’offre comme un doublon probable."  # pylint: disable=line-too-long
        score = best_cand.get("preliminary_match_score", 0)
        return f"Aucun candidat France Travail suffisamment crédible n’a été identifié pour considérer l’offre comme un doublon probable. Le meilleur résultat possède un score de {  # pylint: disable=line-too-long
            score:.2f}."
    elif category == "HUMAN_REVIEW_REQUIRED":
        ", ".join(reason_codes)
        if "AMBIGUOUS_SCORE_MARGIN" in reason_codes:
            return "Plusieurs candidats possèdent des scores de similarité très proches. Une vérification humaine est nécessaire pour trancher."  # pylint: disable=line-too-long
        if "COMPANY_MATCH_GEO_DIFFERS" in reason_codes:
            return "L'entreprise correspond, mais la localisation géographique est différente. Une vérification humaine est nécessaire."  # pylint: disable=line-too-long
        if "COMPANY_DIFFERS_STRONG_CONTENT" in reason_codes:
            return "Le titre et la description sont très similaires mais l'entreprise diffère. Une vérification humaine est nécessaire."  # pylint: disable=line-too-long
        return "Le titre et la description sont proches, mais l’entreprise et la localisation diffèrent. Une vérification humaine est nécessaire."  # pylint: disable=line-too-long
    return "Erreur lors du traitement de l'offre."


def main():
    """."""
    run_id = "run_triage_full_20260624"
    run_dir = PROCESSED_DATA_ROOT / "matching" / "free_work_vs_france_travail" / run_id

    fw_input_path = PROCESSED_DATA_ROOT / "free_work" / \
        "full_catalog" / "20260624_081715" / "offers_normalized.json"
    ft_input_path = PROCESSED_DATA_ROOT / "france_travail" / \
        "snapshots" / "current" / "france_travail_offers_snapshot.json"

    candidate_matches_path = run_dir / "candidate_matches.json"
    triage_results_path = run_dir / "triage_results.json"

    if not run_dir.exists():
        print(f"Error: Run directory {run_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    print("Loading datasets...")
    fw_data = json.load(fw_input_path.open("r", encoding="utf-8"))
    ft_data = json.load(ft_input_path.open("r", encoding="utf-8"))
    triage_results = json.load(triage_results_path.open("r", encoding="utf-8"))
    candidate_matches = json.load(candidate_matches_path.open("r", encoding="utf-8"))

    fw_hash = get_sha256(fw_input_path)
    ft_hash = get_sha256(ft_input_path)

    # Map by source_id
    fw_by_id = {str(x["source_id"]): x for x in fw_data}
    ft_by_id = {str(x["france_travail_id"]): x for x in ft_data}
    triage_by_id = {str(x["free_work_source_id"]): x for x in triage_results}
    candidates_by_id = {str(x["free_work_source_id"]): x for x in candidate_matches}

    # Expected totals
    expected_fw_total = 8457
    if len(fw_data) != expected_fw_total:
        print(
            f"Error: Free-Work offers count is {len(fw_data)} but expected {expected_fw_total}.", file=sys.stderr)  # pylint: disable=line-too-long
        sys.exit(1)

    # Verify lists
    print("Generating master audit results...")
    audit_results = []

    counters = {
        "DUPLICATE_HIGH_CONFIDENCE": 0,
        "PROBABLY_NEW": 0,
        "HUMAN_REVIEW_REQUIRED": 0,
        "PROCESSING_ERROR": 0
    }

    for fw_sid, fw_item in fw_by_id.items():
        triage_item = triage_by_id.get(fw_sid)
        cand_item = candidates_by_id.get(fw_sid)

        if not triage_item:
            print(f"Error: Missing triage info for {fw_sid}", file=sys.stderr)
            sys.exit(1)

        category = triage_item["triage_category"]
        reason_codes = triage_item["triage_reason_codes"]
        data_coverage = triage_item["data_coverage"]
        rule_version = triage_item["decision_rule_version"]

        counters[category] += 1

        # Build free-work info
        fw_loc = fw_item.get("location") or {}
        fw_title = fw_item.get("title") or ""
        fw_desc = fw_item.get("description") or ""

        free_work_info = {
            "source_id": fw_sid,
            "source_url": fw_item.get("source_url"),
            "title_raw": fw_title,
            "title_normalized": cand_item.get(
                "free_work_title_normalized",
                ""),
            "company_raw": fw_item.get("company_name"),
            "company_normalized": cand_item.get(
                "free_work_company_normalized",
                ""),
            "location_raw": fw_loc.get("locality") if isinstance(
                fw_loc,
                dict) else str(fw_loc),
            "locality_normalized": cand_item.get(
                    "free_work_location",
                    {}).get(
                        "locality_normalized",
                        ""),
            "postal_code": cand_item.get(
                "free_work_location",
                {}).get(
                "postal_code",
                ""),
            "department_code": cand_item.get(
                "free_work_location",
                {}).get(
                "department_code",
                ""),
            "published_at": fw_item.get("published_at"),
            "description_excerpt": get_description_excerpt(fw_desc),
            "description_length": len(fw_desc)}

        # Get candidates
        top_cands = cand_item.get("top_candidates", []) if cand_item else []

        def format_candidate(c, rank):
            # Recalculate score breakdown
            """."""
            components = c.get("components", {})
            title_seq = components.get("title_sequence_similarity", 0)
            title_jac = components.get("title_token_jaccard", 0)
            title_weighted = components.get("title_weighted_token_similarity", 0)
            title_compact_seq = components.get("title_compact_sequence_similarity", 0)

            title_score = 45 * (title_seq * 0.25 + title_jac * 0.25 +
                                title_weighted * 0.25 + title_compact_seq * 0.25)

            desc_jac = components.get("description_token_jaccard")
            desc_weighted = components.get("description_weighted_token_similarity")
            desc_score = 0
            if desc_jac is not None and desc_weighted is not None:
                desc_score = 25 * (desc_jac * 0.4 + desc_weighted * 0.6)

            comp_seq = components.get("company_sequence_similarity")
            comp_score = 0
            if comp_seq is not None:
                comp_score = comp_seq * 10

            geo_label = components.get("geography", "UNKNOWN")
            geo_score = 0
            if geo_label == "EXACT_POSTAL_CODE":
                geo_score = 15
            elif geo_label == "SAME_DEPARTMENT":
                geo_score = 8

            rome_match = components.get("rome_query_match", False)
            rome_score = 5 if rome_match else 0

            # Evidence blocks
            evidence = list(c.get("candidate_blocks", []))
            comp_comp = c.get("company_comparison", {})
            geo_comp = c.get("geography_comparison", {})
            title_comp = c.get("title_comparison", {})

            if comp_comp.get("match_type"):
                evidence.append(f"Company Match: {comp_comp['match_type']}")
            if geo_comp.get("result"):
                evidence.append(f"Geography Match: {geo_comp['result']}")
            if title_comp.get("shared_significant_tokens"):
                tokens_str = ", ".join(title_comp["shared_significant_tokens"])
                evidence.append(f"Shared tokens: {tokens_str}")

            # Fetch raw description
            ft_id = str(c["france_travail_id"])
            ft_raw = ft_by_id.get(ft_id) or {}
            ft_desc = ft_raw.get("description", "")

            return {
                "source_id": ft_id,
                "source_url": ft_raw.get("source_url"),  # Keep null if not present
                "title_raw": c["title"],
                "title_normalized": title_comp.get("france_travail_normalized", ""),
                "company_raw": c["company_name"],
                "company_normalized": comp_comp.get("france_travail_normalized", ""),
                "location_raw": ft_raw.get("work_place_name"),
                "postal_code": c["postal_code"],
                "department_code": geo_comp.get("france_travail_department"),
                "published_at": ft_raw.get("published_at"),
                "description_excerpt": get_description_excerpt(ft_desc),
                "score_total": c["preliminary_match_score"],
                "score_breakdown": {
                    "title": round(title_score, 2),
                    "description": round(desc_score, 2),
                    "company": round(comp_score, 2),
                    "geography": round(geo_score, 2),
                    "other": round(rome_score, 2)
                },
                "evidence": evidence,
                "rank": rank
            }

        best_ft_candidate = None
        alt_candidates = []

        if top_cands:
            best_ft_candidate = format_candidate(top_cands[0], 1)

            # Determine how many alternative candidates to keep
            max_cands = 3
            if category == "HUMAN_REVIEW_REQUIRED":
                max_cands = 5

            for r_idx, c in enumerate(top_cands[1:max_cands]):
                alt_candidates.append(format_candidate(c, r_idx + 2))

        # Generate explanation
        explanation = generate_explanation(category, reason_codes, best_ft_candidate)

        # Source trace
        source_trace = {
            "free_work_input_file": "backend/data/processed/free_work/full_catalog/20260624_081715/offers_normalized.json",  # pylint: disable=line-too-long
            "free_work_source_id": fw_sid,
            "france_travail_input_file": "backend/data/processed/france_travail/snapshots/current/france_travail_offers_snapshot.json",  # pylint: disable=line-too-long
            "france_travail_source_id": best_ft_candidate["source_id"] if best_ft_candidate else None,  # pylint: disable=line-too-long
            "matching_run_id": "run_triage_full_20260624",
            "triage_run_id": "run_triage_full_20260624"}

        entry = {
            "free_work": free_work_info,
            "triage": {
                "category": category,
                "reason_codes": reason_codes,
                "rule_version": rule_version,
                "data_coverage": data_coverage,
                "human_explanation": explanation
            },
            "best_france_travail_candidate": best_ft_candidate,
            "alternative_candidates": alt_candidates,
            "human_review": {
                "decision": "",
                "selected_france_travail_id": "",
                "comment": "",
                "reviewed_at": ""
            },
            "source_trace": source_trace
        }
        audit_results.append(entry)

    # Check counters
    print(f"Generated {len(audit_results)} master audit entries.")
    print(f"Counters: {counters}")

    expected_counters = {
        "DUPLICATE_HIGH_CONFIDENCE": 229,
        "PROBABLY_NEW": 1831,
        "HUMAN_REVIEW_REQUIRED": 6397,
        "PROCESSING_ERROR": 0
    }

    for cat, val in expected_counters.items():
        if counters[cat] != val:
            print(
                f"Error: Inconsistent counters for category {cat}. Expected {val}, got {
                    counters[cat]}", file=sys.stderr)
            sys.exit(1)

    # Save master file
    master_path = run_dir / "audit_results.json"
    with master_path.open("w", encoding="utf-8") as f:
        json.dump(audit_results, f, ensure_ascii=False, indent=2)
    print(f"Master file saved to {master_path}")

    # Save specialized sub-files
    subfiles = {
        "DUPLICATE_HIGH_CONFIDENCE": run_dir / "audit_duplicates_high_confidence.json",
        "PROBABLY_NEW": run_dir / "audit_probably_new.json",
        "HUMAN_REVIEW_REQUIRED": run_dir / "audit_human_review_required.json",
        "PROCESSING_ERROR": run_dir / "audit_processing_errors.json"
    }

    for cat, filepath in subfiles.items():
        subset = [x for x in audit_results if x["triage"]["category"] == cat]
        with filepath.open("w", encoding="utf-8") as f:
            json.dump(subset, f, ensure_ascii=False, indent=2)
        print(f"Saved {len(subset)} entries to {filepath}")

    # Section 6: Prioritized human review queue
    print("Prioritizing human review queue...")
    hr_subset = [x for x in audit_results if x["triage"]["category"] == "HUMAN_REVIEW_REQUIRED"]

    prioritized_queue = []

    priority_counters = {
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0
    }

    for item in hr_subset:
        best_cand = item["best_france_travail_candidate"]
        alt_cands = item["alternative_candidates"]

        score = best_cand["score_total"] if best_cand else 0.0
        reason_codes = item["triage"]["reason_codes"]

        # Priority rules
        priority = "LOW"

        if best_cand:
            # Check high rules
            has_high_score = score >= 65.0

            has_close_margin = False
            if alt_cands:
                margin = score - alt_cands[0]["score_total"]
                if margin < 5.0 and score >= 50.0:
                    has_close_margin = True

            # Title close but company different
            best_cand["score_breakdown"]["title"]
            # raw sequence similarity is in evidence or we can check title score
            # title_score is out of 45. 45 * 0.8 = 36.0
            title_close = best_cand["score_breakdown"]["title"] >= 36.0
            company_differs = "Company Match: NO_MATCH" in best_cand["evidence"]
            title_close_comp_diff = title_close and company_differs

            # Company compatible but geography differs
            comp_compatible = any(x in best_cand["evidence"] for x in [
                "Company Match: EXACT_NORMALIZED",
                "Company Match: ALIAS_MATCH",
                "Company Match: CONTAINMENT_MATCH",
                "Company Match: HIGH_SIMILARITY"
            ])
            geo_differs = "Geography Match: DIFFERENT" in best_cand["evidence"]
            comp_compat_geo_diff = comp_compatible and geo_differs

            if has_high_score or has_close_margin or title_close_comp_diff or comp_compat_geo_diff:
                priority = "HIGH"
            elif score >= 40.0:
                priority = "MEDIUM"

        priority_counters[priority] += 1

        # Add priority info to triage
        item["triage"]["priority"] = priority
        prioritized_queue.append(item)

    # Sort prioritized queue: HIGH -> MEDIUM -> LOW, then by score total descending
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    prioritized_queue.sort(key=lambda x: (
        priority_order[x["triage"]["priority"]],
        -x["best_france_travail_candidate"]["score_total"] if x["best_france_travail_candidate"] else 0.0,  # pylint: disable=line-too-long
        x["free_work"]["source_id"]
    ))

    # Save prioritized queue JSON
    pq_json_path = run_dir / "human_review_queue_prioritized.json"
    with pq_json_path.open("w", encoding="utf-8") as f:
        json.dump(prioritized_queue, f, ensure_ascii=False, indent=2)
    print(f"Saved prioritized queue json to {pq_json_path}")
    print(f"Priority counts: {priority_counters}")

    # Save prioritized queue CSV
    pq_csv_path = run_dir / "human_review_queue_prioritized.csv"
    with pq_csv_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["free_work_source_id",
                         "free_work_title",
                         "free_work_company",
                         "free_work_location",
                         "free_work_source_url",
                         "best_france_travail_id",
                         "best_match_score",
                         "priority",
                         "candidate_count",
                         "human_decision",
                         "human_selected_france_travail_id",
                         "human_comment",
                         "reviewed_at"])
        for q in prioritized_queue:
            best_ft_id = q["best_france_travail_candidate"]["source_id"] if q["best_france_travail_candidate"] else ""  # pylint: disable=line-too-long
            best_score = q["best_france_travail_candidate"]["score_total"] if q["best_france_travail_candidate"] else ""  # pylint: disable=line-too-long
            cand_count = len(q["alternative_candidates"]) + \
                (1 if q["best_france_travail_candidate"] else 0)
            writer.writerow([
                q["free_work"]["source_id"],
                q["free_work"]["title_raw"],
                q["free_work"]["company_raw"],
                q["free_work"]["location_raw"],
                q["free_work"]["source_url"],
                best_ft_id,
                best_score,
                q["triage"]["priority"],
                cand_count,
                "", "", "", ""
            ])
    print(f"Saved prioritized queue csv to {pq_csv_path}")

    # Section 7: manual_check_sample.json
    print("Generating manual check sample (60 cases)...")

    # Deterministic sample extraction
    # 20 duplicates: represent different reason codes
    dups = [x for x in audit_results if x["triage"]["category"] == "DUPLICATE_HIGH_CONFIDENCE"]
    dups.sort(key=lambda x: x["free_work"]["source_id"])

    # Group duplicates by reason codes to make it diverse
    dups_by_reason = {}
    for d in dups:
        r_code = d["triage"]["reason_codes"][0] if d["triage"]["reason_codes"] else "UNKNOWN"
        if r_code not in dups_by_reason:
            dups_by_reason[r_code] = []
        dups_by_reason[r_code].append(d)

    sample_dups = []
    # Round robin extraction
    reason_keys = sorted(list(dups_by_reason.keys()))
    idx = 0
    while len(sample_dups) < 20 and any(dups_by_reason.values()):
        key = reason_keys[idx % len(reason_keys)]
        if dups_by_reason[key]:
            sample_dups.append(dups_by_reason[key].pop(0))
        idx += 1

    # 20 probably new: represent different score levels
    news = [x for x in audit_results if x["triage"]["category"] == "PROBABLY_NEW"]
    news.sort(
        key=lambda x: (
            x["best_france_travail_candidate"]["score_total"] if x["best_france_travail_candidate"] else 0.0,  # pylint: disable=line-too-long
            x["free_work"]["source_id"]))

    sample_news = []
    if news:
        # Extract 20 evenly distributed across the sorted list
        step = max(1, len(news) // 20)
        for i in range(20):
            idx = min(i * step, len(news) - 1)
            sample_news.append(news[idx])

    # 20 human review: represent HIGH (7), MEDIUM (7), LOW (6)
    hr_high = [x for x in prioritized_queue if x["triage"]["priority"] == "HIGH"]
    hr_med = [x for x in prioritized_queue if x["triage"]["priority"] == "MEDIUM"]
    hr_low = [x for x in prioritized_queue if x["triage"]["priority"] == "LOW"]

    sample_hr = []

    def extract_n_evenly(lst, n):
        """."""
        lst_sorted = sorted(lst, key=lambda x: x["free_work"]["source_id"])
        if not lst_sorted:
            return []
        if len(lst_sorted) <= n:
            return lst_sorted
        step = len(lst_sorted) // n
        res = []
        for i in range(n):
            idx = min(i * step, len(lst_sorted) - 1)
            res.append(lst_sorted[idx])
        return res

    sample_hr.extend(extract_n_evenly(hr_high, 7))
    sample_hr.extend(extract_n_evenly(hr_med, 7))
    sample_hr.extend(extract_n_evenly(hr_low, 6))

    sample_all = sample_dups + sample_news + sample_hr

    sample_path = run_dir / "manual_check_sample.json"
    with sample_path.open("w", encoding="utf-8") as f:
        json.dump(sample_all, f, ensure_ascii=False, indent=2)
    print(f"Saved manual check sample of {len(sample_all)} items to {sample_path}")

    # Section 8: Generate audit manifest
    print("Generating audit manifest...")

    # Hashes of outputs
    output_files = {
        "audit_results.json": run_dir / "audit_results.json",
        "audit_duplicates_high_confidence.json": run_dir / "audit_duplicates_high_confidence.json",
        "audit_probably_new.json": run_dir / "audit_probably_new.json",
        "audit_human_review_required.json": run_dir / "audit_human_review_required.json",
        "audit_processing_errors.json": run_dir / "audit_processing_errors.json",
        "human_review_queue_prioritized.json": run_dir / "human_review_queue_prioritized.json",
        "human_review_queue_prioritized.csv": run_dir / "human_review_queue_prioritized.csv",
        "manual_check_sample.json": run_dir / "manual_check_sample.json"
    }

    output_hashes = {}
    for name, path in output_files.items():
        output_hashes[name] = get_sha256(path)

    manifest = {
        "input_files": {
            "free_work_input_file": "backend/data/processed/free_work/full_catalog/20260624_081715/offers_normalized.json",  # pylint: disable=line-too-long
            "free_work_sha256": fw_hash,
            "france_travail_input_file": "backend/data/processed/france_travail/snapshots/current/france_travail_offers_snapshot.json",  # pylint: disable=line-too-long
            "france_travail_sha256": ft_hash},
        "configuration": {
            "matching_strategy": "independent_normalized",
            "aliases_enabled": True,
            "rule_version": "CONSERVATIVE_RULESET_V1",
            "triage_run_id": "run_triage_full_20260624"},
        "counters": {
            "total_offers": len(audit_results),
            "categories": counters,
            "priorities": priority_counters},
        "output_hashes": output_hashes,
        "generated_at": "2026-06-24 12:30:13"}

    manifest_path = run_dir / "audit_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"Saved manifest to {manifest_path}")

    # Check key calibration cases
    print("Verifying historical cases...")

    # 1. SAP SD/MM: FW source_id 513371 -> DUPLICATE_HIGH_CONFIDENCE
    # 2. Econocom: FW source_id 621908 -> DUPLICATE_HIGH_CONFIDENCE
    # 3. Experis: FW source_id 637922 -> DUPLICATE_HIGH_CONFIDENCE
    # 4. IAM/comptabilité: FW source_id 422864 -> NOT DUPLICATE_HIGH_CONFIDENCE

    triage_by_id.get("513371")
    # Wait, the sap ID might be different or not. Let's look up by title/company/location or check by ID.  # pylint: disable=line-too-long
    # Let's print out what categories they got.

    def check_and_print_case(source_id, name):
        """."""
        item = triage_by_id.get(source_id)
        if item:
            print(
                f"Historical case {name} ({source_id}): Category = {
                    item['triage_category']}, reason_codes = {
                    item['triage_reason_codes']}")
        else:
            print(f"Warning: Historical case {name} ({source_id}) not found in results.")

    check_and_print_case("606592", "SAP SD/MM Lyon")
    check_and_print_case("621908", "Econocom")
    check_and_print_case("637922", "Experis")
    check_and_print_case("422864", "IAM / comptabilité")


if __name__ == "__main__":
    main()
