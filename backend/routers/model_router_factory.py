from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from postgres_connection import get_db
from repositories.base_repository import BaseRepository
from routers.serialization import serialize_model, serialize_models


RepositoryFactory = Callable[[Session], BaseRepository[Any]]


def create_model_router(
    *,
    prefix: str,
    tags: list[str],
    repository_factory: RepositoryFactory,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=tags)

    def parse_entity_id(repository: BaseRepository[Any], entity_id: str) -> Any:
        primary_keys = inspect(repository.model).primary_key
        if len(primary_keys) != 1:
            return entity_id

        python_type = primary_keys[0].type.python_type
        try:
            return python_type(entity_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"Identifiant invalide: {entity_id}")

    def get_repository(db: Session = Depends(get_db)) -> BaseRepository[Any]:
        return repository_factory(db)

    @router.get("/")
    async def get_all(repository: BaseRepository[Any] = Depends(get_repository)) -> list[dict[str, Any]]:
        return serialize_models(repository.get_all())

    @router.get("/{entity_id}")
    async def get_by_id(entity_id: str, repository: BaseRepository[Any] = Depends(get_repository)) -> dict[str, Any]:
        entity = repository.get_by_id(parse_entity_id(repository, entity_id))
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Ressource introuvable pour l'identifiant {entity_id}")
        return serialize_model(entity)

    return router