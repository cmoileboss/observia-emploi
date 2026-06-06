import os
import logging

from scripts.csv_extractor import CsvExtractor
from logging_config import configure_logging


logger = logging.getLogger(__name__)


def create_output():
    """Crée le fichier data/processed/merged_data.csv à partir des données brutes.
    Le fichier merged_data.csv est une fusion des données brutes avec après nettoyage (retrait colonnes inutiles, uniformisation des codes RNCP). Il est utilisé comme source principale pour les étapes suivantes du pipeline de données."""
    raw_data_folder = os.getenv("RAW_DATA_FOLDER", r"data\raw")
    processed_data_folder = os.getenv("PROCESSED_DATA_FOLDER", r"data\processed")

    if not os.path.exists(raw_data_folder):
        os.makedirs(raw_data_folder, exist_ok=True)
        logger.info("Dossier créé: %s", raw_data_folder)

    if not os.path.exists(processed_data_folder):
        os.makedirs(processed_data_folder, exist_ok=True)
        logger.info("Dossier créé: %s", processed_data_folder)

    output_file = os.path.join(processed_data_folder, "merged_data.csv")
    if os.path.exists(output_file):
        logger.warning("Le fichier %s existe déjà. Veuillez le supprimer ou choisir un autre nom.", output_file)
        return

    extractor = CsvExtractor()
    extractor.charge_raw_data(raw_data_folder)
    extractor.clean_data()
    extractor.merge_data()
    extractor.export(output_file)
    logger.info("Le fichier %s a été créé avec succès.", output_file)

if __name__ == "__main__":
    configure_logging()
    create_output()