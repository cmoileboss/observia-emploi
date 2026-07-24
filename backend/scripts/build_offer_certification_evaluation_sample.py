"""Construit hors PostgreSQL l'échantillon figé offre–certification."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

from postgres_connection import SESSION_LOCAL
from repositories.correspondance_formation_repository import FormationRepository
from repositories.francetravail_repository import OffreRepository
from services.france_travail_training_requirements import (
    FranceTravailTrainingRequirementSourceRow,
    build_france_travail_training_requirements,
    index_training_requirements_by_offer,
)
from services.offer_certification_evaluation_sample import (
    EvaluationCompetence,
    EvaluationOfferSource,
    EvaluationSample,
    EvaluationSampleConfig,
    build_evaluation_artifacts,
    build_evaluation_sample,
    export_evaluation_artifacts,
    load_evaluation_certifications,
)


def load_evaluation_offer_sources() -> tuple[EvaluationOfferSource, ...]:
    """Charge offres, compétences et exigences dans une transaction en lecture seule."""
    session = SESSION_LOCAL()
    transaction = session.begin()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        offers = OffreRepository(session).list_france_travail_evaluation_offers()
        formations = FormationRepository(
            session
        ).list_france_travail_training_requirements()
        requirements = build_france_travail_training_requirements(
            FranceTravailTrainingRequirementSourceRow(
                formation_id=formation.id,
                intitule=formation.intitule_certification,
                code_source=formation.code_rncp,
                niveau=formation.niveau_rncp,
                commentaire=formation.commentaire,
                offre_ids=tuple(offer.id for offer in formation.offres),
                siret_of_contractant=formation.siret_of_contractant,
                has_monthly_flow=bool(formation.flux_mensuels),
                codes_rome=tuple(code.code_rome for code in formation.codes_rome),
            )
            for formation in formations
        )
        requirements_by_offer = index_training_requirements_by_offer(requirements)
        return tuple(
            EvaluationOfferSource(
                source="FRANCE_TRAVAIL",
                source_offer_id=offer.francetravail_id.strip(),
                database_offer_id=offer.id,
                rome_code=offer.rome_code.strip(),
                title=offer.intitule,
                occupation_label=offer.appellation_libelle,
                rome_label=offer.rome_libelle,
                description=offer.description,
                competences=tuple(
                    sorted(
                        (
                            EvaluationCompetence(
                                code=competence.code,
                                libelle=competence.libelle,
                            )
                            for competence in offer.competences
                        ),
                        key=lambda item: (item.code or "", item.libelle or ""),
                    )
                ),
                training_requirements=requirements_by_offer.get(offer.id, ()),
            )
            for offer in offers
        )
    finally:
        transaction.rollback()
        session.close()


def run_evaluation_sample_build(
    enriched_catalogue_path: Path,
    config: EvaluationSampleConfig | None = None,
) -> EvaluationSample:
    """Construit l'échantillon depuis PostgreSQL et le catalogue JSON local."""
    catalogue_bytes = enriched_catalogue_path.read_bytes()
    try:
        catalogue_payload = json.loads(catalogue_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Le catalogue RNCP enrichi n'est pas un JSON UTF-8 valide."
        ) from exc
    certifications, catalogue_codes = load_evaluation_certifications(
        catalogue_payload
    )
    return build_evaluation_sample(
        load_evaluation_offer_sources(),
        certifications,
        catalogue_codes,
        hashlib.sha256(catalogue_bytes).hexdigest(),
        config,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse les chemins et la date explicites du run reproductible."""
    parser = argparse.ArgumentParser(
        description="Construit l'échantillon figé offre–certification sans matching."
    )
    parser.add_argument(
        "--enriched-catalogue",
        type=Path,
        required=True,
        help="Chemin du JSON RNCP enrichi produit par le lot 4.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Dossier de destination des quatre artefacts.",
    )
    parser.add_argument(
        "--run-date",
        type=date.fromisoformat,
        required=True,
        help="Date reproductible du run au format AAAA-MM-JJ.",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Construit, valide et exporte l'échantillon puis affiche ses compteurs."""
    args = parse_args()
    try:
        sample = run_evaluation_sample_build(args.enriched_catalogue)
        artifacts = build_evaluation_artifacts(sample, args.run_date)
        export_evaluation_artifacts(artifacts, args.output_dir)
    except Exception as exc:
        print(f"Erreur de construction de l'échantillon : {exc}", file=sys.stderr)
        sys.exit(1)

    split_counts = {
        split: sum(offer.split == split for offer in sample.offers)
        for split in ("development", "validation")
    }
    print(f"Offres sélectionnées : {len(sample.offers)}")
    print(f"Split development : {split_counts['development']}")
    print(f"Split validation : {split_counts['validation']}")
    print(
        "Couples offre–certification : "
        f"{sum(len(pool.candidates) for pool in sample.candidate_pools)}"
    )
    print(f"Artefacts exportés : {args.output_dir}")


if __name__ == "__main__":
    main()
