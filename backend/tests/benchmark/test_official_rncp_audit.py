"""Tests unitaires de l'audit de la source RNCP officielle."""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
import zipfile

import pytest
import requests

from backend.services.official_rncp_audit import (
    OfficialRncpResource,
    calculate_official_rncp_audit,
    discover_current_rncp_resource,
    download_official_rncp_archive,
    fetch_official_dataset_metadata,
    normalize_rncp_code,
    parse_official_rncp_archive,
    validate_rncp_archive,
)


def make_resource(**overrides) -> OfficialRncpResource:
    values = {
        "dataset_id": "dataset-1",
        "resource_id": "rncp-current",
        "title": "export-fiches-rncp-v4-1-2026-07-21.zip",
        "url": "https://static.data.gouv.fr/rncp-current.zip",
        "schema_version": "4.1",
        "publication_date": date(2026, 7, 21),
        "last_modified": "2026-07-21T10:00:00+00:00",
    }
    values.update(overrides)
    return OfficialRncpResource(**values)


def make_metadata(resources: list[dict]) -> dict:
    return {"id": "dataset-1", "resources": resources}


def make_resource_metadata(
    resource_id: str,
    title: str,
    resource_format: str = "zip",
) -> dict:
    return {
        "id": resource_id,
        "title": title,
        "format": resource_format,
        "url": f"https://static.data.gouv.fr/{resource_id}.zip",
        "last_modified": "2026-07-21T10:00:00+00:00",
    }


def write_archive(tmp_path: Path, xml_content: str, member_name: str | None = None) -> Path:
    archive_path = tmp_path / "official-rncp.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            member_name or "export_fiches_RNCP_V4_1_2026-07-21.xml",
            xml_content.encode("utf-8"),
        )
    return archive_path


def make_fiche(
    code: str,
    *,
    actif: str | None = "Oui",
    include_optional_fields: bool = True,
    replacement: str | None = None,
    block_count: int = 1,
) -> str:
    active_xml = f"<ACTIF>{actif}</ACTIF>" if actif is not None else ""
    if not include_optional_fields:
        return f"<FICHE><NUMERO_FICHE>{code}</NUMERO_FICHE>{active_xml}</FICHE>"
    blocks = "".join(
        (
            "<BLOC_COMPETENCES>"
            f"<CODE>{code}BC{index:02d}</CODE>"
            f"<LIBELLE>Bloc {index}</LIBELLE>"
            f"<LISTE_COMPETENCES>Compétence {index}</LISTE_COMPETENCES>"
            "</BLOC_COMPETENCES>"
        )
        for index in range(1, block_count + 1)
    )
    replacement_xml = (
        "<NOUVELLES_CERTIFICATIONS><NOUVELLE_CERTIFICATION>"
        f"<ID_FICHE_NOUVELLE_CERTIFICATION>{replacement}</ID_FICHE_NOUVELLE_CERTIFICATION>"
        "</NOUVELLE_CERTIFICATION></NOUVELLES_CERTIFICATIONS>"
        if replacement
        else ""
    )
    return (
        "<FICHE>"
        f"<NUMERO_FICHE>{code}</NUMERO_FICHE>"
        "<ANCIENNES_CERTIFICATIONS><ANCIENNE_CERTIFICATION>"
        "<ID_FICHE_ANCIENNE_CERTIFICATION>RNCP99</ID_FICHE_ANCIENNE_CERTIFICATION>"
        "</ANCIENNE_CERTIFICATION></ANCIENNES_CERTIFICATIONS>"
        f"<INTITULE>Titre {code}</INTITULE>"
        "<ETAT_FICHE>Publiée</ETAT_FICHE>"
        "<NOMENCLATURE_EUROPE><NIVEAU>NIV6</NIVEAU>"
        "<LIBELLE>Niveau 6</LIBELLE></NOMENCLATURE_EUROPE>"
        "<ACTIVITES_VISEES>Activités visées</ACTIVITES_VISEES>"
        "<CAPACITES_ATTESTEES>Compétences attestées</CAPACITES_ATTESTEES>"
        "<SECTEURS_ACTIVITE>Numérique</SECTEURS_ACTIVITE>"
        "<TYPE_EMPLOI_ACCESSIBLES>Développeur</TYPE_EMPLOI_ACCESSIBLES>"
        "<CODES_ROME><ROME><CODE>M1805</CODE></ROME>"
        "<ROME><CODE>M1801</CODE></ROME></CODES_ROME>"
        "<DATE_FIN_ENREGISTREMENT>2030-01-01</DATE_FIN_ENREGISTREMENT>"
        f"<BLOCS_COMPETENCES>{blocks}</BLOCS_COMPETENCES>"
        f"{active_xml}"
        "<PREREQUIS_ENTREE_FORMATION>Baccalauréat</PREREQUIS_ENTREE_FORMATION>"
        f"{replacement_xml}"
        "</FICHE>"
    )


def make_xml(*fiches: str, version: str = "4.1") -> str:
    return f"<FICHES><VERSION_FLUX>{version}</VERSION_FLUX>{''.join(fiches)}</FICHES>"


def test_selects_latest_xml_rncp_resource_and_ignores_rs_and_csv():
    metadata = make_metadata(
        [
            make_resource_metadata(
                "rs-current", "export-fiches-rs-v4-1-2026-07-22.zip"
            ),
            make_resource_metadata(
                "rncp-csv", "export-fiches-csv-2026-07-22.zip"
            ),
            make_resource_metadata(
                "rncp-old", "export-fiches-rncp-v3-0-2026-07-20.zip"
            ),
            make_resource_metadata(
                "rncp-current", "export-fiches-rncp-v4-1-2026-07-21.zip"
            ),
        ]
    )

    resource = discover_current_rncp_resource(metadata)

    assert resource.resource_id == "rncp-current"
    assert resource.schema_version == "4.1"
    assert resource.publication_date == date(2026, 7, 21)


def test_selects_highest_xml_version_before_publication_date():
    metadata = make_metadata(
        [
            make_resource_metadata(
                "rncp-v41", "export-fiches-rncp-v4-1-2026-07-20.zip"
            ),
            make_resource_metadata(
                "rncp-v30", "export-fiches-rncp-v3-0-2026-07-22.zip"
            ),
        ]
    )

    resource = discover_current_rncp_resource(metadata)

    assert resource.resource_id == "rncp-v41"
    assert resource.schema_version == "4.1"
    assert resource.publication_date == date(2026, 7, 20)


def test_rejects_metadata_containing_only_rs_resource():
    metadata = make_metadata(
        [
            make_resource_metadata(
                "rs-current", "export-fiches-rs-v4-1-2026-07-21.zip"
            )
        ]
    )

    with pytest.raises(ValueError, match="Aucune archive XML RNCP"):
        discover_current_rncp_resource(metadata)


@pytest.mark.parametrize("code", ["37674", " RNCP37674 "])
def test_normalizes_numeric_and_prefixed_rncp_codes(code):
    assert normalize_rncp_code(code) == "RNCP37674"


@pytest.mark.parametrize(
    "code",
    ["", " ", "RS37674", "rncp37674", "RNCP 37674", "37674A", "0"],
)
def test_rejects_invalid_rncp_code(code):
    with pytest.raises(ValueError, match="Code RNCP invalide"):
        normalize_rncp_code(code)


def test_parses_all_useful_fields_active_status_replacement_and_multiple_blocks(
    tmp_path,
):
    archive_path = write_archive(
        tmp_path,
        make_xml(make_fiche("RNCP37674", replacement="RNCP40000", block_count=2)),
    )

    result = parse_official_rncp_archive(archive_path, ["37674"], "4.1")

    certification = result.certifications[0]
    assert certification.numero_fiche == "RNCP37674"
    assert certification.intitule_officiel == "Titre RNCP37674"
    assert certification.etat_fiche == "Publiée"
    assert certification.actif is True
    assert certification.niveau_code == "NIV6"
    assert certification.niveau_libelle == "Niveau 6"
    assert certification.activites_visees == "Activités visées"
    assert certification.competences_attestees == "Compétences attestées"
    assert certification.secteurs_activite == "Numérique"
    assert certification.types_emplois_accessibles == "Développeur"
    assert certification.codes_rome == ("M1801", "M1805")
    assert certification.prerequis_entree == "Baccalauréat"
    assert len(certification.blocs_competences) == 2
    assert certification.blocs_competences[0].competences == "Compétence 1"
    assert certification.date_fin_enregistrement == "2030-01-01"
    assert certification.anciennes_certifications == ("RNCP99",)
    assert certification.nouvelles_certifications == ("RNCP40000",)


def test_parses_optional_fields_as_absent_and_inactive_status(tmp_path):
    archive_path = write_archive(
        tmp_path,
        make_xml(
            make_fiche(
                "RNCP100",
                actif="Non",
                include_optional_fields=False,
            )
        ),
    )

    result = parse_official_rncp_archive(archive_path, ["RNCP100"], "4.1")

    certification = result.certifications[0]
    assert certification.actif is False
    assert certification.intitule_officiel is None
    assert certification.codes_rome == ()
    assert certification.blocs_competences == ()
    assert certification.nouvelles_certifications == ()


def test_parsing_is_deterministic_and_reports_duplicate_code_as_ambiguous(tmp_path):
    archive_path = write_archive(
        tmp_path,
        make_xml(
            make_fiche("RNCP200"),
            make_fiche("RNCP100"),
            make_fiche("RNCP300"),
            make_fiche("RNCP300"),
        ),
    )

    first_result = parse_official_rncp_archive(
        archive_path, ["300", "200", "100"], "4.1"
    )
    second_result = parse_official_rncp_archive(
        archive_path, ["RNCP100", "RNCP200", "RNCP300"], "4.1"
    )

    assert first_result == second_result
    assert [item.numero_fiche for item in first_result.certifications] == [
        "RNCP100",
        "RNCP200",
    ]
    assert first_result.codes_ambigus == ("RNCP300",)


def test_calculates_field_coverage_and_block_statistics(tmp_path):
    archive_path = write_archive(
        tmp_path,
        make_xml(
            make_fiche("RNCP100", block_count=2),
            make_fiche("RNCP200", actif="Non", include_optional_fields=False),
        ),
    )
    parse_result = parse_official_rncp_archive(
        archive_path, ["RNCP100", "RNCP200", "RNCP404"], "4.1"
    )

    report = calculate_official_rncp_audit(
        ["100", "200", "404"], parse_result, make_resource()
    )

    assert report.nombre_codes_locaux == 3
    assert report.codes_trouves == ("RNCP100", "RNCP200")
    assert report.codes_absents == ("RNCP404",)
    assert report.codes_fiches_inactives == ("RNCP200",)
    assert report.fiches_actives == 1
    assert report.fiches_inactives == 1
    assert report.fiches_avec_remplacement == 0
    assert report.remplissage_champs["competences_attestees"].nombre_renseigne == 1
    assert report.remplissage_champs["competences_attestees"].taux_pourcent == 50.0
    assert report.blocs_par_certification_min == 0
    assert report.blocs_par_certification_moyen == 1.0
    assert report.blocs_par_certification_max == 2


@pytest.mark.parametrize(
    ("member_name", "content", "error_pattern"),
    [
        ("export_fiches_RS_V4_1.xml", "<FICHES />", "n'est pas une archive XML RNCP"),
        ("export_fiches_RNCP_V4_1.xml", "contenu invalide", "contenu XML RNCP est illisible"),
    ],
)
def test_rejects_unexpected_or_invalid_archive(
    tmp_path,
    member_name,
    content,
    error_pattern,
):
    archive_path = write_archive(tmp_path, content, member_name)

    with pytest.raises(ValueError, match=error_pattern):
        validate_rncp_archive(archive_path)


def test_wraps_network_error_when_loading_metadata():
    with patch(
        "backend.services.official_rncp_audit.requests.get",
        side_effect=requests.ConnectionError("indisponible"),
    ):
        with pytest.raises(RuntimeError, match="charger les métadonnées"):
            fetch_official_dataset_metadata()


def test_rejects_invalid_downloaded_archive_and_removes_it(tmp_path):
    response = MagicMock()
    response.url = "https://static.data.gouv.fr/rncp-current.zip"
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"archive invalide"]

    with patch(
        "backend.services.official_rncp_audit.requests.get",
        return_value=response,
    ):
        with pytest.raises(ValueError, match="Archive RNCP illisible"):
            download_official_rncp_archive(make_resource(), tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_rejects_download_redirected_outside_allowed_domains(tmp_path):
    response = MagicMock()
    response.url = "https://example.org/rncp-current.zip"
    response.raise_for_status.return_value = None

    with patch(
        "backend.services.official_rncp_audit.requests.get",
        return_value=response,
    ):
        with pytest.raises(ValueError, match="URL de source officielle non autorisée"):
            download_official_rncp_archive(make_resource(), tmp_path)

    assert list(tmp_path.iterdir()) == []
