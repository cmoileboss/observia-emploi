"""Routes principales exposant les opérations métier du backend."""

from fastapi import APIRouter
from fastapi.params import Depends
from sqlalchemy.orm import Session

from postgres_connection import get_db
from services.service import Service

main_router = APIRouter(prefix="/api", tags=["API"])


def get_service(db: Session = Depends(get_db)) -> Service:
    """Construit le service métier à partir de la session courante."""

    return Service(db)


@main_router.post("/populatedb")
async def populate_database(service: Service = Depends(get_service)):
    """Lance le pipeline d'initialisation de la base de données."""

    service.populate_database()
    return {"message": "Base de données initialisée avec succès."}


@main_router.get("/job/{job_id}/formations")
async def get_best_organismes_for_job_id(
    job_id: str,
    service: Service = Depends(get_service),
):
    """Retourne les formations pertinentes pour l'offre demandée."""

    return service.get_formations_by_offre_id(job_id)

@main_router.get("/bestskills")
async def get_best_skills(service: Service = Depends(get_service)):
    """Retourne les compétences les plus fréquentes dans les offres importées."""

    return service.get_best_skills()

@main_router.get("/formations/historique")
async def get_nb_offers(
    region: str | None = None,
    quarter: str | None = None,
    service: Service = Depends(get_service),
):
    """Retourne les indicateurs agrégés des formations par région et trimestre."""

    return service.count_formation_entries_by_region_and_quarter(region, quarter)
