from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session


ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """Expose les opérations CRUD de base pour un modèle SQLAlchemy."""

    def __init__(self, db: Session, model: type[ModelType]) -> None:
        """Initialise le repository avec une session et un modèle cible."""
        self.db = db
        self.model = model

    def get_all(self) -> list[ModelType]:
        """Retourne une liste d'entités."""
        return self.db.query(self.model).all()

    def get_by_id(self, entity_id):
        """Retourne une entité par sa clé primaire."""
        return self.db.get(self.model, entity_id)

    def add(self, entity: ModelType) -> ModelType:
        """Ajoute une entité à la session."""
        self.db.add(entity)
        return entity

    def delete(self, entity: ModelType) -> None:
        """Supprime une entité."""
        self.db.delete(entity)
