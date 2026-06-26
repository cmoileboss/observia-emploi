"""Route CRUD des offres."""

from repositories.francetravail_repository import OffreRepository
from routers.model_router_factory import create_model_router


router = create_model_router(
    prefix="/offres",
    tags=["offres"],
    repository_factory=OffreRepository,
)
