"""Route CRUD des flux mensuels de formation."""

from repositories.correspondance_formation_repository import FormationFluxMensuelRepository
from routers.model_router_factory import create_model_router


router = create_model_router(
    prefix="/formation-flux-mensuel",
    tags=["formation-flux-mensuel"],
    repository_factory=FormationFluxMensuelRepository,
)
