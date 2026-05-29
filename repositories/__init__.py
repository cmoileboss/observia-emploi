"""Expose les repositories utilises par l'application."""

from repositories.base_repository import BaseRepository
from repositories.correspondance_formation_repository import CorrespondanceFormationRepository
from repositories.francetravail_repository import CompetenceRepository, FormationRepository, FranceTravailRepository

__all__ = [
    "BaseRepository",
    "FranceTravailRepository",
    "FormationRepository",
    "CompetenceRepository",
    "CorrespondanceFormationRepository",
]