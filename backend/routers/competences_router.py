from repositories.francetravail_repository import CompetenceRepository
from routers.model_router_factory import create_model_router


router = create_model_router(
    prefix="/competences",
    tags=["competences"],
    repository_factory=CompetenceRepository,
)