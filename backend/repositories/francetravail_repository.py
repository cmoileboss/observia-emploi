"""Repositories liés aux offres, formations liées et compétences."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.correspondance_formation_model import FormationModel
from backend.models.francetravail_model import CompetenceModel, OffreModel
from backend.repositories.base_repository import BaseRepository


class OffreRepository(BaseRepository[OffreModel]):
    """Encapsule les accès en base pour les offres France Travail."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des offres."""
        super().__init__(db, OffreModel)

    def create_offre(self, offre: OffreModel) -> OffreModel:
        """Persiste une offre France Travail déjà instanciée."""
        existing_offre = self.find_existing(offre)
        if existing_offre is not None:
            return existing_offre
        return self.add(offre)

    def find_existing(self, offre: OffreModel) -> OffreModel | None:
        """Retourne une offre existante selon son identifiant métier."""
        if offre.francetravail_id:
            existing_offre = self.get_by_francetravail_id(offre.francetravail_id)
            if existing_offre is not None:
                return existing_offre

        if offre.freework_id:
            return self.get_by_freework_id(offre.freework_id)

        return None

    def exists(self, francetravail_id: str | None = None, freework_id: str | None = None) -> bool:
        """Retourne vrai si une offre avec un identifiant métier donné existe."""
        if francetravail_id:
            return self.get_by_francetravail_id(francetravail_id) is not None
        if freework_id:
            return self.get_by_freework_id(freework_id) is not None
        return False

    def get_by_francetravail_id(self, francetravail_id: str) -> OffreModel | None:
        """Retourne une offre par son identifiant France Travail."""
        return (
            self.db.query(OffreModel)
            .filter(OffreModel.francetravail_id == francetravail_id)
            .first()
        )

    def get_by_freework_id(self, freework_id: str) -> OffreModel | None:
        """Retourne une offre par son identifiant FreeWork."""
        return self.db.query(OffreModel).filter(OffreModel.freework_id == freework_id).first()

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
        return (
            self.db.query(OffreModel.lieu_code_postal, func.count(OffreModel.id))
            .filter(OffreModel.lieu_code_postal.isnot(None))
            .group_by(OffreModel.lieu_code_postal)
            .all()
        )

    def attach_formation(
        self,
        offre: OffreModel,
        formation: FormationModel,
        commit: bool = True,
    ) -> OffreModel:
        """Associe une formation existante à une offre."""
        if formation not in offre.formations:
            offre.formations.append(formation)
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_competence(
        self,
        offre: OffreModel,
        competence: CompetenceModel,
        commit: bool = True,
    ) -> OffreModel:
        """Associe une compétence existante à une offre."""
        if competence not in offre.competences:
            offre.competences.append(competence)
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_or_create_formation(
        self,
        offre: OffreModel,
        formation: FormationModel,
    ) -> OffreModel:
        """Associe une formation à l'offre en la créant si nécessaire."""
        formation_repository = OffreFormationRepository(self.db)
        code_formation = formation.code_rncp

        existing_formation = None
        if code_formation:
            existing_formation = formation_repository.find_by_code(code_formation)

        if existing_formation is None:
            existing_formation = self.add(formation)

        return self.attach_formation(offre, existing_formation)

    def attach_or_create_competence(
        self,
        offre: OffreModel,
        competence: CompetenceModel,
    ) -> OffreModel:
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
        """Initialise le repository des formations liées aux offres."""

        super().__init__(db, FormationModel)

    def find_by_code(self, code_formation: str) -> FormationModel | None:
        """Recherche une formation par son code métier."""
        return (
            self.db.query(FormationModel)
            .filter(FormationModel.code_rncp == code_formation)
            .first()
        )


class CompetenceRepository(BaseRepository[CompetenceModel]):
    """Fournit les opérations d'accès aux compétences."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des compétences."""

        super().__init__(db, CompetenceModel)

    def find_by_code(self, code: str) -> CompetenceModel | None:
        """Recherche une compétence par son code métier."""
        return self.db.query(CompetenceModel).filter(CompetenceModel.code == code).first()
