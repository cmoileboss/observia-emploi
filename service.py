from sqlalchemy.orm import Session

from repositories.correspondance_formation_repository import RomeCodeRepository
from repositories.francetravail_repository import FTOffreRepository


class Service():
    def __init__(self, db: Session):
        self.offre_repository = FTOffreRepository(db)
        self.rome_repository = RomeCodeRepository(db)
