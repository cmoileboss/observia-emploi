import os
import sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv
import pandas as pd
from logging_config import configure_logging

from models.francetravail_model import FTOffreModel, FTFormationModel, FTCompetenceModel, FTOffreCompetenceModel
from repositories.francetravail_repository import FTOffreRepository
from repositories.correspondance_formation_repository import RomeCodeRepository
from postgres_connection import SessionLocal, Base, engine

logger = logging.getLogger(__name__)

base_url = "https://api.francetravail.io/partenaire/offresdemploi"
access_token_url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
get_offers_url = f"{base_url}/v2/offres/search"

departements = [
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
    Nécessite les variables d'environnement CLIENT_ID et SECRET_KEY.
    Returns:
        str: Le token d'accès à utiliser dans les requêtes API."""
    response = requests.post(
        access_token_url,
        params={"realm": "/partenaire"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("CLIENT_ID"),
            "client_secret": os.getenv("SECRET_KEY"),
            "scope": "api_offresdemploiv2 o2dsoffre",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]

def search_offres_by_rome(code_rome: str):
    """Recherche des offres d'emploi par code ROME.
    Si le nombre total d'offres dépasse 3000, bascule sur une recherche par code ROME et département.
    Injection des offres dans la BDD.
    Args:
        code_rome (str): Le code ROME pour lequel rechercher les offres."""
    token = get_access_token()
    min_range = 0
    max_range = 149
    while True:
        try:
            response = requests.get(
                get_offers_url,
                headers={
                    "Authorization": f"Bearer {token}"},
                params={
                "codeROME": code_rome,
                "range": f"{min_range}-{max_range}",
            },
            timeout=30,
        )
        except requests.RequestException as e:
            logger.error("Erreur lors de la requête pour le code ROME %s : %s", code_rome, e)
            break

        content_range = response.headers.get("Content-Range")
        if content_range and content_range.split("/")[1] == "0":
            logger.info("Aucune offre trouvee pour le code ROME %s.", code_rome)
            break
        if content_range:
            total_count = int(content_range.split("/")[1])
            if total_count >= 3000:
                logger.warning(
                    "Le nombre total d'offres pour le code ROME %s est de %s, "
                    "ce qui dépasse la limite de 3000. Bascule sur un filtrage par département.",
                    code_rome,
                    total_count,
                )
                return get_offres_by_rome_and_departement(code_rome)
        current_offers = response.json()
        if len(current_offers["resultats"]) < 150:
            if len(current_offers["resultats"]) == 0:
                break
            logger.info("Récupération des offres pour le code ROME %s : %s", code_rome, content_range)
            populate_database_with_offres(current_offers["resultats"])
            break
        populate_database_with_offres(current_offers["resultats"])
        logger.info("Recherche des offres pour le code ROME : %s, range : %s", code_rome, content_range)
        min_range += 150
        max_range += 150

        
def get_offres_by_rome_and_departement(code_rome: str):
    """Recherche des offres d'emploi par code ROME et département.
    Injection des offres dans la BDD.
    Args:
        code_rome (str): Le code ROME pour lequel rechercher les offres.
    """
    token = get_access_token()
    for departement in departements:
        min_range = 0
        max_range = 149
        while True:
            try:
                response = requests.get(
                    get_offers_url,
                    headers={
                        "Authorization": f"Bearer {token}"},
                    params={
                        "codeROME": code_rome,
                        "departement": departement,
                        "range": f"{min_range}-{max_range}",
                    },
                    timeout=30,
                )
            except requests.RequestException as e:
                logger.error("Erreur lors de la requête pour le code ROME %s et le departement %s : %s", code_rome, departement, e)
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
                    content_range
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


def populate_database_with_offres(offres):
    """Injection des offres dans la BDD.
    Args:
        offres (list): Liste des offres à injecter.
    """
    db = SessionLocal()
    repository = FTOffreRepository(db)
    rome_repository = RomeCodeRepository(db)
    for offre in offres:
        rome_code = offre.get("romeCode")
        rome = None
        if rome_code:
            rome = rome_repository.get_or_create(rome_code, offre.get("romeLibelle"))

        offre_model = FTOffreModel(
            id=offre["id"],
            intitule=offre["intitule"],
            description=offre.get("description"),
            lieu_code_postal=offre.get("lieuTravail", {}).get("codePostal"),
            rome_code=rome_code,
            rome_libelle=offre.get("romeLibelle"),
            appellation_libelle=offre.get("appellationlibelle"),
            entreprise_nom=offre.get("entreprise", {}).get("nom"),
        )
        if rome is not None:
            offre_model.rome = rome
        for formation in offre.get("formations", []):
            formation_model = FTFormationModel(
                code_formation=formation.get("codeFormation"),
                domaine_libelle=formation.get("domaineLibelle"),
                niveau_libelle=formation.get("niveauLibelle"),
                commentaire=formation.get("commentaire"),
                exigence=formation.get("exigence"),
            )
            offre_model.formations.append(formation_model)
        for competence in offre.get("competences", []):
            competence_model = FTCompetenceModel(
                code=competence.get("code"),
                libelle=competence.get("libelle"),
            )
            offre_model.offre_competences.append(FTOffreCompetenceModel(
                competence=competence_model,
                exigence=competence.get("exigence"),
            ))
        repository.create_offre(offre_model)
    db.commit()
    db.close()

def get_unique_rome_codes_from_csv_file():
    """Lit le fichier CSV des formations enrichies et retourne la liste des codes ROME uniques.
    Returns:
        list: Liste des codes ROME uniques présents dans le fichier CSV."""
    df = pd.read_csv("data/processed/formations_enriched.csv", sep=";")
    return df["code_rome"].unique().tolist()

if __name__ == "__main__":
    configure_logging()
    load_dotenv()
    Base.metadata.create_all(bind=engine)
    rome_codes = get_unique_rome_codes_from_csv_file()
    logger.info("Nombre de codes ROME uniques : %s", len(rome_codes))
    max_workers = min(8, len(rome_codes)) if rome_codes else 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(search_offres_by_rome, rome_code): rome_code
            for rome_code in rome_codes
        }

        for future in as_completed(futures):
            rome_code = futures[future]
            try:
                future.result()
            except Exception:
                logger.exception("Erreur lors du traitement du code ROME %s", rome_code)
    logger.info("Récupération des offres France Travail terminée.")