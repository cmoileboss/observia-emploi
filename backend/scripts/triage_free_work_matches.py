"""."""
from backend.scripts.matching_normalization import (
    normaliser_entreprise,
    normaliser_localite,
    extraire_departement,
    normaliser_titre,
    normaliser_description
)
import argparse
import hashlib
import json
import math
import os
import sys
import time
import csv
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"


# Constants & Configuration
MAX_PRE_CANDIDATES_PER_OFFER = 50
MAX_DETAILED_CANDIDATES_PER_OFFER = 20
MAX_RARE_TOKEN_DOCUMENT_FREQUENCY = 1000
MAX_RARE_TITLE_TOKENS = 3

FRENCH_STOP_WORDS = {
    "les", "des", "une", "pour", "dans", "avec", "cette", "aux",
    "sont", "nous", "vous", "ils", "elles", "comme", "leur",
    "leurs", "mais", "notre", "votre", "sans", "sous", "vers", "par"
}

COMPANY_ALIASES = {
    "econocom infogerance et systeme": "econocom",
    "experis france": "experis"
}

CONSERVATIVE_RULESET_V1 = {
    "triage_rule_version": "CONSERVATIVE_RULESET_V1",
    "matching_strategy": "independent_normalized",
    "aliases_enabled": True,
    "score_thresholds": {
        "strong_duplicate": 75.0,
        "weak_candidate": 30.0
    },
    "ambiguity_margin": 5.0,
    "minimum_data_coverage": {
        "require_title": True,
        "require_desc_or_meta": True
    }
}

START_TIME = time.time()


def normaliser_cle_compacte(texte_normalise: str) -> str:
    """."""
    return "".join(texte_normalise.split())


def extraire_tokens(texte_normalise: str) -> list[str]:
    """."""
    tokens = texte_normalise.split()
    filtered = []
    for t in tokens:
        if len(t) >= 3 and t not in FRENCH_STOP_WORDS and not t.isdigit():
            filtered.append(t)
    return sorted(list(set(filtered)))


def match_entreprises(comp_fw: str, comp_ft: str) -> tuple[str, float]:
    """."""
    if not comp_fw or not comp_ft:
        return "MISSING", 0.0
    if comp_fw == comp_ft:
        return "EXACT_NORMALIZED", 1.0

    generics = {"group", "france", "services", "consulting", "technologies", "solutions", "it"}
    if comp_fw in generics or comp_ft in generics or len(comp_fw) < 3 or len(comp_ft) < 3:
        return "NO_MATCH", 0.0

    if comp_fw.startswith(comp_ft) or comp_ft.startswith(comp_fw):
        return "CONTAINMENT_MATCH", 0.95

    sim = SequenceMatcher(None, comp_fw, comp_ft).ratio()
    if sim >= 0.8:
        return "HIGH_SIMILARITY", sim
    return "NO_MATCH", sim


def match_geographie(fw_pc: str, fw_loc_norm: str, fw_dept: str, ft_pc: str,
                     ft_loc_norm: str, ft_dept: str) -> tuple[str, float]:
    """."""
    if not fw_pc or not ft_pc:
        return "UNKNOWN", 0.0
    if fw_pc == ft_pc:
        return "EXACT_POSTAL_CODE", 1.0
    if fw_loc_norm and ft_loc_norm and fw_loc_norm == ft_loc_norm:
        return "SAME_LOCALITY", 0.9
    if fw_dept and ft_dept and fw_dept == ft_dept:
        return "SAME_DEPARTMENT", 0.5
    return "DIFFERENT", 0.0


def ecriture_atomique(dest_path: Path, content_bytes: bytes) -> None:
    """."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = f"{dest_path.name}_{os.getpid()}_{time.time_ns()}.tmp"
    temp_path = dest_path.with_name(temp_name)
    try:
        temp_path.write_bytes(content_bytes)
    except Exception as e:
        print(f"Warning: Failed to write to temporary file {temp_path}: {e}", file=sys.stderr)
        return

    max_retries = 5
    backoff = 0.05
    for attempt in range(max_retries):
        try:
            temp_path.replace(dest_path)
            return
        except (PermissionError, OSError):
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff *= 2
    if temp_path.exists():
        try:
            temp_path.unlink()
        except Exception:
            pass


def classify_triage(
        fw_item,
        best_cand,
        second_cand,
        cand_count,
        fw_tokens,
        fw_desc_norm,
        fw_company_norm,
        fw_pc,
        fw_dept,
        fw_locality_norm,
        fw_romes):
    # Missing / Incomplete data check
    """."""
    title = fw_item.get("title")
    desc = fw_item.get("description")

    if not title or not str(title).strip():
        return "HUMAN_REVIEW_REQUIRED", ["MISSING_TITLE"]

    has_desc = bool(desc and str(desc).strip())
    has_meta = bool(fw_company_norm or fw_pc or fw_locality_norm)

    if not has_desc and not has_meta:
        return "HUMAN_REVIEW_REQUIRED", ["MISSING_DESC_AND_META"]

    if cand_count == 0 or not best_cand:
        return "PROBABLY_NEW", ["NO_CANDIDATE"]

    score = best_cand["preliminary_match_score"]
    components = best_cand["components"]
    comp_comp = best_cand["company_comparison"]
    geo_comp = best_cand["geography_comparison"]
    title_comp = best_cand["title_comparison"]
    blocks = best_cand["candidate_blocks"]

    # Reason code accumulator

    # Rule 1: EXACT_FINGERPRINT
    if "EXACT_FINGERPRINT" in blocks or "FALLBACK_EXACT_FINGERPRINT" in blocks:
        return "DUPLICATE_HIGH_CONFIDENCE", ["EXACT_FINGERPRINT"]

    # Rule 2: EXACT_TITLE_COMPANY_GEOGRAPHY
    if "COMPACT_TITLE_EXACT" in blocks:
        if comp_comp["match_type"] in ["EXACT_NORMALIZED", "ALIAS_MATCH"]:
            if geo_comp["result"] in ["EXACT_POSTAL_CODE", "SAME_LOCALITY", "SAME_DEPARTMENT"]:
                return "DUPLICATE_HIGH_CONFIDENCE", ["EXACT_TITLE_COMPANY_GEOGRAPHY"]

    # Rule 3: STRONG_TITLE_DESCRIPTION_COMPANY
    if score >= 75.0:
        comp_sim = comp_comp.get("similarity", 0.0)
        title_seq = title_comp.get("sequence_similarity", 0.0)
        desc_jac = components.get("description_token_jaccard")

        if comp_sim >= 0.8 and title_seq >= 0.85 and geo_comp["result"] != "DIFFERENT":
            if desc_jac is not None and desc_jac >= 0.6:
                return "DUPLICATE_HIGH_CONFIDENCE", ["STRONG_TITLE_DESCRIPTION_COMPANY"]

    # Rule 4: EXACT_TITLE_COMPANY_LOCALITY
    if title_comp.get("sequence_similarity", 0.0) == 1.0:
        if comp_comp["match_type"] in ["EXACT_NORMALIZED", "ALIAS_MATCH"]:
            if geo_comp["result"] in ["EXACT_POSTAL_CODE", "SAME_LOCALITY"]:
                return "DUPLICATE_HIGH_CONFIDENCE", ["EXACT_TITLE_COMPANY_LOCALITY"]

    # Probably New
    if score < 30.0:
        return "PROBABLY_NEW", ["LOW_BEST_SCORE"]

    # Human Review
    reasons_review = []
    # Ambiguity
    if second_cand:
        margin = score - second_cand["preliminary_match_score"]
        if margin < 5.0:
            reasons_review.append("AMBIGUOUS_SCORE_MARGIN")

    # Company match but geography differs
    if comp_comp["match_type"] in ["EXACT_NORMALIZED",
                                   "ALIAS_MATCH"] and geo_comp["result"] == "DIFFERENT":
        reasons_review.append("COMPANY_MATCH_GEO_DIFFERS")

    # Company differs but titles/descriptions close
    if comp_comp["match_type"] == "NO_MATCH" and score >= 60.0:
        reasons_review.append("COMPANY_DIFFERS_STRONG_CONTENT")

    if not reasons_review:
        reasons_review.append("INTERMEDIATE_SCORE")

    return "HUMAN_REVIEW_REQUIRED", reasons_review


def main():
    """."""
    parser = argparse.ArgumentParser(description="Triage des offres Free-Work.")
    parser.add_argument(
        "--free-work-input",
        required=True,
        help="offers_normalized.json de Free-Work.")
    parser.add_argument("--france-travail-input", required=True, help="Snapshot France Travail.")
    parser.add_argument("--run-id", type=str, default=None, help="Optionnel. ID de run.")
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="Lancer en mode pilote sur 100 offres.")
    args = parser.parse_args()

    run_id = args.run_id or f"triage_{int(time.time())}"
    output_dir = PROCESSED_DATA_ROOT / "matching" / "free_work_vs_france_travail" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Starting triage run: {run_id} (Pilot: {args.pilot})")

    # Load Inputs
    fw_path = Path(args.free_work_input)
    ft_path = Path(args.france_travail_input)
    fw_data = json.load(fw_path.open("r", encoding="utf-8"))
    ft_data = json.load(ft_path.open("r", encoding="utf-8"))

    # If pilot, restrict to first 100 offers (sorted by source_id for determinism)
    fw_data.sort(key=lambda x: str(x["source_id"]))
    if args.pilot:
        fw_data = fw_data[:100]

    # Verify input hashes
    def get_hash(p):
        """."""
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    fw_hash = get_hash(fw_path)
    ft_hash = get_hash(ft_path)

    # Check Manifest / Checkpoint Recovery
    checkpoint_file = output_dir / "triage_manifest.json"
    processed_offers = {}

    # Load previously triaged results if checkpoint matches
    triage_results_file = output_dir / "triage_results.json"
    candidate_matches_file = output_dir / "candidate_matches.json"

    if checkpoint_file.exists() and triage_results_file.exists():
        try:
            with checkpoint_file.open("r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            if (checkpoint.get("free_work_hash") == fw_hash and
                checkpoint.get("france_travail_hash") == ft_hash and
                    checkpoint.get("matching_strategy") == "independent_normalized"):

                # Load existing triage results
                with triage_results_file.open("r", encoding="utf-8") as f:
                    existing_results = json.load(f)
                for r in existing_results:
                    processed_offers[str(r["free_work_source_id"])] = r
                print(
                    f"Resuming triage. Loaded {
                        len(processed_offers)} completed offers from checkpoint.")
            else:
                print("Incompatible checkpoint inputs. Starting fresh.")
        except Exception as e:
            print(f"Warning reading checkpoint: {e}. Starting fresh.")

    # [1/4] Building France Travail Index
    print("Building France Travail indexes...")
    offers_by_postal_code = defaultdict(set)
    offers_by_department = defaultdict(set)
    offers_by_rome = defaultdict(set)
    offers_by_company = defaultdict(set)
    offers_by_company_token = defaultdict(set)
    offers_by_title_token = defaultdict(set)
    offers_by_compact_title = defaultdict(set)

    offers_by_fp1 = defaultdict(set)
    offers_by_fp2 = defaultdict(set)
    offers_by_fp3 = defaultdict(set)
    offers_by_fp4 = defaultdict(set)

    ft_normalized = {}
    doc_freq_title = defaultdict(int)
    doc_freq_desc = defaultdict(int)

    for item in ft_data:
        fid = item["france_travail_id"]
        title_norm = normaliser_titre(item["title"])
        title_compact = normaliser_cle_compacte(title_norm)
        desc_norm = normaliser_description(item["description"])

        company_raw = item.get("company_name")
        company_norm = normaliser_entreprise(company_raw)
        if company_norm in COMPANY_ALIASES:
            company_norm = COMPANY_ALIASES[company_norm]

        t_tokens = extraire_tokens(title_norm)
        d_tokens = extraire_tokens(desc_norm)

        for tok in t_tokens:
            doc_freq_title[tok] += 1
        for tok in d_tokens:
            doc_freq_desc[tok] += 1

        pc = item.get("postal_code")
        pc_str = str(pc).strip() if pc else ""
        dept = extraire_departement(pc_str)
        rome = item["rome_code"].strip()

        ft_normalized[fid] = {
            "title_norm": title_norm,
            "title_compact": title_compact,
            "desc_norm": desc_norm,
            "company_norm": company_norm,
            "title_tokens": t_tokens,
            "desc_tokens": d_tokens,
            "postal_code": pc_str if pc_str else None,
            "department": dept if dept else None,
            "rome_code": rome,
            "title_raw": item["title"],
            "company_raw": company_raw,
            "description_raw": item["description"],
            "locality_norm": normaliser_localite(
                item.get("work_place_name")) if item.get("work_place_name") else ""}

        if pc_str:
            offers_by_postal_code[pc_str].add(fid)
        if dept:
            offers_by_department[dept].add(fid)
        if rome:
            offers_by_rome[rome].add(fid)
        if company_norm:
            offers_by_company[company_norm].add(fid)
            for tok in extraire_tokens(company_norm):
                offers_by_company_token[tok].add(fid)
        for tok in t_tokens:
            offers_by_title_token[tok].add(fid)
        if title_compact:
            offers_by_compact_title[title_compact].add(fid)

        offers_by_fp1[f"{title_norm}|{company_norm}|{pc_str}"].add(fid)
        offers_by_fp2[f"{title_norm}|{pc_str}"].add(fid)
        offers_by_fp3[f"{company_norm}|{title_norm}"].add(fid)
        offers_by_fp4[f"{title_norm}|{desc_norm}"].add(fid)

    n_ft = len(ft_data)
    idf_title = {tok: math.log((n_ft + 1) / (freq + 1)) + 1 for tok, freq in doc_freq_title.items()}
    idf_desc = {tok: math.log((n_ft + 1) / (freq + 1)) + 1 for tok, freq in doc_freq_desc.items()}

    # Triage classification structures
    results_candidate_matches = []
    results_triage_results = []

    # Reload existing arrays if resuming
    if processed_offers and candidate_matches_file.exists():
        try:
            with candidate_matches_file.open("r", encoding="utf-8") as f:
                results_candidate_matches = json.load(f)
            results_triage_results = list(processed_offers.values())
        except Exception:
            results_candidate_matches = []
            results_triage_results = []
            processed_offers = {}

    # Category Counters
    counters = {
        "DUPLICATE_HIGH_CONFIDENCE": 0,
        "PROBABLY_NEW": 0,
        "HUMAN_REVIEW_REQUIRED": 0,
        "PROCESSING_ERROR": 0}
    for r in results_triage_results:
        counters[r["triage_category"]] += 1

    # [2/4] Matching & Triage Loop
    print("Executing triage loop...")

    total_offers = len(fw_data)
    last_save_time = time.time()

    for idx, fw_item in enumerate(fw_data):
        fw_sid = str(fw_item["source_id"])

        # Checkpoint skip
        if fw_sid in processed_offers:
            continue

        try:
            fw_title_norm = normaliser_titre(fw_item["title"])
            fw_title_compact = normaliser_cle_compacte(fw_title_norm)
            fw_desc = fw_item.get("description")
            fw_desc_norm = normaliser_description(fw_desc) if fw_desc else ""

            fw_company_raw = fw_item.get("company_name")
            fw_company_norm = normaliser_entreprise(fw_company_raw)
            if fw_company_norm in COMPANY_ALIASES:
                fw_company_norm = COMPANY_ALIASES[fw_company_norm]

            fw_tokens = extraire_tokens(fw_title_norm)
            fw_desc_tokens = extraire_tokens(fw_desc_norm) if fw_desc_norm else []

            fw_loc = fw_item.get("location") or {}
            fw_pc = str(fw_loc.get("postal_code") or "").strip()
            fw_dept = extraire_departement(fw_pc)
            fw_locality_norm = normaliser_localite(
                fw_loc.get("locality")) if fw_loc.get("locality") else ""
            fw_romes = [
                r.get("rome_code") for r in fw_item.get(
                    "matched_rome_queries",
                    []) if r.get("rome_code")]

            # Run independent_normalized blocks
            candidates_blocks_map = defaultdict(set)

            # EXACT_FINGERPRINT
            for fid in offers_by_fp1.get(f"{fw_title_norm}|{fw_company_norm}|{fw_pc}", []):
                candidates_blocks_map[fid].add("EXACT_FINGERPRINT")
            for fid in offers_by_fp2.get(f"{fw_title_norm}|{fw_pc}", []):
                candidates_blocks_map[fid].add("EXACT_FINGERPRINT")
            for fid in offers_by_fp3.get(f"{fw_company_norm}|{fw_title_norm}", []):
                candidates_blocks_map[fid].add("EXACT_FINGERPRINT")
            for fid in offers_by_fp4.get(f"{fw_title_norm}|{fw_desc_norm}", []):
                candidates_blocks_map[fid].add("EXACT_FINGERPRINT")

            # COMPACT_TITLE_EXACT
            if fw_title_compact:
                for fid in offers_by_compact_title.get(fw_title_compact, []):
                    candidates_blocks_map[fid].add("COMPACT_TITLE_EXACT")

            # EXACT_POSTAL_CODE
            if fw_pc:
                for fid in offers_by_postal_code.get(fw_pc, []):
                    candidates_blocks_map[fid].add("EXACT_POSTAL_CODE")

            # SAME_DEPARTMENT_TITLE
            if fw_dept:
                dept_offers = offers_by_department.get(fw_dept, set())
                for tok in fw_tokens:
                    for fid in dept_offers.intersection(offers_by_title_token.get(tok, set())):
                        candidates_blocks_map[fid].add("SAME_DEPARTMENT_TITLE")

            # ROME_QUERY_TITLE
            for rome in fw_romes:
                rome_offers = offers_by_rome.get(rome, set())
                for tok in fw_tokens:
                    for fid in rome_offers.intersection(offers_by_title_token.get(tok, set())):
                        candidates_blocks_map[fid].add("ROME_QUERY_TITLE")

            # COMPANY_MATCH
            if fw_company_norm:
                for fid in offers_by_company.get(fw_company_norm, []):
                    candidates_blocks_map[fid].add("COMPANY_MATCH")
                for tok in extraire_tokens(fw_company_norm):
                    for fid in offers_by_company_token.get(tok, []):
                        ft_comp = ft_normalized[fid]["company_norm"]
                        if ft_comp and SequenceMatcher(
                                None, fw_company_norm, ft_comp).ratio() >= 0.8:
                            candidates_blocks_map[fid].add("COMPANY_MATCH")

            # RARE_TITLE_TOKENS
            title_tokens_with_freq = sorted([(t, doc_freq_title.get(t, 0)) for t in fw_tokens if 0 < doc_freq_title.get(  # pylint: disable=line-too-long
                t, 0) < MAX_RARE_TOKEN_DOCUMENT_FREQUENCY], key=lambda x: (x[1], x[0]))
            for tok in [x[0] for x in title_tokens_with_freq[:MAX_RARE_TITLE_TOKENS]]:
                for fid in offers_by_title_token.get(tok, []):
                    candidates_blocks_map[fid].add("RARE_TITLE_TOKENS")

            # Score candidates
            scored_candidates = []
            for fid in candidates_blocks_map:
                ft_item = ft_normalized[fid]

                title_seq = SequenceMatcher(None, fw_title_norm, ft_item["title_norm"]).ratio()
                t1, t2 = set(fw_tokens), set(ft_item["title_tokens"])
                title_jac = len(t1 & t2) / len(t1 | t2) if t1 | t2 else 0
                title_weighted = sum(idf_title.get(t, 1.0) for t in (t1 & t2)) / \
                    sum(idf_title.get(t, 1.0) for t in t1) if t1 else 0
                title_compact_seq = SequenceMatcher(None, fw_title_compact, ft_item["title_compact"]).ratio(  # pylint: disable=line-too-long
                ) if fw_title_compact or ft_item["title_compact"] else 0

                title_score = 45 * (title_seq * 0.25 + title_jac * 0.25 +
                                    title_weighted * 0.25 + title_compact_seq * 0.25)

                desc_jac, desc_weighted = None, None
                desc_score = 0
                desc_src = "description"
                if fw_desc_norm and ft_item["desc_norm"]:
                    d1, d2 = set(fw_desc_tokens), set(ft_item["desc_tokens"])
                    desc_jac = len(d1 & d2) / len(d1 | d2) if d1 | d2 else 0
                    desc_weighted = sum(idf_desc.get(t, 1.0) for t in (d1 & d2)) / \
                        sum(idf_desc.get(t, 1.0) for t in d1) if d1 else 0
                    desc_score = 25 * (desc_jac * 0.4 + desc_weighted * 0.6)
                else:
                    desc_src = "missing"

                comp_seq = None
                comp_score = 0
                if fw_company_norm and ft_item["company_norm"]:
                    comp_seq = SequenceMatcher(
                        None, fw_company_norm, ft_item["company_norm"]).ratio()
                    comp_score = comp_seq * 10

                geo_score = 0
                geo_label = "UNKNOWN"
                if fw_pc and ft_item["postal_code"]:
                    if fw_pc == ft_item["postal_code"]:
                        geo_label = "EXACT_POSTAL_CODE"
                        geo_score = 15
                    elif fw_dept == ft_item["department"]:
                        geo_label = "SAME_DEPARTMENT"
                        geo_score = 8
                    else:
                        geo_label = "DIFFERENT"

                rome_match = ft_item["rome_code"] in fw_romes
                rome_score = 5 if rome_match else 0

                final_score = title_score + desc_score + comp_score + geo_score + rome_score
                coverage = 45 + (25 if fw_desc_norm and ft_item["desc_norm"] else 0) + (15 if fw_pc and ft_item["postal_code"] else 0) + (  # pylint: disable=line-too-long
                    10 if fw_company_norm and ft_item["company_norm"] else 0) + (5 if rome_match else 0)  # pylint: disable=line-too-long

                comp_res, comp_sim_val = match_entreprises(fw_company_norm, ft_item["company_norm"])
                geo_res, _ = match_geographie(
                    fw_pc, fw_locality_norm, fw_dept, ft_item["postal_code"], ft_item["locality_norm"], ft_item["department"])  # pylint: disable=line-too-long

                scored_candidates.append({
                    "france_travail_id": fid,
                    "title": ft_item["title_raw"],
                    "company_name": ft_item["company_raw"],
                    "postal_code": ft_item["postal_code"],
                    "rome_code": ft_item["rome_code"],
                    "preliminary_match_score": round(final_score, 2),
                    "score_version": "compact_v2_stable",
                    "evidence_coverage": coverage,
                    "components": {
                        "title_sequence_similarity": round(title_seq, 4),
                        "title_token_jaccard": round(title_jac, 4),
                        "title_weighted_token_similarity": round(title_weighted, 4),
                        "title_compact_sequence_similarity": round(title_compact_seq, 4),
                        "description_token_jaccard": round(desc_jac, 4) if desc_jac is not None else None,  # pylint: disable=line-too-long
                        "description_weighted_token_similarity": round(desc_weighted, 4) if desc_weighted is not None else None,  # pylint: disable=line-too-long
                        "description_source": desc_src,
                        "company_sequence_similarity": round(comp_seq, 4) if comp_seq is not None else None,  # pylint: disable=line-too-long
                        "geography": geo_label,
                        "rome_query_match": rome_match
                    },
                    "company_comparison": {
                        "free_work_raw": fw_company_raw,
                        "france_travail_raw": ft_item["company_raw"],
                        "free_work_normalized": fw_company_norm,
                        "france_travail_normalized": ft_item["company_norm"],
                        "match_type": comp_res,
                        "similarity": round(comp_sim_val, 4)
                    },
                    "geography_comparison": {
                        "free_work_locality_raw": fw_loc.get("locality"),
                        "france_travail_locality_raw": item.get("work_place_name"),
                        "free_work_locality_normalized": fw_locality_norm,
                        "france_travail_locality_normalized": ft_item["locality_norm"],
                        "free_work_postal_code": fw_pc,
                        "france_travail_postal_code": ft_item["postal_code"],
                        "result": geo_res
                    },
                    "title_comparison": {
                        "free_work_normalized": fw_title_norm,
                        "france_travail_normalized": ft_item["title_norm"],
                        "shared_significant_tokens": list(t1 & t2),
                        "sequence_similarity": round(title_seq, 4),
                        "weighted_token_similarity": round(title_weighted, 4)
                    },
                    "candidate_blocks": sorted(list(candidates_blocks_map[fid]))
                })

            scored_candidates.sort(
                key=lambda x: (-x["preliminary_match_score"], x["france_travail_id"]))
            retained_candidates = scored_candidates[:MAX_DETAILED_CANDIDATES_PER_OFFER]

            # Perform Triage Classification
            best_c = retained_candidates[0] if retained_candidates else None
            second_c = retained_candidates[1] if len(retained_candidates) > 1 else None

            category, reason_codes = classify_triage(
                fw_item, best_c, second_c, len(retained_candidates),
                fw_tokens, fw_desc_norm, fw_company_norm, fw_pc, fw_dept, fw_locality_norm, fw_romes
            )

        except Exception as e:
            category = "PROCESSING_ERROR"
            reason_codes = [f"EXCEPTION_{type(e).__name__}"]
            retained_candidates = []
            best_c = None
            print(f"Error processing offer {fw_sid}: {e}", file=sys.stderr)

        counters[category] += 1

        desc_excerpt = fw_desc[:150] + "..." if fw_desc and len(fw_desc) > 150 else (fw_desc or "")

        # Save candidates
        results_candidate_matches.append({
            "free_work_source_id": fw_sid,
            "free_work_title": fw_item["title"],
            "free_work_title_normalized": fw_title_norm if 'fw_title_norm' in locals() else "",
            "free_work_company": fw_company_raw if 'fw_company_raw' in locals() else "",
            "free_work_company_normalized": fw_company_norm if 'fw_company_norm' in locals() else "",  # pylint: disable=line-too-long
            "free_work_location": {
                "locality": fw_loc.get("locality"),
                "locality_normalized": fw_locality_norm if 'fw_locality_norm' in locals() else "",
                "postal_code": fw_pc if 'fw_pc' in locals() else "",
                "department_code": fw_dept if 'fw_dept' in locals() else ""
            },
            "free_work_source_url": fw_item.get("source_url") or "",
            "free_work_description_excerpt": desc_excerpt,
            "state": "CANDIDATES_FOUND" if retained_candidates else "NO_CANDIDATE",
            "top_candidates": retained_candidates
        })

        # Save triage result
        triage_entry = {
            "free_work_source_id": fw_sid,
            "free_work_title": fw_item["title"],
            "free_work_company": fw_company_raw if 'fw_company_raw' in locals() else "",
            "free_work_location": fw_item.get("location"),
            "free_work_source_url": fw_item.get("source_url") or "",
            "triage_category": category,
            "triage_reason_codes": reason_codes,
            "data_coverage": 45 + (25 if fw_desc_norm else 0) + (10 if fw_company_norm else 0) + (15 if fw_pc else 0) if 'fw_desc_norm' in locals() else 0,  # pylint: disable=line-too-long
            "best_candidate": {
                "france_travail_id": best_c["france_travail_id"],
                "score": best_c["preliminary_match_score"]
            } if best_c else None,
            "candidate_count": len(retained_candidates),
            "decision_rule_version": "CONSERVATIVE_RULESET_V1"
        }
        results_triage_results.append(triage_entry)
        processed_offers[fw_sid] = triage_entry

        # Real-time prints / periodic checkpoint saving
        now = time.time()
        elapsed = now - START_TIME

        # Display progress every 25 offers or every 5 seconds
        if (idx + 1) % 25 == 0 or (now - last_save_time) >= 5.0 or (idx + 1) == total_offers:
            last_save_time = now
            percent = (idx + 1) / total_offers * 100
            speed = (idx + 1) / elapsed if elapsed > 0 else 0
            eta = (total_offers - (idx + 1)) / speed if speed > 0 else 0
            eta_str = f"{int(eta // 60):02d}:{int(eta % 60):02d}" if speed > 0 else "--:--"
            el_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"

            print(f"[2/4] Matching & Triage | {idx + 1} / {total_offers} — {percent:.2f} %")
            print(f"Temps : {el_str} | Vitesse : {speed:.2f} offres/s | ETA : {eta_str}")
            print(
                f"Doublons probables : {
                    counters['DUPLICATE_HIGH_CONFIDENCE']} | Nouvelles : {
                    counters['PROBABLY_NEW']} | Revue humaine : {
                    counters['HUMAN_REVIEW_REQUIRED']} | Erreurs : {
                    counters['PROCESSING_ERROR']}")
            print(f"Heartbeat : {time.strftime('%H:%M:%S')}")

            # Write progress.json
            progress_data = {
                "status": "RUNNING",
                "benchmark_id": run_id,
                "configuration_current": 1,
                "configurations_total": 1,
                "strategy": "independent_normalized",
                "aliases_enabled": True,
                "run_current": 1,
                "runs_total": 1,
                "offers_processed": idx + 1,
                "offers_total": total_offers,
                "percent_run": round(percent, 2),
                "percent_global": round(percent, 2),
                "elapsed_run_seconds": round(elapsed),
                "elapsed_global_seconds": round(elapsed),
                "eta_run_seconds": round(eta) if speed > 0 else None,
                "eta_global_seconds": round(eta) if speed > 0 else None,
                "heartbeat_at": time.strftime("%H:%M:%S"),
                "completed_runs": []
            }
            ecrire_progres_benchmark(PROCESSED_DATA_ROOT / "matching", progress_data)

            # Atomic save of incremental results
            ecriture_atomique(
                candidate_matches_file,
                json.dumps(
                    results_candidate_matches,
                    ensure_ascii=False,
                    indent=2).encode("utf-8") +
                b"\n")
            ecriture_atomique(
                triage_results_file,
                json.dumps(
                    results_triage_results,
                    ensure_ascii=False,
                    indent=2).encode("utf-8") +
                b"\n")

            # Update triage manifest (checkpoint)
            manifest = {
                "triage_rule_version": "CONSERVATIVE_RULESET_V1",
                "matching_strategy": "independent_normalized",
                "aliases_enabled": True,
                "free_work_hash": fw_hash,
                "france_travail_hash": ft_hash,
                "free_work_offers": total_offers,
                "france_travail_offers": n_ft,
                "last_processed_index": idx + 1,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "RUNNING"
            }
            ecriture_atomique(
                checkpoint_file,
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2).encode("utf-8") +
                b"\n")

    # [3/4] Save final categorised lists and queue files
    print("Writing final triage output files...")

    # Filter category outputs
    duplicates = [x for x in results_triage_results if x["triage_category"]
                  == "DUPLICATE_HIGH_CONFIDENCE"]
    probably_new = [x for x in results_triage_results if x["triage_category"] == "PROBABLY_NEW"]
    human_review = [x for x in results_triage_results if x["triage_category"]
                    == "HUMAN_REVIEW_REQUIRED"]
    errors = [x for x in results_triage_results if x["triage_category"] == "PROCESSING_ERROR"]

    # Write duplicates
    ecriture_atomique(
        output_dir /
        "duplicates_high_confidence.json",
        json.dumps(
            duplicates,
            ensure_ascii=False,
            indent=2).encode("utf-8") +
        b"\n")
    # Write probably new
    ecriture_atomique(
        output_dir /
        "probably_new.json",
        json.dumps(
            probably_new,
            ensure_ascii=False,
            indent=2).encode("utf-8") +
        b"\n")
    # Write errors
    ecriture_atomique(
        output_dir /
        "processing_errors.json",
        json.dumps(
            errors,
            ensure_ascii=False,
            indent=2).encode("utf-8") +
        b"\n")

    # Map details to make review queue and import list
    fw_dict = {str(x["source_id"]): x for x in fw_data}

    # Write probably_new_import_candidates.json
    import_candidates = []
    for p in probably_new:
        fw_id = str(p["free_work_source_id"])
        fw_offer = fw_dict[fw_id]
        import_candidates.append({
            "free_work_source_id": fw_id,
            "title": fw_offer["title"],
            "company_name": fw_offer.get("company_name"),
            "location": fw_offer.get("location"),
            "description": fw_offer.get("description"),
            "source_url": fw_offer.get("source_url") or "",
            "import_status": "PENDING_VALIDATION",
            "import_eligible": False
        })
    ecriture_atomique(
        output_dir /
        "probably_new_import_candidates.json",
        json.dumps(
            import_candidates,
            ensure_ascii=False,
            indent=2).encode("utf-8") +
        b"\n")

    # Build human review queues (JSON & CSV)
    # Get matches dict
    matches_dict = {str(m["free_work_source_id"]): m for m in results_candidate_matches}

    review_queue = []
    for hr in human_review:
        fw_id = str(hr["free_work_source_id"])
        fw_offer = fw_dict[fw_id]
        match_entry = matches_dict.get(fw_id)

        # Get top 5 candidates
        cands = match_entry.get("top_candidates", [])[:5] if match_entry else []
        candidates_list = []
        for rank_idx, c in enumerate(cands):
            candidates_list.append({
                "france_travail_id": c["france_travail_id"],
                "title": c["title"],
                "company_name": c["company_name"],
                "postal_code": c["postal_code"],
                "rome_code": c["rome_code"],
                "preliminary_match_score": c["preliminary_match_score"],
                "evidence_coverage": c["evidence_coverage"],
                "rank": rank_idx + 1,
                "components": c["components"]
            })

        review_queue.append({
            "free_work_source_id": fw_id,
            "free_work_title": fw_offer["title"],
            "free_work_company": fw_offer.get("company_name"),
            "free_work_location": fw_offer.get("location"),
            "free_work_description": fw_offer.get("description"),
            "free_work_source_url": fw_offer.get("source_url") or "",
            "candidates_france_travail": candidates_list,
            "human_decision": "",
            "human_selected_france_travail_id": "",
            "human_comment": "",
            "reviewed_at": ""
        })

    # Write human_review_queue.json
    ecriture_atomique(
        output_dir /
        "human_review_queue.json",
        json.dumps(
            review_queue,
            ensure_ascii=False,
            indent=2).encode("utf-8") +
        b"\n")

    # Write human_review_queue.csv
    csv_path = output_dir / "human_review_queue.csv"
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["free_work_source_id",
                             "free_work_title",
                             "free_work_company",
                             "free_work_location",
                             "free_work_source_url",
                             "best_france_travail_id",
                             "best_match_score",
                             "candidate_count",
                             "human_decision",
                             "human_selected_france_travail_id",
                             "human_comment",
                             "reviewed_at"])
            for q in review_queue:
                best_ft_id = q["candidates_france_travail"][0]["france_travail_id"] if q["candidates_france_travail"] else ""  # pylint: disable=line-too-long
                best_score = q["candidates_france_travail"][0]["preliminary_match_score"] if q["candidates_france_travail"] else ""  # pylint: disable=line-too-long
                writer.writerow([q["free_work_source_id"],
                                 q["free_work_title"],
                                 q["free_work_company"],
                                 q["free_work_location"],
                                 q["free_work_source_url"],
                                 best_ft_id,
                                 best_score,
                                 len(q["candidates_france_travail"]),
                                 "",
                                 "",
                                 "",
                                 ""])
    except Exception as e:
        print(f"Warning: Failed to write CSV file: {e}", file=sys.stderr)

    # Triage Summary
    summary = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_triage": len(results_triage_results),
        "duplicate_high_confidence": counters["DUPLICATE_HIGH_CONFIDENCE"],
        "probably_new": counters["PROBABLY_NEW"],
        "human_review_required": counters["HUMAN_REVIEW_REQUIRED"],
        "processing_errors": counters["PROCESSING_ERROR"]
    }
    ecriture_atomique(
        output_dir /
        "triage_summary.json",
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2).encode("utf-8") +
        b"\n")

    # Finalize progress and manifest
    progress_data = {
        "status": "COMPLETED",
        "benchmark_id": run_id,
        "configuration_current": 1,
        "configurations_total": 1,
        "strategy": "independent_normalized",
        "aliases_enabled": True,
        "run_current": 1,
        "runs_total": 1,
        "offers_processed": total_offers,
        "offers_total": total_offers,
        "percent_run": 100.0,
        "percent_global": 100.0,
        "elapsed_run_seconds": round(time.time() - START_TIME),
        "elapsed_global_seconds": round(time.time() - START_TIME),
        "heartbeat_at": time.strftime("%H:%M:%S"),
        "completed_runs": []
    }
    ecrire_progres_benchmark(PROCESSED_DATA_ROOT / "matching", progress_data)

    final_manifest = {
        "triage_rule_version": "CONSERVATIVE_RULESET_V1",
        "matching_strategy": "independent_normalized",
        "aliases_enabled": True,
        "free_work_hash": fw_hash,
        "france_travail_hash": ft_hash,
        "free_work_offers": total_offers,
        "france_travail_offers": n_ft,
        "last_processed_index": total_offers,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "COMPLETED"
    }
    ecriture_atomique(
        checkpoint_file,
        json.dumps(
            final_manifest,
            ensure_ascii=False,
            indent=2).encode("utf-8") +
        b"\n")

    print(f"\nTriage process completed! Outputs saved to {output_dir}")


def ecrire_progres_benchmark(bench_dir, progress_data):
    """."""
    dest_path = bench_dir / "progress.json"
    content_bytes = json.dumps(progress_data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    temp_name = f"progress_triage_{os.getpid()}_{time.time_ns()}.json.tmp"
    temp_path = dest_path.with_name(temp_name)
    try:
        temp_path.write_bytes(content_bytes)
        temp_path.replace(dest_path)
    except Exception as e:
        print(f"Warning writing progress: {e}", file=sys.stderr)
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    main()
