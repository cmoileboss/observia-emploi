"""Enrichit les organismes via l'API SIRENE."""

import os
import time
import logging
from pathlib import Path
import requests
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv

from logging_config import configure_logging
from region_mapping import DEPARTMENT_TO_REGION

load_dotenv()

INSEE_API_KEY = os.getenv("X-INSEE-Api-Key-Integration")
API_BASE_URL = "https://api.insee.fr/api-sirene/3.11/siret"
OUTPUT_COLUMNS = [
    "siret",
    "nom_entreprise",
    "enseigne",
    "adresse",
    "code_postal",
    "ville",
    "code_commune",
    "departement",
    "region",
    "statut",
]
THROTTLE_SECONDS = 2

logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"

def _departement_from_code_commune(code_commune: str | None) -> str | None:
    """Déduit le code département à partir d'un code commune INSEE."""

    if not code_commune:
        return None
    code = str(code_commune)
    if code.startswith("97"):
        return code[:3]
    if code.startswith("2A") or code.startswith("2B"):
        return code[:2]
    return code[:2]


def extract_data_from_response(json_response: dict) -> dict:
    """Extrait les champs utiles depuis la réponse brute de l'API SIRENE."""
    etab = json_response.get("etablissement", {})
    unite = etab.get("uniteLegale", {})
    adresse = etab.get("adresseEtablissement", {})
    periodes = etab.get("periodesEtablissement", [])

    nom = unite.get("denominationUniteLegale")
    if not nom:
        nom_parts = [unite.get("nomUniteLegale"), unite.get("prenom1UniteLegale")]
        nom = " ".join(p for p in nom_parts if p) or None

    enseigne = periodes[0].get("enseigne1Etablissement") if periodes else None

    adresse_parts = [
        adresse.get("numeroVoieEtablissement"),
        adresse.get("typeVoieEtablissement"),
        adresse.get("libelleVoieEtablissement"),
    ]
    adresse_str = " ".join(p for p in adresse_parts if p) or None

    code_commune = adresse.get("codeCommuneEtablissement")
    dept = _departement_from_code_commune(code_commune)
    region = DEPARTMENT_TO_REGION.get(dept) if dept else None

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
    base = {
        "siret": siret,
        "nom_entreprise": None,
        "enseigne": None,
        "adresse": None,
        "code_postal": None,
        "ville": None,
        "code_commune": None,
        "departement": None,
        "region": None,
        "statut": None,
    }
    try:
        resp = session.get(
            f"{API_BASE_URL}/{siret}",
            headers={
                "X-INSEE-Api-Key-Integration": INSEE_API_KEY,
                "accept": "application/json",
            },
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
    logger.info("%s SIRETs uniques à enrichir.", len(sirets))

    already_done: set[str] = set()
    write_header = True
    if os.path.exists(output_csv):
        done_df = pd.read_csv(output_csv, sep=";", dtype={"siret": str})
        already_done = set(done_df["siret"].tolist())
        write_header = False
        logger.info("Reprise : %s SIRETs déjà traités.", len(already_done))

    remaining = [s for s in sirets if s not in already_done]
    logger.info("%s SIRETs restants.", len(remaining))

    session = requests.Session()
    with open(output_csv, mode="a", newline="", encoding="utf-8") as f:
        for i, siret in enumerate(tqdm(remaining, desc="Enrichissement SIRENE")):
            row = fetch_siret(siret, session)
            row_df = pd.DataFrame([row], columns=OUTPUT_COLUMNS)
            row_df.to_csv(f, sep=";", index=False, header=write_header)
            write_header = False
            f.flush()
            if i < len(remaining) - 1:
                time.sleep(THROTTLE_SECONDS)

    logger.info("Termine. Resultat : %s", output_csv)


if __name__ == "__main__":
    import argparse

    configure_logging()

    parser = argparse.ArgumentParser(
        description="Enrichit les SIRETs via l'API INSEE SIRENE"
    )
    parser.add_argument("--input", default="data/processed/merged_data.csv")
    parser.add_argument("--output", default="data/processed/organismes_enriched.csv")
    args = parser.parse_args()

    enrich(args.input, args.output)
