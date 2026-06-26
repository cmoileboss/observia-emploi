"""Expose les repositories utilises par l'application."""

from backend.repositories.base_repository import BaseRepository
from backend.repositories.correspondance_formation_repository import FormationRepository as FormationDataRepository
from backend.repositories.francetravail_repository import (
    CompetenceRepository,
    OffreFormationRepository,
    OffreRepository,
)

__all__ = [
    "BaseRepository",
    "OffreRepository",
    "OffreFormationRepository",
    "CompetenceRepository",
    "FormationDataRepository",
]