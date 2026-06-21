# -*- coding: utf-8 -*-

"""
Transactional importer for France Travail normalized job offers.
Prepares and validates the normalized offers file before database insertion,
and handles database persistence atomically.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy.orm import Session

from repositories.francetravail_repository import FranceTravailRepository
from services.france_travail.exceptions import FranceTravailImportError, FranceTravailMappingError
from services.france_travail.mapper import map_normalized_offer, FranceTravailPersistenceBundle


@dataclass(frozen=True, slots=True)
class FranceTravailPreparedImport:
    """Immutable structure containing mapped offers and aggregate validation statistics."""
    source_run_id: str
    input_file: Path
    bundles: tuple[FranceTravailPersistenceBundle, ...]
    input_offer_count: int
    mapped_offer_count: int
    mapped_competency_count: int
    mapped_training_count: int
    skipped_competency_without_code_count: int
    skipped_training_without_code_count: int
    duplicate_competency_code_count: int
    duplicate_training_code_count: int


@dataclass(frozen=True, slots=True)
class FranceTravailImportResult:
    """Immutable result structure containing details about the database insertion."""
    source_run_id: str
    input_file: Path
    input_offer_count: int
    inserted_offer_count: int
    existing_offer_count: int
    attached_competency_count: int
    attached_training_count: int
    skipped_competency_without_code_count: int
    skipped_training_without_code_count: int
    duplicate_competency_code_count: int
    duplicate_training_code_count: int
    committed: bool
    dry_run: bool


def _validate_non_negative_int(val: Any, name: str) -> int:
    """Validate that a value is an integer, non-negative, and not a boolean."""
    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
        raise FranceTravailImportError(f"Le compteur '{name}' doit être un entier non négatif.")
    return val


def prepare_import(input_file: Path) -> FranceTravailPreparedImport:
    """Validate, parse, and map a normalized job offers JSON file.

    Performs full structure and business validation without database access.
    """
    file_path = Path(input_file)
    if not file_path.exists():
        raise FranceTravailImportError("Le fichier spécifié est introuvable.")
    if not file_path.is_file():
        raise FranceTravailImportError("Le chemin spécifié n'est pas un fichier régulier.")

    try:
        content = file_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise FranceTravailImportError("Le fichier n'est pas un JSON valide.") from exc
    except OSError as exc:
        raise FranceTravailImportError("Impossible de lire le fichier.") from exc

    if not isinstance(data, dict):
        raise FranceTravailImportError("La racine du document doit être un dictionnaire.")

    # Validate source
    source = data.get("source")
    if source != "france_travail":
        raise FranceTravailImportError("La source déclarée dans le fichier est invalide.")

    # Validate source_run_id
    run_id = data.get("source_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise FranceTravailImportError("Le run_id est absent ou invalide.")

    # Validate counters
    raw_offer_count = _validate_non_negative_int(data.get("raw_offer_count"), "raw_offer_count")
    normalized_offer_count = _validate_non_negative_int(data.get("normalized_offer_count"), "normalized_offer_count")
    duplicate_offer_count = _validate_non_negative_int(data.get("duplicate_offer_count"), "duplicate_offer_count")
    normalization_error_count = _validate_non_negative_int(data.get("normalization_error_count"), "normalization_error_count")

    # Validate consistency
    offers = data.get("offers")
    if not isinstance(offers, list):
        raise FranceTravailImportError("Le champ 'offers' doit être une liste.")

    if len(offers) != normalized_offer_count:
        raise FranceTravailImportError("Le nombre d'offres ne correspond pas à normalized_offer_count.")

    if normalized_offer_count + duplicate_offer_count != raw_offer_count:
        raise FranceTravailImportError("Incohérence entre raw_offer_count, normalized_offer_count et duplicate_offer_count.")

    if normalization_error_count != 0:
        raise FranceTravailImportError("Erreurs de normalisation détectées dans le fichier (doit être 0).")

    # Map offers
    bundles: list[FranceTravailPersistenceBundle] = []
    seen_offer_ids: set[str] = set()

    mapped_offer_count = 0
    mapped_competency_count = 0
    mapped_training_count = 0
    skipped_competency_without_code_count = 0
    skipped_training_without_code_count = 0
    duplicate_competency_code_count = 0
    duplicate_training_code_count = 0

    for idx, raw_offer in enumerate(offers):
        if not isinstance(raw_offer, Mapping):
            raise FranceTravailImportError(f"L'offre à l'index {idx} n'est pas un dictionnaire.")

        try:
            bundle = map_normalized_offer(raw_offer)
        except FranceTravailMappingError as exc:
            raise FranceTravailImportError("Une erreur de mapping est survenue lors de la préparation.") from exc

        # Check unique source_offer_id in file
        offer_id = bundle.offer.id
        if offer_id in seen_offer_ids:
            raise FranceTravailImportError("Identifiant d'offre dupliqué au sein du fichier normalisé.")
        seen_offer_ids.add(offer_id)

        bundles.append(bundle)

        mapped_offer_count += 1
        mapped_competency_count += len(bundle.competencies)
        mapped_training_count += len(bundle.trainings)
        skipped_competency_without_code_count += bundle.skipped_competency_without_code_count
        skipped_training_without_code_count += bundle.skipped_training_without_code_count
        duplicate_competency_code_count += bundle.duplicate_competency_code_count
        duplicate_training_code_count += bundle.duplicate_training_code_count

    return FranceTravailPreparedImport(
        source_run_id=run_id,
        input_file=file_path,
        bundles=tuple(bundles),
        input_offer_count=raw_offer_count,
        mapped_offer_count=mapped_offer_count,
        mapped_competency_count=mapped_competency_count,
        mapped_training_count=mapped_training_count,
        skipped_competency_without_code_count=skipped_competency_without_code_count,
        skipped_training_without_code_count=skipped_training_without_code_count,
        duplicate_competency_code_count=duplicate_competency_code_count,
        duplicate_training_code_count=duplicate_training_code_count,
    )


def persist_prepared_import(prepared: FranceTravailPreparedImport, db: Session) -> FranceTravailImportResult:
    """Persist the prepared import bundles inside a single transaction.

    Applies idempotent logic: existing offers are ignored.
    """
    repo = FranceTravailRepository(db)

    inserted_offer_count = 0
    existing_offer_count = 0
    attached_competency_count = 0
    attached_training_count = 0

    try:
        for bundle in prepared.bundles:
            # Check idempotency
            existing = repo.get_offre_by_id(bundle.offer.id)
            if existing is not None:
                existing_offer_count += 1
                continue

            # Create offer without commit
            repo.create_offre(bundle.offer, commit=False)
            inserted_offer_count += 1

            # Attach competencies
            for comp in bundle.competencies:
                repo.attach_or_create_competence(bundle.offer, comp, commit=False)
                attached_competency_count += 1

            # Attach trainings
            for train in bundle.trainings:
                repo.attach_or_create_formation(bundle.offer, train, commit=False)
                attached_training_count += 1

        db.commit()

    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        raise FranceTravailImportError("Erreur lors de la persistance en base de données.") from exc

    return FranceTravailImportResult(
        source_run_id=prepared.source_run_id,
        input_file=prepared.input_file,
        input_offer_count=prepared.input_offer_count,
        inserted_offer_count=inserted_offer_count,
        existing_offer_count=existing_offer_count,
        attached_competency_count=attached_competency_count,
        attached_training_count=attached_training_count,
        skipped_competency_without_code_count=prepared.skipped_competency_without_code_count,
        skipped_training_without_code_count=prepared.skipped_training_without_code_count,
        duplicate_competency_code_count=prepared.duplicate_competency_code_count,
        duplicate_training_code_count=prepared.duplicate_training_code_count,
        committed=True,
        dry_run=False,
    )
