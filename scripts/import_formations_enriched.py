from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.correspondance_formation_model import CorrespondanceFormationModel
from postgres_connection import Base, SessionLocal, engine
from repositories.correspondance_formation_repository import CorrespondanceFormationRepository


CSV_PATH = PROJECT_ROOT / "data" / "processed" / "formations_enriched.csv"


def to_int(value: str | None) -> int | None:
    """Convertit une valeur CSV en entier ou retourne None."""
    if value is None:
        return None
    cleaned_value = value.strip()
    if cleaned_value == "":
        return None
    return int(cleaned_value)


def build_correspondance(row: dict[str, str]) -> CorrespondanceFormationModel:
    """Construit une correspondance formation a partir d'une ligne CSV."""
    return CorrespondanceFormationModel(
        annee=to_int(row.get("annee")),
        mois=to_int(row.get("mois")),
        code_rncp=row.get("code_rncp") or None,
        intitule_certification=row.get("intitule_certification") or None,
        siret_of_contractant=row.get("siret_of_contractant") or None,
        raison_sociale_of_contractant=row.get("raison_sociale_of_contractant") or None,
        entrees_formation=to_int(row.get("entrees_formation")),
        sorties_realisation_partielle=to_int(row.get("sorties_realisation_partielle")),
        sorties_realisation_totale=to_int(row.get("sorties_realisation_totale")),
        code_rome=row.get("code_rome") or None,
        intitule_rome=row.get("intitule_rome") or None,
        niveau_rncp=row.get("niveau_rncp") or None,
        nom_entreprise=row.get("nom_entreprise") or None,
        code_postal=row.get("code_postal") or None,
        region=row.get("region") or None,
        modalite=row.get("modalite") or None,
    )


def main() -> None:
    """Importe toutes les lignes du fichier formations_enriched.csv dans la base."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Fichier introuvable : {CSV_PATH}")

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    inserted_count = 0
    try:
        repository = CorrespondanceFormationRepository(db)

        with CSV_PATH.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file, delimiter=";")
            for row in reader:
                correspondance = build_correspondance(row)
                repository.create_correspondance(correspondance)
                inserted_count += 1

        print(f"{inserted_count} lignes importees dans correspondance_formation.")
    finally:
        db.close()


if __name__ == "__main__":
    main()