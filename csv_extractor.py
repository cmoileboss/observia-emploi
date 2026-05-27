import pandas as pd


class CsvExtractor:


    def charge_raw_data(self, raw_input_folder: str):
        """Chargement des données brutes des fichiers CSV du dossier data"""
        self.correspondance = pd.read_csv(f"{raw_input_folder}/correspondance-rome-rncp-tech-6a16c0f17343f806639940.csv", sep=";", dtype={"code_rncp": str})
        self.formation = pd.read_csv(f"{raw_input_folder}/entree_sortie_formation.csv", sep=";", dtype={"code_rncp": str})

    def clean_data(self):
        """Nettoyage des données : suppression des colonnes inutiles, des code RNCP égaux à -1 et uniformisation des codes RNCP"""
        self.formation = self.formation.drop(columns=["annee_mois", "type_referentiel", "code_rs", "code_certifinfo", "siret_of_contractant", "raison_sociale_of_contractant"])
        self.formation = self.formation[self.formation["code_rncp"] != "-1"]
        self.correspondance["code_rncp"] = self.correspondance["code_rncp"].str.replace("RNCP", "", regex=False)

    def merge_data(self):
        """Fusion des données formation et correspondance"""
        self.merged = self.formation.merge(self.correspondance, on="code_rncp", how="left")

    def export(self, filepath: str):
        """Export des données agrégées vers le dossier processed, dans le fichier merged_date.csv"""
        self.merged.to_csv(f"{filepath}", sep=";", index=False)