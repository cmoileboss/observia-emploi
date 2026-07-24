"""Construit et diagnostique le catalogue RNCP depuis PostgreSQL en lecture seule."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

from postgres_connection import SESSION_LOCAL
from repositories.correspondance_formation_repository import FormationRepository
from services.rncp_catalogue import (
    RncpCatalogue,
    RncpCatalogueSourceRow,
    build_rncp_catalogue,
    calculate_rncp_catalogue_diagnostic,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORT_PATH = BACKEND_ROOT / "data" / "processed" / "rncp_catalogue.json"


def load_rncp_catalogue() -> RncpCatalogue:
    """Charge et construit le catalogue RNCP dans une transaction en lecture seule."""
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
                codes_rome=tuple(rome.code_rome for rome in formation.codes_rome),
                has_monthly_flow=bool(formation.flux_mensuels),
            )
            for formation in formations
        ]
        return build_rncp_catalogue(source_rows)
    finally:
        transaction.rollback()
        session.close()


def export_rncp_catalogue(
    catalogue: RncpCatalogue,
    destination: Path,
    overwrite: bool = False,
) -> None:
    """Exporte explicitement le catalogue RNCP dans un JSON UTF-8 déterministe."""
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"Le fichier d'export existe déjà : {destination}. "
            "Utilisez --overwrite pour le remplacer."
        )

    payload = {
        "certifications": [
            certification.to_dict() for certification in catalogue.certifications
        ]
    }
    content = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse les arguments du diagnostic local."""
    parser = argparse.ArgumentParser(
        description="Construit le catalogue RNCP MCF sans modifier PostgreSQL."
    )
    parser.add_argument(
        "--export-json",
        nargs="?",
        const=DEFAULT_EXPORT_PATH,
        default=None,
        type=Path,
        help=(
            "Exporte le catalogue en JSON. Sans chemin, utilise "
            "backend/data/processed/rncp_catalogue.json."
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
    """Exécute le diagnostic et l'éventuel export explicitement demandé."""
    args = parse_args()
    try:
        catalogue = load_rncp_catalogue()
        diagnostic = calculate_rncp_catalogue_diagnostic(catalogue)
        if args.export_json is not None:
            export_rncp_catalogue(
                catalogue,
                args.export_json,
                overwrite=args.overwrite,
            )
    except Exception as exc:
        print(f"Erreur de construction du catalogue RNCP : {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Lignes catalogue sélectionnées : {diagnostic.nombre_lignes_catalogue}")
    print(f"Certifications RNCP distinctes : {diagnostic.nombre_certifications_rncp}")
    print(f"Organismes distincts : {diagnostic.nombre_organismes_distincts}")
    print(f"Codes ROME distincts : {diagnostic.nombre_codes_rome_distincts}")
    print(
        "Organismes par certification (min/moyenne/max) : "
        f"{diagnostic.organismes_par_certification_min}/"
        f"{diagnostic.organismes_par_certification_moyen:.2f}/"
        f"{diagnostic.organismes_par_certification_max}"
    )
    print(
        "Codes ROME par certification (min/moyenne/max) : "
        f"{diagnostic.codes_rome_par_certification_min}/"
        f"{diagnostic.codes_rome_par_certification_moyen:.2f}/"
        f"{diagnostic.codes_rome_par_certification_max}"
    )
    if args.export_json is not None:
        print(f"Catalogue exporté : {args.export_json}")


if __name__ == "__main__":
    main()
