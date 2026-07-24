"""Construction hors base du catalogue RNCP local enrichi par la source officielle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.official_rncp_audit import (
    OfficialRncpAuditReport,
    OfficialRncpCertification,
    OfficialRncpParseResult,
    OfficialRncpResource,
    normalize_rncp_code,
)
from services.official_rncp_successors import (
    OfficialRncpSuccessionAnalysis,
    OfficialRncpSuccessorAuditReport,
    OfficialRncpSuccessorNode,
)
from services.rncp_catalogue import RncpCatalogue, RncpCertification


@dataclass(frozen=True)
class LocalRncpOrganization:
    """Représente les informations locales disponibles pour un organisme."""

    siret_of_contractant: str
    raison_sociale_of_contractant: str | None
    modalite: str | None
    nom_entreprise: str | None
    code_postal: str | None
    region: str | None

    def to_dict(self) -> dict[str, Any]:
        """Retourne une représentation JSON stable de l'organisme."""
        return {
            "siret_of_contractant": self.siret_of_contractant,
            "raison_sociale_of_contractant": self.raison_sociale_of_contractant,
            "modalite": self.modalite,
            "nom_entreprise": self.nom_entreprise,
            "code_postal": self.code_postal,
            "region": self.region,
        }


@dataclass(frozen=True)
class LocalRncpOrganizationAssociation:
    """Associe un organisme local à une certification RNCP locale."""

    code_rncp: str
    organization: LocalRncpOrganization


@dataclass(frozen=True)
class EnrichedRncpCatalogueCounters:
    """Regroupe les compteurs validés du catalogue RNCP enrichi."""

    nombre_lignes_locales: int
    nombre_certifications: int
    nombre_organismes_distincts: int
    nombre_associations_organismes: int
    nombre_certifications_actives: int
    nombre_certifications_inactives: int
    nombre_statuts_inconnus: int
    nombre_analyses_succession: int

    def to_dict(self) -> dict[str, int]:
        """Retourne les compteurs sous une forme directement sérialisable."""
        return {
            "nombre_lignes_locales": self.nombre_lignes_locales,
            "nombre_certifications": self.nombre_certifications,
            "nombre_organismes_distincts": self.nombre_organismes_distincts,
            "nombre_associations_organismes": self.nombre_associations_organismes,
            "nombre_certifications_actives": self.nombre_certifications_actives,
            "nombre_certifications_inactives": self.nombre_certifications_inactives,
            "nombre_statuts_inconnus": self.nombre_statuts_inconnus,
            "nombre_analyses_succession": self.nombre_analyses_succession,
        }


@dataclass(frozen=True)
class EnrichedRncpCertification:
    """Réunit les vues locale, officielle et de succession d'une certification."""

    local_certification: RncpCertification
    organizations: tuple[LocalRncpOrganization, ...]
    official_certification: OfficialRncpCertification
    succession: OfficialRncpSuccessionAnalysis | None

    def to_dict(self) -> dict[str, Any]:
        """Sépare explicitement les données locales et officielles dans le JSON."""
        payload: dict[str, Any] = {
            "donnees_locales": {
                "code_rncp": self.local_certification.code_rncp,
                "intitule_certification": (
                    self.local_certification.intitule_certification
                ),
                "niveau_rncp": self.local_certification.niveau_rncp,
                "nombre_organismes": len(self.organizations),
                "organismes": [
                    organization.to_dict() for organization in self.organizations
                ],
            },
            "donnees_officielles": _official_certification_to_dict(
                self.official_certification
            ),
        }
        if self.succession is not None:
            payload["succession"] = _succession_to_dict(self.succession)
        return payload


@dataclass(frozen=True)
class EnrichedRncpCatalogue:
    """Contient le catalogue enrichi, sa ressource et ses compteurs."""

    resource: OfficialRncpResource
    xml_version: str
    certifications: tuple[EnrichedRncpCertification, ...]
    counters: EnrichedRncpCatalogueCounters

    def to_dict(self) -> dict[str, Any]:
        """Retourne la structure complète et déterministe de l'export JSON."""
        return {
            "metadata": {
                "format_version": "1.0",
                "ressource_officielle": {
                    "dataset_id": self.resource.dataset_id,
                    "resource_id": self.resource.resource_id,
                    "title": self.resource.title,
                    "url": self.resource.url,
                    "schema_version": self.resource.schema_version,
                    "version_flux_xml": self.xml_version,
                    "publication_date": self.resource.publication_date.isoformat(),
                    "last_modified": self.resource.last_modified,
                },
                "compteurs": self.counters.to_dict(),
            },
            "certifications": [
                certification.to_dict() for certification in self.certifications
            ],
        }


def _official_certification_to_dict(
    certification: OfficialRncpCertification,
) -> dict[str, Any]:
    """Transforme les champs officiels sans perdre les valeurs optionnelles."""
    return {
        "numero_fiche": certification.numero_fiche,
        "intitule_officiel": certification.intitule_officiel,
        "actif": certification.actif,
        "niveau": {
            "code": certification.niveau_code,
            "libelle": certification.niveau_libelle,
        },
        "codes_rome": list(certification.codes_rome),
        "activites_visees": certification.activites_visees,
        "competences_attestees": certification.competences_attestees,
        "metiers_accessibles": certification.types_emplois_accessibles,
        "secteurs_activite": certification.secteurs_activite,
        "blocs_competences": [
            {
                "code": block.code,
                "libelle": block.libelle,
                "competences": block.competences,
            }
            for block in certification.blocs_competences
        ],
        "prerequis": certification.prerequis_entree,
        "date_fin_enregistrement": certification.date_fin_enregistrement,
        "anciennes_certifications": list(certification.anciennes_certifications),
        "nouvelles_certifications": list(certification.nouvelles_certifications),
    }


def _successor_node_to_dict(node: OfficialRncpSuccessorNode) -> dict[str, Any]:
    """Transforme un successeur terminal en données JSON consultables."""
    return {
        "code_rncp": node.code_rncp,
        "intitule_officiel": node.intitule_officiel,
        "actif": node.actif,
        "niveau": {
            "code": node.niveau_code,
            "libelle": node.niveau_libelle,
        },
        "codes_rome": list(node.codes_rome),
        "date_fin_enregistrement": node.date_fin_enregistrement,
        "present_dans_catalogue_local": node.present_dans_catalogue_local,
    }


def _succession_to_dict(
    analysis: OfficialRncpSuccessionAnalysis,
) -> dict[str, Any]:
    """Transforme une analyse de succession sans appliquer de remplacement."""
    origin_code = analysis.origine.code_rncp
    successor_presence = [
        {
            "code_rncp": node.code_rncp,
            "present_dans_catalogue_local": node.present_dans_catalogue_local,
        }
        for node in analysis.fiches_rencontrees
        if node.code_rncp != origin_code
    ]
    return {
        "classification": analysis.classification.value,
        "successeurs_directs": list(analysis.successeurs_directs),
        "chemins_succession": [
            list(path) for path in analysis.chemins_succession
        ],
        "successeurs_actifs_terminaux": [
            _successor_node_to_dict(node)
            for node in analysis.successeurs_actifs_terminaux
        ],
        "presence_successeurs_dans_catalogue_local": successor_presence,
        "references_absentes": list(analysis.references_absentes),
        "references_ambigues": list(analysis.references_ambigues),
        "cycles": [list(cycle) for cycle in analysis.cycles],
    }


def _organization_sort_key(
    organization: LocalRncpOrganization,
) -> tuple[str, str, str, str, str, str]:
    """Retourne la clé de tri stable d'un organisme local."""
    return (
        organization.siret_of_contractant,
        organization.raison_sociale_of_contractant or "",
        organization.modalite or "",
        organization.nom_entreprise or "",
        organization.code_postal or "",
        organization.region or "",
    )


def _group_local_organizations(
    catalogue: RncpCatalogue,
    associations: Iterable[LocalRncpOrganizationAssociation],
    local_certifications: dict[str, RncpCertification],
) -> dict[str, tuple[LocalRncpOrganization, ...]]:
    """Groupe les organismes et vérifie qu'aucune association n'est perdue."""
    association_list = tuple(associations)
    if len(association_list) != catalogue.nombre_lignes_catalogue:
        raise ValueError(
            "Le nombre d'associations d'organismes diffère des lignes locales : "
            f"{len(association_list)} au lieu de {catalogue.nombre_lignes_catalogue}."
        )

    grouped: dict[str, dict[str, LocalRncpOrganization]] = {
        code: {} for code in local_certifications
    }
    for association in association_list:
        normalized_code = normalize_rncp_code(association.code_rncp)
        if normalized_code not in local_certifications:
            raise ValueError(
                "Association d'organisme rattachée à un code RNCP non local : "
                f"{normalized_code}."
            )
        cleaned_siret = association.organization.siret_of_contractant.strip()
        if not cleaned_siret:
            raise ValueError(
                f"SIRET vide pour la certification locale {normalized_code}."
            )
        organization = LocalRncpOrganization(
            siret_of_contractant=cleaned_siret,
            raison_sociale_of_contractant=(
                association.organization.raison_sociale_of_contractant
            ),
            modalite=association.organization.modalite,
            nom_entreprise=association.organization.nom_entreprise,
            code_postal=association.organization.code_postal,
            region=association.organization.region,
        )
        if cleaned_siret in grouped[normalized_code]:
            raise ValueError(
                "Organisme local présent plusieurs fois pour la certification "
                f"{normalized_code} : {cleaned_siret}."
            )
        grouped[normalized_code][cleaned_siret] = organization

    organizations_by_code = {
        code: tuple(sorted(organizations.values(), key=_organization_sort_key))
        for code, organizations in grouped.items()
    }
    for code, local_certification in local_certifications.items():
        actual_count = len(organizations_by_code[code])
        if actual_count != local_certification.nombre_organismes:
            raise ValueError(
                f"Organisme local perdu pour {code} : {actual_count} au lieu de "
                f"{local_certification.nombre_organismes}."
            )
    distinct_sirets = {
        organization.siret_of_contractant
        for organizations in organizations_by_code.values()
        for organization in organizations
    }
    if len(distinct_sirets) != catalogue.nombre_organismes_distincts:
        raise ValueError(
            "Le nombre d'organismes distincts a changé pendant l'enrichissement : "
            f"{len(distinct_sirets)} au lieu de "
            f"{catalogue.nombre_organismes_distincts}."
        )
    return organizations_by_code


def _index_local_certifications(
    catalogue: RncpCatalogue,
) -> dict[str, RncpCertification]:
    """Indexe les certifications locales et refuse les codes dupliqués."""
    indexed: dict[str, RncpCertification] = {}
    duplicate_codes: set[str] = set()
    for certification in catalogue.certifications:
        normalized_code = normalize_rncp_code(certification.code_rncp)
        if normalized_code in indexed:
            duplicate_codes.add(normalized_code)
        else:
            indexed[normalized_code] = certification
    if duplicate_codes:
        raise ValueError(
            "Certifications locales présentes plusieurs fois : "
            f"{', '.join(sorted(duplicate_codes))}."
        )
    return indexed


def _index_official_certifications(
    local_codes: set[str],
    parse_result: OfficialRncpParseResult,
    audit_report: OfficialRncpAuditReport,
) -> dict[str, OfficialRncpCertification]:
    """Indexe les fiches officielles et refuse les codes locaux absents ou ambigus."""
    ambiguous_codes = tuple(
        sorted(local_codes & set(audit_report.codes_ambigus))
    )
    if ambiguous_codes:
        raise ValueError(
            "Codes RNCP locaux ambigus dans l'archive officielle : "
            f"{', '.join(ambiguous_codes)}."
        )
    missing_codes = tuple(sorted(local_codes & set(audit_report.codes_absents)))
    if missing_codes:
        raise ValueError(
            "Codes RNCP locaux absents de l'archive officielle : "
            f"{', '.join(missing_codes)}."
        )
    official_by_code = {
        certification.numero_fiche: certification
        for certification in parse_result.certifications
        if certification.numero_fiche in local_codes
    }
    unresolved_codes = tuple(sorted(local_codes - official_by_code.keys()))
    if unresolved_codes:
        raise ValueError(
            "Fiches officielles locales non résolues : "
            f"{', '.join(unresolved_codes)}."
        )
    return official_by_code


def _index_successions(
    local_codes: set[str],
    official_by_code: dict[str, OfficialRncpCertification],
    succession_report: OfficialRncpSuccessorAuditReport,
) -> dict[str, OfficialRncpSuccessionAnalysis]:
    """Indexe les analyses disponibles sans accepter une origine externe ou active."""
    indexed: dict[str, OfficialRncpSuccessionAnalysis] = {}
    for analysis in succession_report.analyses:
        code = normalize_rncp_code(analysis.origine.code_rncp)
        if code not in local_codes:
            raise ValueError(
                f"Analyse de succession rattachée à un code non local : {code}."
            )
        if code in indexed:
            raise ValueError(
                f"Analyse de succession présente plusieurs fois pour {code}."
            )
        if official_by_code[code].actif is not False:
            raise ValueError(
                f"Analyse de succession fournie pour la fiche non inactive {code}."
            )
        indexed[code] = analysis

    inactive_local_codes = {
        code
        for code, certification in official_by_code.items()
        if certification.actif is False
    }
    missing_analysis_codes = tuple(sorted(inactive_local_codes - set(indexed)))
    if missing_analysis_codes:
        raise ValueError(
            "Analyses de succession manquantes pour les certifications locales "
            f"inactives : {', '.join(missing_analysis_codes)}."
        )
    return indexed


def build_enriched_rncp_catalogue(
    catalogue: RncpCatalogue,
    organization_associations: Iterable[LocalRncpOrganizationAssociation],
    official_parse_result: OfficialRncpParseResult,
    official_audit_report: OfficialRncpAuditReport,
    succession_report: OfficialRncpSuccessorAuditReport,
) -> EnrichedRncpCatalogue:
    """Construit et valide le catalogue enrichi limité aux certifications locales."""
    local_by_code = _index_local_certifications(catalogue)
    if not local_by_code:
        raise ValueError("Le catalogue RNCP local est vide.")
    local_codes = set(local_by_code)
    organizations_by_code = _group_local_organizations(
        catalogue,
        organization_associations,
        local_by_code,
    )
    official_by_code = _index_official_certifications(
        local_codes,
        official_parse_result,
        official_audit_report,
    )
    successions_by_code = _index_successions(
        local_codes,
        official_by_code,
        succession_report,
    )
    certifications = tuple(
        EnrichedRncpCertification(
            local_certification=local_by_code[code],
            organizations=organizations_by_code[code],
            official_certification=official_by_code[code],
            succession=successions_by_code.get(code),
        )
        for code in sorted(local_codes)
    )
    final_codes = tuple(
        normalize_rncp_code(certification.local_certification.code_rncp)
        for certification in certifications
    )
    if len(certifications) != len(catalogue.certifications):
        raise ValueError(
            "Le nombre de certifications enrichies diffère du catalogue local."
        )
    if len(final_codes) != len(set(final_codes)):
        raise ValueError(
            "Une certification locale apparaît plusieurs fois dans le résultat final."
        )
    if set(final_codes) != local_codes:
        raise ValueError(
            "Le catalogue enrichi contient un code externe ou a perdu un code local."
        )

    counters = EnrichedRncpCatalogueCounters(
        nombre_lignes_locales=catalogue.nombre_lignes_catalogue,
        nombre_certifications=len(certifications),
        nombre_organismes_distincts=catalogue.nombre_organismes_distincts,
        nombre_associations_organismes=sum(
            len(certification.organizations) for certification in certifications
        ),
        nombre_certifications_actives=sum(
            certification.official_certification.actif is True
            for certification in certifications
        ),
        nombre_certifications_inactives=sum(
            certification.official_certification.actif is False
            for certification in certifications
        ),
        nombre_statuts_inconnus=sum(
            certification.official_certification.actif is None
            for certification in certifications
        ),
        nombre_analyses_succession=len(successions_by_code),
    )
    return EnrichedRncpCatalogue(
        resource=official_audit_report.resource,
        xml_version=official_audit_report.version_flux,
        certifications=certifications,
        counters=counters,
    )
