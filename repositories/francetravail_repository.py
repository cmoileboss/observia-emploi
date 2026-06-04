from __future__ import annotations

from sqlalchemy.orm import Session

from models.francetravail_model import FTCompetenceModel, FTFormationModel, FTOffreModel
from repositories.base_repository import BaseRepository


class FTOffreRepository(BaseRepository[FTOffreModel]):
    """Encapsule les accès en base pour les offres France Travail."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des offres."""
        super().__init__(db, FTOffreModel)

    def create_offre(self, offre: FTOffreModel) -> FTOffreModel:
        """Persiste une offre France Travail déjà instanciée."""
        if self.exists(offre.id):
            return self.get_offre_by_id(offre.id)
        return self.add(offre, commit=False)

    def exists(self, offre_id: str) -> bool:
        """Retourne vrai si une offre avec l'identifiant donné existe."""
        return self.db.query(FTOffreModel).filter(FTOffreModel.id == offre_id).first() is not None

    def list_offres(self, rome_code: str | None = None, limit: int = 50) -> list[FTOffreModel]:
        """Retourne les offres, filtrées optionnellement par code ROME."""
        query = self.db.query(FTOffreModel)
        if rome_code:
            query = query.filter(FTOffreModel.rome_code == rome_code)
        return query.limit(limit).all()

    def get_offre_by_id(self, offre_id: str) -> FTOffreModel | None:
        """Retourne une offre à partir de son identifiant."""
        return self.db.get(FTOffreModel, offre_id)

    def attach_formation(self, offre: FTOffreModel, formation: FTFormationModel, commit: bool = True) -> FTOffreModel:
        """Associe une formation existante à une offre."""
        if formation not in offre.formations:
            offre.formations.append(formation)
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_competence(self, offre: FTOffreModel, competence: FTCompetenceModel, commit: bool = True) -> FTOffreModel:
        """Associe une compétence existante à une offre."""
        if competence not in offre.competences:
            offre.competences.append(competence)
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
            existing_formation = formation_repository.create_formation(formation)

        return self.attach_formation(offre, existing_formation)

    def attach_or_create_competence(self, offre: FTOffreModel, competence: FTCompetenceModel) -> FTOffreModel:
        """Associe une compétence à l'offre en la créant si nécessaire."""
        competence_repository = FTCompetenceRepository(self.db)
        code = competence.code

        existing_competence = None
        if code:
            existing_competence = competence_repository.find_by_code(code)

        if existing_competence is None:
            existing_competence = competence_repository.create_competence(competence)

        return self.attach_competence(offre, existing_competence)


class FTFormationRepository(BaseRepository[FTFormationModel]):
    """Fournit les opérations d'accès aux formations."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des formations."""
        super().__init__(db, FTFormationModel)

    def create_formation(self, formation: FTFormationModel) -> FTFormationModel:
        """Persiste une formation déjà instanciée."""
        return self.add(formation, commit=False)

    def find_by_code(self, code_formation: str) -> FTFormationModel | None:
        """Recherche une formation par son code métier."""
        return self.db.query(FTFormationModel).filter(FTFormationModel.code_formation == code_formation).first()


class FTCompetenceRepository(BaseRepository[FTCompetenceModel]):
    """Fournit les opérations d'accès aux compétences."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des compétences."""
        super().__init__(db, FTCompetenceModel)

    def create_competence(self, competence: FTCompetenceModel) -> FTCompetenceModel:
        """Persiste une compétence déjà instanciée."""
        return self.add(competence, commit=False)

    def find_by_code(self, code: str) -> FTCompetenceModel | None:
        """Recherche une compétence par son code métier."""
        return self.db.query(FTCompetenceModel).filter(FTCompetenceModel.code == code).first()
