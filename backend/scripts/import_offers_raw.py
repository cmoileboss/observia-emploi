"""Importe les offres Free-Work depuis offers_raw.json vers la base de donnees.

Chaque entree du fichier a la structure :
    {
        "source_id": 655632,
        "matched_rome_queries": [...],
        "offer": { "title": ..., "description": ..., "location": {...},
                   "company": {...}, "skills": [...], ... }
    }

Usage :
    python import_offers_raw.py
    python import_offers_raw.py --file /chemin/custom/offers_raw.json
    python import_offers_raw.py --batch-size 500
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logging_config import configure_logging
from models.francetravail_model import CompetenceModel, OffreModel
from postgres_connection import SESSION_LOCAL
from repositories.correspondance_formation_repository import RomeCodeRepository
from repositories.francetravail_repository import CompetenceRepository, OffreRepository

BACKEND_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_JSON_PATH = BACKEND_ROOT / "data" / "raw" / "free_work" / "full_catalog" / "batches"
DEFAULT_BATCH_SIZE = 200

configure_logging()
logger = logging.getLogger(__name__)


def _map_item_to_model(item: dict) -> OffreModel:
    """Convertit un enregistrement Free-Work en OffreModel."""
    offer = item.get("offer", {})
    location = offer.get("location") or {}
    company = offer.get("company") or {}

    return OffreModel(
        freework_id=str(item["source_id"]),
        intitule=offer.get("title"),
        description=offer.get("description"),
        lieu_code_postal=location.get("postalCode"),
        entreprise_nom=company.get("name"),
    )


def _import_batch(batch: list[dict], db) -> tuple[int, int]:
    """Importe un lot d'offres ; retourne (importees, ignorees)."""
    offre_repo = OffreRepository(db)
    competence_repo = CompetenceRepository(db)
    rome_repo = RomeCodeRepository(db)

    imported = 0
    skipped = 0

    for item in batch:
        offer = item.get("offer", {})

        # Code ROME : premier code valide dans matched_rome_queries
        rome_code = None
        for code in item.get("matched_rome_queries") or []:
            if isinstance(code, str) and code.strip():
                rome_code = code.strip()
                break

        offre_model = _map_item_to_model(item)
        offre_model.rome_code = rome_code

        saved = offre_repo.create_offre(offre_model)

        if saved.id == offre_model.id:  # nouvelle offre (pas un doublon)
            imported += 1
        else:
            skipped += 1

        # Lier le code ROME si present
        if rome_code and saved.rome is None:
            saved.rome = rome_repo.get_or_create(rome_code, None)

        # Competences (skills Free-Work)
        for skill in offer.get("skills") or []:
            skill_code = str(skill.get("id", "")) or skill.get("slug")
            if not skill_code:
                continue
            competence = competence_repo.find_by_code(skill_code)
            if competence is None:
                competence = CompetenceModel(
                    code=skill_code,
                    libelle=skill.get("name"),
                )
                db.add(competence)
                db.flush()
            if competence not in saved.competences:
                saved.competences.append(competence)

    db.commit()
    return imported, skipped


def import_offers(json_path: Path, batch_size: int) -> None:
    """Charge le fichier JSON et insere les offres en base par lots."""
    if not json_path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {json_path}")

    logger.info("Chargement de %s ...", json_path)
    data: list[dict] = json.loads(json_path.read_text(encoding="utf-8"))

    if not isinstance(data, list):
        raise ValueError("Le fichier JSON doit etre une liste d'enregistrements.")

    total = len(data)
    logger.info("%d offre(s) trouvee(s).", total)

    total_imported = 0
    total_skipped = 0

    db = SESSION_LOCAL()
    try:
        with tqdm(total=total, desc="Import", unit="offre") as progress:
            for start in range(0, total, batch_size):
                batch = data[start: start + batch_size]
                imported, skipped = _import_batch(batch, db)
                total_imported += imported
                total_skipped += skipped
                progress.update(len(batch))
    finally:
        db.close()

    logger.info(
        "Import termine : %d inserees, %d doublons ignores (total traite : %d).",
        total_imported,
        total_skipped,
        total,
    )


def _resolve_default_path() -> Path:
    """Retourne le fichier offers_raw.json le plus recent dans les batches."""
    batches_dir = DEFAULT_JSON_PATH
    if not batches_dir.exists():
        return batches_dir / "offers_raw.json"
    batch_dirs = sorted(batches_dir.iterdir(), reverse=True)
    for d in batch_dirs:
        candidate = d / "offers_raw.json"
        if candidate.exists():
            return candidate
    return batches_dir / "offers_raw.json"


def parse_args() -> argparse.Namespace:
    """Parse les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(
        description="Importe offers_raw.json (Free-Work) dans la base de donnees."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Chemin vers le fichier JSON (defaut : batch le plus recent).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Nombre d'offres par lot (defaut : {DEFAULT_BATCH_SIZE}).",
    )
    return parser.parse_args()


def main() -> None:
    """Point d'entree principal."""
    args = parse_args()
    json_path = args.file or _resolve_default_path()
    logger.info("Fichier source : %s", json_path)
    import_offers(json_path=json_path, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
