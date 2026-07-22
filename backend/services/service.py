"""Services métier principaux de l'API Observia Emploi."""

from http.client import BAD_REQUEST
import logging
import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from logging_config import configure_logging
from models.correspondance_formation_model import FormationModel
from region_mapping import DEPARTMENT_TO_REGION

from repositories.correspondance_formation_repository import FormationRepository, RomeCodeRepository
from repositories.francetravail_repository import OffreRepository

from scripts.francetravail_api_call import (
    get_unique_rome_codes_from_csv_file,
    search_offres_by_rome,
)
from scripts.import_formations_enriched import import_formations_enriched
from scripts.collect_free_work_full_catalog import collecter_exhaustive
from scripts.import_offers_raw import import_offers
from scripts.create_output import create_output
from scripts.formations_enricher import FormationsEnricher


configure_logging()
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"

def _normalize_region(region: str | None) -> str:
    """Normalise un libellé de région pour les filtres et clés d'agrégation."""
    if not isinstance(region, str):
        return "regioninconnue"

    cleaned_region = region.strip().lower()
    cleaned_region = cleaned_region.replace("-", "").replace("'", "").replace(" ", "")
    return cleaned_region or "regioninconnue"


REGIONS: list[str] = sorted(
    {_normalize_region(region) for region in DEPARTMENT_TO_REGION.values()}
)


class Service:
    """Regroupe les opérations métier exposées par l'API principale."""

    def __init__(self, db: Session) -> None:
        """Initialise les repositories utilisés par les traitements métier."""

        self.offre_repository = OffreRepository(db)
        self.formation_repository = FormationRepository(db)
        self.rome_repository = RomeCodeRepository(db)

    @staticmethod
    def _normalize_region(region: str | None) -> str:
        """Retourne un libellé exploitable pour les régions manquantes."""
        return _normalize_region(region)

    def count_formation_entries_by_region_and_quarter(
        self,
        region: str | None = None,
        quarter: str | None = None,
    ) -> dict[str, dict[str, dict[str, int] | int] | int]:
        """Retourne le nombre d'entrées de formation par région et par trimestre."""
        if region and region not in REGIONS:
            raise HTTPException(
                status_code=BAD_REQUEST,
                detail=(
                    f"Région invalide : {region}. "
                    f"Les régions valides sont : {', '.join(REGIONS)}"
                ),
            )
        if quarter and not re.fullmatch(r"\d{4}-T[1-4]", quarter):
            raise HTTPException(
                status_code=BAD_REQUEST,
                detail=(
                    f"Trimestre invalide : {quarter}. "
                    "Format attendu : YYYY-T1 a YYYY-T4"
                ),
            )

        selected_region = region
        selected_quarter = quarter
        offer_count = self.offre_repository.count_offres()
        formations = self.formation_repository.get_all()
        result: dict[str, dict[str, dict[str, int]]] = {}
        for formation in formations:
            formation_region = self._normalize_region(formation.region)
            if selected_region and formation_region != selected_region:
                continue

            flux_mensuels = formation.flux_mensuels
            for flux in flux_mensuels:
                if flux.mois is None or flux.annee is None or flux.entrees_formation is None:
                    continue

                flux_quarter = (flux.mois - 1) // 3 + 1
                quarter_str = f"{flux.annee}-T{flux_quarter}"
                if selected_quarter and quarter_str != selected_quarter:
                    continue

                if formation_region not in result:
                    result[formation_region] = {}
                if quarter_str not in result[formation_region]:
                    result[formation_region][quarter_str] = {
                        "entrees_formation": 0,
                        "sorties_realisation_partielle": 0,
                        "sorties_realisation_totale": 0,
                    }
                result[formation_region][quarter_str]["entrees_formation"] += flux.entrees_formation
                quarter_result = result[formation_region][quarter_str]
                quarter_result["entrees_formation"] += flux.entrees_formation
                quarter_result["sorties_realisation_partielle"] += (
                    flux.sorties_realisation_partielle or 0
                )
                quarter_result["sorties_realisation_totale"] += (
                    flux.sorties_realisation_totale or 0
                )

        offres_by_region: dict[str, int] = {}
        for code_postal, count in self.offre_repository.count_offres_by_code_postal():
            offer_region = self.get_region_by_code_postal(code_postal)
            if offer_region and (selected_region is None or offer_region == selected_region):
                offres_by_region[offer_region] = offres_by_region.get(offer_region, 0) + count

        grand_total = sum(
            sum(quarter_values["entrees_formation"] for quarter_values in quarters.values())
            for quarters in result.values()
        )
        sorted_result = {
            region: {
                **dict(sorted(quarters.items())),
                "Total des entrées en formation pour les trimestres choisis": sum(
                    quarter_values["entrees_formation"]
                    for quarter_values in quarters.values()
                ),
                "Total des sorties en réalisation partielle pour les trimestres choisis": sum(
                    quarter_values["sorties_realisation_partielle"]
                    for quarter_values in quarters.values()
                ),
                "Total des sorties en réalisation totale pour les trimestres choisis": sum(
                    quarter_values["sorties_realisation_totale"]
                    for quarter_values in quarters.values()
                ),
                "Nombre d'offres dans la région": offres_by_region.get(region, 0),
            }
            for region, quarters in sorted(result.items())
        }
        if selected_region is None and selected_quarter is None:
            sorted_result["Total des entrées en formation dans toute la France"] = grand_total
            sorted_result["Nombre d'offres trouvées dans toute la France"] = offer_count
        return sorted_result

    def get_region_by_code_postal(self, code_postal: str) -> str | None:
        """Retourne la région correspondant à un code postal français."""
        code_postal = code_postal.strip().upper()
        # DOM-TOM : codes à 5 chiffres commençant par 971-976
        for prefix in ("971", "972", "973", "974", "976"):
            if code_postal.startswith(prefix):
                return self._normalize_region(DEPARTMENT_TO_REGION.get(prefix))
        dept = code_postal[:2]
        return self._normalize_region(DEPARTMENT_TO_REGION.get(dept))

    def get_formations_by_offre_id(
        self,
        offre_id: str,
    ) -> list[FormationModel] | dict[str, str]:
        """Retourne les formations liées au code ROME d'une offre France Travail."""
        offre = self.offre_repository.get_by_francetravail_id(offre_id)
        if offre is None:
            return {"error": f"Aucune offre trouvée avec l'identifiant {offre_id}"}
        rome_formations = self.rome_repository.list_formations_by_rome(offre.rome_code)
        seen_ids = {f.id for f in offre.formations}
        merged = list(offre.formations) + [f for f in rome_formations if f.id not in seen_ids]
        return merged

    def get_best_skills(self) -> dict[str, int]:
        """Retourne les compétences les plus demandées dans les offres France Travail."""
        offres = self.offre_repository.get_all()
        skill_count: dict[str, int] = {}
        for offre in offres:
            for competence in offre.competences:
                if competence:
                    skill_count[competence.libelle] = skill_count.get(competence.libelle, 0) + 1
        return dict(
            sorted(
                ((label, count) for label, count in skill_count.items() if count > 1),
                key=lambda item: item[1],
                reverse=True,
            )
        )

    def populate_database(self) -> None:
        """Initialise la base de données avec les données enrichies."""
        logger.info("=== Création du fichier de données fusionnées et nettoyées ===")
        create_output()
        logger.info("=== Enrichissement des données de formation ===")
        enricher = FormationsEnricher()
        enricher.load(
            merged_path=str(PROCESSED_DATA_ROOT / "merged_data.csv"),
            organismes_path=str(RAW_DATA_ROOT / "organismes_enriched.csv"),
            cdc_path=str(RAW_DATA_ROOT / "cdc_filtered_tech.csv"),
        )
        enricher.enrich()
        enricher.export(str(PROCESSED_DATA_ROOT / "formations_enriched.csv"))
        logger.info("=== Import des formations enrichies dans la base de données ===")
        import_formations_enriched()
        logger.info("=== Appel à l'API France Travail ===")
        rome_codes = get_unique_rome_codes_from_csv_file()
        logger.info("Nombre de codes ROME uniques : %s", len(rome_codes))
        for rome_code in rome_codes:
            search_offres_by_rome(rome_code)
        logger.info("=== Collecte des offres Free-Work ===")
        batch_id = collecter_exhaustive(
            delay_seconds=1.0,
            timeout_seconds=30,
            max_retries=3,
            max_pages=None,
            resume_batch_id=None,
        )
        offers_raw_path = (
            BACKEND_ROOT / "data" / "raw"
            / "free_work" / "full_catalog" / "batches" / batch_id / "offers_raw.json"
        )
        logger.info("=== Import des offres Free-Work en base ===")
        import_offers(json_path=offers_raw_path, batch_size=200)
        logger.info("Stockage des données terminé.")
