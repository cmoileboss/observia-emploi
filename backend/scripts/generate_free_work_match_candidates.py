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
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"


def normaliser_cle(texte: str, est_titre: bool = False, est_entreprise: bool = False) -> str:
    """Normalize text as company, title, or generic key."""
    if est_entreprise:
        return normaliser_entreprise(texte)
    if est_titre:
        return normaliser_titre(texte)
    return texte


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

START_TIME = time.time()


def normaliser_cle_compacte(texte_normalise: str) -> str:
    """Remove whitespace from normalized text."""
    return "".join(texte_normalise.split())


def extraire_tokens(texte_normalise: str) -> list[str]:
    """Extract significant tokens from normalized text."""
    tokens = texte_normalise.split()
    filtered = []
    for t in tokens:
        if len(t) >= 3 and t not in FRENCH_STOP_WORDS and not t.isdigit():
            filtered.append(t)
    return sorted(list(set(filtered)))


def calculer_sha256_fichier(filepath: Path) -> str:
    """Calculate SHA256 hash of file."""
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ecriture_atomique(dest_path: Path, content_bytes: bytes) -> str:
    """Atomically write file with change detection."""
    if dest_path.exists():
        if dest_path.read_bytes() == content_bytes:
            return "inchangé"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_name(dest_path.name + ".tmp")
    try:
        temp_path.write_bytes(content_bytes)
        temp_path.replace(dest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return "mis à jour"


def write_progress(
        stage: str,
        stage_number: int,
        current: int,
        total: int,
        message: str,
        status: str = "RUNNING",
        extra_stats: dict = None):
    """Write stage progress data to JSON file."""
    elapsed = time.time() - START_TIME
    percent = round((current / total) * 100, 2) if total else 0.0
    if current > 0 and elapsed > 0:
        speed = current / elapsed
        remaining_sec = round((total - current) / speed)
    else:
        remaining_sec = None

    progress_data = {
        "status": status,
        "stage": stage,
        "stage_number": stage_number,
        "stage_total": 6,
        "current": current,
        "total": total,
        "percent": percent,
        "elapsed_seconds": round(elapsed),
        "estimated_remaining_seconds": remaining_sec,
        "message": message
    }
    if extra_stats:
        progress_data.update(extra_stats)

    dest_path = PROCESSED_DATA_ROOT / "matching" / "progress.json"
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        content_bytes = json.dumps(
            progress_data,
            ensure_ascii=False,
            indent=2).encode("utf-8") + b"\n"
    except Exception as e:
        print(f"Warning: Failed to format progress data: {e}", file=sys.stderr)
        return

    temp_name = f"progress_matching_{os.getpid()}_{time.time_ns()}.json.tmp"
    temp_path = dest_path.with_name(temp_name)

    try:
        temp_path.write_bytes(content_bytes)
    except Exception as e:
        print(
            f"Warning: Failed to write to temporary progress file {temp_path}: {e}",
            file=sys.stderr)
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        return

    max_retries = 5
    backoff = 0.05
    for attempt in range(max_retries):
        try:
            temp_path.replace(dest_path)
            return  # Success
        except (PermissionError, OSError) as e:
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff *= 2
            else:
                print(
                    f"Warning: Failed to replace progress file after {max_retries} attempts: {e}",
                    file=sys.stderr)
        except Exception as e:
            print(f"Warning: Unexpected error replacing progress file: {e}", file=sys.stderr)
            break

    if temp_path.exists():
        try:
            temp_path.unlink()
        except Exception:
            pass


class ProgressTracker:
    """Track and display multi-stage processing progress."""
    def __init__(self, stage_number: int, stage_name: str, total: int, message: str):
        """Initialize progress tracker with stage info."""
        self.stage_number = stage_number
        self.stage_name = stage_name
        self.total = total
        self.message = message
        self.last_print_time = 0.0
        self.last_print_count = 0
        self.update(0, force=True)

    def update(self, current: int, force: bool = False, extra_stats: dict = None):
        """Update progress display and metrics."""
        now = time.time()
        elapsed = now - START_TIME
        percent = round((current / self.total) * 100, 2) if self.total else 0.0

        write_progress(
            self.stage_name,
            self.stage_number,
            current,
            self.total,
            self.message,
            "RUNNING",
            extra_stats)

        if force or current == 0 or current == self.total or (
            current -
            self.last_print_count >= 50) or (
            now -
                self.last_print_time >= 5.0):
            self.last_print_time = now
            self.last_print_count = current

            el_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
            if current > 0 and elapsed > 0:
                speed = current / elapsed
                remaining_sec = round((self.total - current) / speed)
                rem_str = f"{int(remaining_sec // 60):02d}:{int(remaining_sec % 60):02d}"
                speed_str = f"{speed:.2f} offres/s"
            else:
                rem_str = "--:--"
                speed_str = "-- offres/s"

            print(f"[{self.stage_number}/6] {current} / {self.total} offres — {percent:.2f} %")
            print(
                f"Temps écoulé : {el_str} | Vitesse : {speed_str} | Temps restant estimé : {rem_str}")  # pylint: disable=line-too-long
            if extra_stats:
                stat_parts = []
                for k, v in extra_stats.items():
                    if k != "heartbeat":
                        stat_parts.append(f"{k}: {v}")
                print(f"Stats intermédiaires: {', '.join(stat_parts)}")
            print(f"Traitement toujours actif — étape {self.stage_number}/6")


def charger_free_work(path: Path) -> list[dict]:
    """Load and validate Free-Work offers with uniqueness checks."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    seen_ids = set()
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"L'offre Free-Work à l'index {idx} n'est pas un dictionnaire.")
        for k in ["source", "source_id", "title"]:
            if k not in item:
                raise ValueError(f"Clé '{k}' manquante dans l'offre Free-Work à l'index {idx}.")
        if item["source"] != "free_work":
            raise ValueError(f"Source invalide à l'index {idx} : {item['source']}.")

        sid = str(item["source_id"]).strip()
        if not sid:
            raise ValueError(f"source_id vide à l'index {idx}.")
        if sid in seen_ids:
            raise ValueError(f"source_id dupliqué détecté : {sid}")
        seen_ids.add(sid)

        if not item["title"] or not str(item["title"]).strip():
            raise ValueError(f"Titre manquant ou vide pour l'offre Free-Work {sid}.")

        desc = item.get("description")
        if not desc or not str(desc).strip():
            item["description"] = None
        else:
            item["description"] = str(desc).strip()

    return data


def charger_france_travail(path: Path) -> list[dict]:
    """Load and validate France Travail offers with required fields."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    seen_ids = set()
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"L'offre France Travail à l'index {idx} n'est pas un dictionnaire.")
        for k in ["france_travail_id", "title", "description", "rome_code"]:
            if k not in item:
                raise ValueError(
                    f"Clé '{k}' manquante dans l'offre France Travail à l'index {idx}.")

        fid = str(item["france_travail_id"]).strip()
        if not fid:
            raise ValueError(f"france_travail_id vide à l'index {idx}.")
        if fid in seen_ids:
            raise ValueError(f"france_travail_id dupliqué détecté : {fid}")
        seen_ids.add(fid)

        if not item["title"] or not str(item["title"]).strip():
            raise ValueError(f"Titre manquant ou vide pour l'offre France Travail {fid}.")
        if not item["description"] or not str(item["description"]).strip():
            raise ValueError(f"Description manquante ou vide pour l'offre France Travail {fid}.")
        if not item["rome_code"] or not str(item["rome_code"]).strip():
            raise ValueError(f"rome_code manquant ou vide pour l'offre France Travail {fid}.")

    return data


def match_entreprises(comp_fw: str, comp_ft: str) -> tuple[str, float]:
    """Match and score company names."""
    if not comp_fw or not comp_ft:
        return "MISSING", 0.0
    if comp_fw == comp_ft:
        return "EXACT_NORMALIZED", 1.0

    # Guard on generic and very short names
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
    """Match and score geographic locations."""
    if not fw_pc or not ft_pc:
        return "UNKNOWN", 0.0
    if fw_pc == ft_pc:
        return "EXACT_POSTAL_CODE", 1.0
    if fw_loc_norm and ft_loc_norm and fw_loc_norm == ft_loc_norm:
        return "SAME_LOCALITY", 0.9
    if fw_dept and ft_dept and fw_dept == ft_dept:
        return "SAME_DEPARTMENT", 0.5
    return "DIFFERENT", 0.0


def generer_matching(
        fw_path: Path,
        ft_path: Path,
        strategy: str = "independent_normalized",
        use_aliases: bool = False,
        benchmark_id: str = None) -> None:
    """Generate candidate matches and scoring for Free-Work offers."""
    global START_TIME
    START_TIME = time.time()
    # [1/6] Chargement et validation des entrées
    write_progress("INPUT_LOADING", 1, 0, 1, "Chargement et validation des entrées")
    t_start_load = time.time()
    fw_data = charger_free_work(fw_path)
    ft_data = charger_france_travail(ft_path)
    t_load = time.time() - t_start_load
    write_progress("INPUT_LOADING", 1, 1, 1, "Chargement et validation des entrées")

    fw_data.sort(key=lambda x: str(x["source_id"]))

    # [2/6] Construction des index France Travail et normalisation commune
    write_progress("INDEX_CONSTRUCTION", 2, 0, len(ft_data),
                   "Construction des index France Travail")
    t_start_index = time.time()
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
    corse_outremer_cases = 0

    for idx, item in enumerate(ft_data):
        fid = item["france_travail_id"]

        title_norm = normaliser_titre(item["title"])
        title_compact = normaliser_cle_compacte(title_norm)
        desc_norm = normaliser_description(item["description"])

        company_raw = item.get("company_name")
        company_norm = normaliser_entreprise(company_raw)
        if use_aliases and company_norm in COMPANY_ALIASES:
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
        if dept in ["2A", "2B"] or (dept.isdigit() and int(dept) > 95):
            corse_outremer_cases += 1

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

        fp1 = f"{title_norm}|{company_norm}|{pc_str}"
        offers_by_fp1[fp1].add(fid)
        fp2 = f"{title_norm}|{pc_str}"
        offers_by_fp2[fp2].add(fid)
        fp3 = f"{company_norm}|{title_norm}"
        offers_by_fp3[fp3].add(fid)
        fp4 = f"{title_norm}|{desc_norm}"
        offers_by_fp4[fp4].add(fid)

        if idx > 0 and idx % 2000 == 0:
            write_progress("INDEX_CONSTRUCTION", 2, idx, len(ft_data),
                           "Construction des index France Travail")

    n_total = len(ft_data)
    idf_title = {}
    for tok, freq in doc_freq_title.items():
        idf_title[tok] = math.log((n_total + 1) / (freq + 1)) + 1

    idf_desc = {}
    for tok, freq in doc_freq_desc.items():
        idf_desc[tok] = math.log((n_total + 1) / (freq + 1)) + 1

    t_index = time.time() - t_start_index
    write_progress("INDEX_CONSTRUCTION", 2, len(ft_data), len(
        ft_data), "Construction des index France Travail")

    # [3/6] Génération et pré-score des candidats
    t_start_matching = time.time()
    results = []

    offers_with_candidates = 0
    offers_without_candidates = 0
    total_candidates_before_pre_limit = 0
    total_pre_candidates_retained = 0
    total_detailed_candidates_retained = 0

    block_counts = defaultdict(int)
    multi_block_count = 0
    exact_fp_count = 0
    score_distribution = {"0-39": 0, "40-59": 0, "60-74": 0, "75-84": 0, "85-100": 0}

    all_scored_pairs = []

    # Cascade intermediate metrics
    candidates_before_company = 0
    candidates_after_company = 0
    candidates_after_geography = 0
    candidates_after_title = 0
    candidates_sent_to_detailed_score = 0

    offers_lost_at_company = 0
    offers_lost_at_geography = 0
    offers_lost_at_title = 0
    offers_rejected_by_score = 0
    offers_ambiguous = 0

    offers_accepted_by_primary_chain = 0
    offers_requiring_fallback = 0
    offers_recovered_by_fallback = 0
    offers_still_without_candidate = 0

    fallback_reasons_dist = defaultdict(int)

    tracker_stage3 = ProgressTracker(3, "CANDIDATE_GENERATION", len(
        fw_data), "Génération et pré-score des candidats")

    for fw_idx, fw_item in enumerate(fw_data):
        fw_sid = str(fw_item["source_id"])
        fw_title_norm = normaliser_titre(fw_item["title"])
        fw_title_compact = normaliser_cle_compacte(fw_title_norm)

        fw_desc = fw_item.get("description")
        fw_desc_norm = normaliser_description(fw_desc) if fw_desc else ""

        fw_company_raw = fw_item.get("company_name")
        fw_company_norm = normaliser_entreprise(fw_company_raw)
        if use_aliases and fw_company_norm in COMPANY_ALIASES:
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

        # Block mapping
        candidates_blocks_map = defaultdict(set)
        candidate_generation_paths = defaultdict(list)

        strategy_info = {
            "strategy": strategy,
            "use_aliases": use_aliases,
            "primary_chain_executed": False,
            "primary_chain_result": "NONE",
            "primary_chain_stopped_at": "NONE",
            "fallback_executed": False,
            "fallback_reason": "NONE"
        }

        # Sub-functions to run blocks
        def run_legacy_blocks(is_fallback=False):
            """Run legacy block-based matching for backward compatibility."""
            block_prefix = "FALLBACK_" if is_fallback else ""
            # Bloc 1 : Empreintes strictes
            fp1 = f"{fw_title_norm}|{fw_company_norm}|{fw_pc}"
            for fid in offers_by_fp1.get(fp1, []):
                candidates_blocks_map[fid].add(f"{block_prefix}EXACT_FINGERPRINT")
                candidate_generation_paths[fid].append(f"{block_prefix}EXACT_FINGERPRINT")
            fp2 = f"{fw_title_norm}|{fw_pc}"
            for fid in offers_by_fp2.get(fp2, []):
                candidates_blocks_map[fid].add(f"{block_prefix}EXACT_FINGERPRINT")
                candidate_generation_paths[fid].append(f"{block_prefix}EXACT_FINGERPRINT")
            fp3 = f"{fw_company_norm}|{fw_title_norm}"
            for fid in offers_by_fp3.get(fp3, []):
                candidates_blocks_map[fid].add(f"{block_prefix}EXACT_FINGERPRINT")
                candidate_generation_paths[fid].append(f"{block_prefix}EXACT_FINGERPRINT")
            fp4 = f"{fw_title_norm}|{fw_desc_norm}"
            for fid in offers_by_fp4.get(fp4, []):
                candidates_blocks_map[fid].add(f"{block_prefix}EXACT_FINGERPRINT")
                candidate_generation_paths[fid].append(f"{block_prefix}EXACT_FINGERPRINT")

            # Bloc 2 : Clé compacte identique
            if fw_title_compact:
                for fid in offers_by_compact_title.get(fw_title_compact, []):
                    candidates_blocks_map[fid].add(f"{block_prefix}COMPACT_TITLE_EXACT")
                    candidate_generation_paths[fid].append(f"{block_prefix}COMPACT_TITLE_EXACT")

            # Bloc 3 : Code postal exact
            if fw_pc:
                for fid in offers_by_postal_code.get(fw_pc, []):
                    candidates_blocks_map[fid].add(f"{block_prefix}EXACT_POSTAL_CODE")
                    candidate_generation_paths[fid].append(f"{block_prefix}EXACT_POSTAL_CODE")

            # Bloc 4 : Département + Titre commun significatif
            if fw_dept:
                dept_offers = offers_by_department.get(fw_dept, set())
                for tok in fw_tokens:
                    token_offers = offers_by_title_token.get(tok, set())
                    for fid in dept_offers.intersection(token_offers):
                        candidates_blocks_map[fid].add(f"{block_prefix}SAME_DEPARTMENT_TITLE")
                        candidate_generation_paths[fid].append(
                            f"{block_prefix}SAME_DEPARTMENT_TITLE")

            # Bloc 5 : ROME + Titre commun significatif (Only for legacy /
            # independent, NOT fallback)
            if not is_fallback:
                for rome in fw_romes:
                    rome_offers = offers_by_rome.get(rome, set())
                    for tok in fw_tokens:
                        token_offers = offers_by_title_token.get(tok, set())
                        for fid in rome_offers.intersection(token_offers):
                            candidates_blocks_map[fid].add("ROME_QUERY_TITLE")
                            candidate_generation_paths[fid].append("ROME_QUERY_TITLE")

            # Bloc 6 : Entreprise
            if fw_company_norm:
                for fid in offers_by_company.get(fw_company_norm, []):
                    candidates_blocks_map[fid].add(f"{block_prefix}COMPANY_MATCH")
                    candidate_generation_paths[fid].append(f"{block_prefix}COMPANY_MATCH")
                for tok in extraire_tokens(fw_company_norm):
                    for fid in offers_by_company_token.get(tok, []):
                        comp_ft = ft_normalized[fid]["company_norm"]
                        if comp_ft:
                            sim = SequenceMatcher(None, fw_company_norm, comp_ft).ratio()
                            if sim >= 0.8:
                                candidates_blocks_map[fid].add(f"{block_prefix}COMPANY_MATCH")
                                candidate_generation_paths[fid].append(
                                    f"{block_prefix}COMPANY_MATCH")

            # Bloc 7 : Tokens rares du titre
            title_tokens_with_freq = []
            for tok in fw_tokens:
                freq = doc_freq_title.get(tok, 0)
                if freq > 0 and freq < MAX_RARE_TOKEN_DOCUMENT_FREQUENCY:
                    title_tokens_with_freq.append((tok, freq))
            title_tokens_with_freq.sort(key=lambda x: (x[1], x[0]))
            rare_tokens = [x[0] for x in title_tokens_with_freq[:MAX_RARE_TITLE_TOKENS]]
            for tok in rare_tokens:
                for fid in offers_by_title_token.get(tok, []):
                    candidates_blocks_map[fid].add(f"{block_prefix}RARE_TITLE_TOKENS")
                    candidate_generation_paths[fid].append(f"{block_prefix}RARE_TITLE_TOKENS")

        if strategy == "independent_normalized":
            run_legacy_blocks(is_fallback=False)

        else:
            # CASCADE STRATEGIES: strict_chain OR hybrid_cascade
            strategy_info["primary_chain_executed"] = True
            candidates_before_company += len(ft_data)

            # 1. Company Filter
            company_matched_fids = set()
            if not fw_company_norm:
                strategy_info["primary_chain_stopped_at"] = "COMPANY"
                strategy_info["primary_chain_result"] = "COMPANY_MISSING"
                offers_lost_at_company += 1
            else:
                candidate_fids_comp = set(offers_by_company.get(fw_company_norm, []))
                for tok in extraire_tokens(fw_company_norm):
                    candidate_fids_comp.update(offers_by_company_token.get(tok, []))

                for fid in candidate_fids_comp:
                    ft_comp = ft_normalized[fid]["company_norm"]
                    res_comp, _ = match_entreprises(fw_company_norm, ft_comp)
                    if res_comp in [
                        "EXACT_NORMALIZED",
                        "ALIAS_MATCH",
                        "CONTAINMENT_MATCH",
                            "HIGH_SIMILARITY"]:
                        company_matched_fids.add(fid)

                candidates_after_company += len(company_matched_fids)
                if not company_matched_fids:
                    strategy_info["primary_chain_stopped_at"] = "COMPANY"
                    strategy_info["primary_chain_result"] = "NO_COMPANY_CANDIDATE"
                    offers_lost_at_company += 1

            # 2. Geographical Filter
            geo_matched_fids = set()
            if company_matched_fids:
                for fid in company_matched_fids:
                    ft_item = ft_normalized[fid]
                    res_geo, _ = match_geographie(
                        fw_pc, fw_locality_norm, fw_dept,
                        ft_item["postal_code"], ft_item["locality_norm"], ft_item["department"]
                    )
                    if res_geo != "DIFFERENT":
                        geo_matched_fids.add(fid)

                candidates_after_geography += len(geo_matched_fids)
                if not geo_matched_fids:
                    strategy_info["primary_chain_stopped_at"] = "GEOGRAPHY"
                    strategy_info["primary_chain_result"] = "NO_GEOGRAPHY_CANDIDATE"
                    offers_lost_at_geography += 1

            # 3. Title Filter
            primary_fids = set()
            if geo_matched_fids:
                for fid in geo_matched_fids:
                    ft_item = ft_normalized[fid]
                    t1 = set(fw_tokens)
                    t2 = set(ft_item["title_tokens"])
                    title_seq = SequenceMatcher(None, fw_title_norm, ft_item["title_norm"]).ratio()
                    # Require at least 1 token or similarity >= 0.30
                    if (t1 & t2) or title_seq >= 0.30:
                        primary_fids.add(fid)
                        candidates_blocks_map[fid].add("PRIMARY_CHAIN")
                        candidate_generation_paths[fid].append("PRIMARY_CHAIN")

                candidates_after_title += len(primary_fids)
                if not primary_fids:
                    strategy_info["primary_chain_stopped_at"] = "TITLE"
                    strategy_info["primary_chain_result"] = "NO_TITLE_CANDIDATE"
                    offers_lost_at_title += 1
                else:
                    strategy_info["primary_chain_stopped_at"] = "COMPLETED"
                    strategy_info["primary_chain_result"] = "SUCCESS"

            # 4. Fallback execution check (only for hybrid_cascade)
            run_fallback = False
            fallback_reason = "NONE"

            if strategy in [
                "strict_chain",
                    "hybrid_cascade"] and strategy_info["primary_chain_result"] == "SUCCESS":
                # Score primary candidates
                best_score = -1.0
                second_score = -1.0
                for fid in primary_fids:
                    ft_item = ft_normalized[fid]
                    t1 = set(fw_tokens)
                    t2 = set(ft_item["title_tokens"])
                    j_t = len(t1 & t2) / len(t1 | t2) if t1 | t2 else 0
                    w_t = sum(idf_title.get(t, 1.0) for t in (t1 & t2)) / \
                        sum(idf_title.get(t, 1.0) for t in t1) if t1 else 0
                    ft_compact = ft_item["title_compact"]
                    c_t = SequenceMatcher(None, fw_title_compact, ft_compact).ratio(
                    ) if fw_title_compact or ft_compact else 0

                    comp_score = 8 if fw_company_norm == ft_item["company_norm"] else 0
                    geo_score = 7 if fw_pc == ft_item["postal_code"] else 0
                    rome_score = 5 if ft_item["rome_code"] in fw_romes else 0

                    pre_score = j_t * 35 + w_t * 35 + c_t * 10 + comp_score + geo_score + rome_score
                    if pre_score > best_score:
                        second_score = best_score
                        best_score = pre_score
                    elif pre_score > second_score:
                        second_score = pre_score

                if best_score < 40.0:
                    offers_rejected_by_score += 1
                    if strategy == "hybrid_cascade":
                        run_fallback = True
                        fallback_reason = "LOW_PRIMARY_SCORE"
                elif (best_score - second_score) < 5.0 and len(primary_fids) > 1:
                    offers_ambiguous += 1
                    if strategy == "hybrid_cascade":
                        run_fallback = True
                        fallback_reason = "AMBIGUOUS_PRIMARY_MARGIN"

            if strategy == "hybrid_cascade" and not run_fallback:
                if strategy_info["primary_chain_result"] == "COMPANY_MISSING":
                    run_fallback = True
                    fallback_reason = "MISSING_PRIMARY_DATA"
                elif strategy_info["primary_chain_result"] == "NO_COMPANY_CANDIDATE":
                    run_fallback = True
                    fallback_reason = "NO_COMPANY_CANDIDATE"
                elif strategy_info["primary_chain_result"] in ["NO_GEOGRAPHY_CANDIDATE", "GEOGRAPHY_MISSING"]:  # pylint: disable=line-too-long
                    run_fallback = True
                    fallback_reason = "NO_GEOGRAPHY_CANDIDATE"
                elif strategy_info["primary_chain_result"] == "NO_TITLE_CANDIDATE":
                    run_fallback = True
                    fallback_reason = "NO_TITLE_CANDIDATE"

            if run_fallback:
                offers_requiring_fallback += 1
                fallback_reasons_dist[fallback_reason] += 1
                strategy_info["fallback_executed"] = True
                strategy_info["fallback_reason"] = fallback_reason

                # Temporarily store blocks
                temp_map = len(candidates_blocks_map)
                run_legacy_blocks(is_fallback=True)

                # Check if we recovered any candidates
                if len(candidates_blocks_map) > temp_map:
                    offers_recovered_by_fallback += 1
            else:
                if strategy_info["primary_chain_result"] == "SUCCESS":
                    offers_accepted_by_primary_chain += 1

        raw_candidates_ids = list(candidates_blocks_map.keys())
        candidates_before_pre_limit = len(raw_candidates_ids)
        total_candidates_before_pre_limit += candidates_before_pre_limit

        # 3. Pré-score rapide
        pre_scored_candidates = []
        for fid in raw_candidates_ids:
            ft_item = ft_normalized[fid]

            t1 = set(fw_tokens)
            t2 = set(ft_item["title_tokens"])
            jaccard_title = len(t1 & t2) / len(t1 | t2) if t1 | t2 else 0

            sum_idf_common = sum(idf_title.get(tok, 1.0) for tok in (t1 & t2))
            sum_idf_total = sum(idf_title.get(tok, 1.0) for tok in t1)
            weighted_title = sum_idf_common / sum_idf_total if sum_idf_total else 0

            ft_title_compact = ft_item["title_compact"]
            compact_sim = SequenceMatcher(None, fw_title_compact, ft_title_compact).ratio(
            ) if fw_title_compact or ft_title_compact else 0

            comp_score = 0
            if fw_company_norm and ft_item["company_norm"]:
                if fw_company_norm == ft_item["company_norm"]:
                    comp_score = 8
                else:
                    sim = SequenceMatcher(None, fw_company_norm, ft_item["company_norm"]).ratio()
                    if sim >= 0.8:
                        comp_score = sim * 8

            geo_score = 0
            if fw_pc and ft_item["postal_code"]:
                if fw_pc == ft_item["postal_code"]:
                    geo_score = 7
                elif fw_dept == ft_item["department"]:
                    geo_score = 3.5

            rome_score = 5 if ft_item["rome_code"] in fw_romes else 0

            pre_score = (
                jaccard_title * 35 +
                weighted_title * 35 +
                compact_sim * 10 +
                comp_score +
                geo_score +
                rome_score
            )
            pre_scored_candidates.append((fid, pre_score))

        pre_scored_candidates.sort(key=lambda x: (-x[1], x[0]))
        retained_pre_candidates = pre_scored_candidates[:MAX_PRE_CANDIDATES_PER_OFFER]
        pre_candidates_retained = len(retained_pre_candidates)
        total_pre_candidates_retained += pre_candidates_retained
        candidates_sent_to_detailed_score += pre_candidates_retained

        # 4. Score détaillé
        detailed_candidates = []
        for fid, _ in retained_pre_candidates:
            ft_item = ft_normalized[fid]

            title_seq = SequenceMatcher(None, fw_title_norm, ft_item["title_norm"]).ratio()
            t1 = set(fw_tokens)
            t2 = set(ft_item["title_tokens"])
            title_jac = len(t1 & t2) / len(t1 | t2) if t1 | t2 else 0

            sum_idf_common = sum(idf_title.get(tok, 1.0) for tok in (t1 & t2))
            sum_idf_total = sum(idf_title.get(tok, 1.0) for tok in t1)
            title_weighted = sum_idf_common / sum_idf_total if sum_idf_total else 0

            ft_title_compact = ft_item["title_compact"]
            title_compact_seq = SequenceMatcher(
                None, fw_title_compact, ft_title_compact).ratio() if fw_title_compact or ft_title_compact else 0  # pylint: disable=line-too-long

            title_score_contrib = 45 * (title_seq * 0.25 + title_jac *
                                        0.25 + title_weighted * 0.25 + title_compact_seq * 0.25)

            desc_jac = None
            desc_weighted = None
            desc_score_contrib = 0
            description_source = "description"

            if fw_desc_norm and ft_item["desc_norm"]:
                d1 = set(fw_desc_tokens)
                d2 = set(ft_item["desc_tokens"])
                desc_jac = len(d1 & d2) / len(d1 | d2) if d1 | d2 else 0

                sum_idf_common_desc = sum(idf_desc.get(tok, 1.0) for tok in (d1 & d2))
                sum_idf_total_desc = sum(idf_desc.get(tok, 1.0) for tok in d1)
                desc_weighted = sum_idf_common_desc / \
                    sum_idf_total_desc if sum_idf_total_desc else 0  # pylint: disable=line-too-long

                desc_score_contrib = 25 * (desc_jac * 0.4 + desc_weighted * 0.6)
            else:
                description_source = "missing"

            company_seq = None
            company_score_contrib = 0
            if fw_company_norm and ft_item["company_norm"]:
                company_seq = SequenceMatcher(
                    None, fw_company_norm, ft_item["company_norm"]).ratio()
                company_score_contrib = company_seq * 10

            geography_label = "UNKNOWN"
            geo_score_contrib = 0
            if fw_pc and ft_item["postal_code"]:
                if fw_pc == ft_item["postal_code"]:
                    geography_label = "EXACT_POSTAL_CODE"
                    geo_score_contrib = 15
                elif fw_dept == ft_item["department"]:
                    geography_label = "SAME_DEPARTMENT"
                    geo_score_contrib = 8
                else:
                    geography_label = "DIFFERENT"
                    geo_score_contrib = 0

            rome_match = ft_item["rome_code"] in fw_romes
            rome_score_contrib = 5 if rome_match else 0

            final_score = title_score_contrib + desc_score_contrib + \
                company_score_contrib + geo_score_contrib + rome_score_contrib

            coverage = 45
            if fw_desc_norm and ft_item["desc_norm"]:
                coverage += 25
            if fw_pc and ft_item["postal_code"]:
                coverage += 15
            if fw_company_norm and ft_item["company_norm"]:
                coverage += 10
            if ft_item["rome_code"] and fw_romes:
                coverage += 5

            # Detailed comparisons
            comp_res, comp_sim_val = match_entreprises(fw_company_norm, ft_item["company_norm"])
            geo_res, _ = match_geographie(
                fw_pc, fw_locality_norm, fw_dept,
                ft_item["postal_code"], ft_item["locality_norm"], ft_item["department"]
            )

            # Titles comparison tokens
            shared_toks = list(t1 & t2)

            detailed_candidates.append({
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
                    "description_source": description_source,
                    "company_sequence_similarity": round(company_seq, 4) if company_seq is not None else None,  # pylint: disable=line-too-long
                    "geography": geography_label,
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
                    "shared_significant_tokens": shared_toks,
                    "sequence_similarity": round(title_seq, 4),
                    "weighted_token_similarity": round(title_weighted, 4)
                },
                "candidate_blocks": sorted(list(candidates_blocks_map[fid])),
                "candidate_generation_paths": sorted(list(set(candidate_generation_paths[fid])))
            })

        detailed_candidates.sort(
            key=lambda x: (-x["preliminary_match_score"], x["france_travail_id"]))
        retained_detailed_candidates = detailed_candidates[:MAX_DETAILED_CANDIDATES_PER_OFFER]
        detailed_candidates_retained = len(retained_detailed_candidates)
        total_detailed_candidates_retained += detailed_candidates_retained

        state_label = "CANDIDATES_FOUND" if detailed_candidates_retained > 0 else "NO_CANDIDATE"
        if detailed_candidates_retained > 0:
            offers_with_candidates += 1
            best_score = retained_detailed_candidates[0]["preliminary_match_score"]
            if best_score < 40:
                score_distribution["0-39"] += 1
            elif best_score < 60:
                score_distribution["40-59"] += 1
            elif best_score < 75:
                score_distribution["60-74"] += 1
            elif best_score < 85:
                score_distribution["75-84"] += 1
            else:
                score_distribution["85-100"] += 1

            all_scored_pairs.append((best_score, fw_item, retained_detailed_candidates[0]))
        else:
            offers_without_candidates += 1
            all_scored_pairs.append((0.0, fw_item, None))
            if strategy in ["strict_chain", "hybrid_cascade"]:
                offers_still_without_candidate += 1

        for cand in retained_detailed_candidates:
            blocks = cand["candidate_blocks"]
            for b in blocks:
                block_counts[b] += 1
            if len(blocks) >= 2:
                multi_block_count += 1
            if "EXACT_FINGERPRINT" in blocks or "FALLBACK_EXACT_FINGERPRINT" in blocks:
                exact_fp_count += 1

        desc_excerpt = fw_desc[:150] + "..." if fw_desc and len(fw_desc) > 150 else (fw_desc or "")

        results.append({
            "free_work_source_id": fw_sid,
            "free_work_title": fw_item["title"],
            "free_work_title_normalized": fw_title_norm,
            "free_work_company": fw_company_raw,
            "free_work_company_normalized": fw_company_norm,
            "free_work_location": {
                "locality": fw_loc.get("locality"),
                "locality_normalized": fw_locality_norm,
                "postal_code": fw_pc,
                "department_code": fw_dept
            },
            "free_work_source_url": fw_item.get("source_url") or "",
            "free_work_description_excerpt": desc_excerpt,
            "free_work_description_length": len(fw_desc) if fw_desc else 0,
            "free_work_description_hash": hashlib.sha256(fw_desc.encode("utf-8")).hexdigest() if fw_desc else "",  # pylint: disable=line-too-long
            "state": state_label,
            "candidates_before_pre_limit": candidates_before_pre_limit,
            "pre_candidates_retained": pre_candidates_retained,
            "detailed_candidates_retained": detailed_candidates_retained,
            "generation_strategy": strategy_info,
            "top_candidates": retained_detailed_candidates
        })

        tracker_stage3.update(fw_idx + 1)

    t_matching = time.time() - t_start_matching

    # [4/6] Calcul des scores détaillés (Déjà intégrés)
    write_progress("DETAILED_SCORING", 4, len(fw_data), len(fw_data), "Calcul des scores détaillés")

    # [5/6] Génération de l’échantillon humain
    write_progress("HUMAN_SAMPLE_GENERATION", 5, 0, 1, "Génération de l’échantillon humain")
    scores_85_100 = []
    scores_75_84 = []
    scores_60_74 = []
    scores_40_59 = []
    scores_0_39 = []
    scores_none = []

    for best_score, fw_item, best_cand in all_scored_pairs:
        review_entry = {
            "free_work_source_id": fw_item["source_id"],
            "free_work_title": fw_item["title"],
            "free_work_company": fw_item.get("company_name"),
            "free_work_location": fw_item.get("location"),
            "france_travail_candidate": best_cand,
            "human_decision": None,
            "human_comment": None
        }

        if best_cand is None:
            scores_none.append(review_entry)
        elif best_score >= 85:
            scores_85_100.append(review_entry)
        elif best_score >= 75:
            scores_75_84.append(review_entry)
        elif best_score >= 60:
            scores_60_74.append(review_entry)
        elif best_score >= 40:
            scores_40_59.append(review_entry)
        else:
            scores_0_39.append(review_entry)

    scores_85_100.sort(key=lambda x: x["free_work_source_id"])
    scores_75_84.sort(key=lambda x: x["free_work_source_id"])
    scores_60_74.sort(key=lambda x: x["free_work_source_id"])
    scores_40_59.sort(key=lambda x: x["free_work_source_id"])
    scores_0_39.sort(key=lambda x: x["free_work_source_id"])
    scores_none.sort(key=lambda x: x["free_work_source_id"])

    review_sample = (
        scores_85_100[:10] +
        scores_75_84[:10] +
        scores_60_74[:10] +
        scores_40_59[:10] +
        scores_0_39[:10] +
        scores_none[:10]
    )
    write_progress("HUMAN_SAMPLE_GENERATION", 5, 1, 1, "Génération de l’échantillon humain")

    # [6/6] Écriture et validation des sorties
    write_progress("WRITING_OUTPUTS", 6, 0, 1, "Écriture et validation des sorties")
    fw_sha = calculer_sha256_fichier(fw_path)
    ft_sha = calculer_sha256_fichier(ft_path)

    # Output directory handling
    if benchmark_id:
        output_dir = PROCESSED_DATA_ROOT / "matching" / "benchmarks" / benchmark_id / strategy
    else:
        ft_hash_short = ft_sha[:12]
        batch_fw = fw_path.parent.name
        output_dir = PROCESSED_DATA_ROOT / "matching" / \
            "free_work_vs_france_travail" / f"{batch_fw}__{ft_hash_short}_{strategy}"

    output_dir.mkdir(parents=True, exist_ok=True)

    output_bytes = json.dumps(
        results,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8") + b"\n"

    review_bytes = json.dumps(
        review_sample,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8") + b"\n"

    status_matches = ecriture_atomique(output_dir / "candidate_matches.json", output_bytes)
    status_review = ecriture_atomique(output_dir / "review_sample.json", review_bytes)

    # Manifeste
    manifest = {
        "matching_schema_version": 2,
        "score_version": "compact_v2_stable",
        "strategy": strategy,
        "use_aliases": use_aliases,
        "free_work_input_sha256": fw_sha,
        "france_travail_input_sha256": ft_sha,
        "free_work_offers": len(fw_data),
        "france_travail_offers": len(ft_data),
        "offers_with_candidates": offers_with_candidates,
        "offers_without_candidates": offers_without_candidates,
        "total_candidates_before_pre_limit": total_candidates_before_pre_limit,
        "total_pre_candidates_retained": total_pre_candidates_retained,
        "total_detailed_candidates_retained": total_detailed_candidates_retained,
        "average_detailed_candidates_retained": round(
            total_detailed_candidates_retained / len(fw_data),
            4) if fw_data else 0.0,
        "max_pre_candidates_per_offer": MAX_PRE_CANDIDATES_PER_OFFER,
        "max_detailed_candidates_per_offer": MAX_DETAILED_CANDIDATES_PER_OFFER,
        "corse_outremer_cases": corse_outremer_cases,
        "block_counts": dict(block_counts),
        "candidates_from_at_least_two_blocks": multi_block_count,
        "exact_fingerprint_matches": exact_fp_count,
        "score_distribution": score_distribution,
        "review_sample_size": len(review_sample)}

    if benchmark_id:
        manifest.update({
            "load_time_seconds": round(t_load, 4),
            "index_time_seconds": round(t_index, 4),
            "candidate_generation_time_seconds": round(t_matching, 4),
            "total_time_seconds": round(t_load + t_index + t_matching, 4)
        })

    # Add cascade-specific fields
    if strategy in ["strict_chain", "hybrid_cascade"]:
        manifest.update({
            "candidates_before_company": candidates_before_company,
            "candidates_after_company": candidates_after_company,
            "candidates_after_geography": candidates_after_geography,
            "candidates_after_title": candidates_after_title,
            "candidates_sent_to_detailed_score": candidates_sent_to_detailed_score,
            "offers_lost_at_company": offers_lost_at_company,
            "offers_lost_at_geography": offers_lost_at_geography,
            "offers_lost_at_title": offers_lost_at_title,
            "offers_rejected_by_score": offers_rejected_by_score,
            "offers_ambiguous": offers_ambiguous,
            "offers_accepted_by_primary_chain": offers_accepted_by_primary_chain,
            "offers_requiring_fallback": offers_requiring_fallback,
            "offers_recovered_by_fallback": offers_recovered_by_fallback,
            "offers_still_without_candidate": offers_still_without_candidate,
            "fallback_reasons_distribution": dict(fallback_reasons_dist)
        })

    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8") + b"\n"

    status_manifest = ecriture_atomique(output_dir / "matching_manifest.json", manifest_bytes)

    # Finalise progress.json
    write_progress("COMPLETED", 6, 1, 1, "Écriture et validation des sorties terminée", "COMPLETED")

    print(
        f"matching_completed | load_time: {
            t_load:.2f}s | index_time: {
            t_index:.2f}s | matching_time: {
                t_matching:.2f}s")

    if status_matches == "inchangé" and status_review == "inchangé" and status_manifest == "inchangé":  # pylint: disable=line-too-long
        print("inchangé")
    else:
        print("mis à jour")


def main() -> None:
    """Parse arguments and execute matching generation."""
    parser = argparse.ArgumentParser(
        description="Génère les candidats de rapprochement hors ligne."
    )
    parser.add_argument(
        "--free-work-input",
        required=True,
        help="Chemin vers offers_normalized.json de Free-Work."
    )
    parser.add_argument(
        "--france-travail-input",
        required=True,
        help="Chemin vers le snapshot France Travail."
    )
    parser.add_argument(
        "--strategy",
        choices=["independent_normalized", "hybrid_cascade", "strict_chain"],
        default="independent_normalized",
        help="Stratégie de rapprochement."
    )
    parser.add_argument(
        "--use-aliases",
        action="store_true",
        help="Utiliser la configuration d'alias d'entreprises."
    )
    parser.add_argument(
        "--benchmark-id",
        type=str,
        default=None,
        help="ID de benchmark si exécuté dans le cadre de tests de performance."
    )
    args = parser.parse_args()

    fw_path = Path(args.free_work_input)
    ft_path = Path(args.france_travail_input)

    try:
        generer_matching(
            fw_path=fw_path,
            ft_path=ft_path,
            strategy=args.strategy,
            use_aliases=args.use_aliases,
            benchmark_id=args.benchmark_id
        )
    except Exception as e:
        try:
            write_progress("FAILED", 0, 0, 1, f"Erreur fatale de traitement : {str(e)}", "FAILED")
        except Exception:
            pass
        print(f"Erreur d'exécution : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
