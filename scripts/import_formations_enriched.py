from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.correspondance_formation_model import FormationModel, FormationFluxMensuelModel, RomeCodeModel
from postgres_connection import Base, SessionLocal, engine
from repositories.correspondance_formation_repository import FormationRepository, RomeCodeRepository


CSV_PATH = PROJECT_ROOT / "data" / "processed" / "formations_enriched.csv"


def to_int(value: str | None) -> int | None:
    """Convertit une valeur CSV en entier ou retourne None."""
    if value is None:
        return None
    cleaned_value = value.strip()
    if cleaned_value == "":
        return None
    return int(cleaned_value)


def main() -> None:
    """Importe toutes les lignes du fichier formations_enriched.csv dans la base."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Fichier introuvable : {CSV_PATH}")

    Base.metadata.create_all(bind=engine)

    # Lire toutes les lignes en mémoire pour pouvoir les grouper
    with CSV_PATH.open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file, delimiter=";"))

    # Grouper par (intitule_certification, siret_of_contractant)
    formations_dict: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (row["intitule_certification"], row["siret_of_contractant"])
        formations_dict.setdefault(key, []).append(row)

    db = SessionLocal()
    inserted_count = 0
    try:
        repository = FormationRepository(db)
        rome_repository = RomeCodeRepository(db)

        for (intitule, siret), group in formations_dict.items():
            if repository.exists_by_intitule_and_siret(intitule, siret):
                continue

            first = group[0]
            formation = FormationModel(
                intitule_certification=intitule,
                siret_of_contractant=siret,
                code_rncp=first["code_rncp"] or None,
                raison_sociale_of_contractant=first["raison_sociale_of_contractant"] or None,
                niveau_rncp=first["niveau_rncp"] or None,
                modalite=first["modalite"] or None,
                nom_entreprise=first["nom_entreprise"] or None,
                code_postal=first["code_postal"] or None,
                region=first["region"] or None,
            )
            print(f"Import de la formation : {formation.intitule_certification} (SIRET: {formation.siret_of_contractant})")
            seen_flux: set[tuple] = set()
            seen_rome: set[str] = set()
            for row in group:
                flux_key = (to_int(row["annee"]), to_int(row["mois"]))
                if flux_key not in seen_flux:
                    seen_flux.add(flux_key)
                    formation.flux_mensuels.append(FormationFluxMensuelModel(
                        annee=to_int(row["annee"]),
                        mois=to_int(row["mois"]),
                        entrees_formation=to_int(row["entrees_formation"]),
                        sorties_realisation_partielle=to_int(row["sorties_realisation_partielle"]),
                        sorties_realisation_totale=to_int(row["sorties_realisation_totale"]),
                    ))
                    print(f"  - Ajout du flux mensuel : {flux_key}")

                rome_key = row["code_rome"]
                if rome_key and rome_key not in seen_rome:
                    seen_rome.add(rome_key)
                    rome = rome_repository.get_or_create(rome_key, row["intitule_rome"] or None)
                    formation.codes_rome.append(rome)
                    print(f"  - Ajout du code ROME : {rome_key}")
            repository.add(formation)
            db.commit()
            inserted_count += 1

        print(f"{inserted_count} formations importées dans la base.")
    finally:
        db.close()


if __name__ == "__main__":
    main()