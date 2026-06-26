"""
Enrichit merged_data.csv avec :
- la géolocalisation des organismes (depuis organismes_enriched.csv issu de SIRENE)
- la modalité dominante par RNCP (depuis le CDC filtré)

Produit : data/processed/formations_enriched.csv
"""

import logging

import pandas as pd

from logging_config import configure_logging


logger = logging.getLogger(__name__)


class FormationsEnricher:
    """Enrichit les formations avec les données géographiques et de modalité."""

    GEO_COLS = [
        "siret",
        "nom_entreprise",
        "enseigne",
        "adresse",
        "code_postal",
        "ville",
        "code_commune",
        "departement",
        "region",
    ]

    def __init__(self) -> None:
        """Initialise les DataFrames utilisés pendant l'enrichissement."""

        self.merged = pd.DataFrame()
        self.organismes = pd.DataFrame()
        self.modalite = pd.DataFrame()
        self.result = pd.DataFrame()

    def load(self, merged_path: str, organismes_path: str, cdc_path: str) -> None:
        """Charge les jeux de données nécessaires à l'enrichissement."""

        self.merged = pd.read_csv(
            merged_path,
            sep=";",
            dtype={"siret_of_contractant": str, "code_rncp": str},
        )
        self.organismes = pd.read_csv(
            organismes_path,
            sep=";",
            dtype={"siret": str},
        )[self.GEO_COLS]
        self.modalite = self._compute_modalite_dominante(cdc_path)

    @staticmethod
    def _compute_modalite_dominante(cdc_path: str) -> pd.DataFrame:
        """Retourne [code_rncp, modalite] avec la modalité majoritaire par RNCP."""
        cdc = pd.read_csv(
            cdc_path, sep=";",
            dtype={"code_rncp": str, "nb_dossiers": "Int64"},
            encoding="utf-8",
        )
        return (
            cdc.groupby(["code_rncp", "modalite_presence"])["nb_dossiers"]
            .sum()
            .reset_index()
            .sort_values("nb_dossiers", ascending=False)
            .drop_duplicates("code_rncp")
            [["code_rncp", "modalite_presence"]]
            .rename(columns={"modalite_presence": "modalite"})
        )

    def enrich(self) -> None:
        """Fusionne les données de formation avec les enrichissements disponibles."""

        with_geo = self.merged.merge(
            self.organismes,
            left_on="siret_of_contractant",
            right_on="siret",
            how="left",
        ).drop(columns=["siret"])

        self.result = with_geo.merge(self.modalite, on="code_rncp", how="left")

    def export(self, output_path: str) -> None:
        """Écrit le jeu de données enrichi dans un fichier CSV."""

        self.result.to_csv(output_path, sep=";", index=False, encoding="utf-8")
        n = len(self.result)
        n_reg = self.result["region"].notna().sum()
        n_mod = self.result["modalite"].notna().sum()
        logger.info(
            "formations_enriched : %s lignes (région: %.1f%%, modalité: %.1f%%)",
            f"{n:,}",
            n_reg / n * 100,
            n_mod / n * 100,
        )


if __name__ == "__main__":
    configure_logging()
    enricher = FormationsEnricher()
    enricher.load(
        merged_path=r"data\processed\merged_data.csv",
        organismes_path=r"data\processed\organismes_enriched.csv",
        cdc_path=r"data\raw\cdc_filtered_tech.csv",
    )
    enricher.enrich()
    enricher.export(r"data\processed\formations_enriched.csv")
