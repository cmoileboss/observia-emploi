import pandas as pd
import logging

from logging_config import configure_logging

logger = logging.getLogger(__name__)


class CsvExtractor:

    def charge_raw_data(self, raw_input_folder: str):
        """Chargement des données brutes des fichiers CSV du dossier data"""
        self.correspondance = pd.read_csv(f"{raw_input_folder}/correspondance-rome-rncp-tech-6a16c0f17343f806639940.csv", sep=";", dtype={"code_rncp": str})
        self.formation = pd.read_csv(f"{raw_input_folder}/entree_sortie_formation.csv", sep=";", dtype={"code_rncp": str})
        logger.info("Données brutes chargées depuis le dossier %s", raw_input_folder)

    def clean_data(self):
        """Nettoyage des données : suppression des colonnes inutiles, des code RNCP égaux à -1 et uniformisation des codes RNCP"""
        self.formation = self.formation.drop(columns=["annee_mois", "type_referentiel", "code_rs", "code_certifinfo", "date_chargement"])
        logger.info("Données nettoyées : colonnes inutiles supprimées")
        self.formation = self.formation[self.formation["code_rncp"] != "-1"]
        logger.info("Données nettoyées : lignes avec code RNCP égal à -1 supprimées")
        self.correspondance["code_rncp"] = self.correspondance["code_rncp"].str.replace("RNCP", "", regex=False)
        logger.info("Données nettoyées : codes RNCP uniformisés")

    def merge_data(self):
        """Fusion des données formation et correspondance"""
        self.merged = self.formation.merge(self.correspondance, on="code_rncp", how="inner")
        self.merged = self.merged[self.merged["entrees_formation"] > 0]
        logger.info("Données fusionnées : lignes avec entrées formation supérieures à 0 conservées")

    def export(self, filepath: str):
        """Export des données agrégées vers le dossier processed, dans le fichier merged_data.csv"""
        self.merged.to_csv(f"{filepath}", sep=";", index=False)
        logger.info("Données exportées vers le fichier %s", filepath)
