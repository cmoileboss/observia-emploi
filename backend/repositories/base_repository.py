"""Repository générique pour les opérations CRUD de base."""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import inspect
from sqlalchemy.orm import Session


ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """Expose les opérations CRUD de base pour un modèle SQLAlchemy."""

    def __init__(self, db: Session, model: type[ModelT]) -> None:
        """Initialise le repository avec une session et un modèle cible."""
        self.db = db
        self.model = model

    def get_all(self, skip: int = 0, limit: int | None = None) -> list[ModelT]:
        """Retourne une liste d'entités avec pagination optionnelle."""
        query = self.db.query(self.model).offset(skip)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def get_by_id(self, entity_id):
        """Retourne une entité par sa clé primaire."""
        primary_key_columns = inspect(self.model).primary_key
        if len(primary_key_columns) == 1:
            return self.db.get(self.model, entity_id)

        if not isinstance(entity_id, (tuple, list)):
            first_primary_key = primary_key_columns[0]
            return self.db.query(self.model).filter(first_primary_key == entity_id).first()

        return self.db.get(self.model, tuple(entity_id))

    def add(self, entity: ModelT) -> ModelT:
        """Ajoute une entité à la session."""
        self.db.add(entity)
        return entity

    def delete(self, entity: ModelT) -> None:
        """Supprime une entité."""
        self.db.delete(entity)
