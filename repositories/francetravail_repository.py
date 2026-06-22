from __future__ import annotations

from sqlalchemy.orm import Session

from models.francetravail_model import FTCompetenceModel, FTFormationModel, FTOffreCompetenceModel, FTOffreModel
from repositories.base_repository import BaseRepository


class FTOffreRepository(BaseRepository[FTOffreModel]):
    """Encapsule les accès en base pour les offres France Travail."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des offres."""
        super().__init__(db, FTOffreModel)

    def create_offre(self, offre: FTOffreModel) -> FTOffreModel:
        """Persiste une offre France Travail déjà instanciée."""
        if self.exists(offre.id):
            return self.get_by_id(offre.id)
        return self.add(offre)

    def exists(self, offre_id: str, rome_code: str | None = None) -> bool:
        """Retourne vrai si une offre avec l'identifiant donné existe."""
        query = self.db.query(FTOffreModel).filter(FTOffreModel.id == offre_id)
        if rome_code is not None:
            query = query.filter(FTOffreModel.rome_code == rome_code)
        return query.first() is not None

    def list_offres(self, rome_code: str) -> list[FTOffreModel]:
        """Retourne les offres, filtrées optionnellement par code ROME."""
        query = self.db.query(FTOffreModel)
        if rome_code:
            query = query.filter(FTOffreModel.rome_code == rome_code)
        return query.all()

    def count_offres(self):
        """Retourne le nombre total d'offres."""
        return self.db.query(FTOffreModel).count()

    def count_offres_by_code_postal(self) -> list[tuple[str, int]]:
        """Retourne le nombre d'offres groupé par code postal."""
        from sqlalchemy import func
        return (
            self.db.query(FTOffreModel.lieu_code_postal, func.count(FTOffreModel.id))
            .filter(FTOffreModel.lieu_code_postal.isnot(None))
            .group_by(FTOffreModel.lieu_code_postal)
            .all()
        )

    def attach_formation(self, offre: FTOffreModel, formation: FTFormationModel, commit: bool = True) -> FTOffreModel:
        """Associe une formation existante à une offre."""
        if formation not in offre.formations:
            offre.formations.append(formation)
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_competence(self, offre: FTOffreModel, competence: FTCompetenceModel, exigence: str | None = None, commit: bool = True) -> FTOffreModel:
        """Associe une compétence existante à une offre avec son niveau d'exigence."""
        already_linked = any(oc.competence_id == competence.id for oc in offre.offre_competences)
        if not already_linked:
            offre.offre_competences.append(
                FTOffreCompetenceModel(competence=competence, exigence=exigence)
            )
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_or_create_formation(self, offre: FTOffreModel, formation: FTFormationModel) -> FTOffreModel:
        """Associe une formation à l'offre en la créant si nécessaire."""
        formation_repository = FTFormationRepository(self.db)
        code_formation = formation.code_formation

        existing_formation = None
        if code_formation:
            existing_formation = formation_repository.find_by_code(code_formation)

        if existing_formation is None:
            existing_formation = self.add(formation)

        return self.attach_formation(offre, existing_formation)

    def attach_or_create_competence(self, offre: FTOffreModel, competence: FTCompetenceModel, exigence: str | None = None) -> FTOffreModel:
        """Associe une compétence à l'offre en la créant si nécessaire."""
        competence_repository = FTCompetenceRepository(self.db)
        code = competence.code

        existing_competence = None
        if code:
            existing_competence = competence_repository.find_by_code(code)

        if existing_competence is None:
            existing_competence = self.add(competence)

        return self.attach_competence(offre, existing_competence, exigence=exigence)


class FTFormationRepository(BaseRepository[FTFormationModel]):
    """Fournit les opérations d'accès aux formations."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, FTFormationModel)

    def find_by_code(self, code_formation: str) -> FTFormationModel | None:
        """Recherche une formation par son code métier."""
        return self.db.query(FTFormationModel).filter(FTFormationModel.code_formation == code_formation).first()


class FTCompetenceRepository(BaseRepository[FTCompetenceModel]):
    """Fournit les opérations d'accès aux compétences."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, FTCompetenceModel)

    def find_by_code(self, code: str) -> FTCompetenceModel | None:
        """Recherche une compétence par son code métier."""
        return self.db.query(FTCompetenceModel).filter(FTCompetenceModel.code == code).first()
