import os
import argparse
import logging

import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv
from logging_config import configure_logging

load_dotenv()
configure_logging()
logger = logging.getLogger(__name__)

from postgres_connection import Base, engine
from models import francetravail_model, correspondance_formation_model
from routers import francetravail_router

from scripts.formations_enricher import FormationsEnricher
from scripts.create_output import create_output
from scripts.sirene_enricher import enrich
from scripts.import_formations_enriched import import_formations_enriched
from scripts.francetravail_api_call import (
    get_unique_rome_codes_from_csv_file,
    search_offres_by_rome,
)


DATABASE_ENV_VARS = (
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
)

PIPELINE_ENV_VARS = DATABASE_ENV_VARS + (
    "RAW_DATA_FOLDER",
    "PROCESSED_DATA_FOLDER",
    "X-INSEE-Api-Key-Integration",
    "CLIENT_ID",
    "SECRET_KEY",
)


def validate_env_vars(*variable_names: str) -> None:
    missing_vars = [name for name in variable_names if not os.getenv(name)]
    if missing_vars:
        raise EnvironmentError(
            "Variables d'environnement non initialisées : " + ", ".join(missing_vars)
        )


def initialize_database() -> None:
    validate_env_vars(*DATABASE_ENV_VARS)
    logger.info("Initialisation de la base de données")
    Base.metadata.create_all(bind=engine)


def run_data_pipeline() -> None:
    """Lance les scripts métier dans l'ordre de production des données."""
    validate_env_vars(*PIPELINE_ENV_VARS)
    initialize_database()

    raw_folder = os.environ["RAW_DATA_FOLDER"]
    processed_folder = os.environ["PROCESSED_DATA_FOLDER"]

    merged_path = os.path.join(processed_folder, "merged_data.csv")
    organismes_path = os.path.join(processed_folder, "organismes_enriched.csv")
    cdc_path = os.path.join(raw_folder, "cdc_filtered_tech.csv")
    formations_path = os.path.join(processed_folder, "formations_enriched.csv")
    
    logger.info("Démarrage du pipeline de construction des données")

    logger.info("=== 1. Création du fichier de merge des données initiales nettoyées ===")
    create_output()

    logger.info("=== 2. Récupération des données géographiques grâce aux numéros Sirene ===")
    enrich(merged_path, organismes_path)

    logger.info("=== 3. Enrichissement des formations avec les données géographiques ===")
    formations_enricher = FormationsEnricher()
    formations_enricher.load(merged_path, organismes_path, cdc_path)
    formations_enricher.enrich()
    formations_enricher.export(formations_path)

    logger.info("=== 4. Import des formations enrichies dans la base ===")
    import_formations_enriched()

    logger.info("=== 5. Appel à l'API France Travail ===")
    rome_codes = get_unique_rome_codes_from_csv_file()
    logger.info("Nombre de codes ROME uniques : %s", len(rome_codes))
    for rome_code in rome_codes:
        search_offres_by_rome(rome_code)

    logger.info("Pipeline de construction des données terminé.")


app = FastAPI(title="Observia Emploi API")
app.include_router(francetravail_router.router)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-data",
        action="store_true",
        help="Lance le pipeline de construction des données au lieu de démarrer l'API.",
    )
    args = parser.parse_args()

    if args.build_data:
        run_data_pipeline()
    else:
        logger.info("Démarrage de l'API FastAPI")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
