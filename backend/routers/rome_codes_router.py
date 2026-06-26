"""Route CRUD des codes ROME."""

from repositories.correspondance_formation_repository import RomeCodeRepository
from routers.model_router_factory import create_model_router


router = create_model_router(
    prefix="/rome-codes",
    tags=["rome-codes"],
    repository_factory=RomeCodeRepository,
)
