"""Représentation des exigences de formation extraites des offres France Travail."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Iterable


@dataclass(frozen=True)
class FranceTravailTrainingRequirementSourceRow:
    """Contient les données nécessaires pour identifier et valider une exigence."""

    formation_id: int | None
    intitule: str | None
    code_source: str | None
    niveau: str | None
    commentaire: str | None
    offre_ids: tuple[int | None, ...]
    siret_of_contractant: str | None
    has_monthly_flow: bool
    codes_rome: tuple[str | None, ...]


@dataclass(frozen=True)
class FranceTravailTrainingRequirement:
    """Représente une exigence de formation, distincte d'une certification RNCP."""

    formation_id: int
    intitule: str
    code_source: str | None
    niveau: str | None
    commentaire: str | None
    offre_ids: tuple[int, ...]


@dataclass(frozen=True)
class FranceTravailTrainingRequirementsDiagnostic:
    """Regroupe les indicateurs non sensibles des exigences France Travail."""

    nombre_lignes_exigence: int
    nombre_associations_offre_exigence: int
    nombre_offres_distinctes: int
    nombre_exigences_avec_code_source: int
    nombre_exigences_avec_niveau: int
    nombre_exigences_avec_commentaire: int
    exigences_par_offre_min: int
    exigences_par_offre_moyen: float
    exigences_par_offre_max: int
    offres_par_exigence_min: int
    offres_par_exigence_moyen: float
    offres_par_exigence_max: int


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned_value = value.strip()
    return cleaned_value or None


def _has_rome_code(values: tuple[str | None, ...]) -> bool:
    return any(_clean_optional_text(value) is not None for value in values)


def _is_requirement_candidate(row: FranceTravailTrainingRequirementSourceRow) -> bool:
    return (
        _clean_optional_text(row.siret_of_contractant) is None
        and not row.has_monthly_flow
        and not _has_rome_code(row.codes_rome)
    )


def _validate_positive_identifier(value: int | None, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"Identifiant '{field_name}' invalide : {value!r}.")
    return value


def build_france_travail_training_requirement(
    row: FranceTravailTrainingRequirementSourceRow,
) -> FranceTravailTrainingRequirement:
    """Valide et transforme une ligne déjà identifiée comme exigence."""
    formation_id = _validate_positive_identifier(row.formation_id, "formation_id")
    if _clean_optional_text(row.siret_of_contractant) is not None:
        raise ValueError(
            f"L'exigence de formation {formation_id} possède un SIRET renseigné."
        )
    if row.has_monthly_flow:
        raise ValueError(
            f"L'exigence de formation {formation_id} possède un flux mensuel."
        )
    if _has_rome_code(row.codes_rome):
        raise ValueError(
            f"L'exigence de formation {formation_id} possède un code ROME."
        )

    title = _clean_optional_text(row.intitule)
    if title is None:
        raise ValueError(
            f"Champ obligatoire 'intitule' vide pour la formation {formation_id}."
        )
    if not row.offre_ids:
        raise ValueError(
            f"L'exigence de formation {formation_id} n'est liée à aucune offre."
        )
    offer_ids = tuple(
        sorted(
            {
                _validate_positive_identifier(offer_id, "offre_id")
                for offer_id in row.offre_ids
            }
        )
    )

    return FranceTravailTrainingRequirement(
        formation_id=formation_id,
        intitule=title,
        code_source=_clean_optional_text(row.code_source),
        niveau=_clean_optional_text(row.niveau),
        commentaire=_clean_optional_text(row.commentaire),
        offre_ids=offer_ids,
    )


def build_france_travail_training_requirements(
    rows: Iterable[FranceTravailTrainingRequirementSourceRow],
) -> tuple[FranceTravailTrainingRequirement, ...]:
    """Sélectionne et construit les exigences France Travail d'une population mixte."""
    requirements = [
        build_france_travail_training_requirement(row)
        for row in rows
        if _is_requirement_candidate(row)
    ]
    if not requirements:
        raise ValueError("Aucun catalogue d'exigences France Travail trouvé.")

    formation_ids = [requirement.formation_id for requirement in requirements]
    if len(formation_ids) != len(set(formation_ids)):
        raise ValueError("Un formation_id est présent plusieurs fois dans les exigences.")
    return tuple(sorted(requirements, key=lambda requirement: requirement.formation_id))


def index_training_requirements_by_offer(
    requirements: Iterable[FranceTravailTrainingRequirement],
) -> dict[int, tuple[FranceTravailTrainingRequirement, ...]]:
    """Construit un index déterministe offre_id vers exigences de formation."""
    indexed_requirements: dict[int, list[FranceTravailTrainingRequirement]] = {}
    for requirement in sorted(
        requirements,
        key=lambda item: item.formation_id,
    ):
        for offer_id in requirement.offre_ids:
            indexed_requirements.setdefault(offer_id, []).append(requirement)
    return {
        offer_id: tuple(indexed_requirements[offer_id])
        for offer_id in sorted(indexed_requirements)
    }


def calculate_training_requirements_diagnostic(
    requirements: tuple[FranceTravailTrainingRequirement, ...],
) -> FranceTravailTrainingRequirementsDiagnostic:
    """Calcule les indicateurs synthétiques d'un catalogue d'exigences non vide."""
    if not requirements:
        raise ValueError("Le diagnostic requiert au moins une exigence France Travail.")

    requirements_by_offer = index_training_requirements_by_offer(requirements)
    requirements_per_offer = [
        len(offer_requirements)
        for offer_requirements in requirements_by_offer.values()
    ]
    offers_per_requirement = [len(requirement.offre_ids) for requirement in requirements]
    return FranceTravailTrainingRequirementsDiagnostic(
        nombre_lignes_exigence=len(requirements),
        nombre_associations_offre_exigence=sum(offers_per_requirement),
        nombre_offres_distinctes=len(requirements_by_offer),
        nombre_exigences_avec_code_source=sum(
            requirement.code_source is not None for requirement in requirements
        ),
        nombre_exigences_avec_niveau=sum(
            requirement.niveau is not None for requirement in requirements
        ),
        nombre_exigences_avec_commentaire=sum(
            requirement.commentaire is not None for requirement in requirements
        ),
        exigences_par_offre_min=min(requirements_per_offer),
        exigences_par_offre_moyen=fmean(requirements_per_offer),
        exigences_par_offre_max=max(requirements_per_offer),
        offres_par_exigence_min=min(offers_per_requirement),
        offres_par_exigence_moyen=fmean(offers_per_requirement),
        offres_par_exigence_max=max(offers_per_requirement),
    )
