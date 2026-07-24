"""Résolution temporaire des successions entre certifications RNCP officielles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from services.official_rncp_audit import (
    OfficialRncpCertification,
    OfficialRncpParseResult,
    normalize_rncp_code,
    parse_official_rncp_archive,
)


class RncpSuccessorClassification(str, Enum):
    """Décrit l'issue déterministe d'une succession RNCP officielle."""

    HISTORIQUE_SANS_REMPLACEMENT = "HISTORIQUE_SANS_REMPLACEMENT"
    SUCCESSEUR_ACTIF_UNIQUE = "SUCCESSEUR_ACTIF_UNIQUE"
    REMPLACEMENTS_MULTIPLES = "REMPLACEMENTS_MULTIPLES"
    REMPLACEMENT_INTROUVABLE = "REMPLACEMENT_INTROUVABLE"
    CHAINE_AMBIGUE = "CHAINE_AMBIGUE"
    CYCLE_DETECTE = "CYCLE_DETECTE"


@dataclass(frozen=True)
class OfficialRncpSuccessorNode:
    """Expose les informations utiles d'une fiche rencontrée dans une succession."""

    code_rncp: str
    intitule_officiel: str | None
    actif: bool | None
    niveau_code: str | None
    niveau_libelle: str | None
    codes_rome: tuple[str, ...]
    date_fin_enregistrement: str | None
    present_dans_catalogue_local: bool


@dataclass(frozen=True)
class OfficialRncpSuccessionAnalysis:
    """Regroupe la résolution d'une certification locale inactive."""

    origine: OfficialRncpSuccessorNode
    classification: RncpSuccessorClassification
    successeurs_directs: tuple[str, ...]
    chemins_succession: tuple[tuple[str, ...], ...]
    fiches_rencontrees: tuple[OfficialRncpSuccessorNode, ...]
    successeurs_actifs_terminaux: tuple[OfficialRncpSuccessorNode, ...]
    references_absentes: tuple[str, ...]
    references_ambigues: tuple[str, ...]
    cycles: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class OfficialRncpSuccessorAuditReport:
    """Contient les analyses triées et leurs totaux par classification."""

    analyses: tuple[OfficialRncpSuccessionAnalysis, ...]
    totaux_par_classification: dict[RncpSuccessorClassification, int]


def _successor_codes(
    certification: OfficialRncpCertification,
) -> tuple[str, ...]:
    """Normalise et trie les références de remplacement d'une fiche."""
    return tuple(
        sorted(
            {
                normalize_rncp_code(code)
                for code in certification.nouvelles_certifications
            }
        )
    )


def _to_successor_node(
    certification: OfficialRncpCertification,
    local_codes: set[str],
) -> OfficialRncpSuccessorNode:
    """Construit la vue synthétique d'une fiche de la chaîne de succession."""
    return OfficialRncpSuccessorNode(
        code_rncp=certification.numero_fiche,
        intitule_officiel=certification.intitule_officiel,
        actif=certification.actif,
        niveau_code=certification.niveau_code,
        niveau_libelle=certification.niveau_libelle,
        codes_rome=certification.codes_rome,
        date_fin_enregistrement=certification.date_fin_enregistrement,
        present_dans_catalogue_local=certification.numero_fiche in local_codes,
    )


def _resolve_referenced_certifications(
    archive_path: Path,
    local_parse_result: OfficialRncpParseResult,
    expected_schema_version: str,
) -> tuple[
    dict[str, OfficialRncpCertification],
    set[str],
    set[str],
]:
    """Résout les références par vagues ciblées dans la même archive."""
    records_by_code = {
        certification.numero_fiche: certification
        for certification in local_parse_result.certifications
    }
    ambiguous_codes = set(local_parse_result.codes_ambigus)
    missing_codes: set[str] = set()
    inactive_certifications = (
        certification
        for certification in local_parse_result.certifications
        if certification.actif is False
    )
    pending_codes = {
        code
        for certification in inactive_certifications
        for code in _successor_codes(certification)
        if code not in records_by_code and code not in ambiguous_codes
    }

    while pending_codes:
        parse_result = parse_official_rncp_archive(
            archive_path,
            pending_codes,
            expected_schema_version,
        )
        found_records = {
            certification.numero_fiche: certification
            for certification in parse_result.certifications
        }
        ambiguous_codes.update(parse_result.codes_ambigus)
        missing_codes.update(
            pending_codes - found_records.keys() - ambiguous_codes
        )
        records_by_code.update(found_records)
        referenced_codes = {
            code
            for certification in found_records.values()
            for code in _successor_codes(certification)
        }
        pending_codes = {
            code
            for code in referenced_codes
            if code not in records_by_code
            and code not in ambiguous_codes
            and code not in missing_codes
        }

    return records_by_code, ambiguous_codes, missing_codes


def _classify_succession(
    direct_successors: tuple[str, ...],
    active_terminal_codes: set[str],
    missing_references: set[str],
    ambiguous_references: set[str],
    cycles: set[tuple[str, ...]],
    has_branch: bool,
    has_unknown_status: bool,
) -> RncpSuccessorClassification:
    """Classe une succession selon les anomalies et les feuilles observées."""
    if cycles:
        return RncpSuccessorClassification.CYCLE_DETECTE
    if ambiguous_references or has_unknown_status:
        return RncpSuccessorClassification.CHAINE_AMBIGUE
    if missing_references:
        return RncpSuccessorClassification.REMPLACEMENT_INTROUVABLE
    if not direct_successors:
        return RncpSuccessorClassification.HISTORIQUE_SANS_REMPLACEMENT
    if has_branch:
        return RncpSuccessorClassification.REMPLACEMENTS_MULTIPLES
    if len(active_terminal_codes) == 1:
        return RncpSuccessorClassification.SUCCESSEUR_ACTIF_UNIQUE
    return RncpSuccessorClassification.REMPLACEMENT_INTROUVABLE


def _analyse_inactive_certification(
    origin: OfficialRncpCertification,
    records_by_code: dict[str, OfficialRncpCertification],
    ambiguous_codes: set[str],
    missing_codes: set[str],
    local_codes: set[str],
) -> OfficialRncpSuccessionAnalysis:
    """Parcourt le graphe de succession d'une certification inactive."""
    direct_successors = _successor_codes(origin)
    encountered_codes = {origin.numero_fiche}
    active_terminal_codes: set[str] = set()
    missing_references: set[str] = set()
    ambiguous_references: set[str] = set()
    paths: set[tuple[str, ...]] = set()
    cycles: set[tuple[str, ...]] = set()
    has_branch = len(direct_successors) > 1
    has_unknown_status = False

    def visit(code: str, path: tuple[str, ...]) -> None:
        """Suit une branche tout en détectant feuilles, anomalies et cycles."""
        nonlocal has_branch, has_unknown_status
        current_path = path + (code,)
        if code in path:
            cycle_start = path.index(code)
            cycles.add(path[cycle_start:] + (code,))
            paths.add(current_path)
            return
        if code in ambiguous_codes:
            ambiguous_references.add(code)
            paths.add(current_path)
            return
        certification = records_by_code.get(code)
        if certification is None:
            missing_references.add(code)
            paths.add(current_path)
            return

        encountered_codes.add(code)
        if certification.actif is None:
            has_unknown_status = True
        successors = _successor_codes(certification)
        if len(successors) > 1:
            has_branch = True
        if not successors:
            paths.add(current_path)
            if certification.actif is True:
                active_terminal_codes.add(code)
            return
        for successor_code in successors:
            visit(successor_code, current_path)

    for direct_successor in direct_successors:
        visit(direct_successor, (origin.numero_fiche,))
    if not direct_successors:
        paths.add((origin.numero_fiche,))

    missing_references.update(
        code for code in missing_codes if code in {item for path in paths for item in path}
    )
    encountered_nodes = tuple(
        _to_successor_node(records_by_code[code], local_codes)
        for code in sorted(encountered_codes)
    )
    active_terminal_nodes = tuple(
        _to_successor_node(records_by_code[code], local_codes)
        for code in sorted(active_terminal_codes)
    )
    classification = _classify_succession(
        direct_successors,
        active_terminal_codes,
        missing_references,
        ambiguous_references,
        cycles,
        has_branch,
        has_unknown_status,
    )
    return OfficialRncpSuccessionAnalysis(
        origine=_to_successor_node(origin, local_codes),
        classification=classification,
        successeurs_directs=direct_successors,
        chemins_succession=tuple(sorted(paths)),
        fiches_rencontrees=encountered_nodes,
        successeurs_actifs_terminaux=active_terminal_nodes,
        references_absentes=tuple(sorted(missing_references)),
        references_ambigues=tuple(sorted(ambiguous_references)),
        cycles=tuple(sorted(cycles)),
    )


def resolve_official_rncp_successors(
    archive_path: Path,
    local_parse_result: OfficialRncpParseResult,
    local_codes: Iterable[str],
    expected_schema_version: str,
) -> OfficialRncpSuccessorAuditReport:
    """Résout et classe les successions des fiches locales inactives."""
    normalized_local_codes = {
        normalize_rncp_code(code)
        for code in local_codes
    }
    if not normalized_local_codes:
        raise ValueError("Aucun code RNCP local n'a été fourni.")
    ambiguous_local_codes = tuple(
        sorted(set(local_parse_result.codes_ambigus) & normalized_local_codes)
    )
    if ambiguous_local_codes:
        raise ValueError(
            "Codes RNCP locaux ambigus dans l'archive officielle : "
            f"{', '.join(ambiguous_local_codes)}."
        )
    records_by_code, ambiguous_codes, missing_codes = (
        _resolve_referenced_certifications(
            archive_path,
            local_parse_result,
            expected_schema_version,
        )
    )
    inactive_certifications = sorted(
        (
            certification
            for certification in local_parse_result.certifications
            if certification.actif is False
        ),
        key=lambda certification: certification.numero_fiche,
    )
    analyses = tuple(
        _analyse_inactive_certification(
            certification,
            records_by_code,
            ambiguous_codes,
            missing_codes,
            normalized_local_codes,
        )
        for certification in inactive_certifications
    )
    totals = {
        classification: sum(
            analysis.classification is classification
            for analysis in analyses
        )
        for classification in RncpSuccessorClassification
    }
    return OfficialRncpSuccessorAuditReport(
        analyses=analyses,
        totaux_par_classification=totals,
    )
