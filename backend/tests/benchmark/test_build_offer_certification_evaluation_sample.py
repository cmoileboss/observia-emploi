"""Tests de l'orchestration en lecture seule de l'échantillon lot 5."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import backend.scripts.build_offer_certification_evaluation_sample as script_module
from backend.scripts.build_offer_certification_evaluation_sample import (
    load_evaluation_offer_sources,
    run_evaluation_sample_build,
)


def make_offer_model():
    return SimpleNamespace(
        id=1,
        francetravail_id=" FT-001 ",
        rome_code=" M1801 ",
        intitule="Administrateur systèmes",
        appellation_libelle="Administrateur informatique",
        rome_libelle="Administration de systèmes d'information",
        description="Description",
        competences=[SimpleNamespace(code="C1", libelle="Linux")],
    )


def make_requirement_model():
    return SimpleNamespace(
        id=10,
        intitule_certification="Diplôme informatique",
        code_rncp="BAC+3",
        niveau_rncp="6",
        commentaire="Exigé",
        offres=[SimpleNamespace(id=1)],
        siret_of_contractant=None,
        flux_mensuels=[],
        codes_rome=[],
    )


def test_loads_offers_skills_and_requirements_in_read_only_transaction():
    session = MagicMock()
    transaction = session.begin.return_value

    with (
        patch.object(script_module, "SESSION_LOCAL", return_value=session),
        patch.object(script_module, "OffreRepository") as offer_repository,
        patch.object(script_module, "FormationRepository") as formation_repository,
    ):
        offer_repository.return_value.list_france_travail_evaluation_offers.return_value = [
            make_offer_model()
        ]
        formation_repository.return_value.list_france_travail_training_requirements.return_value = [
            make_requirement_model()
        ]
        sources = load_evaluation_offer_sources()

    assert str(session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    assert sources[0].source == "FRANCE_TRAVAIL"
    assert sources[0].source_offer_id == "FT-001"
    assert sources[0].database_offer_id == 1
    assert sources[0].rome_code == "M1801"
    assert sources[0].competences[0].libelle == "Linux"
    assert sources[0].training_requirements[0].intitule == "Diplôme informatique"
    transaction.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_rolls_back_and_closes_when_offer_repository_fails():
    session = MagicMock()
    transaction = session.begin.return_value

    with (
        patch.object(script_module, "SESSION_LOCAL", return_value=session),
        patch.object(script_module, "OffreRepository") as offer_repository,
        pytest.raises(RuntimeError, match="échec repository"),
    ):
        offer_repository.return_value.list_france_travail_evaluation_offers.side_effect = RuntimeError(
            "échec repository"
        )
        load_evaluation_offer_sources()

    transaction.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_orchestration_hashes_the_exact_catalogue_bytes(tmp_path):
    catalogue_payload = {
        "certifications": [
            {
                "donnees_locales": {"code_rncp": "RNCP100"},
                "donnees_officielles": {
                    "actif": True,
                    "intitule_officiel": "Titre",
                    "codes_rome": ["M1801"],
                },
            }
        ]
    }
    catalogue_path = tmp_path / "catalogue.json"
    catalogue_bytes = json.dumps(catalogue_payload).encode("utf-8")
    catalogue_path.write_bytes(catalogue_bytes)
    expected_sample = SimpleNamespace()

    with (
        patch.object(script_module, "load_evaluation_offer_sources", return_value=()),
        patch.object(
            script_module,
            "build_evaluation_sample",
            return_value=expected_sample,
        ) as build_mock,
    ):
        result = run_evaluation_sample_build(catalogue_path)

    assert result is expected_sample
    assert build_mock.call_args.args[3] == hashlib.sha256(catalogue_bytes).hexdigest()
