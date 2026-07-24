"""Tests unitaires de construction du catalogue RNCP."""

import pytest

from backend.services.rncp_catalogue import (
    RncpCatalogueSourceRow,
    build_rncp_catalogue,
    calculate_rncp_catalogue_diagnostic,
)


def make_row(
    formation_id: int,
    code_rncp: str | None = "RNCP100",
    title: str | None = "Administrateur systèmes",
    level: str | None = "6",
    siret: str | None = "11111111111111",
    rome_codes: tuple[str | None, ...] = ("M1801",),
    has_monthly_flow: bool = True,
) -> RncpCatalogueSourceRow:
    return RncpCatalogueSourceRow(
        formation_id=formation_id,
        code_rncp=code_rncp,
        intitule_certification=title,
        niveau_rncp=level,
        siret_of_contractant=siret,
        codes_rome=rome_codes,
        has_monthly_flow=has_monthly_flow,
    )


def test_groups_multiple_organizations_under_one_rncp_code():
    catalogue = build_rncp_catalogue(
        [
            make_row(2, siret="22222222222222"),
            make_row(1, siret="11111111111111"),
        ]
    )

    assert len(catalogue.certifications) == 1
    certification = catalogue.certifications[0]
    assert certification.nombre_organismes == 2
    assert certification.formation_ids == (1, 2)


def test_deduplicates_and_sorts_rome_codes():
    catalogue = build_rncp_catalogue(
        [
            make_row(1, rome_codes=("M1805", "M1801", "M1805")),
            make_row(2, rome_codes=("M1802", "M1801")),
        ]
    )

    assert catalogue.certifications[0].codes_rome == ("M1801", "M1802", "M1805")


def test_sorts_certifications_deterministically_by_rncp_code():
    catalogue = build_rncp_catalogue(
        [
            make_row(2, code_rncp="RNCP200", title="Titre B"),
            make_row(1, code_rncp="RNCP100", title="Titre A"),
        ]
    )

    assert [item.code_rncp for item in catalogue.certifications] == [
        "RNCP100",
        "RNCP200",
    ]


@pytest.mark.parametrize(
    "excluded_row",
    [
        make_row(2, siret=None),
        make_row(2, has_monthly_flow=False),
        make_row(2, rome_codes=()),
    ],
)
def test_excludes_france_travail_requirement_without_mcf_evidence(excluded_row):
    catalogue = build_rncp_catalogue(
        [
            make_row(1),
            excluded_row,
        ]
    )

    assert catalogue.nombre_lignes_catalogue == 1
    assert catalogue.certifications[0].formation_ids == (1,)


def test_rejects_empty_rncp_code_for_catalogue_row():
    with pytest.raises(ValueError, match="code_rncp.*vide"):
        build_rncp_catalogue([make_row(1, code_rncp="   ")])


def test_rejects_empty_certification_title():
    with pytest.raises(ValueError, match="intitule_certification.*vide"):
        build_rncp_catalogue([make_row(1, title=None)])


def test_rejects_incompatible_titles_for_same_rncp_code():
    with pytest.raises(ValueError, match="Intitulés incompatibles.*RNCP100"):
        build_rncp_catalogue(
            [
                make_row(1, title="Administrateur systèmes"),
                make_row(2, title="Développeur web"),
            ]
        )


def test_accepts_title_differences_limited_to_outer_whitespace():
    catalogue = build_rncp_catalogue(
        [
            make_row(1, title=" Administrateur systèmes"),
            make_row(2, title="Administrateur systèmes "),
        ]
    )

    assert catalogue.certifications[0].intitule_certification == "Administrateur systèmes"


def test_rejects_incompatible_levels_for_same_rncp_code():
    with pytest.raises(ValueError, match="Niveaux RNCP incompatibles.*RNCP100"):
        build_rncp_catalogue(
            [
                make_row(1, level="6"),
                make_row(2, level="7"),
            ]
        )


def test_counts_distinct_organizations_only_once():
    catalogue = build_rncp_catalogue(
        [
            make_row(1, siret="11111111111111"),
            make_row(2, siret="11111111111111"),
        ]
    )

    assert catalogue.certifications[0].nombre_organismes == 1
    assert catalogue.nombre_organismes_distincts == 1


def test_rejects_empty_catalogue():
    with pytest.raises(ValueError, match="Aucun catalogue RNCP"):
        build_rncp_catalogue([])


def test_calculates_catalogue_diagnostic():
    catalogue = build_rncp_catalogue(
        [
            make_row(1, code_rncp="RNCP100", title="Titre A", rome_codes=("M1",)),
            make_row(
                2,
                code_rncp="RNCP200",
                title="Titre B",
                siret="22222222222222",
                rome_codes=("M1", "M2", "M3"),
            ),
            make_row(
                3,
                code_rncp="RNCP200",
                title="Titre B",
                siret="33333333333333",
                rome_codes=("M2",),
            ),
        ]
    )

    diagnostic = calculate_rncp_catalogue_diagnostic(catalogue)

    assert diagnostic.nombre_lignes_catalogue == 3
    assert diagnostic.nombre_certifications_rncp == 2
    assert diagnostic.nombre_organismes_distincts == 3
    assert diagnostic.nombre_codes_rome_distincts == 3
    assert diagnostic.organismes_par_certification_min == 1
    assert diagnostic.organismes_par_certification_moyen == 1.5
    assert diagnostic.organismes_par_certification_max == 2
    assert diagnostic.codes_rome_par_certification_min == 1
    assert diagnostic.codes_rome_par_certification_moyen == 2.0
    assert diagnostic.codes_rome_par_certification_max == 3
