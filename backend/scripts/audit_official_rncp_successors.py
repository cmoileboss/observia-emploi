"""Affichage du diagnostic des successeurs officiels des fiches RNCP inactives."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from scripts.build_rncp_catalogue import load_rncp_catalogue
from services.official_rncp_audit import (
    OfficialRncpResource,
    discover_current_rncp_resource,
    download_official_rncp_archive,
    fetch_official_dataset_metadata,
    parse_official_rncp_archive,
)
from services.official_rncp_successors import (
    OfficialRncpSuccessionAnalysis,
    OfficialRncpSuccessorAuditReport,
    OfficialRncpSuccessorNode,
    RncpSuccessorClassification,
    resolve_official_rncp_successors,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = BACKEND_ROOT / "scratch"


def run_official_rncp_successor_audit() -> tuple[
    OfficialRncpResource,
    OfficialRncpSuccessorAuditReport,
]:
    """Télécharge une archive et analyse les successions sans persistance."""
    catalogue = load_rncp_catalogue()
    local_codes = tuple(
        certification.code_rncp for certification in catalogue.certifications
    )
    resource = discover_current_rncp_resource(fetch_official_dataset_metadata())
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="official-rncp-successors-",
        dir=SCRATCH_ROOT,
    ) as temp_dir:
        archive_path = download_official_rncp_archive(resource, Path(temp_dir))
        local_parse_result = parse_official_rncp_archive(
            archive_path,
            local_codes,
            resource.schema_version,
        )
        report = resolve_official_rncp_successors(
            archive_path,
            local_parse_result,
            local_codes,
            resource.schema_version,
        )
    return resource, report


def _format_status(active: bool | None) -> str:
    """Formate le statut actif, inactif ou inconnu d'une fiche."""
    if active is True:
        return "actif"
    if active is False:
        return "inactif"
    return "inconnu"


def _format_codes(codes: tuple[str, ...]) -> str:
    """Formate une collection de codes ou indique son absence."""
    return ", ".join(codes) if codes else "aucun"


def _format_node(node: OfficialRncpSuccessorNode) -> str:
    """Formate les informations utiles d'une fiche de succession."""
    local_presence = "oui" if node.present_dans_catalogue_local else "non"
    level = node.niveau_libelle or node.niveau_code or "non renseigné"
    return (
        f"{node.code_rncp} [{_format_status(node.actif)}] | "
        f"{node.intitule_officiel or 'intitulé non renseigné'} | "
        f"niveau: {level} | ROME: {_format_codes(node.codes_rome)} | "
        f"fin: {node.date_fin_enregistrement or 'non renseignée'} | "
        f"catalogue local: {local_presence}"
    )


def _print_analysis(analysis: OfficialRncpSuccessionAnalysis) -> None:
    """Affiche une analyse individuelle de succession RNCP."""
    print()
    print(_format_node(analysis.origine))
    print(f"Classification : {analysis.classification.value}")
    print(f"Successeurs directs : {_format_codes(analysis.successeurs_directs)}")
    print("Chaînes :")
    for path in analysis.chemins_succession:
        print(f"- {' -> '.join(path)}")
    print("Fiches rencontrées :")
    for node in analysis.fiches_rencontrees:
        print(f"- {_format_node(node)}")
    terminal_codes = tuple(
        node.code_rncp for node in analysis.successeurs_actifs_terminaux
    )
    print(f"Successeurs actifs terminaux : {_format_codes(terminal_codes)}")
    if analysis.references_absentes:
        print(f"Références absentes : {_format_codes(analysis.references_absentes)}")
    if analysis.references_ambigues:
        print(f"Références ambiguës : {_format_codes(analysis.references_ambigues)}")
    for cycle in analysis.cycles:
        print(f"Cycle : {' -> '.join(cycle)}")


def main() -> None:
    """Affiche le diagnostic sans remplacer ni persister de code RNCP."""
    try:
        resource, report = run_official_rncp_successor_audit()
    except Exception as exc:
        print(f"Erreur d'analyse des successeurs RNCP : {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Ressource : {resource.resource_id}")
    print(f"Archive : {resource.title}")
    print(f"Fiches locales inactives : {len(report.analyses)}")
    for analysis in report.analyses:
        _print_analysis(analysis)
    print()
    print("Totaux par classification :")
    for classification in RncpSuccessorClassification:
        print(
            f"- {classification.value}: "
            f"{report.totaux_par_classification[classification]}"
        )


if __name__ == "__main__":
    main()
