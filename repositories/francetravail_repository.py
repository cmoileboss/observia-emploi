from __future__ import annotations

from sqlalchemy.orm import Session

from models.correspondance_formation_model import FormationModel
from models.francetravail_model import CompetenceModel, OffreModel
from repositories.base_repository import BaseRepository


class OffreRepository(BaseRepository[OffreModel]):
    """Encapsule les accès en base pour les offres France Travail."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des offres."""
        super().__init__(db, OffreModel)

    def create_offre(self, offre: OffreModel) -> OffreModel:
        """Persiste une offre France Travail déjà instanciée."""
        if self.exists(offre.id):
            return self.get_by_id(offre.id)
        return self.add(offre)

    def exists(self, offre_id: str, rome_code: str | None = None) -> bool:
        """Retourne vrai si une offre avec l'identifiant donné existe."""
        query = self.db.query(OffreModel).filter(OffreModel.id == offre_id)
        if rome_code is not None:
            query = query.filter(OffreModel.rome_code == rome_code)
        return query.first() is not None

    def list_offres(self, rome_code: str) -> list[OffreModel]:
        """Retourne les offres, filtrées optionnellement par code ROME."""
        query = self.db.query(OffreModel)
        if rome_code:
            query = query.filter(OffreModel.rome_code == rome_code)
        return query.all()

    def count_offres(self):
        """Retourne le nombre total d'offres."""
        return self.db.query(OffreModel).count()

    def count_offres_by_code_postal(self) -> list[tuple[str, int]]:
        """Retourne le nombre d'offres groupé par code postal."""
        from sqlalchemy import func
        return (
            self.db.query(OffreModel.lieu_code_postal, func.count(OffreModel.id))
            .filter(OffreModel.lieu_code_postal.isnot(None))
            .group_by(OffreModel.lieu_code_postal)
            .all()
        )

    def attach_formation(self, offre: OffreModel, formation: FormationModel, commit: bool = True) -> OffreModel:
        """Associe une formation existante à une offre."""
        if formation not in offre.formations:
            offre.formations.append(formation)
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_competence(self, offre: OffreModel, competence: CompetenceModel, commit: bool = True) -> OffreModel:
        """Associe une compétence existante à une offre."""
        if competence not in offre.competences:
            offre.competences.append(competence)
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_or_create_formation(self, offre: OffreModel, formation: FormationModel) -> OffreModel:
        """Associe une formation à l'offre en la créant si nécessaire."""
        formation_repository = OffreFormationRepository(self.db)
        code_formation = formation.code_formation

        existing_formation = None
        if code_formation:
            existing_formation = formation_repository.find_by_code(code_formation)

        if existing_formation is None:
            existing_formation = self.add(formation)

        return self.attach_formation(offre, existing_formation)

    def attach_or_create_competence(self, offre: OffreModel, competence: CompetenceModel) -> OffreModel:
        """Associe une compétence à l'offre en la créant si nécessaire."""
        competence_repository = CompetenceRepository(self.db)
        code = competence.code

        existing_competence = None
        if code:
            existing_competence = competence_repository.find_by_code(code)

        if existing_competence is None:
            existing_competence = self.add(competence)

        return self.attach_competence(offre, existing_competence)


class OffreFormationRepository(BaseRepository[FormationModel]):
    """Fournit les opérations d'accès aux formations."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, FormationModel)

    def find_by_code(self, code_formation: str) -> FormationModel | None:
        """Recherche une formation par son code métier."""
        return self.db.query(FormationModel).filter(FormationModel.code_formation == code_formation).first()


class CompetenceRepository(BaseRepository[CompetenceModel]):
    """Fournit les opérations d'accès aux compétences."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, CompetenceModel)

    def find_by_code(self, code: str) -> CompetenceModel | None:
        """Recherche une compétence par son code métier."""
        return self.db.query(CompetenceModel).filter(CompetenceModel.code == code).first()


FTOffreRepository = OffreRepository
FTFormationRepository = OffreFormationRepository
FTCompetenceRepository = CompetenceRepository
