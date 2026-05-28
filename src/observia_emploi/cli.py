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
from observia_emploi.france_travail.offer_collector import (
    FranceTravailOfferCollectorService,
)
from observia_emploi.france_travail.referential import (
    TEST_ROME_CODES,
    RomeReferentialService,
)
from observia_emploi.france_travail.volume_measurement import (
    RomeVolumeMeasurementService,
)
from observia_emploi.logging_config import setup_logging
from observia_emploi.referentials.rome_extractor import RomeExtractorService

logger = logging.getLogger("observia_emploi.cli")


def main() -> None:
    """Execute ROME tasks (referential, volume or offer collection)."""
    setup_logging(logging.INFO)
    logger.info("Initializing ObservIA Emploi - France Travail Toolbelt...")

    # CLI arguments parser
    parser = argparse.ArgumentParser(
        description="Outil de récupération du référentiel ROME France Travail."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Exécuter en mode hors-ligne avec des données simulées (Mock).",
    )
    parser.add_argument(
        "--measure-volume",
        action="store_true",
        help="Mesurer la volumétrie des offres par ROME.",
    )
    parser.add_argument(
        "--extract-rome",
        action="store_true",
        help=(
            "Extraire les codes ROME uniques et leurs statistiques "
            "depuis merged_data.csv."
        ),
    )
    parser.add_argument(
        "--measure-volumes-from-merged",
        action="store_true",
        help=(
            "Mesurer la volumétrie pour tous les codes ROME "
            "extraits de merged_data.csv."
        ),
    )
    parser.add_argument(
        "--collect-offers-from-merged",
        action="store_true",
        help=(
            "Collecter les offres d'emploi détaillées pour tous les codes ROME "
            "extraits de merged_data.csv."
        ),
    )
    args = parser.parse_args()

    # Handle ROME extraction first to avoid loading client/config or needing secrets
    if args.extract_rome:
        logger.info(
            "Starting Lot 2B: ROME codes and aggregation extraction from CSV..."
        )
        csv_input_path = Path("data/processed/merged_data.csv")
        ref_output_path = Path("data/reference/rome_codes_from_merged_data.json")

        extractor = RomeExtractorService()
        try:
            extracted = extractor.extract_from_csv(csv_input_path)
            extractor.export_to_json(extracted, ref_output_path)
            logger.info("ROME codes extraction completed successfully.")
            sys.exit(0)
        except Exception as e:
            logger.error("Extraction execution failed: %s", e)
            sys.exit(1)

    # Paths
    ref_path = Path("data/processed/reference/rome_metiers_v1.json")
    volumes_path = Path("data/processed/reference/rome_volumes_v1.json")

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

    # Branch logic depending on requested command
    if getattr(args, "collect_offers_from_merged", False):
        logger.info("Starting Lot 2D: Detailed job offers collection...")
        service = FranceTravailOfferCollectorService(client)
        merged_ref_path = Path("data/reference/rome_codes_from_merged_data.json")
        offers_output_path = Path(
            "data/processed/offers/france_travail_offers_from_merged_rome.json"
        )
        try:
            payload = service.collect_all_offers_from_file(merged_ref_path)
            service.export_offers_to_json(payload, offers_output_path)
            logger.info("Lot 2D execution completed successfully.")
        except Exception as e:
            logger.error("Lot 2D offers collection failed: %s", e)
            sys.exit(1)
    elif getattr(args, "measure_volumes_from_merged", False):
        logger.info("Starting Lot 2C: Rome volume measurement from merged data...")
        service = RomeVolumeMeasurementService(client)
        merged_ref_path = Path("data/reference/rome_codes_from_merged_data.json")
        merged_volumes_path = Path(
            "data/processed/reference/rome_volumes_from_merged_data.json"
        )
        try:
            report = service.measure_all_rome_from_file(merged_ref_path)
            service.export_report_to_json(report, merged_volumes_path)
            logger.info("Lot 2C execution completed successfully.")
        except Exception as e:
            logger.error("Lot 2C volume measurement failed: %s", e)
            sys.exit(1)
    elif args.measure_volume:
        logger.info("Starting Lot 2A: Rome volume and aggregation measurement...")
        service = RomeVolumeMeasurementService(client)
        try:
            report = service.measure_rome_volumes(ref_path)
            service.export_report_to_json(report, volumes_path)
            logger.info("Volume and aggregation measurement completed successfully.")
        except Exception as e:
            logger.error("Volume measurement execution failed: %s", e)
            sys.exit(1)
    else:
        logger.info("Starting Lot 1B: Rome referential retrieval...")
        service_ref = RomeReferentialService(client)
        try:
            export_data = service_ref.fetch_and_filter_rome(
                requested_codes=TEST_ROME_CODES,
                scope="v1_test_tech_ia",
            )
            service_ref.export_to_json(export_data, ref_path)
            logger.info("Referential execution completed successfully.")
        except Exception as e:
            logger.error("Referential retrieval execution failed: %s", e)
            sys.exit(1)


if __name__ == "__main__":
    main()
