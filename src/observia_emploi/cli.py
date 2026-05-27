"""Command line interface (CLI) to launch France Travail ROME referential tasks."""

import argparse
import logging
import sys
from pathlib import Path

from observia_emploi.config import Config, FranceTravailConfig
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

    # CLI arguments parser
    parser = argparse.ArgumentParser(
        description="Outil de récupération du référentiel ROME France Travail."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Exécuter en mode hors-ligne avec des données simulées (Mock).",
    )
    args = parser.parse_args()

    # Output file target destination
    output_path = Path("data/processed/reference/rome_metiers_v1.json")

    # Client selection logic based on --offline argument
    if args.offline:
        logger.info("Exécution demandée en mode OFFLINE / MOCK (--offline).")
        try:
            config = Config().france_travail
        except ValueError:
            # Fallback to default placeholders for mock mode if env config is missing
            config = FranceTravailConfig(
                client_id="mock_id",
                client_secret="mock_secret",
                token_url="mock_token_url",
                api_base_url="http://api.mock-url.com",
                scope="api_romev1",
            )
        client = MockFranceTravailClient(config)
    else:
        logger.info("Exécution en mode de PRODUCTION (réel).")
        try:
            config_loader = Config()
            config = config_loader.france_travail
        except ValueError as e:
            logger.error("Erreur de configuration : %s", e)
            logger.error(
                "Pour tester l'application hors-ligne, utilisez l'option '--offline'."
            )
            sys.exit(1)
        client = FranceTravailClient(config)

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
