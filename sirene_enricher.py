import os
import time
import requests
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

INSEE_API_KEY = os.getenv("X-INSEE-Api-Key-Integration")
API_BASE_URL = "https://api.insee.fr/api-sirene/3.11/siret"
OUTPUT_COLUMNS = ["siret", "nom_entreprise", "enseigne", "adresse", "code_postal", "ville", "code_commune", "departement", "region", "statut"]
THROTTLE_SECONDS = 2

DEPT_TO_REGION = {
    "01": "Auvergne-Rhône-Alpes", "03": "Auvergne-Rhône-Alpes", "07": "Auvergne-Rhône-Alpes",
    "15": "Auvergne-Rhône-Alpes", "26": "Auvergne-Rhône-Alpes", "38": "Auvergne-Rhône-Alpes",
    "42": "Auvergne-Rhône-Alpes", "43": "Auvergne-Rhône-Alpes", "63": "Auvergne-Rhône-Alpes",
    "69": "Auvergne-Rhône-Alpes", "73": "Auvergne-Rhône-Alpes", "74": "Auvergne-Rhône-Alpes",
    "21": "Bourgogne-Franche-Comté", "25": "Bourgogne-Franche-Comté", "39": "Bourgogne-Franche-Comté",
    "58": "Bourgogne-Franche-Comté", "70": "Bourgogne-Franche-Comté", "71": "Bourgogne-Franche-Comté",
    "89": "Bourgogne-Franche-Comté", "90": "Bourgogne-Franche-Comté",
    "22": "Bretagne", "29": "Bretagne", "35": "Bretagne", "56": "Bretagne",
    "18": "Centre-Val de Loire", "28": "Centre-Val de Loire", "36": "Centre-Val de Loire",
    "37": "Centre-Val de Loire", "41": "Centre-Val de Loire", "45": "Centre-Val de Loire",
    "2A": "Corse", "2B": "Corse",
    "08": "Grand Est", "10": "Grand Est", "51": "Grand Est", "52": "Grand Est",
    "54": "Grand Est", "55": "Grand Est", "57": "Grand Est", "67": "Grand Est",
    "68": "Grand Est", "88": "Grand Est",
    "02": "Hauts-de-France", "59": "Hauts-de-France", "60": "Hauts-de-France",
    "62": "Hauts-de-France", "80": "Hauts-de-France",
    "75": "Île-de-France", "77": "Île-de-France", "78": "Île-de-France", "91": "Île-de-France",
    "92": "Île-de-France", "93": "Île-de-France", "94": "Île-de-France", "95": "Île-de-France",
    "14": "Normandie", "27": "Normandie", "50": "Normandie", "61": "Normandie", "76": "Normandie",
    "16": "Nouvelle-Aquitaine", "17": "Nouvelle-Aquitaine", "19": "Nouvelle-Aquitaine",
    "23": "Nouvelle-Aquitaine", "24": "Nouvelle-Aquitaine", "33": "Nouvelle-Aquitaine",
    "40": "Nouvelle-Aquitaine", "47": "Nouvelle-Aquitaine", "64": "Nouvelle-Aquitaine",
    "79": "Nouvelle-Aquitaine", "86": "Nouvelle-Aquitaine", "87": "Nouvelle-Aquitaine",
    "09": "Occitanie", "11": "Occitanie", "12": "Occitanie", "30": "Occitanie",
    "31": "Occitanie", "32": "Occitanie", "34": "Occitanie", "46": "Occitanie",
    "48": "Occitanie", "65": "Occitanie", "66": "Occitanie", "81": "Occitanie", "82": "Occitanie",
    "44": "Pays de la Loire", "49": "Pays de la Loire", "53": "Pays de la Loire",
    "72": "Pays de la Loire", "85": "Pays de la Loire",
    "04": "Provence-Alpes-Côte d'Azur", "05": "Provence-Alpes-Côte d'Azur",
    "06": "Provence-Alpes-Côte d'Azur", "13": "Provence-Alpes-Côte d'Azur",
    "83": "Provence-Alpes-Côte d'Azur", "84": "Provence-Alpes-Côte d'Azur",
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane", "974": "La Réunion", "976": "Mayotte",
}


def _departement_from_code_commune(code_commune: str | None) -> str | None:
    if not code_commune:
        return None
    code = str(code_commune)
    # DOM : codes communes à 5 chiffres commençant par 97x
    if code.startswith("97"):
        return code[:3]
    # Corse
    if code.startswith("2A") or code.startswith("2B"):
        return code[:2]
    return code[:2]


def extract_data_from_response(json_response: dict) -> dict:
    """Extrait les champs utiles depuis la réponse brute de l'API SIRENE."""
    etab = json_response.get("etablissement", {})
    unite = etab.get("uniteLegale", {})
    adresse = etab.get("adresseEtablissement", {})
    periodes = etab.get("periodesEtablissement", [])

    # Nom entreprise
    nom = unite.get("denominationUniteLegale")
    if not nom:
        nom_parts = [unite.get("nomUniteLegale"), unite.get("prenom1UniteLegale")]
        nom = " ".join(p for p in nom_parts if p) or None

    # Enseigne (période la plus récente = index 0)
    enseigne = periodes[0].get("enseigne1Etablissement") if periodes else None

    # Adresse : ignorer les segments None
    adresse_parts = [
        adresse.get("numeroVoieEtablissement"),
        adresse.get("typeVoieEtablissement"),
        adresse.get("libelleVoieEtablissement"),
    ]
    adresse_str = " ".join(p for p in adresse_parts if p) or None

    code_commune = adresse.get("codeCommuneEtablissement")
    dept = _departement_from_code_commune(code_commune)
    region = DEPT_TO_REGION.get(dept) if dept else None

    return {
        "nom_entreprise": nom,
        "enseigne": enseigne,
        "adresse": adresse_str,
        "code_postal": adresse.get("codePostalEtablissement"),
        "ville": adresse.get("libelleCommuneEtablissement"),
        "code_commune": code_commune,
        "departement": dept,
        "region": region,
        "statut": "ok",
    }


def fetch_siret(siret: str, session: requests.Session) -> dict:
    """Appelle l'API SIRENE pour un SIRET et retourne un dict prêt à écrire."""
    base = {"siret": siret, "nom_entreprise": None, "enseigne": None, "adresse": None,
            "code_postal": None, "ville": None, "code_commune": None, "departement": None,
            "region": None, "statut": None}
    try:
        resp = session.get(
            f"{API_BASE_URL}/{siret}",
            headers={"X-INSEE-Api-Key-Integration": INSEE_API_KEY, "accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 404:
            return {**base, "statut": "not_found"}
        if resp.status_code != 200:
            return {**base, "statut": f"http_{resp.status_code}"}
        data = extract_data_from_response(resp.json())
        return {**base, **data, "siret": siret}
    except requests.exceptions.ConnectionError:
        return {**base, "statut": "network_error"}
    except (ValueError, KeyError) as e:
        return {**base, "statut": f"parse_error: {e}"}


def enrich(input_csv: str, output_csv: str) -> None:
    """Enrichit les SIRETs uniques du CSV d'entrée et écrit le résultat dans output_csv."""
    df = pd.read_csv(input_csv, sep=";", dtype={"siret_of_contractant": str})
    sirets = df["siret_of_contractant"].dropna().unique().tolist()
    print(f"{len(sirets)} SIRETs uniques à enrichir.")

    # Reprise : charger les SIRETs déjà traités
    already_done: set[str] = set()
    write_header = True
    if os.path.exists(output_csv):
        done_df = pd.read_csv(output_csv, sep=";", dtype={"siret": str})
        already_done = set(done_df["siret"].tolist())
        write_header = False
        print(f"Reprise : {len(already_done)} SIRETs déjà traités.")

    remaining = [s for s in sirets if s not in already_done]
    print(f"{len(remaining)} SIRETs restants.")

    session = requests.Session()
    with open(output_csv, mode="a", newline="", encoding="utf-8") as f:
        for i, siret in enumerate(tqdm(remaining, desc="Enrichissement SIRENE")):
            row = fetch_siret(siret, session)
            row_df = pd.DataFrame([row], columns=OUTPUT_COLUMNS)
            row_df.to_csv(f, sep=";", index=False, header=write_header)
            write_header = False  # header écrit une seule fois
            f.flush()
            if i < len(remaining) - 1:
                time.sleep(THROTTLE_SECONDS)

    print(f"Terminé. Résultat : {output_csv}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Enrichit les SIRETs via l'API INSEE SIRENE")
    parser.add_argument("--input", default="data/processed/merged_data.csv")
    parser.add_argument("--output", default="data/processed/organismes_enriched.csv")
    args = parser.parse_args()

    enrich(args.input, args.output)
