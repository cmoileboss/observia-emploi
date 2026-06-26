from repositories.correspondance_formation_repository import FormationRepository
from routers.model_router_factory import create_model_router


router = create_model_router(
    prefix="/formations",
    tags=["formations"],
    repository_factory=FormationRepository,
)
