import os

import uvicorn
from fastapi import FastAPI

from scripts.csv_extractor import CsvExtractor
from postgres_connection import Base, engine
from models import francetravail_model, correspondance_formation_model
from routers import francetravail_router

from scripts.sirene_enricher import enrich as enrich_sirene
from scripts.formations_enricher import FormationsEnricher
from scripts.create_output import create_output


app = FastAPI(title="Observia Emploi API")
Base.metadata.create_all(bind=engine)
create_output()
# Enregistre les routers
app.include_router(francetravail_router.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
