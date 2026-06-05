import os
import argparse

import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

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
    "PROCESSED_DATA_FILE",
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
    print("Initialisation de la base de données")
    Base.metadata.create_all(bind=engine)


def run_data_pipeline() -> None:
    """Lance les scripts métier dans l'ordre de production des données."""
    validate_env_vars(*PIPELINE_ENV_VARS)
    initialize_database()

    raw_folder = os.environ["RAW_DATA_FOLDER"]
    processed_folder = os.environ["PROCESSED_DATA_FOLDER"]
    processed_file = os.environ["PROCESSED_DATA_FILE"]

    merged_path = os.path.join(processed_folder, processed_file)
    organismes_path = os.path.join(processed_folder, "organismes_enriched.csv")
    cdc_path = os.path.join(raw_folder, "cdc_filtered_tech.csv")
    formations_path = os.path.join(processed_folder, "formations_enriched.csv")
    
    print("Démarrage du pipeline de construction des données")

    print("=== 1. Création du fichier de merge des données initiales nettoyées ===")
    create_output()

    print("\n=== 2. Récupération des données géographiques grâce aux numéros Sirene ===")
    enrich(merged_path, organismes_path)

    print("\n=== 3. Enrichissement des formations avec les données géographiques ===")
    formations_enricher = FormationsEnricher()
    formations_enricher.load(merged_path, organismes_path, cdc_path)
    formations_enricher.enrich()
    formations_enricher.export(formations_path)

    print("\n=== 4. Import des formations enrichies dans la base ===")
    import_formations_enriched()

    print("\n=== 5. Appel à l'API France Travail ===")
    rome_codes = get_unique_rome_codes_from_csv_file()
    print(f"Nombre de codes ROME uniques : {len(rome_codes)}")
    for rome_code in rome_codes:
        search_offres_by_rome(rome_code)

    print("\nPipeline de construction des données terminé.")


app = FastAPI(title="Observia Emploi API")
app.include_router(francetravail_router.router)


@app.on_event("startup")
def startup() -> None:
    initialize_database()

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
        print("Démarrage de l'API FastAPI")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
