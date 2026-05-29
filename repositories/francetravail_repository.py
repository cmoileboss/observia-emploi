from __future__ import annotations

from sqlalchemy.orm import Session

from models.francetravail_model import CompetenceModel, FormationModel, FranceTravailModel
from repositories.base_repository import BaseRepository


class FranceTravailRepository(BaseRepository[FranceTravailModel]):
    """Encapsule les accès en base pour les offres France Travail."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des offres."""
        super().__init__(db, FranceTravailModel)

    def create_offre(self, **kwargs) -> FranceTravailModel:
        """Cree et persiste une offre France Travail."""
        offre = FranceTravailModel(**kwargs)
        return self.add(offre)

    def list_offres(self, rome_code: str | None = None, limit: int = 50) -> list[FranceTravailModel]:
        """Retourne les offres, filtrees optionnellement par code ROME."""
        query = self.db.query(FranceTravailModel)
        if rome_code:
            query = query.filter(FranceTravailModel.rome_code == rome_code)
        return query.limit(limit).all()

    def get_offre_by_id(self, offre_id: str) -> FranceTravailModel | None:
        """Retourne une offre a partir de son identifiant."""
        return self.db.get(FranceTravailModel, offre_id)

    def attach_formation(self, offre: FranceTravailModel, formation: FormationModel, commit: bool = True) -> FranceTravailModel:
        """Associe une formation existante a une offre."""
        if formation not in offre.formations:
            offre.formations.append(formation)
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_competence(self, offre: FranceTravailModel, competence: CompetenceModel, commit: bool = True) -> FranceTravailModel:
        """Associe une competence existante a une offre."""
        if competence not in offre.competences:
            offre.competences.append(competence)
        if commit:
            self.db.commit()
            self.db.refresh(offre)
        return offre

    def attach_or_create_formation(self, offre: FranceTravailModel, **kwargs) -> FranceTravailModel:
        """Associe une formation a l'offre en la creant si necessaire."""
        formation_repository = FormationRepository(self.db)
        code_formation = kwargs.get("code_formation")

        formation = None
        if code_formation:
            formation = formation_repository.find_by_code(code_formation)

        if formation is None:
            formation = formation_repository.create_formation(**kwargs)

        return self.attach_formation(offre, formation)

    def attach_or_create_competence(self, offre: FranceTravailModel, **kwargs) -> FranceTravailModel:
        """Associe une competence a l'offre en la creant si necessaire."""
        competence_repository = CompetenceRepository(self.db)
        code = kwargs.get("code")

        competence = None
        if code:
            competence = competence_repository.find_by_code(code)

        if competence is None:
            competence = competence_repository.create_competence(**kwargs)

        return self.attach_competence(offre, competence)


class FormationRepository(BaseRepository[FormationModel]):
    """Fournit les operations d'acces aux formations."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des formations."""
        super().__init__(db, FormationModel)

    def create_formation(self, **kwargs) -> FormationModel:
        """Cree et persiste une formation."""
        formation = FormationModel(**kwargs)
        return self.add(formation)

    def find_by_code(self, code_formation: str) -> FormationModel | None:
        """Recherche une formation par son code metier."""
        return self.db.query(FormationModel).filter(FormationModel.code_formation == code_formation).first()


class CompetenceRepository(BaseRepository[CompetenceModel]):
    """Fournit les operations d'acces aux competences."""

    def __init__(self, db: Session) -> None:
        """Initialise le repository des competences."""
        super().__init__(db, CompetenceModel)

    def create_competence(self, **kwargs) -> CompetenceModel:
        """Cree et persiste une competence."""
        competence = CompetenceModel(**kwargs)
        return self.add(competence)

    def find_by_code(self, code: str) -> CompetenceModel | None:
        """Recherche une competence par son code metier."""
        return self.db.query(CompetenceModel).filter(CompetenceModel.code == code).first()
