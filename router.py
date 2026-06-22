from fastapi import APIRouter

router = APIRouter()

@router.get("/job/{job_id}/organismes", tags=["formations"])
async def get_best_organismes_for_job_id():
    return {"message": "This endpoint will return the best organismes for a given job id."}

@router.get("/bestskills", tags=["formations"])
async def get_best_skills():
    return {"message": "This endpoint will return the best skills."}

@router.get("/nboffers", tags=["formations"])
async def get_nb_offers():
    return {"message": "This endpoint will return the number of offers."}