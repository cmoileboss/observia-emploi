"""Construit et exporte le catalogue RNCP enrichi sans écriture PostgreSQL."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text

from backend.postgres_connection import SESSION_LOCAL
from backend.repositories.correspondance_formation_repository import FormationRepository
from backend.services.enriched_rncp_catalogue import (
    EnrichedRncpCatalogue,
    LocalRncpOrganization,
    LocalRncpOrganizationAssociation,
    build_enriched_rncp_catalogue,
)
from backend.services.official_rncp_audit import (
    calculate_official_rncp_audit,
    discover_current_rncp_resource,
    download_official_rncp_archive,
    fetch_official_dataset_metadata,
    parse_official_rncp_archive,
)
from backend.services.official_rncp_successors import (
    resolve_official_rncp_successors,
)
from backend.services.rncp_catalogue import (
    RncpCatalogue,
    RncpCatalogueSourceRow,
    build_rncp_catalogue,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = BACKEND_ROOT / "scratch"
DEFAULT_EXPORT_PATH = (
    BACKEND_ROOT / "data" / "processed" / "rncp_catalogue_enrichi.json"
)


def load_local_enrichment_source() -> tuple[
    RncpCatalogue,
    tuple[LocalRncpOrganizationAssociation, ...],
]:
    """Charge le catalogue et ses organismes dans une transaction en lecture seule."""
    session = SESSION_LOCAL()
    transaction = session.begin()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        formations = FormationRepository(session).list_mcf_catalogue_formations()
        source_rows = [
            RncpCatalogueSourceRow(
                formation_id=formation.id,
                code_rncp=formation.code_rncp,
                intitule_certification=formation.intitule_certification,
                niveau_rncp=formation.niveau_rncp,
                siret_of_contractant=formation.siret_of_contractant,
                codes_rome=tuple(
                    rome.code_rome for rome in formation.codes_rome
                ),
                has_monthly_flow=bool(formation.flux_mensuels),
            )
            for formation in formations
        ]
        associations = tuple(
            LocalRncpOrganizationAssociation(
                code_rncp=formation.code_rncp,
                organization=LocalRncpOrganization(
                    siret_of_contractant=formation.siret_of_contractant,
                    raison_sociale_of_contractant=(
                        formation.raison_sociale_of_contractant
                    ),
                    modalite=formation.modalite,
                    nom_entreprise=formation.nom_entreprise,
                    code_postal=formation.code_postal,
                    region=formation.region,
                ),
            )
            for formation in formations
        )
        return build_rncp_catalogue(source_rows), associations
    finally:
        transaction.rollback()
        session.close()


def run_enriched_rncp_catalogue_build() -> EnrichedRncpCatalogue:
    """Orchestre une lecture locale et un unique téléchargement officiel."""
    local_catalogue, organization_associations = load_local_enrichment_source()
    local_codes = tuple(
        certification.code_rncp
        for certification in local_catalogue.certifications
    )
    resource = discover_current_rncp_resource(fetch_official_dataset_metadata())
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="enriched-rncp-catalogue-",
        dir=SCRATCH_ROOT,
    ) as temp_dir:
        archive_path = download_official_rncp_archive(resource, Path(temp_dir))
        official_parse_result = parse_official_rncp_archive(
            archive_path,
            local_codes,
            resource.schema_version,
        )
        official_audit_report = calculate_official_rncp_audit(
            local_codes,
            official_parse_result,
            resource,
        )
        succession_report = resolve_official_rncp_successors(
            archive_path,
            official_parse_result,
            local_codes,
            resource.schema_version,
        )
        return build_enriched_rncp_catalogue(
            local_catalogue,
            organization_associations,
            official_parse_result,
            official_audit_report,
            succession_report,
        )


def export_enriched_rncp_catalogue(
    catalogue: EnrichedRncpCatalogue,
    destination: Path,
    overwrite: bool = False,
) -> None:
    """Exporte le catalogue en JSON UTF-8 déterministe avec saut de ligne final."""
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"Le fichier d'export existe déjà : {destination}. "
            "Utilisez --overwrite pour le remplacer."
        )
    content = json.dumps(
        catalogue.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse les options explicites d'export du catalogue enrichi."""
    parser = argparse.ArgumentParser(
        description="Construit le catalogue RNCP enrichi sans modifier PostgreSQL."
    )
    parser.add_argument(
        "--export-json",
        nargs="?",
        const=DEFAULT_EXPORT_PATH,
        default=None,
        type=Path,
        help=(
            "Exporte le catalogue en JSON. Sans chemin, utilise "
            "backend/data/processed/rncp_catalogue_enrichi.json."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Autorise explicitement le remplacement du fichier exporté.",
    )
    args = parser.parse_args(argv)
    if args.overwrite and args.export_json is None:
        parser.error("--overwrite requiert --export-json.")
    return args


def main() -> None:
    """Construit le catalogue, l'exporte sur demande et affiche ses compteurs."""
    args = parse_args()
    try:
        catalogue = run_enriched_rncp_catalogue_build()
        if args.export_json is not None:
            export_enriched_rncp_catalogue(
                catalogue,
                args.export_json,
                overwrite=args.overwrite,
            )
    except Exception as exc:
        print(f"Erreur de construction du catalogue RNCP enrichi : {exc}", file=sys.stderr)
        sys.exit(1)

    counters = catalogue.counters
    print(f"Certifications enrichies : {counters.nombre_certifications}")
    print(f"Organismes distincts : {counters.nombre_organismes_distincts}")
    print(f"Associations organismes : {counters.nombre_associations_organismes}")
    print(f"Certifications actives : {counters.nombre_certifications_actives}")
    print(f"Certifications inactives : {counters.nombre_certifications_inactives}")
    print(f"Statuts inconnus : {counters.nombre_statuts_inconnus}")
    print(f"Analyses de succession : {counters.nombre_analyses_succession}")
    if args.export_json is not None:
        print(f"Catalogue exporté : {args.export_json}")


if __name__ == "__main__":
    main()
