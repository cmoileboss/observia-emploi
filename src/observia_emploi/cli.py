"""Command line interface (CLI) to launch France Travail ROME referential tasks."""

import logging
import os
import sys
from pathlib import Path

from observia_emploi.config import FranceTravailConfig, settings
from observia_emploi.france_travail.client import (
    FranceTravailClient,
    MockFranceTravailClient,
)
from observia_emploi.france_travail.referential import (
    TEST_ROME_CODES,
    RomeReferentialService,
)
from observia_emploi.logging_config import setup_logging

logger = logging.getLogger("observia_emploi.cli")


def main() -> None:
    """Execute ROME referential fetch, filter and export task."""
    setup_logging(logging.INFO)
    logger.info("Initializing ObservIA Emploi - Lot 1B referential tool...")

    # Output file target destination
    output_path = Path("data/processed/reference/rome_metiers_v1.json")

    # Graceful client selection based on configuration availability or environment
    if settings is None:
        logger.warning(
            "Missing environment configuration in .env. "
            "Falling back to MockFranceTravailClient (OFFLINE/MOCK Mode)."
        )
        mock_config = FranceTravailConfig(
            client_id="mock_id",
            client_secret="mock_secret",
            token_url="mock_token_url",
            api_base_url="http://api.mock-url.com",
            scope="api_romev1",
        )
        client = MockFranceTravailClient(mock_config)
    else:
        # Respect optional offline flag in environment
        if os.getenv("FRANCE_TRAVAIL_OFFLINE", "false").lower() == "true":
            logger.info("Offline mode requested via environment flag.")
            client = MockFranceTravailClient(settings.france_travail)
        else:
            logger.info("Environment configuration loaded successfully.")
            client = FranceTravailClient(settings.france_travail)

    # Initialize and execute ROME service
    service = RomeReferentialService(client)
    try:
        export_data = service.fetch_and_filter_rome(
            requested_codes=TEST_ROME_CODES,
            scope="v1_test_tech_ia",
        )
        service.export_to_json(export_data, output_path)
        logger.info("Referential execution completed successfully.")
    except Exception as e:
        logger.error("Referential retrieval execution failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
