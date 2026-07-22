"""Charge, nettoie et fusionne les CSV utilisés par le pipeline."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class CsvExtractor:
    """Charge, nettoie et fusionne les jeux de données CSV du pipeline."""

    def __init__(self) -> None:
        """Initialise les DataFrames manipulés pendant le pipeline."""

        self.correspondance = pd.DataFrame()
        self.formation = pd.DataFrame()
        self.merged = pd.DataFrame()

    def charge_raw_data(self, raw_input_folder: str):
        """Charge les fichiers CSV bruts nécessaires au pipeline."""

        self.correspondance = pd.read_csv(
            f"{raw_input_folder}/correspondance-rome-rncp-tech-6a16c0f17343f806639940.csv",
            sep=";",
            dtype={"code_rncp": str},
        )
        self.formation = pd.read_csv(
            f"{raw_input_folder}/entree_sortie_formation.csv",
            sep=";",
            dtype={"code_rncp": str},
        )
        logger.info("Données brutes chargées depuis le dossier %s", raw_input_folder)

    def clean_data(self):
        """Nettoie les données de formation et de correspondance."""

        self.formation = self.formation.drop(
            columns=[
                "annee_mois",
                "type_referentiel",
                "code_rs",
                "code_certifinfo",
                "date_chargement",
            ]
        )
        logger.info("Données nettoyées : colonnes inutiles supprimées")
        self.formation = self.formation[self.formation["code_rncp"] != "-1"]
        logger.info("Données nettoyées : lignes avec code RNCP égal à -1 supprimées")
        self.correspondance["code_rncp"] = self.correspondance["code_rncp"].str.replace(
            "RNCP",
            "",
            regex=False,
        )
        logger.info("Données nettoyées : codes RNCP uniformisés")
        self.correspondance = self.correspondance[
            self.correspondance["code_rome"].str.startswith("M")
        ]
        logger.info("Données nettoyées : lignes avec code ROME ne commençant pas par M supprimées")

    def merge_data(self):
        """Fusionne les données de formation et de correspondance."""

        self.merged = self.formation.merge(self.correspondance, on="code_rncp", how="inner")
        self.merged = self.merged[self.merged["entrees_formation"] > 0]
        logger.info("Données fusionnées : lignes avec entrées formation supérieures à 0 conservées")

    def export(self, filepath: str):
        """Exporte les données fusionnées dans un fichier CSV."""

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        self.merged.to_csv(filepath, sep=";", index=False)
        logger.info("Données exportées vers le fichier %s", filepath)
