# -*- coding: utf-8 -*-

"""
Mapper of persistence for France Travail job offers.
Converts normalized dictionary structures (from offers_normalized.json) into SQLAlchemy model instances.
Does not establish any session, connection, or perform any database operations.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from models.francetravail_model import CompetenceModel, FormationModel, FranceTravailModel
from services.france_travail.exceptions import FranceTravailMappingError


@dataclass(frozen=True, slots=True)
class FranceTravailPersistenceBundle:
    """Immutable bundle containing SQLAlchemy model instances ready for persistence.

    Contains the main offer model, a tuple of attached competencies, a tuple of
    attached formations, and details on skipped or duplicated items.
    """
    offer: FranceTravailModel
    competencies: tuple[CompetenceModel, ...]
    trainings: tuple[FormationModel, ...]
    skipped_competency_without_code_count: int
    skipped_training_without_code_count: int
    duplicate_competency_code_count: int
    duplicate_training_code_count: int


def _map_str(val: Any) -> str | None:
    """Helper to convert string values for database columns.

    Accepts string or None. Strips outer spaces. Converts empty or spaces-only
    strings to None, and other types to None.
    """
    if isinstance(val, str):
        stripped = val.strip()
        return stripped if stripped != "" else None
    return None


def map_normalized_offer(offer: Mapping[str, Any]) -> FranceTravailPersistenceBundle:
    """Map a normalized France Travail offer dict to SQLAlchemy models.

    Parameters
    ----------
    offer:
        A mapping representing a normalized offer (from offers_normalized.json).

    Returns
    -------
    FranceTravailPersistenceBundle
        The persistence bundle containing instantiated SQLAlchemy models.

    Raises
    ------
    FranceTravailMappingError
        If mapping constraints are violated.
    """
    if not isinstance(offer, Mapping):
        raise FranceTravailMappingError("L'offre d'entrée doit être un dictionnaire ou une structure équivalente.")

    if "source_offer_id" not in offer:
        raise FranceTravailMappingError("Le champ 'source_offer_id' est absent de l'offre.")

    source_offer_id = offer["source_offer_id"]
    if source_offer_id is None:
        raise FranceTravailMappingError("Le champ 'source_offer_id' ne peut pas être nul.")
    if not isinstance(source_offer_id, str):
        raise FranceTravailMappingError("Le champ 'source_offer_id' doit être une chaîne de caractères.")

    clean_id = source_offer_id.strip()
    if not clean_id:
        raise FranceTravailMappingError("Le champ 'source_offer_id' ne peut pas être vide après nettoyage.")

    # Instantiate the FranceTravailModel
    # Note: The existing schema does not have columns for:
    # - source, created_at, updated_at, workplace_label, workplace_city_code,
    # - contract_type, contract_label, contract_nature, experience_required,
    # - experience_label, work_duration_label, positions_count, alternance,
    # - sector_code, sector_label, salary_label, origin, origin_url.
    # These fields are kept in the normalized JSON but are not mapped here.
    offer_model = FranceTravailModel(
        id=clean_id,
        intitule=_map_str(offer.get("title")),
        description=_map_str(offer.get("description")),
        lieu_code_postal=_map_str(offer.get("workplace_postal_code")),
        rome_code=_map_str(offer.get("rome_code")),
        rome_libelle=_map_str(offer.get("rome_label")),
        appellation_libelle=_map_str(offer.get("occupation_label")),
        entreprise_nom=_map_str(offer.get("employer_name")),
    )

    # Process competencies
    skipped_competencies = 0
    duplicate_competencies = 0
    competence_models: list[CompetenceModel] = []
    seen_competence_codes: set[str] = set()

    raw_competencies = offer.get("competencies")
    if raw_competencies is not None:
        if not isinstance(raw_competencies, (list, tuple)):
            raise FranceTravailMappingError("Le champ 'competencies' doit être une liste ou un tuple.")

        for idx, comp in enumerate(raw_competencies):
            if not isinstance(comp, Mapping):
                raise FranceTravailMappingError("Chaque compétence doit être représentée par un dictionnaire.")

            raw_code = comp.get("code")
            if raw_code is None or not isinstance(raw_code, str):
                skipped_competencies += 1
                continue

            clean_code = raw_code.strip()
            if not clean_code:
                skipped_competencies += 1
                continue

            if clean_code in seen_competence_codes:
                duplicate_competencies += 1
                continue

            seen_competence_codes.add(clean_code)
            competence_models.append(
                CompetenceModel(
                    code=clean_code,
                    libelle=_map_str(comp.get("label")),
                    exigence=_map_str(comp.get("requirement")),
                )
            )

    # Process trainings
    skipped_trainings = 0
    duplicate_trainings = 0
    training_models: list[FormationModel] = []
    seen_training_codes: set[str] = set()

    raw_trainings = offer.get("trainings")
    if raw_trainings is not None:
        if not isinstance(raw_trainings, (list, tuple)):
            raise FranceTravailMappingError("Le champ 'trainings' doit être une liste ou un tuple.")

        for idx, train in enumerate(raw_trainings):
            if not isinstance(train, Mapping):
                raise FranceTravailMappingError("Chaque formation doit être représentée par un dictionnaire.")

            raw_code = train.get("code")
            if raw_code is None or not isinstance(raw_code, str):
                skipped_trainings += 1
                continue

            clean_code = raw_code.strip()
            if not clean_code:
                skipped_trainings += 1
                continue

            if clean_code in seen_training_codes:
                duplicate_trainings += 1
                continue

            seen_training_codes.add(clean_code)
            training_models.append(
                FormationModel(
                    code_formation=clean_code,
                    domaine_libelle=_map_str(train.get("domain_label")),
                    niveau_libelle=_map_str(train.get("level_label")),
                    exigence=_map_str(train.get("requirement")),
                    commentaire=None,
                )
            )

    return FranceTravailPersistenceBundle(
        offer=offer_model,
        competencies=tuple(competence_models),
        trainings=tuple(training_models),
        skipped_competency_without_code_count=skipped_competencies,
        skipped_training_without_code_count=skipped_trainings,
        duplicate_competency_code_count=duplicate_competencies,
        duplicate_training_code_count=duplicate_trainings,
    )
