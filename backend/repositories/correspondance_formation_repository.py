from __future__ import annotations

from sqlalchemy.orm import Session

from models.correspondance_formation_model import FormationModel, FormationFluxMensuelModel, RomeCodeModel
from repositories.base_repository import BaseRepository


class FormationRepository(BaseRepository[FormationModel]):
    """Encapsule les accès en base pour les formations."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, FormationModel)

    def exists_by_intitule_and_siret(self, intitule_certification: str, siret: str) -> bool:
        """Vérifie l'existence d'une formation par sa clé naturelle (intitulé + siret)."""
        return (
            self.db.query(FormationModel)
            .filter(
                FormationModel.intitule_certification == intitule_certification,
                FormationModel.siret_of_contractant == siret,
            )
            .first()
            is not None
        )

    def list_by_intitule(self, intitule_certification: str) -> list[FormationModel]:
        """Retourne les formations par leur intitulé."""
        return self.db.query(FormationModel).filter(FormationModel.intitule_certification == intitule_certification).all()


    def get_by_intitule_and_siret(self, intitule_certification: str, siret: str) -> FormationModel | None:
        """Retourne une formation par sa clé naturelle (intitulé + siret)."""
        return (
            self.db.query(FormationModel)
            .filter(
                FormationModel.intitule_certification == intitule_certification,
                FormationModel.siret_of_contractant == siret,
            )
            .first()
        )

    def list_by_siret(self, siret: str) -> list[FormationModel]:
        """Retourne les formations d'un organisme donné."""
        return (
            self.db.query(FormationModel)
            .filter(FormationModel.siret_of_contractant == siret)
            .all()
        )

    def list_by_rncp(self, code_rncp: str) -> list[FormationModel]:
        """Retourne les formations associées à un code RNCP donné."""
        return (
            self.db.query(FormationModel)
            .filter(FormationModel.code_rncp == code_rncp)
            .all()
        )

class FormationFluxMensuelRepository(BaseRepository[FormationFluxMensuelModel]):
    """Encapsule les accès en base pour les flux mensuels des formations."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, FormationFluxMensuelModel)

class RomeCodeRepository(BaseRepository[RomeCodeModel]):
    """Encapsule les accès en base pour les codes ROME."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, RomeCodeModel)

    def get_or_create(self, code_rome: str, intitule_rome: str | None) -> RomeCodeModel:
        """Retourne un code ROME existant ou le crée."""
        existing = self.get_by_id(code_rome)
        if existing:
            return existing
        rome = RomeCodeModel(code_rome=code_rome, intitule_rome=intitule_rome)
        self.add(rome)
        return rome
    
    def list_formations_by_rome(self, code_rome: str) -> list[FormationModel]:
        """Retourne les formations associées à un code ROME donné."""
        rome = self.get_by_id(code_rome)
        return rome.formations if rome else []