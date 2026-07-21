"""Tests unitaires des exigences de formation France Travail."""

import pytest

from backend.services.france_travail_training_requirements import (
    FranceTravailTrainingRequirementSourceRow,
    build_france_travail_training_requirement,
    build_france_travail_training_requirements,
    calculate_training_requirements_diagnostic,
    index_training_requirements_by_offer,
)


def make_row(
    formation_id: int | None,
    intitule: str | None = "Développement informatique",
    code_source: str | None = "FORM-42",
    niveau: str | None = "Bac + 3",
    commentaire: str | None = "Formation souhaitée",
    offre_ids: tuple[int | None, ...] = (10,),
    siret: str | None = None,
    has_monthly_flow: bool = False,
    codes_rome: tuple[str | None, ...] = (),
) -> FranceTravailTrainingRequirementSourceRow:
    return FranceTravailTrainingRequirementSourceRow(
        formation_id=formation_id,
        intitule=intitule,
        code_source=code_source,
        niveau=niveau,
        commentaire=commentaire,
        offre_ids=offre_ids,
        siret_of_contractant=siret,
        has_monthly_flow=has_monthly_flow,
        codes_rome=codes_rome,
    )


def test_selects_valid_training_requirement():
    requirements = build_france_travail_training_requirements([make_row(1)])

    assert len(requirements) == 1
    assert requirements[0].formation_id == 1
    assert requirements[0].intitule == "Développement informatique"


@pytest.mark.parametrize(
    "excluded_row",
    [
        make_row(2, siret="11111111111111"),
        make_row(2, has_monthly_flow=True),
        make_row(2, codes_rome=("M1805",)),
    ],
)
def test_excludes_rows_that_do_not_match_france_travail_criteria(excluded_row):
    requirements = build_france_travail_training_requirements(
        [make_row(1), excluded_row]
    )

    assert [requirement.formation_id for requirement in requirements] == [1]


@pytest.mark.parametrize(
    "invalid_row,error_match",
    [
        (make_row(1, siret="11111111111111"), "SIRET renseigné"),
        (make_row(1, has_monthly_flow=True), "flux mensuel"),
        (make_row(1, codes_rome=("M1805",)), "code ROME"),
    ],
)
def test_strict_builder_rejects_invalid_selected_requirement(invalid_row, error_match):
    with pytest.raises(ValueError, match=error_match):
        build_france_travail_training_requirement(invalid_row)


@pytest.mark.parametrize("formation_id", [None, 0, -1])
def test_rejects_invalid_formation_id(formation_id):
    with pytest.raises(ValueError, match="formation_id.*invalide"):
        build_france_travail_training_requirement(make_row(formation_id))


def test_rejects_empty_title():
    with pytest.raises(ValueError, match="intitule.*vide"):
        build_france_travail_training_requirements([make_row(1, intitule="   ")])


def test_rejects_requirement_without_offer():
    with pytest.raises(ValueError, match="aucune offre"):
        build_france_travail_training_requirements([make_row(1, offre_ids=())])


@pytest.mark.parametrize("offre_id", [None, 0, -1])
def test_rejects_invalid_offer_id(offre_id):
    with pytest.raises(ValueError, match="offre_id.*invalide"):
        build_france_travail_training_requirements(
            [make_row(1, offre_ids=(offre_id,))]
        )


def test_deduplicates_and_sorts_offer_ids():
    requirements = build_france_travail_training_requirements(
        [make_row(1, offre_ids=(30, 10, 30, 20))]
    )

    assert requirements[0].offre_ids == (10, 20, 30)


def test_sorts_requirements_deterministically_without_merging_equal_titles():
    requirements = build_france_travail_training_requirements(
        [make_row(2), make_row(1)]
    )

    assert [requirement.formation_id for requirement in requirements] == [1, 2]


def test_preserves_source_code_without_rncp_interpretation():
    requirements = build_france_travail_training_requirements(
        [make_row(1, code_source=" DOMAINE-ABC ")]
    )

    assert requirements[0].code_source == "DOMAINE-ABC"


def test_strips_only_outer_whitespace_from_text_fields():
    requirements = build_france_travail_training_requirements(
        [
            make_row(
                1,
                intitule="  Développement  DATA  ",
                code_source="  CODE source  ",
                niveau="  Bac + 3  ",
                commentaire="  Souhaitée  ",
            )
        ]
    )

    requirement = requirements[0]
    assert requirement.intitule == "Développement  DATA"
    assert requirement.code_source == "CODE source"
    assert requirement.niveau == "Bac + 3"
    assert requirement.commentaire == "Souhaitée"


def test_accepts_missing_source_code_level_and_comment():
    requirements = build_france_travail_training_requirements(
        [make_row(1, code_source=" ", niveau=None, commentaire="")]
    )

    requirement = requirements[0]
    assert requirement.code_source is None
    assert requirement.niveau is None
    assert requirement.commentaire is None


def test_builds_deterministic_index_by_offer():
    requirements = build_france_travail_training_requirements(
        [make_row(2, offre_ids=(20,)), make_row(1, offre_ids=(10, 20))]
    )

    index = index_training_requirements_by_offer(requirements)

    assert list(index) == [10, 20]
    assert [item.formation_id for item in index[10]] == [1]
    assert [item.formation_id for item in index[20]] == [1, 2]


def test_supports_multiple_requirements_for_one_offer():
    requirements = build_france_travail_training_requirements(
        [make_row(1, offre_ids=(10,)), make_row(2, offre_ids=(10,))]
    )

    assert len(index_training_requirements_by_offer(requirements)[10]) == 2


def test_supports_one_requirement_linked_to_multiple_offers():
    requirements = build_france_travail_training_requirements(
        [make_row(1, offre_ids=(10, 20, 30))]
    )

    assert list(index_training_requirements_by_offer(requirements)) == [10, 20, 30]


def test_rejects_empty_requirements_catalogue():
    with pytest.raises(ValueError, match="Aucun catalogue d'exigences"):
        build_france_travail_training_requirements([])


def test_rejects_duplicate_formation_ids():
    with pytest.raises(ValueError, match="formation_id.*plusieurs fois"):
        build_france_travail_training_requirements([make_row(1), make_row(1)])


def test_diagnostic_rejects_empty_requirements():
    with pytest.raises(ValueError, match="au moins une exigence"):
        calculate_training_requirements_diagnostic(())


def test_calculates_training_requirements_diagnostic():
    requirements = build_france_travail_training_requirements(
        [
            make_row(1, offre_ids=(10, 20), commentaire="Commentaire"),
            make_row(
                2,
                offre_ids=(20,),
                code_source=None,
                niveau=None,
                commentaire=None,
            ),
        ]
    )

    diagnostic = calculate_training_requirements_diagnostic(requirements)

    assert diagnostic.nombre_lignes_exigence == 2
    assert diagnostic.nombre_associations_offre_exigence == 3
    assert diagnostic.nombre_offres_distinctes == 2
    assert diagnostic.nombre_exigences_avec_code_source == 1
    assert diagnostic.nombre_exigences_avec_niveau == 1
    assert diagnostic.nombre_exigences_avec_commentaire == 1
    assert diagnostic.exigences_par_offre_min == 1
    assert diagnostic.exigences_par_offre_moyen == 1.5
    assert diagnostic.exigences_par_offre_max == 2
    assert diagnostic.offres_par_exigence_min == 1
    assert diagnostic.offres_par_exigence_moyen == 1.5
    assert diagnostic.offres_par_exigence_max == 2
