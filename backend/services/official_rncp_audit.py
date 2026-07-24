"""Audit temporaire du catalogue RNCP officiel publié par France compétences."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests


DATASET_METADATA_URL = (
    "https://www.data.gouv.fr/api/1/datasets/"
    "repertoire-national-des-certifications-professionnelles-et-repertoire-specifique/"
)
ALLOWED_SOURCE_HOSTS = {
    "data.gouv.fr",
    "www.data.gouv.fr",
    "static.data.gouv.fr",
    "francecompetences.fr",
    "www.francecompetences.fr",
}
RESOURCE_TITLE_PATTERN = re.compile(
    r"^export-fiches-rncp-v(?P<major>\d+)-(?P<minor>\d+)-"
    r"(?P<date>\d{4}-\d{2}-\d{2})\.zip$",
    re.IGNORECASE,
)
RNCP_CODE_PATTERN = re.compile(r"^(?:RNCP)?(?P<number>[1-9]\d*)$")
DEFAULT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class OfficialRncpResource:
    """Décrit une archive XML RNCP officielle découverte via data.gouv.fr."""

    dataset_id: str
    resource_id: str
    title: str
    url: str
    schema_version: str
    publication_date: date
    last_modified: str | None


@dataclass(frozen=True)
class OfficialRncpCompetencyBlock:
    """Représente un bloc de compétences utile au diagnostic."""

    code: str | None
    libelle: str | None
    competences: str | None


@dataclass(frozen=True)
class OfficialRncpCertification:
    """Représente temporairement les champs audités d'une fiche RNCP officielle."""

    numero_fiche: str
    intitule_officiel: str | None
    etat_fiche: str | None
    actif: bool | None
    niveau_code: str | None
    niveau_libelle: str | None
    activites_visees: str | None
    competences_attestees: str | None
    secteurs_activite: str | None
    types_emplois_accessibles: str | None
    codes_rome: tuple[str, ...]
    prerequis_entree: str | None
    blocs_competences: tuple[OfficialRncpCompetencyBlock, ...]
    date_fin_enregistrement: str | None
    anciennes_certifications: tuple[str, ...]
    nouvelles_certifications: tuple[str, ...]


@dataclass(frozen=True)
class OfficialRncpParseResult:
    """Contient le résultat déterministe du parsing XML ciblé."""

    version_flux: str
    xml_member_name: str
    certifications: tuple[OfficialRncpCertification, ...]
    codes_ambigus: tuple[str, ...]


@dataclass(frozen=True)
class OfficialRncpFieldCoverage:
    """Décrit le remplissage d'un champ parmi les fiches trouvées."""

    nombre_renseigne: int
    nombre_total: int
    taux_pourcent: float


@dataclass(frozen=True)
class OfficialRncpAuditReport:
    """Regroupe les indicateurs agrégés de couverture du catalogue local."""

    resource: OfficialRncpResource
    version_flux: str
    nombre_codes_locaux: int
    codes_trouves: tuple[str, ...]
    codes_absents: tuple[str, ...]
    codes_ambigus: tuple[str, ...]
    codes_fiches_inactives: tuple[str, ...]
    fiches_actives: int
    fiches_inactives: int
    fiches_etat_inconnu: int
    fiches_avec_remplacement: int
    remplissage_champs: dict[str, OfficialRncpFieldCoverage]
    blocs_par_certification_min: int
    blocs_par_certification_moyen: float
    blocs_par_certification_max: int


def _clean_optional_text(value: str | None) -> str | None:
    """Supprime les espaces extérieurs et convertit le vide en valeur nulle."""
    if value is None:
        return None
    cleaned_value = value.strip()
    return cleaned_value or None


def _validate_allowed_url(url: str) -> None:
    """Refuse toute URL extérieure aux domaines autorisés pour ce lot."""
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in ALLOWED_SOURCE_HOSTS:
        raise ValueError(f"URL de source officielle non autorisée : {url}")


def fetch_official_dataset_metadata() -> dict[str, Any]:
    """Charge les métadonnées officielles du jeu RNCP/RS depuis data.gouv.fr."""
    _validate_allowed_url(DATASET_METADATA_URL)
    try:
        response = requests.get(DATASET_METADATA_URL, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()
        _validate_allowed_url(response.url)
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(
            "Impossible de charger les métadonnées officielles RNCP."
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError("Les métadonnées RNCP doivent être un objet JSON.")
    organization = payload.get("organization")
    organization_name = organization.get("name") if isinstance(organization, dict) else None
    if _clean_optional_text(organization_name) != "France compétences":
        raise ValueError("Le producteur du jeu RNCP n'est pas France compétences.")
    if not isinstance(payload.get("resources"), list):
        raise ValueError("La liste des ressources officielles RNCP est absente.")
    return payload


def discover_current_rncp_resource(
    metadata: Mapping[str, Any],
) -> OfficialRncpResource:
    """Sélectionne l'archive XML RNCP courante sans accepter RS ni CSV."""
    dataset_id = _clean_optional_text(str(metadata.get("id") or ""))
    resources = metadata.get("resources")
    if dataset_id is None or not isinstance(resources, list):
        raise ValueError("Métadonnées du jeu RNCP incomplètes.")

    candidates: list[tuple[tuple[int, int], date, OfficialRncpResource]] = []
    for resource_data in resources:
        if not isinstance(resource_data, Mapping):
            continue
        title = _clean_optional_text(str(resource_data.get("title") or ""))
        if title is None:
            continue
        title_match = RESOURCE_TITLE_PATTERN.fullmatch(title)
        if title_match is None:
            continue
        if str(resource_data.get("format") or "").strip().casefold() != "zip":
            continue

        resource_id = _clean_optional_text(str(resource_data.get("id") or ""))
        resource_url = _clean_optional_text(str(resource_data.get("url") or ""))
        if resource_id is None or resource_url is None:
            continue
        _validate_allowed_url(resource_url)

        major = int(title_match.group("major"))
        minor = int(title_match.group("minor"))
        publication_date = date.fromisoformat(title_match.group("date"))
        resource = OfficialRncpResource(
            dataset_id=dataset_id,
            resource_id=resource_id,
            title=title,
            url=resource_url,
            schema_version=f"{major}.{minor}",
            publication_date=publication_date,
            last_modified=_clean_optional_text(
                str(resource_data.get("last_modified") or "")
            ),
        )
        candidates.append(((major, minor), publication_date, resource))

    if not candidates:
        raise ValueError("Aucune archive XML RNCP officielle n'a été trouvée.")
    return max(candidates, key=lambda item: (item[0], item[1], item[2].resource_id))[2]


def normalize_rncp_code(value: str) -> str:
    """Normalise uniquement la différence contrôlée entre nombre et préfixe RNCP."""
    if not isinstance(value, str):
        raise ValueError(f"Code RNCP invalide : {value!r}.")
    cleaned_value = value.strip()
    match = RNCP_CODE_PATTERN.fullmatch(cleaned_value)
    if match is None:
        raise ValueError(f"Code RNCP invalide : {value!r}.")
    return f"RNCP{match.group('number')}"


def _find_rncp_xml_member(archive_path: Path) -> zipfile.ZipInfo:
    """Retourne l'unique fichier XML RNCP d'une archive ZIP valide."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            xml_members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and Path(member.filename).suffix.casefold() == ".xml"
            ]
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Archive RNCP illisible : {archive_path}") from exc

    if len(xml_members) != 1:
        raise ValueError("L'archive RNCP doit contenir un unique fichier XML.")
    member = xml_members[0]
    normalized_name = member.filename.casefold().replace("-", "_")
    if "rncp" not in normalized_name or re.search(r"(?:^|_)rs(?:_|\.)", normalized_name):
        raise ValueError("L'archive fournie n'est pas une archive XML RNCP.")
    if member.file_size <= 0:
        raise ValueError("Le fichier XML RNCP de l'archive est vide.")
    return member


def validate_rncp_archive(archive_path: Path) -> str:
    """Vérifie que l'archive est lisible et contient une racine XML RNCP attendue."""
    member = _find_rncp_xml_member(archive_path)
    try:
        with zipfile.ZipFile(archive_path) as archive, archive.open(member) as xml_stream:
            _, root = next(ET.iterparse(xml_stream, events=("start",)))
    except (OSError, StopIteration, ET.ParseError, zipfile.BadZipFile) as exc:
        raise ValueError("Le contenu XML RNCP est illisible.") from exc
    if root.tag != "FICHES":
        raise ValueError(f"Racine XML RNCP inattendue : {root.tag!r}.")
    return member.filename


def download_official_rncp_archive(
    resource: OfficialRncpResource,
    destination_directory: Path,
) -> Path:
    """Télécharge l'archive RNCP dans un répertoire temporaire puis la valide."""
    _validate_allowed_url(resource.url)
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / Path(resource.title).name
    partial_destination = destination.with_suffix(destination.suffix + ".part")
    if destination.exists() or partial_destination.exists():
        raise FileExistsError(f"Le fichier temporaire existe déjà : {destination}")

    try:
        response = requests.get(
            resource.url,
            stream=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        _validate_allowed_url(response.url)
        with partial_destination.open("wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output_file.write(chunk)
        partial_destination.replace(destination)
        validate_rncp_archive(destination)
    except (requests.RequestException, OSError, ValueError) as exc:
        if partial_destination.exists():
            partial_destination.unlink()
        if destination.exists():
            destination.unlink()
        if isinstance(exc, ValueError):
            raise
        raise RuntimeError("Impossible de télécharger l'archive RNCP officielle.") from exc
    return destination


def _find_text(element: ET.Element, path: str) -> str | None:
    """Retourne le texte nettoyé d'un élément XML optionnel."""
    return _clean_optional_text(element.findtext(path))


def _find_sorted_texts(element: ET.Element, path: str) -> tuple[str, ...]:
    """Retourne les textes XML non vides, dédupliqués et triés."""
    values = {
        cleaned_value
        for node in element.findall(path)
        if (cleaned_value := _clean_optional_text(node.text)) is not None
    }
    return tuple(sorted(values))


def _parse_active_status(value: str | None, numero_fiche: str) -> bool | None:
    """Convertit le statut officiel Oui/Non en booléen sans approximation."""
    cleaned_value = _clean_optional_text(value)
    if cleaned_value is None:
        return None
    if cleaned_value == "Oui":
        return True
    if cleaned_value == "Non":
        return False
    raise ValueError(
        f"Statut ACTIF inattendu pour la fiche {numero_fiche} : {cleaned_value!r}."
    )


def _parse_competency_blocks(
    fiche: ET.Element,
) -> tuple[OfficialRncpCompetencyBlock, ...]:
    """Extrait et trie les blocs de compétences d'une fiche RNCP."""
    blocks = [
        OfficialRncpCompetencyBlock(
            code=_find_text(block, "CODE"),
            libelle=_find_text(block, "LIBELLE"),
            competences=_find_text(block, "LISTE_COMPETENCES"),
        )
        for block in fiche.findall("./BLOCS_COMPETENCES/BLOC_COMPETENCES")
    ]
    return tuple(sorted(blocks, key=lambda block: (block.code or "", block.libelle or "")))


def _parse_certification(fiche: ET.Element) -> OfficialRncpCertification:
    """Transforme une fiche XML RNCP en représentation temporaire d'audit."""
    raw_code = _find_text(fiche, "NUMERO_FICHE")
    if raw_code is None:
        raise ValueError("Une fiche officielle RNCP ne possède pas de NUMERO_FICHE.")
    numero_fiche = normalize_rncp_code(raw_code)
    return OfficialRncpCertification(
        numero_fiche=numero_fiche,
        intitule_officiel=_find_text(fiche, "INTITULE"),
        etat_fiche=_find_text(fiche, "ETAT_FICHE"),
        actif=_parse_active_status(_find_text(fiche, "ACTIF"), numero_fiche),
        niveau_code=_find_text(fiche, "./NOMENCLATURE_EUROPE/NIVEAU"),
        niveau_libelle=_find_text(fiche, "./NOMENCLATURE_EUROPE/LIBELLE"),
        activites_visees=_find_text(fiche, "ACTIVITES_VISEES"),
        competences_attestees=_find_text(fiche, "CAPACITES_ATTESTEES"),
        secteurs_activite=_find_text(fiche, "SECTEURS_ACTIVITE"),
        types_emplois_accessibles=_find_text(fiche, "TYPE_EMPLOI_ACCESSIBLES"),
        codes_rome=_find_sorted_texts(fiche, "./CODES_ROME/ROME/CODE"),
        prerequis_entree=_find_text(fiche, "PREREQUIS_ENTREE_FORMATION"),
        blocs_competences=_parse_competency_blocks(fiche),
        date_fin_enregistrement=_find_text(fiche, "DATE_FIN_ENREGISTREMENT"),
        anciennes_certifications=_find_sorted_texts(
            fiche,
            "./ANCIENNES_CERTIFICATIONS/ANCIENNE_CERTIFICATION/"
            "ID_FICHE_ANCIENNE_CERTIFICATION",
        ),
        nouvelles_certifications=_find_sorted_texts(
            fiche,
            "./NOUVELLES_CERTIFICATIONS/NOUVELLE_CERTIFICATION/"
            "ID_FICHE_NOUVELLE_CERTIFICATION",
        ),
    )


def parse_official_rncp_archive(
    archive_path: Path,
    local_codes: Iterable[str],
    expected_schema_version: str,
) -> OfficialRncpParseResult:
    """Parcourt le XML officiel et conserve uniquement les codes RNCP locaux."""
    target_codes = {normalize_rncp_code(code) for code in local_codes}
    if not target_codes:
        raise ValueError("Aucun code RNCP local n'a été fourni.")
    member_name = validate_rncp_archive(archive_path)
    records_by_code: dict[str, OfficialRncpCertification] = {}
    ambiguous_codes: set[str] = set()
    version_flux: str | None = None
    fiche_count = 0

    try:
        with zipfile.ZipFile(archive_path) as archive, archive.open(member_name) as stream:
            context = ET.iterparse(stream, events=("start", "end"))
            _, root = next(context)
            for event, element in context:
                if event != "end":
                    continue
                if element.tag == "VERSION_FLUX":
                    version_flux = _clean_optional_text(element.text)
                elif element.tag == "FICHE":
                    fiche_count += 1
                    raw_code = _find_text(element, "NUMERO_FICHE")
                    if raw_code is None:
                        raise ValueError(
                            "Une fiche officielle RNCP ne possède pas de NUMERO_FICHE."
                        )
                    official_code = normalize_rncp_code(raw_code)
                    if official_code in target_codes:
                        certification = _parse_certification(element)
                        if official_code in records_by_code:
                            ambiguous_codes.add(official_code)
                            records_by_code.pop(official_code, None)
                        elif official_code not in ambiguous_codes:
                            records_by_code[official_code] = certification
                    element.clear()
                    root.clear()
    except (OSError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise ValueError("Le contenu XML RNCP est invalide.") from exc

    if fiche_count == 0:
        raise ValueError("L'archive officielle RNCP ne contient aucune fiche.")
    if version_flux is None:
        raise ValueError("La version du flux XML RNCP est absente.")
    if version_flux != expected_schema_version:
        raise ValueError(
            f"Version XML RNCP inattendue : {version_flux}, "
            f"version attendue : {expected_schema_version}."
        )
    return OfficialRncpParseResult(
        version_flux=version_flux,
        xml_member_name=member_name,
        certifications=tuple(
            records_by_code[code] for code in sorted(records_by_code)
        ),
        codes_ambigus=tuple(sorted(ambiguous_codes)),
    )


def _has_level(certification: OfficialRncpCertification) -> bool:
    """Indique si une fiche possède un code ou un libellé de niveau."""
    return certification.niveau_code is not None or certification.niveau_libelle is not None


def calculate_official_rncp_audit(
    local_codes: Iterable[str],
    parse_result: OfficialRncpParseResult,
    resource: OfficialRncpResource,
) -> OfficialRncpAuditReport:
    """Calcule la couverture et le remplissage des fiches RNCP locales."""
    normalized_local_codes = tuple(sorted({normalize_rncp_code(code) for code in local_codes}))
    if not normalized_local_codes:
        raise ValueError("Aucun code RNCP local n'a été fourni.")

    certifications = parse_result.certifications
    found_codes = tuple(certification.numero_fiche for certification in certifications)
    ambiguous_codes = tuple(
        code for code in parse_result.codes_ambigus if code in normalized_local_codes
    )
    missing_codes = tuple(
        code
        for code in normalized_local_codes
        if code not in found_codes and code not in ambiguous_codes
    )
    field_checks = {
        "numero_fiche": lambda item: item.numero_fiche is not None,
        "intitule_officiel": lambda item: item.intitule_officiel is not None,
        "etat_actif_inactif": lambda item: item.actif is not None,
        "niveau": _has_level,
        "activites_visees": lambda item: item.activites_visees is not None,
        "competences_attestees": lambda item: item.competences_attestees is not None,
        "secteurs_activite": lambda item: item.secteurs_activite is not None,
        "types_emplois_accessibles": lambda item: item.types_emplois_accessibles is not None,
        "codes_rome": lambda item: bool(item.codes_rome),
        "prerequis_entree": lambda item: item.prerequis_entree is not None,
        "blocs_competences": lambda item: bool(item.blocs_competences),
        "date_fin_enregistrement": lambda item: item.date_fin_enregistrement is not None,
        "ancienne_ou_nouvelle_certification": lambda item: bool(
            item.anciennes_certifications or item.nouvelles_certifications
        ),
    }
    total_found = len(certifications)
    coverage = {}
    for field_name, field_check in field_checks.items():
        filled_count = sum(field_check(certification) for certification in certifications)
        coverage[field_name] = OfficialRncpFieldCoverage(
            nombre_renseigne=filled_count,
            nombre_total=total_found,
            taux_pourcent=(filled_count / total_found * 100.0) if total_found else 0.0,
        )

    block_counts = [len(certification.blocs_competences) for certification in certifications]
    return OfficialRncpAuditReport(
        resource=resource,
        version_flux=parse_result.version_flux,
        nombre_codes_locaux=len(normalized_local_codes),
        codes_trouves=found_codes,
        codes_absents=missing_codes,
        codes_ambigus=ambiguous_codes,
        codes_fiches_inactives=tuple(
            certification.numero_fiche
            for certification in certifications
            if certification.actif is False
        ),
        fiches_actives=sum(certification.actif is True for certification in certifications),
        fiches_inactives=sum(certification.actif is False for certification in certifications),
        fiches_etat_inconnu=sum(certification.actif is None for certification in certifications),
        fiches_avec_remplacement=sum(
            bool(certification.nouvelles_certifications)
            for certification in certifications
        ),
        remplissage_champs=coverage,
        blocs_par_certification_min=min(block_counts) if block_counts else 0,
        blocs_par_certification_moyen=fmean(block_counts) if block_counts else 0.0,
        blocs_par_certification_max=max(block_counts) if block_counts else 0,
    )
