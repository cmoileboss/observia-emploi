"""Configuration pytest : neutralise les dépendances lourdes avant les imports."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ajoute backend/ au chemin de recherche des modules Python
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Remplace par des MagicMock tous les modules qui déclenchent des connexions BDD,
# des appels réseau ou des lectures de fichiers à l'import
_HEAVY_MODULES = [
    "postgres_connection",
    "logging_config",
    "models",
    "models.correspondance_formation_model",
    "models.francetravail_model",
    "repositories",
    "repositories.base_repository",
    "repositories.correspondance_formation_repository",
    "repositories.francetravail_repository",
    "scripts",
    "scripts.francetravail_api_call",
    "scripts.import_formations_enriched",
    "scripts.collect_free_work_full_catalog",
    "scripts.import_offers_raw",
    "scripts.create_output",
    "scripts.formations_enricher",
    "scripts.llm_analyse",
]
for _mod in _HEAVY_MODULES:
    sys.modules.setdefault(_mod, MagicMock())
