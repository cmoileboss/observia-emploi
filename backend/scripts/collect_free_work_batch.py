"""."""
from backend.scripts.collect_free_work import collecter_offres
import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Insertion du dossier parent pour que les imports depuis scripts.* fonctionnent

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"


def charger_selection_rome(csv_path: Path) -> dict[str, str]:
    """
    Charge les codes ROME et leurs intitulés depuis le fichier CSV.
    Renvoie un dictionnaire {code_rome: intitule_rome}.
    Lève des exceptions spécifiques en cas d'erreur de validation.
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Fichier ROME introuvable : {csv_path}\n"
            f"Ce fichier est un résultat du pipeline de préparation de données.\n"
            f"Le pipeline de données doit être exécuté avant le batch. Vous pouvez le lancer via :\n"  # pylint: disable=line-too-long
            f"python main.py --build-data"
        )

    selection = {}

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")

        if not reader.fieldnames:
            raise ValueError(f"Fichier ROME structure invalide (vide) : {csv_path}")

        required_headers = {"code_rome", "intitule_rome"}
        if not required_headers.issubset(reader.fieldnames):
            raise ValueError(
                f"Fichier ROME structure invalide, en-têtes attendus : code_rome et intitule_rome. "
                f"En-têtes trouvés : {reader.fieldnames}"
            )

        for line_num, row in enumerate(reader, start=2):
            code = row.get("code_rome")
            label = row.get("intitule_rome")

            if code is None:
                # Ligne vide ou mal formée
                continue

            code = code.strip()
            if not code:
                raise ValueError(
                    f"Fichier ROME invalide à la ligne {line_num} : le code ROME est vide.")

            if label is None or not label.strip():
                raise ValueError(
                    f"Fichier ROME invalide pour le code {code} à la ligne {line_num} : l'intitulé est vide.")  # pylint: disable=line-too-long

            label = label.strip()

            if code in selection:
                if selection[code] != label:
                    raise ValueError(
                        f"Fichier ROME invalide : le code ROME '{code}' est associé à des intitulés différents "  # pylint: disable=line-too-long
                        f"('{selection[code]}' et '{label}')."
                    )
                continue

            selection[code] = label

    return selection


def should_retry_exception(exc: Exception) -> bool:
    """Détermine si une exception est éligible pour un retry (codes 429, 502, 503, 504)."""
    if isinstance(exc, requests.RequestException):
        if exc.response is not None:
            return exc.response.status_code in [429, 502, 503, 504]
        # Recherche fallback dans le message
        exc_str = str(exc)
        for code in ["429", "502", "503", "504"]:
            if code in exc_str:
                return True
    return False


def collecter_avec_retry(label: str, max_attempts: int) -> tuple[Path, int]:
    """Exécute la collecte avec une limite de retry et une attente prudente."""
    attempts = 0
    while True:
        attempts += 1
        try:
            raw_dir = collecter_offres(label)
            return raw_dir, attempts
        except Exception as e:
            if attempts >= max_attempts or not should_retry_exception(e):
                raise

            sleep_time = 5.0
            if isinstance(e, requests.RequestException) and e.response is not None:
                retry_after = e.response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    sleep_time = float(retry_after)

            print(
                f"Tentative {attempts} échouée pour '{label}' : {e}. Nouvelle tentative dans {sleep_time}s...")  # pylint: disable=line-too-long
            time.sleep(sleep_time)


def valider_batch_parent(parent_path: Path) -> dict:
    """Valide la structure et la complétude du batch parent avant sa reprise."""
    if not parent_path.exists():
        raise FileNotFoundError(f"Dossier parent introuvable : {parent_path}")

    manifest_path = parent_path / "batch_manifest.json"
    offers_path = parent_path / "offers_deduplicated.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"batch_manifest.json introuvable : {manifest_path}")
    if not offers_path.exists():
        raise FileNotFoundError(f"offers_deduplicated.json introuvable : {offers_path}")

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Fichier batch_manifest.json parent invalide : {e}")

    try:
        with offers_path.open("r", encoding="utf-8") as f:
            json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Fichier offers_deduplicated.json parent invalide : {e}")

    if not isinstance(manifest, dict):
        raise ValueError("Le manifeste parent doit être un dictionnaire.")

    if manifest.get("source") != "free_work":
        raise ValueError(f"Source invalide dans le manifeste parent : {manifest.get('source')}")

    if "queries" not in manifest or not isinstance(manifest["queries"], list):
        raise ValueError("Clé 'queries' absente ou invalide dans le manifeste parent.")

    seen_romes = set()
    for q in manifest["queries"]:
        rome = q.get("rome_code")
        if not rome:
            raise ValueError("Un élément de la liste 'queries' n'a pas de code ROME.")
        if rome in seen_romes:
            raise ValueError(f"Code ROME dupliqué dans le manifeste parent : {rome}")
        seen_romes.add(rome)

    succeeded_queries = [q for q in manifest["queries"] if q.get("status") == "success"]
    for sq in succeeded_queries:
        raw_dir_str = sq.get("raw_run_directory")
        if not raw_dir_str:
            raise ValueError(
                f"raw_run_directory manquant pour le succès ROME {
                    sq.get('rome_code')}")
        raw_dir = PROJECT_ROOT / raw_dir_str
        if not raw_dir.exists():
            raise FileNotFoundError(f"Dossier brut référencé introuvable : {raw_dir}")
        raw_offers_file = raw_dir / "offers_merged_raw.json"
        if not raw_offers_file.exists():
            raise FileNotFoundError(f"Fichier d'offres brutes introuvable : {raw_offers_file}")

    failed_queries = [q for q in manifest["queries"] if q.get("status") != "success"]
    if not failed_queries:
        raise ValueError("Le batch parent ne contient aucune requête en échec. Rien à reprendre.")

    if manifest.get("queries_attempted") != len(manifest["queries"]):
        raise ValueError("Incohérence du compteur queries_attempted dans le manifeste parent.")
    if manifest.get("queries_succeeded") != len(succeeded_queries):
        raise ValueError("Incohérence du compteur queries_succeeded dans le manifeste parent.")
    if manifest.get("queries_failed") != len(failed_queries):
        raise ValueError("Incohérence du compteur queries_failed dans le manifeste parent.")

    return manifest


def canonicalize(obj):
    """Normalise récursivement le payload pour ignorer les éléments du contexte de recherche."""
    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            if k == "elasticHighlights":
                continue
            if k == "@id" and isinstance(v, str) and v.startswith("/.well-known/genid/"):
                continue
            new_dict[k] = canonicalize(v)
        return new_dict
    elif isinstance(obj, list):
        return [canonicalize(x) for x in obj]
    else:
        return obj


def orchestrer_batch(
    rome_codes_filter: list[str] | None,
    delay_seconds: float,
    rome_csv_path: Path,
    resume_parent_path: Path | None = None,
    max_attempts: int = 2
) -> Path:
    """
    Orchestre la collecte par lot, fusion et déduplication des offres Free-Work.
    Supporte la reprise de batch en échec.
    """
    # 1. Chargement et validation de la sélection ROME de référence
    selection = charger_selection_rome(rome_csv_path)

    parent_manifest = None
    reused_queries_map = {}

    if resume_parent_path:
        parent_manifest = valider_batch_parent(resume_parent_path)
        for q in parent_manifest["queries"]:
            if q["status"] == "success":
                reused_queries_map[q["rome_code"]] = q

    # 2. Validation des codes filtrés
    if rome_codes_filter:
        invalid_codes = [c for c in rome_codes_filter if c not in selection]
        if invalid_codes:
            raise ValueError(
                f"Codes ROME demandés invalides ou absents de la sélection : {
                    ', '.join(invalid_codes)}")

    # Déterminer la liste des codes ROME à traiter
    if resume_parent_path:
        # Reprise : uniquement les codes ROME qui ont échoué dans le parent
        codes_to_run = [q["rome_code"]
                        for q in parent_manifest["queries"] if q["status"] != "success"]
    else:
        codes_to_run = rome_codes_filter if rome_codes_filter else list(selection.keys())

    queries_results = []
    queries_attempted = 0
    queries_succeeded = 0
    queries_failed = 0

    # 3. Collecte séquentielle pour les codes à exécuter
    for idx, code in enumerate(codes_to_run):
        label = selection[code]
        queries_attempted += 1
        print(f"[{queries_attempted}/{len(codes_to_run)}] Collecte du code ROME {code} - {label}...")  # pylint: disable=line-too-long

        try:
            raw_dir, attempts = collecter_avec_retry(label, max_attempts)
            offers_file = raw_dir / "offers_merged_raw.json"

            with offers_file.open("r", encoding="utf-8") as f:
                raw_offers = json.load(f)

            if not isinstance(raw_offers, list):
                raise ValueError("Le fichier des offres brutes n'est pas une liste.")

            offers_collected = len(raw_offers)
            queries_succeeded += 1

            try:
                raw_run_dir_str = str(raw_dir.relative_to(PROJECT_ROOT)).replace("\\", "/")
            except ValueError:
                raw_run_dir_str = str(raw_dir).replace("\\", "/")

            queries_results.append({
                "rome_code": code,
                "rome_label": label,
                "query": label,
                "status": "success",
                "raw_run_directory": raw_run_dir_str,
                "offers_collected": offers_collected,
                "error": None,
                "attempts": attempts
            })
        except Exception as e:
            queries_failed += 1
            print(f"Erreur lors de la collecte pour {code} ({label}) : {e}", file=sys.stderr)
            queries_results.append({
                "rome_code": code,
                "rome_label": label,
                "query": label,
                "status": "failed",
                "raw_run_directory": None,
                "offers_collected": 0,
                "error": str(e),
                "attempts": max_attempts
            })

        if idx < len(codes_to_run) - 1:
            time.sleep(delay_seconds)

    # Fusionner les requêtes réutilisées avec les nouvelles tentatives
    all_queries = []
    for code in selection.keys():
        if code in reused_queries_map:
            all_queries.append(reused_queries_map[code])
        else:
            # Recherche de la nouvelle tentative
            new_q = next((q for q in queries_results if q["rome_code"] == code), None)
            if new_q:
                all_queries.append(new_q)

    # 4. Fusion et déduplication globale
    global_offers = {}
    offers_before_global_deduplication = 0

    # Dictionnaire temporaire pour regrouper tous les doublons par source_id
    # afin d'analyser les conflits
    offers_by_id = {}

    for q_res in all_queries:
        if q_res["status"] != "success":
            continue

        raw_dir = PROJECT_ROOT / q_res["raw_run_directory"]
        offers_file = raw_dir / "offers_merged_raw.json"

        with offers_file.open("r", encoding="utf-8") as f:
            raw_offers = json.load(f)

        for offer in raw_offers:
            identifiant = offer.get("id") or offer.get("@id")
            if identifiant is None:
                raise ValueError("Structure JSON invalide : l'offre ne possède ni 'id' ni '@id'.")

            source_id = str(identifiant)
            offers_before_global_deduplication += 1

            rome_query_entry = {
                "rome_code": q_res["rome_code"],
                "rome_label": q_res["rome_label"],
                "query": q_res["query"]
            }

            if source_id not in offers_by_id:
                offers_by_id[source_id] = []
            offers_by_id[source_id].append({
                "rome_code": q_res["rome_code"],
                "query": q_res["query"],
                "offer": offer
            })

            if source_id not in global_offers:
                global_offers[source_id] = {
                    "source": "free_work",
                    "source_id": source_id,
                    "matched_rome_queries": [rome_query_entry],
                    "offer": offer
                }
            else:
                matched_queries = global_offers[source_id]["matched_rome_queries"]
                if rome_query_entry not in matched_queries:
                    matched_queries.append(rome_query_entry)

    # Diagnostic des conflits de payloads et calcul des compteurs
    duplicate_payloads_identical = 0
    duplicate_payloads_search_context_only = 0
    duplicate_payloads_business_fields_different = 0
    diagnostics = []

    for source_id, items in offers_by_id.items():
        if len(items) > 1:
            first_item = items[0]
            first_payload = first_item["offer"]

            # Pour cet ID, est-ce que toutes les comparaisons ne diffèrent que sur le contexte ?
            any_diff = False
            all_diffs_context_only = True
            all_differing_keys = set()

            for other_item in items[1:]:
                other_payload = other_item["offer"]
                if first_payload == other_payload:
                    duplicate_payloads_identical += 1
                else:
                    any_diff = True
                    # Recherche des clés de premier niveau différentes
                    keys = set(first_payload.keys()) | set(other_payload.keys())
                    item_diff_keys = {
                        k for k in keys if first_payload.get(k) != other_payload.get(k)}
                    all_differing_keys.update(item_diff_keys)

                    # Validation context vs business
                    c1 = canonicalize(first_payload)
                    c2 = canonicalize(other_payload)
                    if c1 == c2:
                        duplicate_payloads_search_context_only += 1
                    else:
                        all_diffs_context_only = False
                        duplicate_payloads_business_fields_different += 1

            if any_diff:
                diagnostics.append({
                    "source_id": source_id,
                    "differing_top_level_keys": sorted(list(all_differing_keys)),
                    "queries": [
                        {"rome_code": it["rome_code"], "query": it["query"]}
                        for it in items
                    ],
                    "only_search_context_fields_differ": all_diffs_context_only
                })

    # Tri déterministe du diagnostic
    diagnostics.sort(key=lambda x: x["source_id"])

    # 5. Fichiers de sortie globaux
    utc_now = datetime.now(timezone.utc)
    batch_id = utc_now.strftime("%Y%m%d_%H%M%S")
    processed_dir = PROCESSED_DATA_ROOT / "free_work" / "batches" / batch_id
    processed_dir.mkdir(parents=True, exist_ok=True)

    offers_deduplicated = list(global_offers.values())
    offers_after_global_deduplication = len(offers_deduplicated)
    duplicates_removed = offers_before_global_deduplication - offers_after_global_deduplication

    # Sauvegarde des offres dédupliquées
    offers_file_path = processed_dir / "offers_deduplicated.json"
    with offers_file_path.open("w", encoding="utf-8") as f:
        json.dump(offers_deduplicated, f, ensure_ascii=False, indent=2)

    # Sauvegarde du diagnostic de conflit
    diagnostics_file_path = processed_dir / "payload_conflict_diagnostics.json"
    with diagnostics_file_path.open("w", encoding="utf-8") as f:
        json.dump(diagnostics, f, ensure_ascii=False, indent=2)

    try:
        rome_source_rel = str(rome_csv_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        rome_source_rel = str(rome_csv_path).replace("\\", "/")

    # Compteurs globaux pour le manifeste de reprise
    queries_failed_total = sum(1 for q in all_queries if q["status"] != "success")
    batch_complete = (queries_failed_total == 0)

    manifest = {
        "source": "free_work",
        "batch_id": batch_id,
        "created_at_utc": utc_now.isoformat(),
        "rome_source_file": rome_source_rel,
        "rome_codes_available": len(selection),
        "rome_codes_requested": len(selection) if resume_parent_path else len(codes_to_run),
        "queries_attempted": len(all_queries),
        "queries_succeeded": len(all_queries) -
        queries_failed_total,
        "queries_failed": queries_failed_total,
        "offers_before_global_deduplication": offers_before_global_deduplication,
        "offers_after_global_deduplication": offers_after_global_deduplication,
        "duplicates_removed": duplicates_removed,
        "conflicting_duplicate_payloads": duplicate_payloads_search_context_only +
        duplicate_payloads_business_fields_different,
        "duplicate_payloads_identical": duplicate_payloads_identical,
        "duplicate_payloads_search_context_only": duplicate_payloads_search_context_only,
        "duplicate_payloads_business_fields_different": duplicate_payloads_business_fields_different,  # pylint: disable=line-too-long
        "offers_file": "offers_deduplicated.json",
        "queries": all_queries}

    if resume_parent_path:
        manifest.update({
            "batch_complete": batch_complete,
            "parent_batch_id": parent_manifest["batch_id"],
            "resume_mode": True,
            "queries_reused": len(reused_queries_map),
            "queries_retried": len(codes_to_run),
            "retried_rome_codes": sorted(codes_to_run),
            "remaining_failed_queries": queries_failed_total
        })

    manifest_file_path = processed_dir / "batch_manifest.json"
    with manifest_file_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Batch terminé. Manifeste sauvegardé dans : {manifest_file_path}")
    return processed_dir


def valider_delai(valeur_str: str) -> float:
    """."""
    try:
        valeur = float(valeur_str)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{valeur_str}' n'est pas un nombre valide.")
    if valeur < 0:
        raise argparse.ArgumentTypeError("erreur : --delay-seconds doit être supérieur ou égal à 0")
    return valeur


def valider_max_attempts(valeur_str: str) -> int:
    """."""
    try:
        valeur = int(valeur_str)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{valeur_str}' n'est pas un entier valide.")
    if valeur < 1:
        raise argparse.ArgumentTypeError("erreur : --max-attempts doit être supérieur ou égal à 1")
    return valeur


def lire_arguments() -> argparse.Namespace:
    """."""
    parser = argparse.ArgumentParser(
        description="Orchestre la collecte et la fusion globale Free-Work par code ROME."
    )
    parser.add_argument(
        "--rome-code",
        action="append",
        dest="rome_codes",
        help="Code ROME à collecter (répétable)."
    )
    parser.add_argument(
        "--delay-seconds",
        type=valider_delai,
        default=1.0,
        help="Délai en secondes entre deux recherches ROME."
    )
    parser.add_argument(
        "--resume-batch",
        help="Chemin vers le batch parent incomplet à reprendre."
    )
    parser.add_argument(
        "--max-attempts",
        type=valider_max_attempts,
        default=2,
        help="Nombre maximal de tentatives pour les requêtes en échec."
    )
    return parser.parse_args()


def main() -> None:
    """."""
    args = lire_arguments()
    rome_csv_path = PROCESSED_DATA_ROOT / "formations_enriched.csv"
    resume_path = Path(args.resume_batch) if args.resume_batch else None
    try:
        orchestrer_batch(
            rome_codes_filter=args.rome_codes,
            delay_seconds=args.delay_seconds,
            rome_csv_path=rome_csv_path,
            resume_parent_path=resume_path,
            max_attempts=args.max_attempts
        )
    except ValueError as e:
        print(f"Erreur de validation : {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Erreur de fichier : {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erreur inattendue : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
