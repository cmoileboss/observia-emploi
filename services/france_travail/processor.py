# -*- coding: utf-8 -*-

"""
Offline processor for France Travail raw archives.
Validates the manifest.json and raw pages, normalizes offers, de-duplicates
them by source_offer_id, and writes the output atomically as a processed JSON file.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from services.france_travail.exceptions import (
    FranceTravailNormalizationError,
    FranceTravailProcessingError,
)
from services.france_travail.normalizer import normalize_offer, normalized_offer_to_dict


@dataclass(frozen=True, slots=True)
class FranceTravailProcessingResult:
    """Dataclass holding results of the archive processing run."""
    source_run_id: str
    input_directory: Path
    output_file: Path
    raw_page_count: int
    raw_offer_count: int
    normalized_offer_count: int
    duplicate_offer_count: int
    normalization_error_count: int


def process_archive(
    archive_directory: str | Path,
    output_root_directory: str | Path,
) -> FranceTravailProcessingResult:
    """Validate, normalize, and deduplicate a France Travail raw archive.

    Parameters
    ----------
    archive_directory:
        The path to the raw archive directory (created by raw_storage).
    output_root_directory:
        The root directory where processed results are written.

    Returns
    -------
    FranceTravailProcessingResult
        Detailed statistics about the run.

    Raises
    ------
    FranceTravailProcessingError
        If validation fails, or if a normalization/storage error occurs.
    """
    input_path = Path(archive_directory).resolve()
    output_root = Path(output_root_directory).resolve()

    if not input_path.exists():
        raise FranceTravailProcessingError(f"Le répertoire d'archive n'existe pas : '{input_path}'")
    if not input_path.is_dir():
        raise FranceTravailProcessingError(f"Le chemin de l'archive n'est pas un répertoire : '{input_path}'")

    manifest_path = input_path / "manifest.json"
    if not manifest_path.is_file():
        raise FranceTravailProcessingError(f"Le fichier manifest.json est manquant : '{manifest_path}'")

    # Load and validate manifest
    try:
        manifest_content = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_content)
    except (json.JSONDecodeError, OSError) as exc:
        raise FranceTravailProcessingError("Le fichier manifest.json n'est pas un JSON valide.") from exc

    if not isinstance(manifest, dict):
        raise FranceTravailProcessingError("La racine du manifest.json doit être un dictionnaire.")

    # Validate mandatory manifest fields
    source = manifest.get("source")
    if source not in ("france_travail_offres_emploi", "france_travail_offres_emploi_rome"):
        raise FranceTravailProcessingError("La source déclarée dans le manifeste est invalide.")

    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise FranceTravailProcessingError("Le run_id dans le manifeste est absent ou vide.")

    pages_to_process: list[tuple[Path, dict[str, Any]]] = []
    expected_offer_count = 0

    if source == "france_travail_offres_emploi":
        # Validate numbers in manifest (strict check to prevent booleans)
        expected_page_count = manifest.get("page_count")
        expected_offer_count = manifest.get("offer_count")
        if isinstance(expected_page_count, bool) or not isinstance(expected_page_count, int) or expected_page_count < 0:
            raise FranceTravailProcessingError("Le page_count dans le manifeste doit être un entier positif.")
        if isinstance(expected_offer_count, bool) or not isinstance(expected_offer_count, int) or expected_offer_count < 0:
            raise FranceTravailProcessingError("Le offer_count dans le manifeste doit être un entier positif.")

        pages_list = manifest.get("pages")
        if not isinstance(pages_list, list):
            raise FranceTravailProcessingError("Le champ 'pages' dans le manifeste doit être une liste.")

        if len(pages_list) != expected_page_count:
            raise FranceTravailProcessingError(
                f"Le nombre de pages déclarées ({len(pages_list)}) ne correspond pas à page_count ({expected_page_count})."
            )

        # Process pages in deterministic order and prevent duplicate files or indices
        seen_indices: set[int] = set()
        seen_files: set[str] = set()
        sum_result_count = 0

        for page_entry in pages_list:
            if not isinstance(page_entry, dict):
                raise FranceTravailProcessingError("Chaque entrée de page dans le manifeste doit être un dictionnaire.")

            idx = page_entry.get("index")
            if isinstance(idx, bool) or not isinstance(idx, int) or idx <= 0:
                raise FranceTravailProcessingError("L'index d'une page doit être un entier strictement positif.")
            if idx in seen_indices:
                raise FranceTravailProcessingError(f"Index de page dupliqué : {idx}")
            seen_indices.add(idx)

            filename = page_entry.get("file")
            if not isinstance(filename, str) or not filename.strip():
                raise FranceTravailProcessingError("Le nom de fichier d'une page est manquant ou vide dans le manifeste.")
            if filename in seen_files:
                raise FranceTravailProcessingError(f"Fichier de page dupliqué : '{filename}'")
            seen_files.add(filename)

            res_cnt = page_entry.get("result_count")
            if isinstance(res_cnt, bool) or not isinstance(res_cnt, int) or res_cnt < 0:
                raise FranceTravailProcessingError("Le result_count doit être un entier positif.")
            sum_result_count += res_cnt

        if sum_result_count != expected_offer_count:
            raise FranceTravailProcessingError(
                f"La somme des result_count ({sum_result_count}) ne correspond pas à offer_count ({expected_offer_count})."
            )

        try:
            sorted_pages = sorted(pages_list, key=lambda x: x["index"])
        except Exception as exc:
            raise FranceTravailProcessingError("Impossible de trier les pages du manifeste par index.") from exc

        for page_entry in sorted_pages:
            filename = page_entry["file"]
            page_path = input_path / filename
            # Security check: prevent directory traversal
            try:
                resolved_page_path = page_path.resolve()
                resolved_input_path = input_path.resolve()
                if resolved_input_path not in resolved_page_path.parents:
                    raise FranceTravailProcessingError(f"Le fichier de page '{filename}' sort du répertoire d'archive.")
            except FranceTravailProcessingError:
                raise
            except Exception as exc:
                raise FranceTravailProcessingError(f"Erreur de validation de chemin pour '{filename}'.") from exc

            if not page_path.is_file():
                raise FranceTravailProcessingError(f"Fichier de page manquant : '{filename}'")

            # Explicitly check if the page file is manifest.json itself
            if page_path.name == "manifest.json":
                raise FranceTravailProcessingError("Une page ne peut pas être manifest.json.")

            try:
                page_data = json.loads(page_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise FranceTravailProcessingError(f"Le fichier de page '{filename}' n'est pas un JSON valide.") from exc

            if not isinstance(page_data, dict):
                raise FranceTravailProcessingError(f"La racine de la page '{filename}' doit être un dictionnaire.")

            results = page_data.get("resultats")
            if not isinstance(results, list):
                raise FranceTravailProcessingError(f"Le champ 'resultats' de la page '{filename}' doit être une liste.")

            pages_to_process.append((page_path, page_data))

    elif source == "france_travail_offres_emploi_rome":
        complete = manifest.get("complete")
        if not isinstance(complete, bool) or not complete:
            raise FranceTravailProcessingError("L'archive multi-ROME est incomplète ou en échec.")

        expected_page_count = manifest.get("total_page_count")
        expected_offer_count = manifest.get("total_offer_count")
        if isinstance(expected_page_count, bool) or not isinstance(expected_page_count, int) or expected_page_count < 0:
            raise FranceTravailProcessingError("Le total_page_count doit être un entier positif.")
        if isinstance(expected_offer_count, bool) or not isinstance(expected_offer_count, int) or expected_offer_count < 0:
            raise FranceTravailProcessingError("Le total_offer_count doit être un entier positif.")

        codes_list = manifest.get("codes")
        if not isinstance(codes_list, list):
            raise FranceTravailProcessingError("Le champ 'codes' doit être une liste.")

        # Discover pages for each code in order
        actual_total_pages = 0
        actual_total_offers_declared = 0

        seen_rome_codes = set()

        for code_entry in codes_list:
            if not isinstance(code_entry, dict):
                raise FranceTravailProcessingError("Chaque entrée de code doit être un dictionnaire.")

            rome_code = code_entry.get("rome_code")
            if not isinstance(rome_code, str) or not rome_code.strip():
                raise FranceTravailProcessingError("Le champ 'rome_code' est obligatoire.")

            if rome_code in seen_rome_codes:
                raise FranceTravailProcessingError(f"Code ROME dupliqué dans le manifeste : {rome_code}")
            seen_rome_codes.add(rome_code)

            # Validate rome_code format to prevent traversal
            import re
            if not re.match(r"^[A-Z]\d{4}$", rome_code):
                raise FranceTravailProcessingError(f"Format de code ROME invalide : {rome_code}")

            p_count = code_entry.get("page_count")
            o_count = code_entry.get("offer_count")
            if isinstance(p_count, bool) or not isinstance(p_count, int) or p_count < 0:
                raise FranceTravailProcessingError("Le page_count d'un code doit être un entier positif.")
            if isinstance(o_count, bool) or not isinstance(o_count, int) or o_count < 0:
                raise FranceTravailProcessingError("Le offer_count d'un code doit être un entier positif.")

            success = code_entry.get("success")
            if not isinstance(success, bool) or not success:
                raise FranceTravailProcessingError(f"Le code ROME {rome_code} n'a pas été collecté avec succès.")

            code_dir = input_path / "rome" / rome_code

            if not code_dir.exists() or not code_dir.is_dir():
                raise FranceTravailProcessingError(f"Le dossier pour le code ROME {rome_code} est introuvable.")

            # Security check: prevent traversal
            try:
                resolved_code_dir = code_dir.resolve()
                resolved_input_path = input_path.resolve()
                if resolved_input_path not in resolved_code_dir.parents:
                    raise FranceTravailProcessingError("Traversée de répertoire détectée via le code ROME.")
            except FranceTravailProcessingError:
                raise
            except Exception as exc:
                raise FranceTravailProcessingError("Erreur de validation de chemin pour le code ROME.") from exc

            # Find page files
            page_files = list(code_dir.glob("page_*.json"))
            page_files.sort(key=lambda x: x.name)

            if len(page_files) != p_count:
                raise FranceTravailProcessingError(
                    f"Le nombre de fichiers trouvés ({len(page_files)}) ne correspond pas à page_count ({p_count}) pour le code {rome_code}."
                )

            code_offers_sum = 0
            for file_path in page_files:
                try:
                    resolved_file_path = file_path.resolve()
                    resolved_input_path = input_path.resolve()
                    if resolved_input_path not in resolved_file_path.parents:
                        raise FranceTravailProcessingError(f"Le fichier de page '{file_path}' sort du répertoire d'archive.")
                except FranceTravailProcessingError:
                    raise
                except Exception as exc:
                    raise FranceTravailProcessingError(f"Erreur de validation de chemin pour '{file_path.name}'.") from exc

                if not file_path.is_file():
                    raise FranceTravailProcessingError(f"Chemin de page invalide (pas un fichier) : {file_path}")

                if file_path.name == "manifest.json":
                    raise FranceTravailProcessingError("Une page ne peut pas être manifest.json.")

                try:
                    page_data = json.loads(file_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    raise FranceTravailProcessingError(f"Le fichier de page '{file_path.name}' n'est pas un JSON valide.") from exc

                if not isinstance(page_data, dict):
                    raise FranceTravailProcessingError(f"La racine de la page '{file_path.name}' doit être un dictionnaire.")

                results = page_data.get("resultats")
                if not isinstance(results, list):
                    raise FranceTravailProcessingError(f"Le champ 'resultats' de la page '{file_path.name}' doit être une liste.")

                for i, raw_offer in enumerate(results):
                    if not isinstance(raw_offer, dict):
                        raise FranceTravailProcessingError(f"L'offre à l'index {i} de la page '{file_path.name}' n'est pas un dictionnaire.")

                code_offers_sum += len(results)
                pages_to_process.append((file_path, page_data))

            if code_offers_sum != o_count:
                raise FranceTravailProcessingError(
                    f"La somme des offres lues ({code_offers_sum}) ne correspond pas à offer_count ({o_count}) pour le code {rome_code}."
                )

            actual_total_pages += p_count
            actual_total_offers_declared += o_count

        if actual_total_pages != expected_page_count:
            raise FranceTravailProcessingError(
                f"Le total des pages lues ({actual_total_pages}) ne correspond pas à total_page_count ({expected_page_count})."
            )
        if actual_total_offers_declared != expected_offer_count:
            raise FranceTravailProcessingError(
                f"Le total des offres déclarées ({actual_total_offers_declared}) ne correspond pas à total_offer_count ({expected_offer_count})."
            )

    normalized_offers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_raw_offers = 0
    duplicate_count = 0

    for page_path, page_data in pages_to_process:
        results = page_data.get("resultats")

        # Process each offer
        for i, raw_offer in enumerate(results):
            if not isinstance(raw_offer, dict):
                raise FranceTravailProcessingError(f"L'offre à l'index {i} de la page '{page_path.name}' n'est pas un dictionnaire.")
            total_raw_offers += 1

            try:
                norm_offer = normalize_offer(raw_offer)
            except FranceTravailNormalizationError as exc:
                raise FranceTravailProcessingError(
                    f"Une erreur de normalisation s'est produite lors du traitement : {exc}"
                ) from exc

            offer_dict = normalized_offer_to_dict(norm_offer)
            offer_id = offer_dict["source_offer_id"]

            if offer_id in seen_ids:
                duplicate_count += 1
            else:
                seen_ids.add(offer_id)
                normalized_offers.append(offer_dict)

    if total_raw_offers != expected_offer_count:
        raise FranceTravailProcessingError(
            f"Le nombre total d'offres lues ({total_raw_offers}) ne correspond pas à offer_count ({expected_offer_count})."
        )

    # Prepare output directory
    output_dir = output_root / run_id
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FranceTravailProcessingError(f"Impossible de créer le répertoire de sortie : '{output_dir}'") from exc


    output_file = output_dir / "offers_normalized.json"

    # Build final JSON content
    processed_data = {
        "source": "france_travail",
        "source_run_id": run_id,
        "processed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "raw_page_count": len(pages_to_process),
        "raw_offer_count": total_raw_offers,
        "normalized_offer_count": len(normalized_offers),
        "duplicate_offer_count": duplicate_count,
        "normalization_error_count": 0,
        "offers": normalized_offers,
    }

    # Atomic write
    # Use NamedTemporaryFile in the destination directory to ensure os.replace is atomic (on the same volume)
    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(output_dir),
            delete=False,
            encoding="utf-8",
            suffix=".tmp"
        ) as tmp_file:
            json.dump(processed_data, tmp_file, ensure_ascii=False, indent=2)
            tmp_file.write("\n")  # single trailing newline
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        # Replace final file
        os.replace(tmp_file.name, str(output_file))
    except Exception as exc:
        # Cleanup temp file on failure
        if tmp_file and os.path.exists(tmp_file.name):
            try:
                os.remove(tmp_file.name)
            except OSError:
                pass
        raise FranceTravailProcessingError("Erreur d'écriture atomique du fichier traité.") from exc

    return FranceTravailProcessingResult(
        source_run_id=run_id,
        input_directory=input_path,
        output_file=output_file,
        raw_page_count=len(pages_to_process),
        raw_offer_count=total_raw_offers,
        normalized_offer_count=len(normalized_offers),
        duplicate_offer_count=duplicate_count,
        normalization_error_count=0,
    )
