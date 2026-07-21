"""Audite la couverture du catalogue RNCP local avec la source officielle."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from backend.scripts.build_rncp_catalogue import load_rncp_catalogue
from backend.services.official_rncp_audit import (
    OfficialRncpAuditReport,
    calculate_official_rncp_audit,
    discover_current_rncp_resource,
    download_official_rncp_archive,
    fetch_official_dataset_metadata,
    parse_official_rncp_archive,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = BACKEND_ROOT / "scratch"
DISPLAY_CODE_LIMIT = 20


def run_official_rncp_audit() -> OfficialRncpAuditReport:
    """Télécharge temporairement la source officielle et calcule le diagnostic."""
    catalogue = load_rncp_catalogue()
    local_codes = tuple(
        certification.code_rncp for certification in catalogue.certifications
    )
    metadata = fetch_official_dataset_metadata()
    resource = discover_current_rncp_resource(metadata)
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="official-rncp-", dir=SCRATCH_ROOT) as temp_dir:
        archive_path = download_official_rncp_archive(resource, Path(temp_dir))
        parse_result = parse_official_rncp_archive(
            archive_path,
            local_codes,
            resource.schema_version,
        )
    return calculate_official_rncp_audit(local_codes, parse_result, resource)


def _format_codes(codes: tuple[str, ...]) -> str:
    """Formate une liste bornée de codes pour l'affichage du diagnostic."""
    if not codes:
        return "aucun"
    displayed_codes = codes[:DISPLAY_CODE_LIMIT]
    suffix = " ..." if len(codes) > DISPLAY_CODE_LIMIT else ""
    return ", ".join(displayed_codes) + suffix


def main() -> None:
    """Affiche le diagnostic agrégé sans modifier PostgreSQL."""
    try:
        report = run_official_rncp_audit()
    except Exception as exc:
        print(f"Erreur d'audit de la source RNCP officielle : {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Jeu data.gouv.fr : {report.resource.dataset_id}")
    print(f"Ressource : {report.resource.resource_id}")
    print(f"Archive : {report.resource.title}")
    print(f"Version : {report.version_flux}")
    print(f"Date de ressource : {report.resource.publication_date.isoformat()}")
    print(f"Codes locaux : {report.nombre_codes_locaux}")
    print(f"Codes trouvés : {len(report.codes_trouves)}")
    print(f"Codes absents : {len(report.codes_absents)}")
    print(f"Codes ambigus : {len(report.codes_ambigus)}")
    print(f"Fiches actives : {report.fiches_actives}")
    print(f"Fiches inactives : {report.fiches_inactives}")
    print(f"Fiches à l'état inconnu : {report.fiches_etat_inconnu}")
    print(f"Fiches avec certification de remplacement : {report.fiches_avec_remplacement}")
    print("Remplissage des champs :")
    for field_name, coverage in report.remplissage_champs.items():
        print(
            f"- {field_name}: {coverage.nombre_renseigne}/{coverage.nombre_total} "
            f"({coverage.taux_pourcent:.2f} %)"
        )
    print(
        "Blocs par certification (min/moyenne/max) : "
        f"{report.blocs_par_certification_min}/"
        f"{report.blocs_par_certification_moyen:.2f}/"
        f"{report.blocs_par_certification_max}"
    )
    print(f"Codes absents (aperçu) : {_format_codes(report.codes_absents)}")
    print(f"Codes ambigus (aperçu) : {_format_codes(report.codes_ambigus)}")
    print(f"Codes des fiches inactives : {_format_codes(report.codes_fiches_inactives)}")


if __name__ == "__main__":
    main()
