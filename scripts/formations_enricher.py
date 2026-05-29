"""
Enrichit merged_data.csv avec :
- la géolocalisation des organismes (depuis organismes_enriched.csv issu de SIRENE)
- la modalité dominante par RNCP (depuis le CDC filtré)

Produit : data/processed/formations_enriched.csv
"""

import pandas as pd


class FormationsEnricher:

    GEO_COLS = ["siret", "nom_entreprise", "enseigne", "adresse", "code_postal",
                "ville", "code_commune", "departement", "region"]

    def load(self, merged_path: str, organismes_path: str, cdc_path: str) -> None:
        self.merged = pd.read_csv(
            merged_path, sep=";",
            dtype={"siret_of_contractant": str, "code_rncp": str},
        )
        self.organismes = pd.read_csv(
            organismes_path, sep=";", dtype={"siret": str},
        )[self.GEO_COLS]
        self.modalite = self._compute_modalite_dominante(cdc_path)

    @staticmethod
    def _compute_modalite_dominante(cdc_path: str) -> pd.DataFrame:
        """Retourne [code_rncp, modalite] avec la modalite majoritaire par RNCP."""
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
        with_geo = self.merged.merge(
            self.organismes,
            left_on="siret_of_contractant",
            right_on="siret",
            how="left",
        ).drop(columns=["siret"])

        self.result = with_geo.merge(self.modalite, on="code_rncp", how="left")

    def export(self, output_path: str) -> None:
        self.result.to_csv(output_path, sep=";", index=False, encoding="utf-8")
        n = len(self.result)
        n_reg = self.result["region"].notna().sum()
        n_mod = self.result["modalite"].notna().sum()
        print(f"formations_enriched : {n:,} lignes  (region: {n_reg/n*100:.1f}%, modalite: {n_mod/n*100:.1f}%)")