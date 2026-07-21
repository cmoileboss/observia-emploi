"""Point d'entrée de l'API Observia Emploi."""

import os
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv
from logging_config import configure_logging

from postgres_connection import Base, engine
from routers.competences_router import router as competences_router
from routers.formation_flux_mensuel_router import router as formation_flux_mensuel_router
from routers.formations_router import router as formations_router
from routers.offres_router import router as offres_router
from routers.rome_codes_router import router as rome_codes_router
from routers.main_router import main_router


load_dotenv()
configure_logging()
logger = logging.getLogger(__name__)


DATABASE_ENV_VARS = (
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
)

PIPELINE_ENV_VARS = DATABASE_ENV_VARS + (
    "CLIENT_ID",
    "SECRET_ID",
)

ENV_VARS = PIPELINE_ENV_VARS + DATABASE_ENV_VARS


missing_vars = [name for name in ENV_VARS if not os.getenv(name)]
if missing_vars:
    raise EnvironmentError(
        "Variables d'environnement non initialisées : " + ", ".join(missing_vars)
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """."""
    logger.info("Les variables d'environnement %s sont bien initialisées.", ", ".join(ENV_VARS))
    logger.info("Initialisation de la base de données")
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Observia Emploi API", lifespan=lifespan)
app.include_router(offres_router)
app.include_router(competences_router)
app.include_router(formations_router)
app.include_router(formation_flux_mensuel_router)
app.include_router(rome_codes_router)
app.include_router(main_router)


def main() -> None:
    """Démarre le serveur Uvicorn pour l'API FastAPI."""

    logger.info("Démarrage de l'API FastAPI")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        app_dir=os.path.dirname(__file__),
    )


if __name__ == "__main__":
    main()
