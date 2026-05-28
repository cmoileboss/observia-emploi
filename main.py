import os

from csv_extractor import CsvExtractor

def process_data(raw_data_folder, output_file):
    extractor = CsvExtractor()
    extractor.charge_raw_data(raw_data_folder)
    extractor.clean_data()
    extractor.merge_data()
    extractor.export(output_file)

def main():
    RAW_DATA_FOLDER = os.getenv("RAW_DATA_FOLDER", r"data\raw")
    PROCESSED_DATA_FOLDER = os.getenv("PROCESSED_DATA_FOLDER", r"data\processed")
    PROCESSED_DATA_FILE = os.getenv("PROCESSED_DATA_FILE", "merged_data.csv")
    
    if not os.path.exists(RAW_DATA_FOLDER):
        raise FileNotFoundError(f"Le dossier {RAW_DATA_FOLDER} n'existe pas. Veuillez vérifier le chemin d'accès.")
    
    if not os.path.exists(PROCESSED_DATA_FOLDER):
        raise FileNotFoundError(f"Le dossier de destination {PROCESSED_DATA_FOLDER} n'existe pas. Veuillez vérifier le chemin d'accès.")

    output_file = os.path.join(PROCESSED_DATA_FOLDER, PROCESSED_DATA_FILE)
    if os.path.exists(output_file):
        raise FileExistsError(f"Le fichier {output_file} existe déjà. Veuillez le supprimer ou choisir un autre nom.")
    else:
        process_data(RAW_DATA_FOLDER, output_file)
        print(f"Le fichier {output_file} a été créé avec succès.")

if __name__ == "__main__":
    main()