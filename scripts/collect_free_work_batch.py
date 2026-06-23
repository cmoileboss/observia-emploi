import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Insertion du dossier parent pour que les imports depuis scripts.* fonctionnent
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_free_work import collecter_offres


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
            f"Le pipeline de données doit être exécuté avant le batch. Vous pouvez le lancer via :\n"
            f"python main.py --build-data"
        )

    selection = {}
    seen_codes = set()

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
                raise ValueError(f"Fichier ROME invalide à la ligne {line_num} : le code ROME est vide.")

            if label is None or not label.strip():
                raise ValueError(
                    f"Fichier ROME invalide pour le code {code} à la ligne {line_num} : l'intitulé est vide."
                )

            label = label.strip()

            if code in selection:
                if selection[code] != label:
                    raise ValueError(
                        f"Fichier ROME invalide : le code ROME '{code}' est associé à des intitulés différents "
                        f"('{selection[code]}' et '{label}')."
                    )
                continue

            selection[code] = label

    return selection


def orchestrer_batch(
    rome_codes_filter: list[str] | None,
    delay_seconds: float,
    rome_csv_path: Path
) -> Path:
    """
    Orchestre la collecte par lot, fusion et déduplication des offres Free-Work.
    """
    # 1. Chargement et validation de la sélection
    selection = charger_selection_rome(rome_csv_path)

    # 2. Validation des codes filtrés
    if rome_codes_filter:
        invalid_codes = [c for c in rome_codes_filter if c not in selection]
        if invalid_codes:
            raise ValueError(
                f"Codes ROME demandés invalides ou absents de la sélection : {', '.join(invalid_codes)}"
            )

    codes_to_run = rome_codes_filter if rome_codes_filter else list(selection.keys())

    queries_results = []
    queries_attempted = 0
    queries_succeeded = 0
    queries_failed = 0

    # 3. Collecte séquentielle
    for idx, code in enumerate(codes_to_run):
        label = selection[code]
        queries_attempted += 1
        print(f"[{queries_attempted}/{len(codes_to_run)}] Collecte du code ROME {code} - {label}...")

        try:
            # Appel direct
            raw_dir = collecter_offres(label)
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
                "error": None
            })
        except (ValueError, PermissionError, requests.RequestException, OSError, RuntimeError) as e:
            queries_failed += 1
            print(f"Erreur lors de la collecte pour {code} ({label}) : {e}", file=sys.stderr)
            queries_results.append({
                "rome_code": code,
                "rome_label": label,
                "query": label,
                "status": "failed",
                "raw_run_directory": None,
                "offers_collected": 0,
                "error": str(e)
            })

        if idx < len(codes_to_run) - 1:
            time.sleep(delay_seconds)

    # 4. Fusion et déduplication globale
    global_offers = {}
    offers_before_global_deduplication = 0
    conflicting_duplicate_payloads = 0

    for q_res in queries_results:
        if q_res["status"] != "success":
            continue

        raw_dir = PROJECT_ROOT / q_res["raw_run_directory"]
        offers_file = raw_dir / "offers_merged_raw.json"

        with offers_file.open("r", encoding="utf-8") as f:
            raw_offers = json.load(f)

        if not isinstance(raw_offers, list):
            raise ValueError(f"Structure de données invalide dans {offers_file} : doit être une liste.")

        for offer in raw_offers:
            if not isinstance(offer, dict):
                raise ValueError("Chaque offre doit être un dictionnaire.")

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

            if source_id not in global_offers:
                global_offers[source_id] = {
                    "source": "free_work",
                    "source_id": source_id,
                    "matched_rome_queries": [rome_query_entry],
                    "offer": offer
                }
            else:
                existing_offer = global_offers[source_id]["offer"]
                if existing_offer != offer:
                    conflicting_duplicate_payloads += 1

                matched_queries = global_offers[source_id]["matched_rome_queries"]
                if rome_query_entry not in matched_queries:
                    matched_queries.append(rome_query_entry)

    # 5. Fichiers de sortie globaux
    utc_now = datetime.now(timezone.utc)
    batch_id = utc_now.strftime("%Y%m%d_%H%M%S")
    processed_dir = PROJECT_ROOT / "data" / "processed" / "free_work" / "batches" / batch_id
    processed_dir.mkdir(parents=True, exist_ok=True)

    offers_deduplicated = list(global_offers.values())
    offers_after_global_deduplication = len(offers_deduplicated)
    duplicates_removed = offers_before_global_deduplication - offers_after_global_deduplication

    offers_file_path = processed_dir / "offers_deduplicated.json"
    with offers_file_path.open("w", encoding="utf-8") as f:
        json.dump(offers_deduplicated, f, ensure_ascii=False, indent=2)

    try:
        rome_source_rel = str(rome_csv_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        rome_source_rel = str(rome_csv_path).replace("\\", "/")

    manifest = {
        "source": "free_work",
        "batch_id": batch_id,
        "created_at_utc": utc_now.isoformat(),
        "rome_source_file": rome_source_rel,
        "rome_codes_available": len(selection),
        "rome_codes_requested": len(codes_to_run),
        "queries_attempted": queries_attempted,
        "queries_succeeded": queries_succeeded,
        "queries_failed": queries_failed,
        "offers_before_global_deduplication": offers_before_global_deduplication,
        "offers_after_global_deduplication": offers_after_global_deduplication,
        "duplicates_removed": duplicates_removed,
        "conflicting_duplicate_payloads": conflicting_duplicate_payloads,
        "offers_file": "offers_deduplicated.json",
        "queries": queries_results
    }

    manifest_file_path = processed_dir / "batch_manifest.json"
    with manifest_file_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Batch terminé. Manifeste sauvegardé dans : {manifest_file_path}")
    return processed_dir


def valider_delai(valeur_str: str) -> float:
    try:
        valeur = float(valeur_str)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{valeur_str}' n'est pas un nombre valide.")
    if valeur < 0:
        raise argparse.ArgumentTypeError("erreur : --delay-seconds doit être supérieur ou égal à 0")
    return valeur


def lire_arguments() -> argparse.Namespace:
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
    return parser.parse_args()


def main() -> None:
    args = lire_arguments()
    rome_csv_path = PROJECT_ROOT / "data" / "processed" / "formations_enriched.csv"
    try:
        orchestrer_batch(
            rome_codes_filter=args.rome_codes,
            delay_seconds=args.delay_seconds,
            rome_csv_path=rome_csv_path
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
