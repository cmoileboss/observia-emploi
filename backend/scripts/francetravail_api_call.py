"""Appels à l'API France Travail et import des offres en base."""

from pathlib import Path

import os
import logging

import pandas as pd
import requests
from dotenv import load_dotenv

from enums.niveau_rncp_enum import NiveauRNCP
from logging_config import configure_logging
from models.correspondance_formation_model import FormationModel
from models.francetravail_model import CompetenceModel, OffreModel
from postgres_connection import Base, engine
from postgres_connection import SESSION_LOCAL
from repositories.correspondance_formation_repository import RomeCodeRepository
from repositories.francetravail_repository import (
    CompetenceRepository,
    OffreFormationRepository,
    OffreRepository,
)

current_file = Path(__file__).resolve()
current_dir = current_file.parent


def resolve_csv_path() -> Path:
    """Retourne le chemin du CSV enrichi selon l'environnement d'exécution."""
    file_path = Path("backend/data/processed/formations_enriched.csv")
    abs_path = file_path.resolve()
    return abs_path


CSV_PATH = resolve_csv_path()


def normalize_niveau_rncp(niveau_libelle: str | None) -> str | None:
    """Mappe un libellé RNCP brut vers le nom normalisé de l'énumération."""

    if not niveau_libelle:
        return None

    cleaned = niveau_libelle.strip()

    for niveau in NiveauRNCP:
        if niveau.value == cleaned:
            return niveau.name

    return None

logger = logging.getLogger(__name__)

BASE_URL = "https://api.francetravail.io/partenaire/offresdemploi"
ACCESS_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
GET_OFFERS_URL = f"{BASE_URL}/v2/offres/search"

DEPARTEMENTS = [
    "01", "02", "03", "04", "05", "06", "07", "08", "09",
    "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "2A", "2B",
    "21", "22", "23", "24", "25", "26", "27", "28", "29",
    "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
    "40", "41", "42", "43", "44", "45", "46", "47", "48", "49",
    "50", "51", "52", "53", "54", "55", "56", "57", "58", "59",
    "60", "61", "62", "63", "64", "65", "66", "67", "68", "69",
    "70", "71", "72", "73", "74", "75", "76", "77", "78", "79",
    "80", "81", "82", "83", "84", "85", "86", "87", "88", "89",
    "90", "91", "92", "93", "94", "95",
    "971", "972", "973", "974", "976",
]

def get_access_token() -> str:
    """Obtient un token d'accès OAuth2 pour l'API France Travail.
    Nécessite les variables d'environnement CLIENT_ID et SECRET_ID.
    Returns:
        str: Le token d'accès à utiliser dans les requêtes API."""
    response = requests.post(
        ACCESS_TOKEN_URL,
        params={"realm": "/partenaire"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("CLIENT_ID"),
            "client_secret": os.getenv("SECRET_ID"),
            "scope": "api_offresdemploiv2 o2dsoffre",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]

def search_offres_by_rome(code_rome: str) -> None:
    """Recherche les offres d'emploi associées à un code ROME.

    Si le nombre total d'offres dépasse 3000, la recherche bascule
    sur un filtrage par département avant l'import en base.
    """
    token = get_access_token()
    min_range = 0
    max_range = 149
    while True:
        try:
            response = requests.get(
                GET_OFFERS_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "codeROME": code_rome,
                    "range": f"{min_range}-{max_range}",
                },
                timeout=30,
            )
        except requests.RequestException as e:
            logger.error(
                "Erreur lors de la requête pour le code ROME %s : %s",
                code_rome,
                e,
            )
            return

        if response.status_code == 204:
            logger.info("Aucune offre (204 No Content) pour le code ROME %s.", code_rome)
            break

        content_range = response.headers.get("Content-Range")
        if content_range and content_range.split("/")[1] == "0":
            logger.info("Aucune offre trouvée pour le code ROME %s.", code_rome)
            return
        if content_range:
            total_count = int(content_range.split("/")[1])
            if total_count >= 3000:
                logger.warning(
                    "Le nombre total d'offres pour le code ROME %s est de %s, "
                    "ce qui dépasse la limite de 3000. Bascule sur un filtrage par département.",
                    code_rome,
                    total_count,
                )
                get_offres_by_rome_and_departement(code_rome)
                return
        if not response.content:
            logger.warning(
                "Réponse vide (status %s) pour le code ROME %s.",
                response.status_code,
                code_rome,
            )
            return
        if response.status_code not in (200, 206):
            logger.warning(
                "Status inattendu %s pour le code ROME %s.",
                response.status_code,
                code_rome,
            )
            return
        current_offers = response.json()
        if len(current_offers["resultats"]) < 150:
            if len(current_offers["resultats"]) == 0:
                return
            logger.info(
                "Récupération des offres pour le code ROME %s : %s",
                code_rome,
                content_range,
            )
            populate_database_with_offres(current_offers["resultats"])
            return
        populate_database_with_offres(current_offers["resultats"])
        logger.info(
            "Recherche des offres pour le code ROME : %s, range : %s",
            code_rome,
            content_range,
        )
        min_range += 150
        max_range += 150


def get_offres_by_rome_and_departement(code_rome: str) -> None:
    """Recherche des offres d'emploi par code ROME et département.
    Injection des offres dans la BDD.
    Args:
        code_rome (str): Le code ROME pour lequel rechercher les offres.
    """
    token = get_access_token()
    for departement in DEPARTEMENTS:
        min_range = 0
        max_range = 149
        while True:
            try:
                response = requests.get(
                    GET_OFFERS_URL,
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "codeROME": code_rome,
                        "departement": departement,
                        "range": f"{min_range}-{max_range}",
                    },
                    timeout=30,
                )
                response.raise_for_status()
            except requests.RequestException as e:
                logger.error(
                    "Erreur lors de la requête pour le code ROME %s et le departement %s : %s",
                    code_rome,
                    departement,
                    e,
                )
                break

            if response.status_code == 204:
                logger.info("Aucune offre (204 No Content) pour le code ROME %s et le département %s.", code_rome, departement)
                break

            content_range = response.headers.get("Content-Range")
            if content_range and content_range.split("/")[1] == "0":
                logger.info(
                    "Aucune offre trouvée pour le code ROME %s et le département %s.",
                    code_rome,
                    departement,
                )
                break
            current_offers = response.json()
            if len(current_offers["resultats"]) < 150:
                if len(current_offers["resultats"]) == 0:
                    break
                logger.info(
                    "Récupération des offres pour le code ROME %s et le département %s : %s",
                    code_rome,
                    departement,
                    content_range,
                )
                populate_database_with_offres(current_offers["resultats"])
                break
            populate_database_with_offres(current_offers["resultats"])
            logger.info(
                "Récupération des offres pour le code ROME %s et le département %s : %s",
                code_rome,
                departement,
                content_range,
            )
            min_range += 150
            max_range += 150


def populate_database_with_offres(offres: list[dict]) -> None:
    """Injection des offres dans la BDD.
    Args:
        offres (list): Liste des offres à injecter.
    """
    db = SESSION_LOCAL()
    offre_repository = OffreRepository(db)
    rome_repository = RomeCodeRepository(db)
    formation_repository = OffreFormationRepository(db)
    competence_repository = CompetenceRepository(db)
    for offre in offres:
        rome_code = offre.get("romeCode")
        rome = None
        if rome_code:
            rome = rome_repository.get_or_create(rome_code, offre.get("romeLibelle"))

        offre_model = OffreModel(
            francetravail_id=offre["id"],
            intitule=offre["intitule"],
            description=(
                offre.get("description").strip()
                if offre.get("description")
                else None
            ),
            lieu_code_postal=offre.get("lieuTravail", {}).get("codePostal"),
            rome_code=rome_code,
            rome_libelle=offre.get("romeLibelle"),
            appellation_libelle=(
                offre.get("appellationlibelle").strip()
                if offre.get("appellationlibelle")
                else None
            ),
            entreprise_nom=(
                offre.get("entreprise", {}).get("nom").strip()
                if offre.get("entreprise", {}).get("nom")
                else None
            ),
        )
        saved_offre = offre_repository.create_offre(offre_model)
        if rome is not None and saved_offre.rome is None:
            saved_offre.rome = rome

        for formation_data in offre.get("formations", []):
            code_formation = formation_data.get("codeFormation")
            if code_formation is None:
                continue
            formation = formation_repository.find_by_code(code_formation)
            if formation is None:
                formation = FormationModel(
                    code_rncp=code_formation,
                    intitule_certification=(
                        formation_data.get("domaineLibelle").strip()
                        if formation_data.get("domaineLibelle")
                        else None
                    ),
                    niveau_rncp=normalize_niveau_rncp(formation_data.get("niveauLibelle")),
                    commentaire=(
                        formation_data.get("commentaire").strip()
                        if formation_data.get("commentaire")
                        else None
                    ),
                )
                db.add(formation)
                db.flush()
            offre_repository.attach_formation(saved_offre, formation, commit=False)

        for competence_data in offre.get("competences", []):
            competence_code = competence_data.get("code")
            if competence_code is None:
                continue
            competence = competence_repository.find_by_code(competence_code)
            if competence is None:
                competence = CompetenceModel(
                    code=competence_code,
                    libelle=(
                        competence_data.get("libelle").strip()
                        if competence_data.get("libelle")
                        else None
                    ),
                )
                db.add(competence)
                db.flush()
            offre_repository.attach_competence(saved_offre, competence, commit=False)

    db.commit()
    db.close()

def get_unique_rome_codes_from_csv_file():
    """Lit le fichier CSV des formations enrichies et retourne la liste des codes ROME uniques.
    Returns:
        list: Liste des codes ROME uniques présents dans le fichier CSV."""
    df = pd.read_csv(CSV_PATH, sep=";")
    return df["code_rome"].unique().tolist()

if __name__ == "__main__":
    configure_logging()
    load_dotenv()
    Base.metadata.create_all(bind=engine)
    rome_codes = get_unique_rome_codes_from_csv_file()
    logger.info("Nombre de codes ROME uniques : %s", len(rome_codes))
    for code in rome_codes:
        search_offres_by_rome(code)
    logger.info("Récupération des offres France Travail terminée.")
