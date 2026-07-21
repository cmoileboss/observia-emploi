"""."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"

USER_AGENT = "ObservIA-Emploi/1.0 (projet pédagogique)"
ROBOTS_URL = "https://www.free-work.com/robots.txt"
API_URL = "https://www.free-work.com/api/job_postings"
START_TIME = time.time()


def normaliser_cle(texte: str | None) -> str:
    """Normalize text to ASCII lowercase for deduplication keys."""
    if texte is None:
        return ""
    s = str(texte)
    s = unicodedata.normalize("NFKC", s).casefold()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def write_progress(
        stage_name: str,
        stage_number: int,
        current: int,
        total: int,
        message: str,
        status: str = "RUNNING",
        extra_stats: dict = None):
    """Write collection progress status to JSON file with ETA."""
    elapsed = time.time() - START_TIME
    percent = round((current / total) * 100, 2) if total else 0.0
    if current > 0 and elapsed > 0:
        speed = current / elapsed
        remaining_sec = round((total - current) / speed)
    else:
        remaining_sec = None

    progress_data = {
        "status": status,
        "stage": stage_name,
        "stage_number": stage_number,
        "stage_total": 2,
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

    temp_name = f"progress_collect_{os.getpid()}_{time.time_ns()}.json.tmp"
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


def is_robots_allowed(url: str) -> bool:
    """Check robots.txt to verify collection is allowed."""
    try:
        headers = {"User-Agent": USER_AGENT}
        r = requests.get(ROBOTS_URL, headers=headers, timeout=10)
        if r.status_code == 200:
            rp = RobotFileParser()
            rp.parse(r.text.splitlines())
            return rp.can_fetch(USER_AGENT, url)
    except Exception as e:
        print(f"Warning: robots.txt check failed: {e}", file=sys.stderr)
    return True  # Fallback to allowed if check fails


def format_duration(seconds: float) -> str:
    """Format seconds to MM:SS duration string."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def collecter_exhaustive(
    delay_seconds: float,
    timeout_seconds: int,
    max_retries: int,
    max_pages: int | None,
    resume_batch_id: str | None
) -> str:
    """Exhaustively collect Free-Work job offers with pagination, deduplication, and resume support."""
    print("Démarrage de la collecte exhaustive Free-Work...")

    # Configuration structurante pour le hash de validation du checkpoint
    config_hash = hashlib.sha256(
        f"{API_URL}|{USER_AGENT}".encode("utf-8")
    ).hexdigest()

    batch_id = resume_batch_id
    is_resume = False

    if batch_id:
        batch_dir = RAW_DATA_ROOT / "free_work" / "full_catalog" / "batches" / batch_id
        checkpoint_path = batch_dir / "resume_state.json"
        if checkpoint_path.exists():
            try:
                with checkpoint_path.open("r", encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("input_configuration_hash") == config_hash:
                    print(f"Reprise du batch {batch_id} validée.")
                    is_resume = True
                else:
                    print("La configuration a changé, impossible de reprendre ce batch.")
                    sys.exit(1)
            except Exception as e:
                print(f"Erreur lors de la lecture du checkpoint : {e}")
                sys.exit(1)
        else:
            print(f"Le batch {batch_id} ne contient aucun checkpoint à reprendre.")
            sys.exit(1)
    else:
        utc_now = datetime.now(timezone.utc)
        batch_id = utc_now.strftime("%Y%m%d_%H%M%S")
        batch_dir = RAW_DATA_ROOT / "free_work" / "full_catalog" / "batches" / batch_id
        is_resume = False

    batch_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = batch_dir / "pages"
    pages_dir.mkdir(exist_ok=True)

    # Initialisation de l'état
    if is_resume:
        next_page_url = state["next_page_url"]
        visited_page_urls = set(state["visited_page_urls"])
        pages_succeeded = state["pages_succeeded"]
        pages_failed = state.get("pages_failed", {})
        raw_offer_occurrences = state.get("raw_offer_occurrences", 0)
        unique_source_ids = set(state.get("unique_source_ids", []))
        total_items_announced = state.get("total_items_announced", 0)
    else:
        # Première page par défaut
        next_page_url = f"{API_URL}?page=1&itemsPerPage=100&locationKeys=fr~~~"
        visited_page_urls = set()
        pages_succeeded = []
        pages_failed = {}
        raw_offer_occurrences = 0
        unique_source_ids = set()
        total_items_announced = 0

    # Vérification robots.txt
    robots_check = is_robots_allowed(API_URL)

    current_url = next_page_url
    pages_limit = max_pages
    pages_processed = len(pages_succeeded)
    stop_reason = "completed"

    print(f"Dossier de collecte : {batch_dir}")

    # Récupération des offres déjà chargées si on reprend
    uniques_offers = []
    if is_resume:
        offers_raw_path = batch_dir / "offers_raw.json"
        if offers_raw_path.exists():
            try:
                with offers_raw_path.open("r", encoding="utf-8") as f:
                    uniques_offers = json.load(f)
            except Exception:
                uniques_offers = []

    # Dictionnaire temporaire pour comparer les doublons
    offers_by_id = {str(o["source_id"]): o for o in uniques_offers}

    # Liste des pages d'erreurs
    failed_pages_list = []
    failed_pages_path = batch_dir / "failed_pages.json"
    if failed_pages_path.exists():
        try:
            with failed_pages_path.open("r", encoding="utf-8") as f:
                failed_pages_list = json.load(f)
        except Exception:
            pass

    duplicate_diagnostics = []

    # Boucle de pagination
    while current_url:
        # Vérification d'arrêt sur max_pages
        if pages_limit and len(pages_succeeded) >= pages_limit:
            stop_reason = "pages_limit_reached"
            print(f"Limite de pages atteinte ({pages_limit}). Arrêt.")
            break

        # Extraction du numéro de page
        parsed_url = urlparse(current_url)
        params = dict(q.split("=") for q in parsed_url.query.split("&") if "=" in q)
        page_num = int(params.get("page", 1))

        # Éviter boucle infinie
        if current_url in visited_page_urls:
            stop_reason = "infinite_loop_detected"
            print(f"Boucle infinie détectée sur l'URL : {current_url}. Arrêt.")
            break

        print(f"Collecte de la page {page_num}...")
        visited_page_urls.add(current_url)

        # Tentatives avec Retry-After et timeout
        response = None
        attempt_err = None
        for attempt in range(max_retries + 1):
            try:
                headers = {"User-Agent": USER_AGENT}
                response = requests.get(current_url, headers=headers, timeout=timeout_seconds)
                if response.status_code == 200:
                    break
                elif response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_time = int(
                        retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                    print(f"HTTP 429: Trop de requêtes. Attente de {sleep_time}s...")
                    time.sleep(sleep_time)
                elif response.status_code >= 500:
                    sleep_time = 2 ** attempt
                    print(
                        f"HTTP {
                            response.status_code}: Erreur serveur. Nouvelle tentative dans {sleep_time}s...")  # pylint: disable=line-too-long
                    time.sleep(sleep_time)
                else:
                    response.raise_for_status()
            except Exception as e:
                attempt_err = e
                sleep_time = 2 ** attempt
                if attempt < max_retries:
                    print(f"Erreur de connexion : {e}. Nouvelle tentative dans {sleep_time}s...")
                    time.sleep(sleep_time)

        if response is None or response.status_code != 200:
            err_msg = str(attempt_err) if attempt_err else f"HTTP {
                response.status_code if response else 'Inconnu'}"
            print(f"Échec définitif de la page {page_num} : {err_msg}")
            pages_failed[str(page_num)] = current_url
            failed_pages_list.append({"page": page_num, "url": current_url, "error": err_msg})
            # Passage à la page suivante quand même (estimée par URL params)
            next_page_num = page_num + 1
            current_url = f"{API_URL}?page={next_page_num}&itemsPerPage=100&locationKeys=fr~~~"
            continue

        # Traitement JSON
        try:
            data = response.json()
        except Exception as e:
            print(f"Erreur de décodage JSON sur la page {page_num} : {e}")
            pages_failed[str(page_num)] = current_url
            failed_pages_list.append(
                {"page": page_num, "url": current_url, "error": "JSON invalide"})
            next_page_num = page_num + 1
            current_url = f"{API_URL}?page={next_page_num}&itemsPerPage=100&locationKeys=fr~~~"
            continue

        # Validation de structure minimale
        if "hydra:member" not in data or "hydra:totalItems" not in data:
            print(f"Structure de schéma invalide sur la page {page_num}")
            pages_failed[str(page_num)] = current_url
            failed_pages_list.append(
                {"page": page_num, "url": current_url, "error": "Schéma invalide"})
            next_page_num = page_num + 1
            current_url = f"{API_URL}?page={next_page_num}&itemsPerPage=100&locationKeys=fr~~~"
            continue

        # Extraction
        total_items_announced = data["hydra:totalItems"]
        offres = data["hydra:member"]
        page_size_observed = len(offres)

        # Sauvegarde brute de la page
        page_file = pages_dir / f"page_{page_num:04d}.json"
        try:
            page_file.write_bytes(response.content)
        except Exception as e:
            print(f"Avertissement: Impossible d'écrire le fichier brute {page_file}: {e}")

        # Intégration des offres
        for offer in offres:
            raw_offer_occurrences += 1
            sid = str(offer.get("id") or offer.get("@id", ""))
            if not sid:
                continue

            # Création de l'offre formatée compatible normalizer
            offer_formatted = {
                "source": "free_work",
                "source_id": sid,
                "matched_rome_queries": [],
                "collection_mode": "FULL_CATALOG",
                "offer": offer
            }

            # Déduplication
            if sid in offers_by_id:
                # Doublon détecté, comparer les payloads
                old_offer = offers_by_id[sid]["offer"]
                # On compare à l'aide de dumps triés
                old_dump = json.dumps(old_offer, sort_keys=True)
                new_dump = json.dumps(offer, sort_keys=True)
                if old_dump != new_dump:
                    diffs = []
                    # Chercher les clés différentes
                    all_keys = set(old_offer.keys()) | set(offer.keys())
                    for k in all_keys:
                        if old_offer.get(k) != offer.get(k):
                            diffs.append(k)

                    # Comparer updatedAt si disponible
                    old_updated = old_offer.get("updatedAt")
                    new_updated = offer.get("updatedAt")
                    version_kept = "new"
                    if old_updated and new_updated:
                        if old_updated > new_updated:
                            version_kept = "old"
                        else:
                            offers_by_id[sid] = offer_formatted
                    else:
                        offers_by_id[sid] = offer_formatted

                    duplicate_diagnostics.append({
                        "source_id": sid,
                        "diff_keys": diffs,
                        "old_updated_at": old_updated,
                        "new_updated_at": new_updated,
                        "version_kept": version_kept
                    })
            else:
                unique_source_ids.add(sid)
                offers_by_id[sid] = offer_formatted

        pages_succeeded.append(page_num)

        # Calculer l'URL suivante de pagination
        view = data.get("hydra:view")
        next_url = None
        if view and isinstance(view, dict):
            next_url = view.get("hydra:next")

        if next_url and isinstance(next_url, str):
            next_url = next_url.strip()
            if next_url.startswith("/job_postings"):
                next_url = "/api" + next_url
            elif next_url.startswith("job_postings"):
                next_url = "/api/" + next_url
            current_url = urljoin(API_URL, next_url)
        else:
            current_url = None

        # Sauvegarde atomique de l'état temporaire pour reprise
        state_data = {
            "batch_id": batch_id,
            "endpoint_initial": API_URL,
            "next_page_url": current_url,
            "visited_page_urls": list(visited_page_urls),
            "pages_succeeded": pages_succeeded,
            "pages_failed": pages_failed,
            "raw_offer_occurrences": raw_offer_occurrences,
            "unique_source_ids": list(unique_source_ids),
            "total_items_announced": total_items_announced,
            "input_configuration_hash": config_hash,
            "collector_version": "1.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING"
        }
        try:
            state_bytes = json.dumps(
                state_data,
                ensure_ascii=False,
                indent=2).encode("utf-8") + b"\n"
            temp_state_path = checkpoint_path if 'checkpoint_path' in locals() else batch_dir / \
                "resume_state.json"
            # Écriture atomique
            tmp_checkpoint = temp_state_path.with_name(temp_state_path.name + ".tmp")
            tmp_checkpoint.write_bytes(state_bytes)
            tmp_checkpoint.replace(temp_state_path)
        except Exception as e:
            print(f"Warning: Failed to save checkpoint state: {e}", file=sys.stderr)

        # Sauvegarde de la liste brute agrégée courante
        uniques_list = list(offers_by_id.values())
        try:
            uniques_bytes = json.dumps(uniques_list, ensure_ascii=False,
                                       indent=2).encode("utf-8") + b"\n"
            tmp_raw = (batch_dir / "offers_raw.json").with_name("offers_raw.json.tmp")
            tmp_raw.write_bytes(uniques_bytes)
            tmp_raw.replace(batch_dir / "offers_raw.json")
        except Exception as e:
            print(f"Warning: Failed to save intermediate raw offers: {e}", file=sys.stderr)

        # Progression console & progress.json
        elapsed = time.time() - START_TIME
        pages_processed = len(pages_succeeded)
        est_total_pages = max(1, (total_items_announced + 99) // 100)
        pages_speed = (pages_processed / elapsed * 60) if elapsed > 0 else 0
        offers_speed = (raw_offer_occurrences / elapsed * 60) if elapsed > 0 else 0
        eta = (est_total_pages - pages_processed) / \
            (pages_processed / elapsed) if pages_processed > 0 else 0

        extra_stats = {
            "pages_processed": pages_processed,
            "pages_total_estimated": est_total_pages,
            "raw_offers": raw_offer_occurrences,
            "unique_offers": len(unique_source_ids),
            "duplicates": raw_offer_occurrences - len(unique_source_ids),
            "pages_per_minute": round(pages_speed, 2),
            "offers_per_minute": round(offers_speed, 2),
            "eta_seconds": round(eta) if eta > 0 else 0,
            "heartbeat": time.time()
        }

        # Affiche à la console et écrit progress.json de façon robuste
        write_progress(
            "FULL_CATALOG_SCRAPING",
            1,
            pages_processed,
            est_total_pages,
            "Collecte exhaustive en cours",
            "RUNNING",
            extra_stats)
        print(f"[{pages_processed}/{est_total_pages}] {len(unique_source_ids)} uniques | {raw_offer_occurrences - len(unique_source_ids)} doublons | Vitesse: {offers_speed:.1f} offres/min | Restant: {format_duration(eta)}")  # pylint: disable=line-too-long

        # Respect du délai
        if delay_seconds > 0 and current_url:
            time.sleep(delay_seconds)

    # Fin de la boucle de pagination
    # Enregistrer les fichiers finaux
    uniques_list = list(offers_by_id.values())
    uniques_bytes = json.dumps(uniques_list, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    # Écriture de offers_raw.json et offers_deduplicated.json
    try:
        # Écritures atomiques
        tmp_raw = (batch_dir / "offers_raw.json").with_name("offers_raw.json.tmp")
        tmp_raw.write_bytes(uniques_bytes)
        tmp_raw.replace(batch_dir / "offers_raw.json")

        tmp_dedup = (
            batch_dir /
            "offers_deduplicated.json").with_name("offers_deduplicated.json.tmp")
        tmp_dedup.write_bytes(uniques_bytes)
        tmp_dedup.replace(batch_dir / "offers_deduplicated.json")
    except Exception as e:
        print(f"Erreur d'écriture finale des fichiers d'offres : {e}", file=sys.stderr)

    # Écriture de failed_pages.json
    try:
        failed_bytes = json.dumps(
            failed_pages_list,
            ensure_ascii=False,
            indent=2).encode("utf-8") + b"\n"
        tmp_failed = failed_pages_path.with_name(failed_pages_path.name + ".tmp")
        tmp_failed.write_bytes(failed_bytes)
        tmp_failed.replace(failed_pages_path)
    except Exception as e:
        print(f"Erreur d'écriture de failed_pages.json : {e}", file=sys.stderr)

    # Écriture de duplicate_diagnostics.json
    try:
        diag_bytes = json.dumps(
            duplicate_diagnostics,
            ensure_ascii=False,
            indent=2).encode("utf-8") + b"\n"
        tmp_diag = (
            batch_dir /
            "duplicate_diagnostics.json").with_name("duplicate_diagnostics.json.tmp")
        tmp_diag.write_bytes(diag_bytes)
        tmp_diag.replace(batch_dir / "duplicate_diagnostics.json")
    except Exception as e:
        print(f"Erreur d'écriture de duplicate_diagnostics.json : {e}", file=sys.stderr)

    # Calcul de hashes
    raw_hash = ""
    dedup_hash = ""
    if (batch_dir / "offers_raw.json").exists():
        h = hashlib.sha256()
        with (batch_dir / "offers_raw.json").open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        raw_hash = h.hexdigest()
    if (batch_dir / "offers_deduplicated.json").exists():
        h = hashlib.sha256()
        with (batch_dir / "offers_deduplicated.json").open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        dedup_hash = h.hexdigest()

    # Finalisation du checkpoint
    state_data = {
        "batch_id": batch_id,
        "endpoint_initial": API_URL,
        "next_page_url": current_url,
        "visited_page_urls": list(visited_page_urls),
        "pages_succeeded": pages_succeeded,
        "pages_failed": pages_failed,
        "raw_offer_occurrences": raw_offer_occurrences,
        "unique_source_ids": list(unique_source_ids),
        "total_items_announced": total_items_announced,
        "input_configuration_hash": config_hash,
        "collector_version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETED" if stop_reason == "completed" else stop_reason.upper()
    }
    try:
        state_bytes = json.dumps(state_data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        tmp_checkpoint = (batch_dir / "resume_state.json").with_name("resume_state.json.tmp")
        tmp_checkpoint.write_bytes(state_bytes)
        tmp_checkpoint.replace(batch_dir / "resume_state.json")
    except Exception as e:
        print(f"Warning: Failed to save final checkpoint state: {e}", file=sys.stderr)

    # Manifeste de collecte
    manifest = {
        "batch_id": batch_id,
        "collection_mode": "FULL_CATALOG",
        "endpoint_initial": API_URL,
        "started_at": datetime.fromtimestamp(START_TIME, timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETED" if stop_reason == "completed" else stop_reason.upper(),
        "page_size_observed": 100,
        "total_items_announced_initially": total_items_announced,
        "total_items_announced_finally": total_items_announced,
        "pages_requested": len(visited_page_urls),
        "pages_succeeded": len(pages_succeeded),
        "pages_failed": len(pages_failed),
        "raw_offer_occurrences": raw_offer_occurrences,
        "unique_source_offers": len(unique_source_ids),
        "duplicate_occurrences": raw_offer_occurrences - len(unique_source_ids),
        "payload_conflicts": len(duplicate_diagnostics),
        "first_page_url": f"{API_URL}?page=1&itemsPerPage=100&locationKeys=fr~~~",
        "last_page_url": f"{API_URL}?page={pages_processed}&itemsPerPage=100&locationKeys=fr~~~",
        "delay_seconds": delay_seconds,
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
        "user_agent": USER_AGENT,
        "robots_check_result": "ALLOWED" if robots_check else "DISALLOWED",
        "output_hashes": {
            "offers_raw.json": raw_hash,
            "offers_deduplicated.json": dedup_hash
        }
    }
    try:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        tmp_manifest = (
            batch_dir /
            "collection_manifest.json").with_name("collection_manifest.json.tmp")
        tmp_manifest.write_bytes(manifest_bytes)
        tmp_manifest.replace(batch_dir / "collection_manifest.json")
    except Exception as e:
        print(f"Erreur d'écriture de collection_manifest.json : {e}", file=sys.stderr)

    # Finalise progress.json
    write_progress(
        "FULL_CATALOG_SCRAPING",
        1,
        pages_processed,
        pages_processed,
        "Collecte exhaustive terminée avec succès",
        "COMPLETED",
        {
            "pages_processed": pages_processed,
            "pages_total_estimated": pages_processed,
            "raw_offers": raw_offer_occurrences,
            "unique_offers": len(unique_source_ids),
            "duplicates": raw_offer_occurrences - len(unique_source_ids),
            "pages_per_minute": round((pages_processed / (time.time() - START_TIME) * 60) if time.time() - START_TIME > 0 else 0, 2),  # pylint: disable=line-too-long
            "offers_per_minute": round((raw_offer_occurrences / (time.time() - START_TIME) * 60) if time.time() - START_TIME > 0 else 0, 2),  # pylint: disable=line-too-long
            "eta_seconds": 0,
            "heartbeat": time.time()
        }
    )

    print(f"Collecte exhaustive terminée. Dossier : {batch_dir}")
    return batch_id


def main() -> None:
    """Main entry point to collect full Free-Work catalog."""
    parser = argparse.ArgumentParser(description="Collecte exhaustive du catalogue Free-Work.")
    parser.add_argument("--delay-seconds", type=float, default=1.0, help="Délai entre requêtes.")
    parser.add_argument("--timeout-seconds", type=int, default=20, help="Timeout de connexion.")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Tentatives de relance sur erreur HTTP.")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Nombre max de pages à collecter (pilote).")
    parser.add_argument(
        "--resume-batch-id",
        type=str,
        default=None,
        help="ID du batch à reprendre.")
    args = parser.parse_args()

    try:
        collecter_exhaustive(
            delay_seconds=args.delay_seconds,
            timeout_seconds=args.timeout_seconds,
            max_retries=args.max_retries,
            max_pages=args.max_pages,
            resume_batch_id=args.resume_batch_id
        )
    except Exception as e:
        print(f"Erreur d'exécution : {e}", file=sys.stderr)
        try:
            write_progress("FULL_CATALOG_SCRAPING", 1, 0, 1, f"Erreur fatale : {e}", "FAILED")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
