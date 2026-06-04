from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from postgres_connection import get_db
from models.francetravail_model import FTOffreModel

router = APIRouter(prefix="/offres", tags=["France Travail"])


@router.get("/")
def list_offres(rome_code: str | None = None, db: Session = Depends(get_db)):
    query = db.query(FTOffreModel)
    if rome_code:
        query = query.filter(FTOffreModel.rome_code == rome_code)
    return query.limit(50).all()


@router.get("/{offre_id}")
def get_offre(offre_id: str, db: Session = Depends(get_db)):
    offre = db.query(FTOffreModel).filter(FTOffreModel.id == offre_id).first()
    if not offre:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    return offre
