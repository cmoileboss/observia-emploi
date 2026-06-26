"""Importe les formations enrichies depuis le CSV vers la base de données."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from logging_config import configure_logging
from models.correspondance_formation_model import FormationFluxMensuelModel, FormationModel
from postgres_connection import Base, engine
from postgres_connection import SESSION_LOCAL
from repositories.correspondance_formation_repository import FormationRepository, RomeCodeRepository

current_file = Path(__file__).resolve()
current_dir = current_file.parent

CSV_PATH = current_dir / ".." / "data" / "processed" / "formations_enriched.csv"

logger = logging.getLogger(__name__)


def to_int(value: str | None) -> int | None:
    """Convertit une valeur CSV en entier ou retourne None."""
    if value is None:
        return None
    cleaned_value = value.strip()
    if cleaned_value == "":
        return None
    return int(cleaned_value)


def import_formations_enriched() -> None:
    """Importe toutes les lignes du fichier formations_enriched.csv dans la base."""
    if not Path(CSV_PATH).exists():
        raise FileNotFoundError(f"Fichier introuvable : {CSV_PATH}")

    Base.metadata.create_all(bind=engine)

    # Lire toutes les lignes en mémoire pour pouvoir les grouper
    with Path(CSV_PATH).open("r", encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file, delimiter=";"))

    # Grouper par (intitule_certification, siret_of_contractant)
    formations_dict: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (row["intitule_certification"], row["siret_of_contractant"])
        formations_dict.setdefault(key, []).append(row)

    db = SESSION_LOCAL()
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
            logger.info(
                "Import de la formation : %s (SIRET: %s)",
                formation.intitule_certification,
                formation.siret_of_contractant,
            )
            seen_flux: set[tuple[int | None, int | None]] = set()
            seen_rome: set[str] = set()
            for row in group:
                flux_key = (to_int(row["annee"]), to_int(row["mois"]))
                if flux_key not in seen_flux:
                    seen_flux.add(flux_key)
                    formation.flux_mensuels.append(
                        FormationFluxMensuelModel(
                            annee=to_int(row["annee"]),
                            mois=to_int(row["mois"]),
                            entrees_formation=to_int(row["entrees_formation"]),
                            sorties_realisation_partielle=to_int(
                                row["sorties_realisation_partielle"]
                            ),
                            sorties_realisation_totale=to_int(
                                row["sorties_realisation_totale"]
                            ),
                        )
                    )
                    logger.info("  - Ajout du flux mensuel : %s", flux_key)

                rome_key = row["code_rome"]
                if rome_key and rome_key not in seen_rome:
                    seen_rome.add(rome_key)
                    rome = rome_repository.get_or_create(rome_key, row["intitule_rome"] or None)
                    formation.codes_rome.append(rome)
                    logger.info("  - Ajout du code ROME : %s", rome_key)
            repository.add(formation)
            db.commit()
            inserted_count += 1

        logger.info("%s formations importees dans la base.", inserted_count)
    finally:
        db.close()


if __name__ == "__main__":
    configure_logging()
    import_formations_enriched()
