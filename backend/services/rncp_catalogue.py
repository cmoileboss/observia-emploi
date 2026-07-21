"""Construction métier du catalogue de certifications RNCP."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean
from typing import Any, Iterable


@dataclass(frozen=True)
class RncpCatalogueSourceRow:
    """Représente une ligne de formation nécessaire à la construction du catalogue."""

    formation_id: int
    code_rncp: str | None
    intitule_certification: str | None
    niveau_rncp: str | None
    siret_of_contractant: str | None
    codes_rome: tuple[str | None, ...]
    has_monthly_flow: bool


@dataclass(frozen=True)
class RncpCertification:
    """Représente une certification RNCP dédupliquée pour le benchmark."""

    code_rncp: str
    intitule_certification: str
    niveau_rncp: str | None
    codes_rome: tuple[str, ...]
    nombre_organismes: int
    formation_ids: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        """Retourne la représentation exportable identifiée par le code RNCP."""
        return {
            "code_rncp": self.code_rncp,
            "intitule_certification": self.intitule_certification,
            "niveau_rncp": self.niveau_rncp,
            "codes_rome": list(self.codes_rome),
            "nombre_organismes": self.nombre_organismes,
        }


@dataclass(frozen=True)
class RncpCatalogue:
    """Contient le catalogue RNCP et ses compteurs globaux non sensibles."""

    certifications: tuple[RncpCertification, ...]
    nombre_lignes_catalogue: int
    nombre_organismes_distincts: int
    nombre_codes_rome_distincts: int


@dataclass(frozen=True)
class RncpCatalogueDiagnostic:
    """Regroupe les indicateurs synthétiques du catalogue RNCP."""

    nombre_lignes_catalogue: int
    nombre_certifications_rncp: int
    nombre_organismes_distincts: int
    nombre_codes_rome_distincts: int
    organismes_par_certification_min: int
    organismes_par_certification_moyen: float
    organismes_par_certification_max: int
    codes_rome_par_certification_min: int
    codes_rome_par_certification_moyen: float
    codes_rome_par_certification_max: int


@dataclass
class _CertificationGroup:
    """Accumule les lignes partageant un même code RNCP."""

    intitule_certification: str
    niveau_rncp: str | None
    codes_rome: set[str] = field(default_factory=set)
    sirets: set[str] = field(default_factory=set)
    formation_ids: set[int] = field(default_factory=set)


def _clean_optional_text(value: str | None) -> str | None:
    """Supprime les espaces extérieurs et convertit le vide en valeur nulle."""

    if value is None:
        return None
    cleaned_value = value.strip()
    return cleaned_value or None


def _clean_rome_codes(values: tuple[str | None, ...]) -> set[str]:
    """Nettoie, déduplique et retourne les codes ROME non vides."""

    return {
        cleaned_code
        for value in values
        if (cleaned_code := _clean_optional_text(value)) is not None
    }


def _is_catalogue_row(row: RncpCatalogueSourceRow) -> bool:
    """Indique si une ligne contient les preuves d'appartenance au catalogue MCF."""

    return (
        _clean_optional_text(row.siret_of_contractant) is not None
        and row.has_monthly_flow
        and bool(_clean_rome_codes(row.codes_rome))
    )


def _required_text(value: str | None, field_name: str, formation_id: int) -> str:
    """Retourne un texte obligatoire nettoyé ou lève une erreur explicite."""

    cleaned_value = _clean_optional_text(value)
    if cleaned_value is None:
        raise ValueError(
            f"Champ obligatoire '{field_name}' vide pour la formation {formation_id}."
        )
    return cleaned_value


def build_rncp_catalogue(rows: Iterable[RncpCatalogueSourceRow]) -> RncpCatalogue:
    """Sélectionne et regroupe les lignes MCF en certifications RNCP distinctes."""
    groups: dict[str, _CertificationGroup] = {}
    selected_row_count = 0
    all_sirets: set[str] = set()
    all_rome_codes: set[str] = set()

    for row in rows:
        if not _is_catalogue_row(row):
            continue

        selected_row_count += 1
        code_rncp = _required_text(row.code_rncp, "code_rncp", row.formation_id)
        title = _required_text(
            row.intitule_certification,
            "intitule_certification",
            row.formation_id,
        )
        level = _clean_optional_text(row.niveau_rncp)
        siret = _required_text(
            row.siret_of_contractant,
            "siret_of_contractant",
            row.formation_id,
        )
        rome_codes = _clean_rome_codes(row.codes_rome)

        group = groups.get(code_rncp)
        if group is None:
            group = _CertificationGroup(
                intitule_certification=title,
                niveau_rncp=level,
            )
            groups[code_rncp] = group
        else:
            if group.intitule_certification != title:
                raise ValueError(
                    f"Intitulés incompatibles pour le code RNCP {code_rncp} : "
                    f"'{group.intitule_certification}' et '{title}'."
                )
            if (
                group.niveau_rncp is not None
                and level is not None
                and group.niveau_rncp != level
            ):
                raise ValueError(
                    f"Niveaux RNCP incompatibles pour le code {code_rncp} : "
                    f"'{group.niveau_rncp}' et '{level}'."
                )
            if group.niveau_rncp is None and level is not None:
                group.niveau_rncp = level

        group.codes_rome.update(rome_codes)
        group.sirets.add(siret)
        group.formation_ids.add(row.formation_id)
        all_sirets.add(siret)
        all_rome_codes.update(rome_codes)

    if not groups:
        raise ValueError("Aucun catalogue RNCP trouvé parmi les lignes fournies.")

    certifications = tuple(
        RncpCertification(
            code_rncp=code_rncp,
            intitule_certification=group.intitule_certification,
            niveau_rncp=group.niveau_rncp,
            codes_rome=tuple(sorted(group.codes_rome)),
            nombre_organismes=len(group.sirets),
            formation_ids=tuple(sorted(group.formation_ids)),
        )
        for code_rncp, group in sorted(groups.items())
    )
    return RncpCatalogue(
        certifications=certifications,
        nombre_lignes_catalogue=selected_row_count,
        nombre_organismes_distincts=len(all_sirets),
        nombre_codes_rome_distincts=len(all_rome_codes),
    )


def calculate_rncp_catalogue_diagnostic(
    catalogue: RncpCatalogue,
) -> RncpCatalogueDiagnostic:
    """Calcule les indicateurs synthétiques d'un catalogue RNCP non vide."""
    if not catalogue.certifications:
        raise ValueError("Le diagnostic requiert au moins une certification RNCP.")

    organization_counts = [
        certification.nombre_organismes for certification in catalogue.certifications
    ]
    rome_counts = [len(certification.codes_rome) for certification in catalogue.certifications]
    return RncpCatalogueDiagnostic(
        nombre_lignes_catalogue=catalogue.nombre_lignes_catalogue,
        nombre_certifications_rncp=len(catalogue.certifications),
        nombre_organismes_distincts=catalogue.nombre_organismes_distincts,
        nombre_codes_rome_distincts=catalogue.nombre_codes_rome_distincts,
        organismes_par_certification_min=min(organization_counts),
        organismes_par_certification_moyen=fmean(organization_counts),
        organismes_par_certification_max=max(organization_counts),
        codes_rome_par_certification_min=min(rome_counts),
        codes_rome_par_certification_moyen=fmean(rome_counts),
        codes_rome_par_certification_max=max(rome_counts),
    )
