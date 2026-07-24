"""Tests du diagnostic PostgreSQL des exigences France Travail."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.scripts.build_france_travail_training_requirements import (
    load_france_travail_training_requirements,
)


def test_load_requirements_uses_read_only_transaction_and_closes_session():
    session = MagicMock()
    transaction = session.begin.return_value
    formation = SimpleNamespace(
        id=1,
        intitule_certification="Développement informatique",
        code_rncp="FORM-42",
        niveau_rncp="Bac + 3",
        commentaire=None,
        siret_of_contractant=None,
        offres=[SimpleNamespace(id=20), SimpleNamespace(id=10)],
        flux_mensuels=[],
        codes_rome=[],
    )

    with (
        patch(
            "backend.scripts.build_france_travail_training_requirements.SESSION_LOCAL",
            return_value=session,
        ),
        patch(
            "backend.scripts.build_france_travail_training_requirements.FormationRepository"
        ) as repository_class,
    ):
        repository_class.return_value.list_france_travail_training_requirements.return_value = [
            formation
        ]
        requirements = load_france_travail_training_requirements()

    assert requirements[0].offre_ids == (10, 20)
    assert str(session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    transaction.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_load_requirements_preserves_error_and_cleans_resources():
    session = MagicMock()
    transaction = session.begin.return_value
    repository_error = RuntimeError("Lecture des exigences impossible")

    with (
        patch(
            "backend.scripts.build_france_travail_training_requirements.SESSION_LOCAL",
            return_value=session,
        ),
        patch(
            "backend.scripts.build_france_travail_training_requirements.FormationRepository"
        ) as repository_class,
    ):
        repository_class.return_value.list_france_travail_training_requirements.side_effect = (
            repository_error
        )
        with pytest.raises(RuntimeError) as raised_error:
            load_france_travail_training_requirements()

    assert raised_error.value is repository_error
    transaction.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
