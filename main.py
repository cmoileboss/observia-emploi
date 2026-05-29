import os

import uvicorn
from fastapi import FastAPI

from csv_extractor import CsvExtractor
from postgres_connection import Base, engine
from models import francetravail_model, correspondance_formation_model
from routers import francetravail_router

from sirene_enricher import enrich as enrich_sirene
from formations_enricher import FormationsEnricher


def step_csv_extractor(raw_folder: str, merged_path: str) -> None:
    if os.path.exists(merged_path):
        print(f"[skip] {merged_path} existe deja.")
        return
    extractor = CsvExtractor()
    extractor.charge_raw_data(raw_folder)
    extractor.clean_data()
    extractor.merge_data()
    extractor.export(merged_path)
    print(f"[ok]  {merged_path} cree.")


def step_sirene(merged_path: str, organismes_path: str) -> None:
    if os.path.exists(organismes_path):
        print(f"[skip] {organismes_path} existe deja.")
        return
    enrich_sirene(merged_path, organismes_path)


def step_formations(merged_path: str, organismes_path: str,
                    cdc_path: str, output_path: str) -> None:
    if os.path.exists(output_path):
        print(f"[skip] {output_path} existe deja.")
        return
    enricher = FormationsEnricher()
    enricher.load(merged_path, organismes_path, cdc_path)
    enricher.enrich()
    enricher.export(output_path)


def create_output():
    RAW_DATA_FOLDER = os.getenv("RAW_DATA_FOLDER", r"data\raw")
    PROCESSED_DATA_FOLDER = os.getenv("PROCESSED_DATA_FOLDER", r"data\processed")
    PROCESSED_DATA_FILE = os.getenv("PROCESSED_DATA_FILE", "merged_data.csv")
    
    if not os.path.exists(RAW_DATA_FOLDER):
        raise FileNotFoundError(f"Le dossier {RAW_DATA_FOLDER} n'existe pas. Veuillez vérifier le chemin d'accès.")
    
    if not os.path.exists(PROCESSED_DATA_FOLDER):
        raise FileNotFoundError(f"Le dossier de destination {PROCESSED_DATA_FOLDER} n'existe pas. Veuillez vérifier le chemin d'accès.")

    output_file = os.path.join(PROCESSED_DATA_FOLDER, PROCESSED_DATA_FILE)
    if os.path.exists(output_file):
        print(f"Le fichier {output_file} existe déjà. Veuillez le supprimer ou choisir un autre nom.")
    else:
        step_csv_extractor(RAW_DATA_FOLDER, output_file)
        print(f"Le fichier {output_file} a été créé avec succès.")

def main():
    raw_folder       = os.getenv("RAW_DATA_FOLDER", r"data\raw")
    processed_folder = os.getenv("PROCESSED_DATA_FOLDER", r"data\processed")

    # Garde-fou : si la variable d'env pointe sur un fichier (ancien .env), on prend le parent
    if os.path.isfile(processed_folder) or processed_folder.lower().endswith(".csv"):
        processed_folder = os.path.dirname(processed_folder) or r"data\processed"

    if not os.path.exists(raw_folder):
        raise FileNotFoundError(f"Dossier introuvable : {raw_folder}")
    os.makedirs(processed_folder, exist_ok=True)

    merged_path     = os.path.join(processed_folder, "merged_data.csv")
    organismes_path = os.path.join(processed_folder, "organismes_enriched.csv")
    cdc_path        = os.path.join(raw_folder, "cdc_filtered_tech.csv")
    formations_path = os.path.join(processed_folder, "formations_enriched.csv")

    print("=== 1. Extraction et nettoyage MCF ===")
    step_csv_extractor(raw_folder, merged_path)

    print("\n=== 2. Enrichissement SIRENE (API INSEE) ===")
    step_sirene(merged_path, organismes_path)

    print("\n=== 3. Enrichissement formations (geo + modalite) ===")
    step_formations(merged_path, organismes_path, cdc_path, formations_path)

    print("\nPipeline termine.")


app = FastAPI(title="Observia Emploi API")
Base.metadata.create_all(bind=engine)
create_output()
# Enregistre les routers
app.include_router(francetravail_router.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
