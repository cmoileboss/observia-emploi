"""Tests unitaires du catalogue RNCP enrichi hors PostgreSQL."""

from datetime import date

import pytest

from backend.services.enriched_rncp_catalogue import (
    LocalRncpOrganization,
    LocalRncpOrganizationAssociation,
    build_enriched_rncp_catalogue,
)
from backend.services.official_rncp_audit import (
    OfficialRncpCertification,
    OfficialRncpCompetencyBlock,
    OfficialRncpParseResult,
    OfficialRncpResource,
    calculate_official_rncp_audit,
)
from backend.services.official_rncp_successors import (
    OfficialRncpSuccessionAnalysis,
    OfficialRncpSuccessorAuditReport,
    OfficialRncpSuccessorNode,
    RncpSuccessorClassification,
)
from backend.services.rncp_catalogue import (
    RncpCatalogue,
    RncpCatalogueSourceRow,
    RncpCertification,
    build_rncp_catalogue,
)


def make_resource() -> OfficialRncpResource:
    return OfficialRncpResource(
        dataset_id="dataset-1",
        resource_id="resource-1",
        title="export-fiches-rncp-v4-1-2026-07-22.zip",
        url="https://static.data.gouv.fr/rncp.zip",
        schema_version="4.1",
        publication_date=date(2026, 7, 22),
        last_modified="2026-07-22T02:00:00+00:00",
    )


def make_local_catalogue(
    rows: tuple[tuple[int, str, str, str, str], ...],
) -> RncpCatalogue:
    return build_rncp_catalogue(
        RncpCatalogueSourceRow(
            formation_id=formation_id,
            code_rncp=code,
            intitule_certification=title,
            niveau_rncp=level,
            siret_of_contractant=siret,
            codes_rome=("M1801",),
            has_monthly_flow=True,
        )
        for formation_id, code, title, level, siret in rows
    )


def make_organization(
    code: str,
    siret: str,
    *,
    name: str | None = "Organisme local",
    region: str | None = "Occitanie",
) -> LocalRncpOrganizationAssociation:
    return LocalRncpOrganizationAssociation(
        code_rncp=code,
        organization=LocalRncpOrganization(
            siret_of_contractant=siret,
            raison_sociale_of_contractant=name,
            modalite="Présentiel",
            nom_entreprise="Site local",
            code_postal="31000",
            region=region,
        ),
    )


def make_official_certification(
    code: str,
    *,
    active: bool | None = True,
    optional_fields: bool = True,
    successors: tuple[str, ...] = (),
) -> OfficialRncpCertification:
    return OfficialRncpCertification(
        numero_fiche=code,
        intitule_officiel=f"Titre officiel {code}" if optional_fields else None,
        etat_fiche="Publiée" if optional_fields else None,
        actif=active,
        niveau_code="NIV6" if optional_fields else None,
        niveau_libelle="Niveau 6" if optional_fields else None,
        activites_visees="Activités" if optional_fields else None,
        competences_attestees="Compétences" if optional_fields else None,
        secteurs_activite="Numérique" if optional_fields else None,
        types_emplois_accessibles="Développeur" if optional_fields else None,
        codes_rome=("M1801",) if optional_fields else (),
        prerequis_entree="Baccalauréat" if optional_fields else None,
        blocs_competences=(
            OfficialRncpCompetencyBlock(
                code=f"{code}BC01",
                libelle="Bloc 1",
                competences="Compétence du bloc",
            ),
        )
        if optional_fields
        else (),
        date_fin_enregistrement="31/12/2030" if optional_fields else None,
        anciennes_certifications=("RNCP99",) if optional_fields else (),
        nouvelles_certifications=successors,
    )


def make_node(
    certification: OfficialRncpCertification,
    *,
    present_locally: bool,
) -> OfficialRncpSuccessorNode:
    return OfficialRncpSuccessorNode(
        code_rncp=certification.numero_fiche,
        intitule_officiel=certification.intitule_officiel,
        actif=certification.actif,
        niveau_code=certification.niveau_code,
        niveau_libelle=certification.niveau_libelle,
        codes_rome=certification.codes_rome,
        date_fin_enregistrement=certification.date_fin_enregistrement,
        present_dans_catalogue_local=present_locally,
    )


def make_succession_report(
    *analyses: OfficialRncpSuccessionAnalysis,
) -> OfficialRncpSuccessorAuditReport:
    return OfficialRncpSuccessorAuditReport(
        analyses=tuple(analyses),
        totaux_par_classification={
            classification: sum(
                analysis.classification is classification
                for analysis in analyses
            )
            for classification in RncpSuccessorClassification
        },
    )


def enrich(
    catalogue: RncpCatalogue,
    organizations: tuple[LocalRncpOrganizationAssociation, ...],
    official_certifications: tuple[OfficialRncpCertification, ...],
    succession_report: OfficialRncpSuccessorAuditReport | None = None,
    ambiguous_codes: tuple[str, ...] = (),
):
    parse_result = OfficialRncpParseResult(
        version_flux="4.1",
        xml_member_name="rncp.xml",
        certifications=official_certifications,
        codes_ambigus=ambiguous_codes,
    )
    local_codes = tuple(
        certification.code_rncp for certification in catalogue.certifications
    )
    audit_report = calculate_official_rncp_audit(
        local_codes,
        parse_result,
        make_resource(),
    )
    return build_enriched_rncp_catalogue(
        catalogue,
        organizations,
        parse_result,
        audit_report,
        succession_report or make_succession_report(),
    )


def test_enriches_active_certification_with_separate_local_and_official_data():
    catalogue = make_local_catalogue(
        ((1, "RNCP100", "Titre local", "6", "11111111111111"),)
    )
    enriched = enrich(
        catalogue,
        (make_organization("RNCP100", "11111111111111"),),
        (make_official_certification("RNCP100"),),
    )

    payload = enriched.certifications[0].to_dict()
    assert payload["donnees_locales"]["intitule_certification"] == "Titre local"
    assert payload["donnees_officielles"]["intitule_officiel"] == (
        "Titre officiel RNCP100"
    )
    assert payload["donnees_officielles"]["actif"] is True
    assert "succession" not in payload


def test_preserves_and_sorts_all_local_organization_information():
    catalogue = make_local_catalogue(
        (
            (1, "RNCP100", "Titre local", "6", "22222222222222"),
            (2, "RNCP100", "Titre local", "6", "11111111111111"),
        )
    )
    enriched = enrich(
        catalogue,
        (
            make_organization("RNCP100", "22222222222222", name="Organisme B"),
            make_organization("RNCP100", "11111111111111", name="Organisme A"),
        ),
        (make_official_certification("RNCP100"),),
    )

    organizations = enriched.certifications[0].to_dict()["donnees_locales"][
        "organismes"
    ]
    assert [item["siret_of_contractant"] for item in organizations] == [
        "11111111111111",
        "22222222222222",
    ]
    assert organizations[0] == {
        "siret_of_contractant": "11111111111111",
        "raison_sociale_of_contractant": "Organisme A",
        "modalite": "Présentiel",
        "nom_entreprise": "Site local",
        "code_postal": "31000",
        "region": "Occitanie",
    }


def test_enriches_inactive_certification_with_active_successor():
    catalogue = make_local_catalogue(
        ((1, "RNCP100", "Titre local", "6", "11111111111111"),)
    )
    origin = make_official_certification(
        "RNCP100",
        active=False,
        successors=("RNCP200",),
    )
    successor = make_official_certification("RNCP200", active=True)
    origin_node = make_node(origin, present_locally=True)
    successor_node = make_node(successor, present_locally=False)
    analysis = OfficialRncpSuccessionAnalysis(
        origine=origin_node,
        classification=RncpSuccessorClassification.SUCCESSEUR_ACTIF_UNIQUE,
        successeurs_directs=("RNCP200",),
        chemins_succession=(("RNCP100", "RNCP200"),),
        fiches_rencontrees=(origin_node, successor_node),
        successeurs_actifs_terminaux=(successor_node,),
        references_absentes=(),
        references_ambigues=(),
        cycles=(),
    )

    enriched = enrich(
        catalogue,
        (make_organization("RNCP100", "11111111111111"),),
        (origin,),
        make_succession_report(analysis),
    )

    succession = enriched.certifications[0].to_dict()["succession"]
    assert succession["classification"] == "SUCCESSEUR_ACTIF_UNIQUE"
    assert succession["successeurs_directs"] == ["RNCP200"]
    assert succession["successeurs_actifs_terminaux"][0]["code_rncp"] == (
        "RNCP200"
    )
    assert succession["presence_successeurs_dans_catalogue_local"] == [
        {"code_rncp": "RNCP200", "present_dans_catalogue_local": False}
    ]


def test_enriches_inactive_certification_without_replacement():
    catalogue = make_local_catalogue(
        ((1, "RNCP100", "Titre local", "6", "11111111111111"),)
    )
    origin = make_official_certification("RNCP100", active=False, successors=())
    origin_node = make_node(origin, present_locally=True)
    analysis = OfficialRncpSuccessionAnalysis(
        origine=origin_node,
        classification=RncpSuccessorClassification.HISTORIQUE_SANS_REMPLACEMENT,
        successeurs_directs=(),
        chemins_succession=(("RNCP100",),),
        fiches_rencontrees=(origin_node,),
        successeurs_actifs_terminaux=(),
        references_absentes=(),
        references_ambigues=(),
        cycles=(),
    )

    enriched = enrich(
        catalogue,
        (make_organization("RNCP100", "11111111111111"),),
        (origin,),
        make_succession_report(analysis),
    )

    succession = enriched.certifications[0].to_dict()["succession"]
    assert succession["classification"] == "HISTORIQUE_SANS_REMPLACEMENT"
    assert succession["successeurs_actifs_terminaux"] == []


def test_rejects_missing_succession_analysis_for_inactive_local_certification():
    catalogue = make_local_catalogue(
        (
            (1, "RNCP100", "Titre local 1", "6", "11111111111111"),
            (2, "RNCP200", "Titre local 2", "6", "22222222222222"),
        )
    )
    analyzed_origin = make_official_certification("RNCP100", active=False)
    missing_origin = make_official_certification("RNCP200", active=False)
    origin_node = make_node(analyzed_origin, present_locally=True)
    analysis = OfficialRncpSuccessionAnalysis(
        origine=origin_node,
        classification=RncpSuccessorClassification.HISTORIQUE_SANS_REMPLACEMENT,
        successeurs_directs=(),
        chemins_succession=(("RNCP100",),),
        fiches_rencontrees=(origin_node,),
        successeurs_actifs_terminaux=(),
        references_absentes=(),
        references_ambigues=(),
        cycles=(),
    )

    with pytest.raises(ValueError, match="manquantes.*RNCP200"):
        enrich(
            catalogue,
            (
                make_organization("RNCP100", "11111111111111"),
                make_organization("RNCP200", "22222222222222"),
            ),
            (analyzed_origin, missing_origin),
            make_succession_report(analysis),
        )


def test_keeps_absent_optional_official_fields_as_null_or_empty():
    catalogue = make_local_catalogue(
        ((1, "RNCP100", "Titre local", "6", "11111111111111"),)
    )
    enriched = enrich(
        catalogue,
        (make_organization("RNCP100", "11111111111111"),),
        (make_official_certification("RNCP100", optional_fields=False),),
    )

    official = enriched.certifications[0].to_dict()["donnees_officielles"]
    assert official["intitule_officiel"] is None
    assert official["niveau"] == {"code": None, "libelle": None}
    assert official["codes_rome"] == []
    assert official["blocs_competences"] == []
    assert official["prerequis"] is None


def test_rejects_local_code_absent_from_official_archive():
    catalogue = make_local_catalogue(
        ((1, "RNCP100", "Titre local", "6", "11111111111111"),)
    )

    with pytest.raises(ValueError, match="absents.*RNCP100"):
        enrich(
            catalogue,
            (make_organization("RNCP100", "11111111111111"),),
            (),
        )


def test_rejects_ambiguous_local_official_code():
    catalogue = make_local_catalogue(
        ((1, "RNCP100", "Titre local", "6", "11111111111111"),)
    )

    with pytest.raises(ValueError, match="ambigus.*RNCP100"):
        enrich(
            catalogue,
            (make_organization("RNCP100", "11111111111111"),),
            (),
            ambiguous_codes=("RNCP100",),
        )


def test_does_not_add_external_successor_to_main_catalogue():
    catalogue = make_local_catalogue(
        ((1, "RNCP100", "Titre local", "6", "11111111111111"),)
    )
    origin = make_official_certification(
        "RNCP100",
        active=False,
        successors=("RNCP999",),
    )
    origin_node = make_node(origin, present_locally=True)
    external = make_node(
        make_official_certification("RNCP999"),
        present_locally=False,
    )
    analysis = OfficialRncpSuccessionAnalysis(
        origine=origin_node,
        classification=RncpSuccessorClassification.SUCCESSEUR_ACTIF_UNIQUE,
        successeurs_directs=("RNCP999",),
        chemins_succession=(("RNCP100", "RNCP999"),),
        fiches_rencontrees=(origin_node, external),
        successeurs_actifs_terminaux=(external,),
        references_absentes=(),
        references_ambigues=(),
        cycles=(),
    )

    enriched = enrich(
        catalogue,
        (make_organization("RNCP100", "11111111111111"),),
        (origin,),
        make_succession_report(analysis),
    )

    assert enriched.counters.nombre_certifications == 1
    assert [
        item["donnees_locales"]["code_rncp"]
        for item in enriched.to_dict()["certifications"]
    ] == ["RNCP100"]


def test_rejects_lost_local_organization():
    catalogue = make_local_catalogue(
        (
            (1, "RNCP100", "Titre local", "6", "11111111111111"),
            (2, "RNCP100", "Titre local", "6", "22222222222222"),
        )
    )

    with pytest.raises(ValueError, match="associations d'organismes"):
        enrich(
            catalogue,
            (make_organization("RNCP100", "11111111111111"),),
            (make_official_certification("RNCP100"),),
        )


def test_rejects_duplicate_local_certification():
    certification = RncpCertification(
        code_rncp="RNCP100",
        intitule_certification="Titre local",
        niveau_rncp="6",
        codes_rome=("M1801",),
        nombre_organismes=1,
        formation_ids=(1,),
    )
    catalogue = RncpCatalogue(
        certifications=(certification, certification),
        nombre_lignes_catalogue=1,
        nombre_organismes_distincts=1,
        nombre_codes_rome_distincts=1,
    )

    with pytest.raises(ValueError, match="Certifications locales.*plusieurs fois"):
        enrich(
            catalogue,
            (make_organization("RNCP100", "11111111111111"),),
            (make_official_certification("RNCP100"),),
        )


def test_sorts_certifications_deterministically():
    catalogue = make_local_catalogue(
        (
            (2, "RNCP200", "Titre B", "6", "22222222222222"),
            (1, "RNCP100", "Titre A", "5", "11111111111111"),
        )
    )
    enriched = enrich(
        catalogue,
        (
            make_organization("RNCP200", "22222222222222"),
            make_organization("RNCP100", "11111111111111"),
        ),
        (
            make_official_certification("RNCP200"),
            make_official_certification("RNCP100"),
        ),
    )

    assert [
        item["donnees_locales"]["code_rncp"]
        for item in enriched.to_dict()["certifications"]
    ] == ["RNCP100", "RNCP200"]
