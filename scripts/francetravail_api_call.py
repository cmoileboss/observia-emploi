import os
import requests
from dotenv import load_dotenv
import pandas as pd


base_url = "https://api.francetravail.io/partenaire/offresdemploi"
access_token_url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
get_offers_url = f"{base_url}/v2/offres/search"

def get_access_token() -> str:
    response = requests.post(
        access_token_url,
        params={"realm": "/partenaire"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("CLIENT_ID"),
            "client_secret": os.getenv("SECRET_KEY"),
            "scope": "api_offresdemploiv2 o2dsoffre",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]

def search_offres_by_rome(code_rome: str):
    token = get_access_token()
    total_offers = []
    min_range = 0
    max_range = 149
    while True:
        response = requests.get(
            get_offers_url,
            headers={
                "Authorization": f"Bearer {token}"},
            params={
                "codeROME": code_rome,
                "range": f"{min_range}-{max_range}",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            print(f"Erreur lors de la récupération des offres pour le code ROME {code_rome} : {response.status_code} - {response.text}")
            break
        current_offers = response.json()
        if len(current_offers["resultats"]) < 150:
            if len(current_offers["resultats"]) == 0:
                break
            total_offers.extend(current_offers["resultats"])
            break
        total_offers.extend(current_offers["resultats"])
        min_range += 150
        max_range += 150

        content_range = response.headers.get("Content-Range")
        if content_range:
            total_count = int(content_range.split("/")[1])
            if min_range >= total_count:
                break
            if max_range >= total_count:
                max_range = total_count - 1
    return total_offers

def get_unique_rome_codes_from_csv_file():
    df = pd.read_csv("data/processed/formations_enriched.csv", sep=";")
    return df["code_rome"].unique().tolist()

if __name__ == "__main__":
    load_dotenv()
    rome_codes = get_unique_rome_codes_from_csv_file()
    print(f"Nombre de codes ROME uniques : {len(rome_codes)}")
    total_offres = 0
    for rome_code in rome_codes:
        print(f"Recherche des offres pour le code ROME : {rome_code}")
        offres = search_offres_by_rome(rome_code)
        total_offres += len(offres)
        print(f"Nombre d'offres trouvées pour le code ROME {rome_code} : {len(offres)}")
    print(f"Nombre total d'offres trouvées : {total_offres}")
