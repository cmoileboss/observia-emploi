# -*- coding: utf-8 -*-

"""
Normalizer for France Travail job offers.
Converts raw JSON payload dicts into immutable type-safe dataclasses.
No dependencies on SQLAlchemy, Pydantic, FastAPI, PostgreSQL, or network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from services.france_travail.exceptions import FranceTravailNormalizationError


@dataclass(frozen=True, slots=True)
class NormalizedFranceTravailCompetence:
    """Immutable normalized competence structure."""
    code: str | None
    label: str | None
    requirement: str | None


@dataclass(frozen=True, slots=True)
class NormalizedFranceTravailTraining:
    """Immutable normalized training structure."""
    code: str | None
    domain_label: str | None
    level_label: str | None
    requirement: str | None


@dataclass(frozen=True, slots=True)
class NormalizedFranceTravailOffer:
    """Immutable normalized job offer structure."""
    source: str
    source_offer_id: str
    title: str | None
    description: str | None
    created_at: str | None
    updated_at: str | None
    rome_code: str | None
    rome_label: str | None
    occupation_label: str | None
    workplace_label: str | None
    workplace_postal_code: str | None
    workplace_city_code: str | None
    employer_name: str | None
    contract_type: str | None
    contract_label: str | None
    contract_nature: str | None
    experience_required: str | None
    experience_label: str | None
    work_duration_label: str | None
    positions_count: int | None
    alternance: bool | None
    sector_code: str | None
    sector_label: str | None
    salary_label: str | None
    origin: str | None
    origin_url: str | None
    competencies: tuple[NormalizedFranceTravailCompetence, ...]
    trainings: tuple[NormalizedFranceTravailTraining, ...]


def _norm_str(val: Any) -> str | None:
    """Normalize string fields: strip whitespace, convert empty or spaces-only to None."""
    if val is None:
        return None
    if not isinstance(val, str):
        return None
    stripped = val.strip()
    if not stripped:
        return None
    return stripped


def _norm_int(val: Any) -> int | None:
    """Normalize integer fields: accept only ints (not bools), must be non-negative."""
    if val is None:
        return None
    if isinstance(val, bool):  # Python booleans are subclasses of int
        return None
    if not isinstance(val, int):
        return None
    if val < 0:
        return None
    return val


def _norm_bool(val: Any) -> bool | None:
    """Normalize boolean fields: accept only bools."""
    if isinstance(val, bool):
        return val
    return None


def normalize_offer(raw_offer: Mapping[str, Any]) -> NormalizedFranceTravailOffer:
    """Normalize a raw France Travail job offer dict into NormalizedFranceTravailOffer.

    Parameters
    ----------
    raw_offer:
        The raw offer dictionary from the API.

    Returns
    -------
    NormalizedFranceTravailOffer
        The immutable normalized offer.

    Raises
    ------
    FranceTravailNormalizationError
        If 'id' is missing, empty, or not a string.
    """
    if "id" not in raw_offer:
        raise FranceTravailNormalizationError("L'identifiant de l'offre 'id' est absent.")

    raw_id = raw_offer["id"]
    if raw_id is None:
        raise FranceTravailNormalizationError("L'identifiant de l'offre 'id' est nul.")
    if not isinstance(raw_id, str):
        raise FranceTravailNormalizationError("L'identifiant de l'offre 'id' doit être une chaîne.")

    clean_id = raw_id.strip()
    if not clean_id:
        raise FranceTravailNormalizationError("L'identifiant de l'offre 'id' est vide ou composé uniquement d'espaces.")

    # workplace, employer, salary, origin structures
    workplace = raw_offer.get("lieuTravail")
    if not isinstance(workplace, dict):
        workplace = None

    employer = raw_offer.get("entreprise")
    if not isinstance(employer, dict):
        employer = None

    salary = raw_offer.get("salaire")
    if not isinstance(salary, dict):
        salary = None

    origin = raw_offer.get("origineOffre")
    if not isinstance(origin, dict):
        origin = None

    # Normalizing description safely
    raw_description = raw_offer.get("description")
    description_val = raw_description if isinstance(raw_description, str) else None

    # Normalizing dates safely (keep as str if not None)
    created_at_val = _norm_str(raw_offer.get("dateCreation"))
    updated_at_val = _norm_str(raw_offer.get("dateActualisation"))

    # Competencies normalization
    competencies_list: list[NormalizedFranceTravailCompetence] = []
    raw_competencies = raw_offer.get("competences")
    if isinstance(raw_competencies, list):
        seen_comp: set[tuple[str | None, str | None, str | None]] = set()
        for item in raw_competencies:
            if isinstance(item, dict):
                code_val = _norm_str(item.get("code"))
                label_val = _norm_str(item.get("libelle"))
                req_val = _norm_str(item.get("exigence"))

                # Skip completely empty competency
                if code_val is None and label_val is None and req_val is None:
                    continue

                triplet = (code_val, label_val, req_val)
                if triplet not in seen_comp:
                    seen_comp.add(triplet)
                    competencies_list.append(
                        NormalizedFranceTravailCompetence(
                            code=code_val,
                            label=label_val,
                            requirement=req_val,
                        )
                    )

    # Trainings normalization
    trainings_list: list[NormalizedFranceTravailTraining] = []
    raw_trainings = raw_offer.get("formations")
    if isinstance(raw_trainings, list):
        seen_train: set[tuple[str | None, str | None, str | None, str | None]] = set()
        for item in raw_trainings:
            if isinstance(item, dict):
                code_val = _norm_str(item.get("codeFormation"))
                domain_val = _norm_str(item.get("domaineLibelle"))
                level_val = _norm_str(item.get("niveauLibelle"))
                req_val = _norm_str(item.get("exigence"))

                # Skip completely empty training
                if code_val is None and domain_val is None and level_val is None and req_val is None:
                    continue

                quadruplet = (code_val, domain_val, level_val, req_val)
                if quadruplet not in seen_train:
                    seen_train.add(quadruplet)
                    trainings_list.append(
                        NormalizedFranceTravailTraining(
                            code=code_val,
                            domain_label=domain_val,
                            level_label=level_val,
                            requirement=req_val,
                        )
                    )

    # Construct the NormalizedFranceTravailOffer dataclass
    return NormalizedFranceTravailOffer(
        source="france_travail",
        source_offer_id=clean_id,
        title=_norm_str(raw_offer.get("intitule")),
        description=description_val,
        created_at=created_at_val,
        updated_at=updated_at_val,
        rome_code=_norm_str(raw_offer.get("romeCode")),
        rome_label=_norm_str(raw_offer.get("romeLibelle")),
        occupation_label=_norm_str(raw_offer.get("appellationlibelle")),
        workplace_label=_norm_str(workplace.get("libelle")) if workplace else None,
        workplace_postal_code=_norm_str(workplace.get("codePostal")) if workplace else None,
        workplace_city_code=_norm_str(workplace.get("commune")) if workplace else None,
        employer_name=_norm_str(employer.get("nom")) if employer else None,
        contract_type=_norm_str(raw_offer.get("typeContrat")),
        contract_label=_norm_str(raw_offer.get("typeContratLibelle")),
        contract_nature=_norm_str(raw_offer.get("natureContrat")),
        experience_required=_norm_str(raw_offer.get("experienceExige")),
        experience_label=_norm_str(raw_offer.get("experienceLibelle")),
        work_duration_label=_norm_str(raw_offer.get("dureeTravailLibelle")),
        positions_count=_norm_int(raw_offer.get("nombrePostes")),
        alternance=_norm_bool(raw_offer.get("alternance")),
        sector_code=_norm_str(raw_offer.get("secteurActivite")),
        sector_label=_norm_str(raw_offer.get("secteurActiviteLibelle")),
        salary_label=_norm_str(salary.get("libelle")) if salary else None,
        origin=_norm_str(origin.get("origine")) if origin else None,
        origin_url=_norm_str(origin.get("urlOrigine")) if origin else None,
        competencies=tuple(competencies_list),
        trainings=tuple(trainings_list),
    )


def normalized_offer_to_dict(offer: NormalizedFranceTravailOffer) -> dict[str, Any]:
    """Convert NormalizedFranceTravailOffer to a dictionary composed of JSON serializable values.

    Parameters
    ----------
    offer:
        The normalized offer instance.

    Returns
    -------
    dict[str, Any]
        The plain dictionary representation.
    """
    offer_dict = asdict(offer)
    # Convert competencies and trainings tuples/lists to lists of dicts
    offer_dict["competencies"] = [dict(c) for c in offer_dict.get("competencies", [])]
    offer_dict["trainings"] = [dict(t) for t in offer_dict.get("trainings", [])]
    return offer_dict
