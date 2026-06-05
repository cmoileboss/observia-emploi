import os

from scripts.csv_extractor import CsvExtractor


def create_output():
    raw_data_folder = os.getenv("RAW_DATA_FOLDER", r"data\raw")
    processed_data_folder = os.getenv("PROCESSED_DATA_FOLDER", r"data\processed")
    processed_data_file = os.getenv("PROCESSED_DATA_FILE", "merged_data.csv")

    if not os.path.exists(raw_data_folder):
        os.makedirs(raw_data_folder, exist_ok=True)
        print(f"Dossier créé: {raw_data_folder}")

    if not os.path.exists(processed_data_folder):
        os.makedirs(processed_data_folder, exist_ok=True)
        print(f"Dossier créé: {processed_data_folder}")

    output_file = os.path.join(processed_data_folder, processed_data_file)
    if os.path.exists(output_file):
        print(f"Le fichier {output_file} existe déjà. Veuillez le supprimer ou choisir un autre nom.")
        return

    extractor = CsvExtractor()
    extractor.charge_raw_data(raw_data_folder)
    extractor.clean_data()
    extractor.merge_data()
    extractor.export(output_file)
    print(f"Le fichier {output_file} a été créé avec succès.")

if __name__ == "__main__":
    create_output()