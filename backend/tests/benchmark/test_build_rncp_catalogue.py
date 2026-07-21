"""Tests du point d'entrée PostgreSQL du catalogue RNCP."""

import json
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import backend.scripts.build_rncp_catalogue as script_module
from backend.scripts.build_rncp_catalogue import (
    export_rncp_catalogue,
    load_rncp_catalogue,
    parse_args,
)
from backend.services.rncp_catalogue import RncpCatalogueSourceRow, build_rncp_catalogue


def make_catalogue():
    return build_rncp_catalogue(
        [
            RncpCatalogueSourceRow(
                formation_id=20,
                code_rncp="RNCP200",
                intitule_certification="Développeur web",
                niveau_rncp="6",
                siret_of_contractant="22222222222222",
                codes_rome=("M1805", "M1801"),
                has_monthly_flow=True,
            ),
            RncpCatalogueSourceRow(
                formation_id=10,
                code_rncp="RNCP100",
                intitule_certification="Administrateur systèmes",
                niveau_rncp="5",
                siret_of_contractant="11111111111111",
                codes_rome=("M1802", "M1801"),
                has_monthly_flow=True,
            ),
        ]
    )


def test_load_catalogue_uses_read_only_transaction_and_rolls_back():
    session = MagicMock()
    transaction = session.begin.return_value
    formation = SimpleNamespace(
        id=1,
        code_rncp="RNCP100",
        intitule_certification="Administrateur systèmes",
        niveau_rncp="6",
        siret_of_contractant="11111111111111",
        codes_rome=[SimpleNamespace(code_rome="M1801")],
        flux_mensuels=[SimpleNamespace(id=1)],
    )

    with (
        patch(
            "backend.scripts.build_rncp_catalogue.SESSION_LOCAL",
            return_value=session,
        ),
        patch(
            "backend.scripts.build_rncp_catalogue.FormationRepository"
        ) as repository_class,
    ):
        repository_class.return_value.list_mcf_catalogue_formations.return_value = [
            formation
        ]
        catalogue = load_rncp_catalogue()

    assert catalogue.certifications[0].code_rncp == "RNCP100"
    assert str(session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    transaction.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_load_catalogue_preserves_repository_error_and_cleans_resources():
    session = MagicMock()
    transaction = session.begin.return_value
    repository_error = RuntimeError("Lecture du catalogue impossible")

    with (
        patch(
            "backend.scripts.build_rncp_catalogue.SESSION_LOCAL",
            return_value=session,
        ),
        patch(
            "backend.scripts.build_rncp_catalogue.FormationRepository"
        ) as repository_class,
    ):
        repository_class.return_value.list_mcf_catalogue_formations.side_effect = (
            repository_error
        )
        with pytest.raises(RuntimeError) as raised_error:
            load_rncp_catalogue()

    assert raised_error.value is repository_error
    transaction.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_main_without_export_creates_no_file(tmp_path):
    destination = tmp_path / "rncp_catalogue.json"
    args = parse_args([])

    with (
        patch.object(
            script_module,
            "parse_args",
            return_value=args,
        ),
        patch.object(script_module, "load_rncp_catalogue", return_value=make_catalogue()),
        patch.object(script_module, "export_rncp_catalogue") as export_mock,
    ):
        script_module.main()

    export_mock.assert_not_called()
    assert args.export_json is None
    assert args.overwrite is False
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_export_is_utf8_newline_terminated_and_excludes_local_ids(tmp_path):
    destination = tmp_path / "rncp_catalogue.json"

    export_rncp_catalogue(make_catalogue(), destination)

    content = destination.read_bytes()
    assert "Développeur web".encode("utf-8") in content
    assert content.endswith(b"\n")
    payload = json.loads(content.decode("utf-8"))
    for certification in payload["certifications"]:
        assert "formation_ids" not in certification
        assert "source_formation_ids" not in certification


def test_two_exports_of_same_catalogue_have_identical_bytes(tmp_path):
    first_destination = tmp_path / "first.json"
    second_destination = tmp_path / "second.json"
    catalogue = make_catalogue()

    export_rncp_catalogue(catalogue, first_destination)
    export_rncp_catalogue(catalogue, second_destination)

    assert first_destination.read_bytes() == second_destination.read_bytes()


def test_export_orders_certifications_and_rome_codes_deterministically(tmp_path):
    destination = tmp_path / "rncp_catalogue.json"

    export_rncp_catalogue(make_catalogue(), destination)

    certifications = json.loads(destination.read_text(encoding="utf-8"))[
        "certifications"
    ]
    assert [item["code_rncp"] for item in certifications] == ["RNCP100", "RNCP200"]
    assert certifications[0]["codes_rome"] == ["M1801", "M1802"]
    assert certifications[1]["codes_rome"] == ["M1801", "M1805"]


def test_export_refuses_to_replace_existing_file(tmp_path):
    destination = tmp_path / "rncp_catalogue.json"
    original_content = b"contenu existant\n"
    destination.write_bytes(original_content)

    with pytest.raises(FileExistsError, match="existe déjà.*--overwrite"):
        export_rncp_catalogue(make_catalogue(), destination)

    assert destination.read_bytes() == original_content


def test_export_replaces_existing_file_only_with_overwrite(tmp_path):
    destination = tmp_path / "rncp_catalogue.json"
    destination.write_bytes(b"contenu existant\n")

    export_rncp_catalogue(make_catalogue(), destination, overwrite=True)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert len(payload["certifications"]) == 2


def test_parse_args_rejects_overwrite_without_export():
    with pytest.raises(SystemExit) as raised_error:
        parse_args(["--overwrite"])

    assert raised_error.value.code == 2


def test_parse_args_accepts_explicit_export_with_overwrite(tmp_path):
    destination = tmp_path / "rncp_catalogue.json"

    args = parse_args(["--export-json", str(destination), "--overwrite"])

    assert args.export_json == destination
    assert args.overwrite is True


def test_main_forwards_explicit_overwrite_to_export(tmp_path):
    destination = tmp_path / "rncp_catalogue.json"
    catalogue = make_catalogue()

    with (
        patch.object(
            script_module,
            "parse_args",
            return_value=Namespace(export_json=destination, overwrite=True),
        ),
        patch.object(script_module, "load_rncp_catalogue", return_value=catalogue),
        patch.object(script_module, "export_rncp_catalogue") as export_mock,
    ):
        script_module.main()

    export_mock.assert_called_once_with(catalogue, destination, overwrite=True)
    assert not destination.exists()
