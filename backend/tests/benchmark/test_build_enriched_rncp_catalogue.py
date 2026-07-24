"""Tests de l'orchestration et de l'export du catalogue RNCP enrichi."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import backend.scripts.build_enriched_rncp_catalogue as script_module
from backend.scripts.build_enriched_rncp_catalogue import (
    export_enriched_rncp_catalogue,
    load_local_enrichment_source,
    run_enriched_rncp_catalogue_build,
)


def test_loads_local_catalogue_and_organizations_in_read_only_transaction():
    session = MagicMock()
    transaction = session.begin.return_value
    formation = SimpleNamespace(
        id=1,
        code_rncp="RNCP100",
        intitule_certification="Titre local",
        niveau_rncp="6",
        siret_of_contractant="11111111111111",
        raison_sociale_of_contractant="Organisme local",
        modalite="Présentiel",
        nom_entreprise="Site local",
        code_postal="31000",
        region="Occitanie",
        codes_rome=[SimpleNamespace(code_rome="M1801")],
        flux_mensuels=[SimpleNamespace(id=1)],
    )

    with (
        patch.object(script_module, "SESSION_LOCAL", return_value=session),
        patch.object(script_module, "FormationRepository") as repository_class,
    ):
        repository_class.return_value.list_mcf_catalogue_formations.return_value = [
            formation
        ]
        catalogue, associations = load_local_enrichment_source()

    assert catalogue.certifications[0].code_rncp == "RNCP100"
    assert associations[0].organization.raison_sociale_of_contractant == (
        "Organisme local"
    )
    assert associations[0].organization.region == "Occitanie"
    assert str(session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    transaction.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_orchestration_downloads_once_and_reuses_same_archive(tmp_path):
    local_catalogue = SimpleNamespace(
        certifications=[SimpleNamespace(code_rncp="RNCP100")]
    )
    associations = (SimpleNamespace(code_rncp="RNCP100"),)
    metadata = {"id": "dataset-1", "resources": []}
    resource = SimpleNamespace(schema_version="4.1")
    parse_result = SimpleNamespace(certifications=())
    audit_report = SimpleNamespace(codes_absents=())
    succession_report = SimpleNamespace(analyses=())
    expected_catalogue = SimpleNamespace()
    archive_path = tmp_path / "rncp.zip"

    with (
        patch.object(script_module, "SCRATCH_ROOT", tmp_path),
        patch.object(
            script_module,
            "load_local_enrichment_source",
            return_value=(local_catalogue, associations),
        ),
        patch.object(
            script_module,
            "fetch_official_dataset_metadata",
            return_value=metadata,
        ),
        patch.object(
            script_module,
            "discover_current_rncp_resource",
            return_value=resource,
        ),
        patch.object(
            script_module,
            "download_official_rncp_archive",
            return_value=archive_path,
        ) as download_mock,
        patch.object(
            script_module,
            "parse_official_rncp_archive",
            return_value=parse_result,
        ) as parse_mock,
        patch.object(
            script_module,
            "calculate_official_rncp_audit",
            return_value=audit_report,
        ) as audit_mock,
        patch.object(
            script_module,
            "resolve_official_rncp_successors",
            return_value=succession_report,
        ) as succession_mock,
        patch.object(
            script_module,
            "build_enriched_rncp_catalogue",
            return_value=expected_catalogue,
        ) as build_mock,
    ):
        result = run_enriched_rncp_catalogue_build()

    assert result is expected_catalogue
    download_mock.assert_called_once_with(resource, download_mock.call_args.args[1])
    parse_mock.assert_called_once_with(archive_path, ("RNCP100",), "4.1")
    audit_mock.assert_called_once_with(("RNCP100",), parse_result, resource)
    succession_mock.assert_called_once_with(
        archive_path,
        parse_result,
        ("RNCP100",),
        "4.1",
    )
    build_mock.assert_called_once_with(
        local_catalogue,
        associations,
        parse_result,
        audit_report,
        succession_report,
    )


def test_exports_identical_utf8_json_bytes_with_final_newline(tmp_path):
    catalogue = SimpleNamespace(
        to_dict=lambda: {
            "metadata": {"titre": "Catalogue enrichi"},
            "certifications": [
                {"donnees_locales": {"code_rncp": "RNCP100"}}
            ],
        }
    )
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    export_enriched_rncp_catalogue(catalogue, first_path)
    export_enriched_rncp_catalogue(catalogue, second_path)

    first_content = first_path.read_bytes()
    assert first_content == second_path.read_bytes()
    assert first_content.endswith(b"\n")
    assert "enrichi".encode("utf-8") in first_content
    assert json.loads(first_content.decode("utf-8"))["certifications"][0][
        "donnees_locales"
    ]["code_rncp"] == "RNCP100"
