import pandas as pd


class CsvExtractor:

    raw_input = "data/row"
    processed_output = "data/processed"

    def charge_raw_date(self):
        self.correspondance = pd.read_csv(f"{self.raw_input}/correspondance-rome-rncp-tech-6a16c0f17343f806639940.csv", sep=";")
        self.formation = pd.read_csv(f"{self.raw_input}/entree_sortie_formation.csv", sep=";")

    def clean_data(self):
        self.formation = self.formation.drop(columns=["annee", "mois", "type_referentiel", "code_rs", "code_certifinfo"])
        self.formation = self.formation[self.formation["code_rncp"] != "-1"]
        self.correspondance["code_rncp"] = self.correspondance["code_rncp"].str.replace("RNCP", "", regex=False)


    