"""Diagnostique les exigences de formation France Travail en lecture seule."""

from __future__ import annotations

import sys

from sqlalchemy import text

from postgres_connection import SESSION_LOCAL
from repositories.correspondance_formation_repository import FormationRepository
from services.france_travail_training_requirements import (
    FranceTravailTrainingRequirement,
    FranceTravailTrainingRequirementSourceRow,
    build_france_travail_training_requirements,
    calculate_training_requirements_diagnostic,
)


def load_france_travail_training_requirements(
) -> tuple[FranceTravailTrainingRequirement, ...]:
    """Charge les exigences France Travail dans une transaction en lecture seule."""
    session = SESSION_LOCAL()
    transaction = session.begin()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        formations = FormationRepository(
            session
        ).list_france_travail_training_requirements()
        source_rows = [
            FranceTravailTrainingRequirementSourceRow(
                formation_id=formation.id,
                intitule=formation.intitule_certification,
                code_source=formation.code_rncp,
                niveau=formation.niveau_rncp,
                commentaire=formation.commentaire,
                offre_ids=tuple(offre.id for offre in formation.offres),
                siret_of_contractant=formation.siret_of_contractant,
                has_monthly_flow=bool(formation.flux_mensuels),
                codes_rome=tuple(rome.code_rome for rome in formation.codes_rome),
            )
            for formation in formations
        ]
        return build_france_travail_training_requirements(source_rows)
    finally:
        transaction.rollback()
        session.close()


def main() -> None:
    """Affiche uniquement le diagnostic agrégé des exigences France Travail."""
    try:
        requirements = load_france_travail_training_requirements()
        diagnostic = calculate_training_requirements_diagnostic(requirements)
    except Exception as exc:
        print(f"Erreur de construction des exigences France Travail : {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Lignes d'exigence : {diagnostic.nombre_lignes_exigence}")
    print(
        "Associations offre-exigence : "
        f"{diagnostic.nombre_associations_offre_exigence}"
    )
    print(f"Offres distinctes concernées : {diagnostic.nombre_offres_distinctes}")
    print(
        "Exigences avec code_source : "
        f"{diagnostic.nombre_exigences_avec_code_source}"
    )
    print(f"Exigences avec niveau : {diagnostic.nombre_exigences_avec_niveau}")
    print(
        "Exigences avec commentaire : "
        f"{diagnostic.nombre_exigences_avec_commentaire}"
    )
    print(
        "Exigences par offre (min/moyenne/max) : "
        f"{diagnostic.exigences_par_offre_min}/"
        f"{diagnostic.exigences_par_offre_moyen:.2f}/"
        f"{diagnostic.exigences_par_offre_max}"
    )
    print(
        "Offres par exigence (min/moyenne/max) : "
        f"{diagnostic.offres_par_exigence_min}/"
        f"{diagnostic.offres_par_exigence_moyen:.2f}/"
        f"{diagnostic.offres_par_exigence_max}"
    )


if __name__ == "__main__":
    main()
