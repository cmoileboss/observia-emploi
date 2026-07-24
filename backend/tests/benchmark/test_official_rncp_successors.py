"""Tests de résolution des successeurs RNCP officiels."""

from pathlib import Path
import zipfile

import pytest

from backend.services.official_rncp_audit import parse_official_rncp_archive
from backend.services.official_rncp_successors import (
    RncpSuccessorClassification,
    resolve_official_rncp_successors,
)


def make_fiche(
    code: str,
    *,
    active: str | None,
    successors: tuple[str, ...] = (),
    title: str | None = None,
) -> str:
    active_xml = f"<ACTIF>{active}</ACTIF>" if active is not None else ""
    successors_xml = "".join(
        (
            "<NOUVELLE_CERTIFICATION>"
            f"<ID_FICHE_NOUVELLE_CERTIFICATION>{successor}</ID_FICHE_NOUVELLE_CERTIFICATION>"
            "</NOUVELLE_CERTIFICATION>"
        )
        for successor in successors
    )
    return (
        "<FICHE>"
        f"<NUMERO_FICHE>{code}</NUMERO_FICHE>"
        f"<INTITULE>{title or f'Titre {code}'}</INTITULE>"
        "<NOMENCLATURE_EUROPE><NIVEAU>NIV6</NIVEAU>"
        "<LIBELLE>Niveau 6</LIBELLE></NOMENCLATURE_EUROPE>"
        "<CODES_ROME><ROME><CODE>M1801</CODE></ROME></CODES_ROME>"
        "<DATE_FIN_ENREGISTREMENT>31/12/2030</DATE_FIN_ENREGISTREMENT>"
        f"{active_xml}"
        f"<NOUVELLES_CERTIFICATIONS>{successors_xml}</NOUVELLES_CERTIFICATIONS>"
        "</FICHE>"
    )


def write_archive(tmp_path: Path, *fiches: str) -> Path:
    archive_path = tmp_path / "rncp.zip"
    xml_content = (
        "<FICHES><VERSION_FLUX>4.1</VERSION_FLUX>"
        f"{''.join(fiches)}</FICHES>"
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("export_fiches_RNCP_V4_1.xml", xml_content)
    return archive_path


def resolve(tmp_path: Path, fiches: tuple[str, ...], local_codes: tuple[str, ...]):
    archive_path = write_archive(tmp_path, *fiches)
    local_result = parse_official_rncp_archive(
        archive_path,
        local_codes,
        "4.1",
    )
    return resolve_official_rncp_successors(
        archive_path,
        local_result,
        local_codes,
        "4.1",
    )


def test_resolves_direct_active_successor_with_details(tmp_path):
    report = resolve(
        tmp_path,
        (
            make_fiche("RNCP100", active="Non", successors=("RNCP200",)),
            make_fiche("RNCP200", active="Oui", title="Successeur actif"),
        ),
        ("RNCP100",),
    )

    analysis = report.analyses[0]
    terminal = analysis.successeurs_actifs_terminaux[0]
    assert analysis.classification is RncpSuccessorClassification.SUCCESSEUR_ACTIF_UNIQUE
    assert analysis.chemins_succession == (("RNCP100", "RNCP200"),)
    assert terminal.code_rncp == "RNCP200"
    assert terminal.intitule_officiel == "Successeur actif"
    assert terminal.niveau_libelle == "Niveau 6"
    assert terminal.codes_rome == ("M1801",)
    assert terminal.date_fin_enregistrement == "31/12/2030"
    assert terminal.present_dans_catalogue_local is False


def test_resolves_inactive_chain_to_active_terminal(tmp_path):
    report = resolve(
        tmp_path,
        (
            make_fiche("RNCP100", active="Non", successors=("RNCP200",)),
            make_fiche("RNCP200", active="Non", successors=("RNCP300",)),
            make_fiche("RNCP300", active="Oui"),
        ),
        ("RNCP100",),
    )

    analysis = report.analyses[0]
    assert analysis.classification is RncpSuccessorClassification.SUCCESSEUR_ACTIF_UNIQUE
    assert analysis.chemins_succession == (
        ("RNCP100", "RNCP200", "RNCP300"),
    )
    assert analysis.successeurs_actifs_terminaux[0].code_rncp == "RNCP300"


def test_classifies_unknown_status_inside_chain_as_ambiguous(tmp_path):
    report = resolve(
        tmp_path,
        (
            make_fiche("RNCP100", active="Non", successors=("RNCP200",)),
            make_fiche("RNCP200", active=None, successors=("RNCP300",)),
            make_fiche("RNCP300", active="Oui"),
        ),
        ("RNCP100",),
    )

    analysis = report.analyses[0]
    assert analysis.classification is RncpSuccessorClassification.CHAINE_AMBIGUE
    assert analysis.chemins_succession == (
        ("RNCP100", "RNCP200", "RNCP300"),
    )
    assert analysis.successeurs_actifs_terminaux[0].code_rncp == "RNCP300"


def test_rejects_ambiguous_local_code(tmp_path):
    archive_path = write_archive(
        tmp_path,
        make_fiche("RNCP100", active="Non", title="Premier"),
        make_fiche("RNCP100", active="Non", title="Second"),
    )
    local_result = parse_official_rncp_archive(
        archive_path,
        ("RNCP100",),
        "4.1",
    )

    with pytest.raises(
        ValueError,
        match="Codes RNCP locaux ambigus.*RNCP100",
    ):
        resolve_official_rncp_successors(
            archive_path,
            local_result,
            ("RNCP100",),
            "4.1",
        )


def test_classifies_inactive_record_without_successor_as_historical(tmp_path):
    report = resolve(
        tmp_path,
        (make_fiche("RNCP100", active="Non"),),
        ("RNCP100",),
    )

    assert (
        report.analyses[0].classification
        is RncpSuccessorClassification.HISTORIQUE_SANS_REMPLACEMENT
    )
    assert report.analyses[0].successeurs_actifs_terminaux == ()


def test_classifies_multiple_successors(tmp_path):
    report = resolve(
        tmp_path,
        (
            make_fiche(
                "RNCP100",
                active="Non",
                successors=("RNCP300", "RNCP200"),
            ),
            make_fiche("RNCP200", active="Oui"),
            make_fiche("RNCP300", active="Oui"),
        ),
        ("RNCP100",),
    )

    analysis = report.analyses[0]
    assert analysis.classification is RncpSuccessorClassification.REMPLACEMENTS_MULTIPLES
    assert analysis.successeurs_directs == ("RNCP200", "RNCP300")
    assert tuple(
        node.code_rncp for node in analysis.successeurs_actifs_terminaux
    ) == ("RNCP200", "RNCP300")


def test_classifies_missing_reference(tmp_path):
    report = resolve(
        tmp_path,
        (make_fiche("RNCP100", active="Non", successors=("RNCP999",)),),
        ("RNCP100",),
    )

    analysis = report.analyses[0]
    assert analysis.classification is RncpSuccessorClassification.REMPLACEMENT_INTROUVABLE
    assert analysis.references_absentes == ("RNCP999",)


def test_classifies_duplicated_successor_as_ambiguous(tmp_path):
    report = resolve(
        tmp_path,
        (
            make_fiche("RNCP100", active="Non", successors=("RNCP200",)),
            make_fiche("RNCP200", active="Oui", title="Premier"),
            make_fiche("RNCP200", active="Oui", title="Second"),
        ),
        ("RNCP100",),
    )

    analysis = report.analyses[0]
    assert analysis.classification is RncpSuccessorClassification.CHAINE_AMBIGUE
    assert analysis.references_ambigues == ("RNCP200",)


def test_detects_cycle(tmp_path):
    report = resolve(
        tmp_path,
        (
            make_fiche("RNCP100", active="Non", successors=("RNCP200",)),
            make_fiche("RNCP200", active="Non", successors=("RNCP100",)),
        ),
        ("RNCP100",),
    )

    analysis = report.analyses[0]
    assert analysis.classification is RncpSuccessorClassification.CYCLE_DETECTE
    assert analysis.cycles == (("RNCP100", "RNCP200", "RNCP100"),)


def test_marks_successor_already_present_in_local_catalogue(tmp_path):
    report = resolve(
        tmp_path,
        (
            make_fiche("RNCP100", active="Non", successors=("RNCP200",)),
            make_fiche("RNCP200", active="Oui"),
        ),
        ("RNCP100", "RNCP200"),
    )

    terminal = report.analyses[0].successeurs_actifs_terminaux[0]
    assert terminal.code_rncp == "RNCP200"
    assert terminal.present_dans_catalogue_local is True


def test_sorts_analyses_paths_and_totals_deterministically(tmp_path):
    report = resolve(
        tmp_path,
        (
            make_fiche("RNCP200", active="Non"),
            make_fiche("RNCP100", active="Non", successors=("RNCP400", "RNCP300")),
            make_fiche("RNCP400", active="Oui"),
            make_fiche("RNCP300", active="Oui"),
        ),
        ("RNCP200", "RNCP100"),
    )

    assert tuple(analysis.origine.code_rncp for analysis in report.analyses) == (
        "RNCP100",
        "RNCP200",
    )
    assert report.analyses[0].chemins_succession == (
        ("RNCP100", "RNCP300"),
        ("RNCP100", "RNCP400"),
    )
    assert (
        report.totaux_par_classification[
            RncpSuccessorClassification.REMPLACEMENTS_MULTIPLES
        ]
        == 1
    )
    assert (
        report.totaux_par_classification[
            RncpSuccessorClassification.HISTORIQUE_SANS_REMPLACEMENT
        ]
        == 1
    )
