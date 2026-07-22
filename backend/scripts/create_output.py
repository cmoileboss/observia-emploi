"""Construit le fichier merged_data.csv à partir des sources brutes."""

import os
import logging
from pathlib import Path

from scripts.csv_extractor import CsvExtractor
from logging_config import configure_logging


configure_logging()
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"


def create_output():
    """Crée le fichier de données fusionnées à partir des sources brutes.

    Le fichier `merged_data.csv` est la source principale des étapes
    suivantes du pipeline de données.
    """

    output_file = PROCESSED_DATA_ROOT / "merged_data.csv"
    if output_file.exists():
        logger.info(
            "Le fichier %s existe déjà. On passe à la suite.",
            output_file,
        )
        return

    extractor = CsvExtractor()
    extractor.charge_raw_data(RAW_DATA_ROOT)
    extractor.clean_data()
    extractor.merge_data()
    extractor.export(output_file)
    logger.info("Le fichier %s a été créé avec succès avec les données fusionnées et nettoyées.", output_file)
