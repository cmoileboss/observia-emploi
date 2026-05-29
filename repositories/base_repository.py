from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session


ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """Expose les operations CRUD de base pour un modele SQLAlchemy."""

    def __init__(self, db: Session, model: type[ModelType]) -> None:
        """Initialise le repository avec une session et un modele cible."""
        self.db = db
        self.model = model

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[ModelType]:
        """Retourne une liste d'entites avec pagination optionnelle."""
        query = self.db.query(self.model).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def get_by_id(self, entity_id):
        """Retourne une entite par sa cle primaire."""
        return self.db.get(self.model, entity_id)

    def add(self, entity: ModelType, commit: bool = True) -> ModelType:
        """Ajoute une entite a la session puis la persiste si demande."""
        self.db.add(entity)
        if commit:
            self.db.commit()
            self.db.refresh(entity)
        return entity

    def add_all(self, entities: list[ModelType], commit: bool = True) -> list[ModelType]:
        """Ajoute plusieurs entites en une seule operation."""
        self.db.add_all(entities)
        if commit:
            self.db.commit()
            for entity in entities:
                self.db.refresh(entity)
        return entities

    def delete(self, entity: ModelType, commit: bool = True) -> None:
        """Supprime une entite puis valide la transaction si demande."""
        self.db.delete(entity)
        if commit:
            self.db.commit()

    def commit(self) -> None:
        """Valide explicitement la transaction courante."""
        self.db.commit()

    def refresh(self, entity: ModelType) -> None:
        """Rafraichit une entite depuis la base de donnees."""
        self.db.refresh(entity)
