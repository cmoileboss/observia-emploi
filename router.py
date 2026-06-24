from fastapi import APIRouter
from fastapi.params import Depends
from sqlalchemy.orm import Session
from postgres_connection import get_db
from service import Service

router = APIRouter()

def get_service(db: Session = Depends(get_db)) -> Service:
    return Service(db)

@router.get("/job/{job_id}/formations", tags=["formations"])
async def get_best_organismes_for_job_id(job_id: str, service: Service = Depends(get_service)):
    return service.get_formations_by_offre_id(job_id)

@router.get("/bestskills", tags=["formations"])
async def get_best_skills(service: Service = Depends(get_service)):
    return service.get_best_skills()

@router.get("/formations/historique", tags=["formations"])
async def get_nb_offers(region: str | None = None, quarter: str | None = None, service: Service = Depends(get_service)):
    return service.count_formation_entries_by_region_and_quarter(region, quarter)