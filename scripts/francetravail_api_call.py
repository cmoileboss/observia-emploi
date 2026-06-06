import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv
import pandas as pd
from logging_config import configure_logging

from models.francetravail_model import FTOffreModel, FTFormationModel, FTCompetenceModel, FTOffreCompetenceModel
from repositories.francetravail_repository import FTOffreRepository
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
    token = get_access_token()
    total_offers = []
    min_range = 0
    max_range = 149
    while True:
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
        if response.status_code >= 400:
            logger.error(
                "Erreur lors de la recuperation des offres pour le code ROME %s : %s - %s",
                code_rome,
                response.status_code,
                response.text,
            )
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
                    "ce qui depasse la limite de 3000. Bascule sur un filtrage par departement.",
                    code_rome,
                    total_count,
                )
                return get_offres_by_rome_and_departement(code_rome)
        current_offers = response.json()
        if len(current_offers["resultats"]) < 150:
            if len(current_offers["resultats"]) == 0:
                break
            populate_database_with_offres(current_offers["resultats"])
            break
        populate_database_with_offres(current_offers["resultats"])
        logger.info("Recherche des offres pour le code ROME : %s, range : %s", code_rome, content_range)
        min_range += 150
        max_range += 150

        
def get_offres_by_rome_and_departement(code_rome: str):
    token = get_access_token()
    total_offers = []
    for departement in departements:
        min_range = 0
        max_range = 149
        while True:
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
            if response.status_code >= 400:
                logger.error(
                    "Erreur lors de la recuperation des offres pour le code ROME %s et le departement %s : %s - %s",
                    code_rome,
                    departement,
                    response.status_code,
                    response.text,
                )
                break
            content_range = response.headers.get("Content-Range")
            if content_range and content_range.split("/")[1] == "0":
                logger.info(
                    "Aucune offre trouvee pour le code ROME %s et le departement %s.",
                    code_rome,
                    departement,
                )
                break
            current_offers = response.json()
            if len(current_offers["resultats"]) < 150:
                if len(current_offers["resultats"]) == 0:
                    break
                populate_database_with_offres(current_offers["resultats"])
                break
            populate_database_with_offres(current_offers["resultats"])
            logger.info(
                "Recuperation des offres pour le code ROME %s et le departement %s : %s",
                code_rome,
                departement,
                content_range,
            )
            min_range += 150
            max_range += 150
 

def populate_database_with_offres(offres):
    db = SessionLocal()
    repository = FTOffreRepository(db)
    for offre in offres:
        offre_model = FTOffreModel(
            id=offre["id"],
            intitule=offre["intitule"],
            description=offre.get("description"),
            lieu_code_postal=offre.get("lieuTravail", {}).get("codePostal"),
            rome_code=offre.get("romeCode"),
            rome_libelle=offre.get("romeLibelle"),
            appellation_libelle=offre.get("appellationlibelle"),
            entreprise_nom=offre.get("entreprise", {}).get("nom"),
        )
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
    df = pd.read_csv("data/processed/formations_enriched.csv", sep=";")
    return df["code_rome"].unique().tolist()

if __name__ == "__main__":
    configure_logging()
    load_dotenv()
    Base.metadata.create_all(bind=engine)
    rome_codes = get_unique_rome_codes_from_csv_file()
    logger.info("Nombre de codes ROME uniques : %s", len(rome_codes))
    total_offres = 0
    for rome_code in rome_codes:
        search_offres_by_rome(rome_code)
    logger.info("Recuperation des offres France Travail terminee.")