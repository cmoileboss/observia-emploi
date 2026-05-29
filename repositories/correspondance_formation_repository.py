from __future__ import annotations

from sqlalchemy.orm import Session

from models.correspondance_formation_model import CorrespondanceFormationModel
from repositories.base_repository import BaseRepository


class CorrespondanceFormationRepository(BaseRepository[CorrespondanceFormationModel]):
    """Encapsule les acces a la table des correspondances formation."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des correspondances formation."""
        super().__init__(db, CorrespondanceFormationModel)

    def create_correspondance(self, correspondance: CorrespondanceFormationModel) -> CorrespondanceFormationModel:
        """Persiste une correspondance formation deja instanciee."""
        return self.add(correspondance)

    def list_by_code_rome(self, code_rome: str) -> list[CorrespondanceFormationModel]:
        """Retourne les correspondances pour un code ROME donne."""
        return (
            self.db.query(CorrespondanceFormationModel)
            .filter(CorrespondanceFormationModel.code_rome == code_rome)
            .all()
        )

    def list_by_siret(self, siret: str) -> list[CorrespondanceFormationModel]:
        """Retourne les correspondances associees a un SIRET donne."""
        return (
            self.db.query(CorrespondanceFormationModel)
            .filter(CorrespondanceFormationModel.siret_of_contractant == siret)
            .all()
        )

    def list_by_rncp(self, code_rncp: str) -> list[CorrespondanceFormationModel]:
        """Retourne les correspondances associees a un code RNCP donne."""
        return (
            self.db.query(CorrespondanceFormationModel)
            .filter(CorrespondanceFormationModel.code_rncp == code_rncp)
            .all()
        )
