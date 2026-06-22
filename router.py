from fastapi import APIRouter
from fastapi.params import Depends
from sqlalchemy.orm import Session
from postgres_connection import get_db
from service import Service

router = APIRouter()

def get_service(db: Session = Depends(get_db)) -> Service:
    return Service(db)

@router.get("/job/{job_id}/organismes", tags=["formations"])
async def get_best_organismes_for_job_id(job_id: int, service: Service = Depends(get_service)):
    return {"message": "This endpoint will return the best organismes for a given job id."}

@router.get("/bestskills", tags=["formations"])
async def get_best_skills(service: Service = Depends(get_service)):
    return {"message": "This endpoint will return the best skills."}

@router.get("/nboffers", tags=["formations"])
async def get_nb_offers(service: Service = Depends(get_service)):
    return {"message": "This endpoint will return the number of offers."}