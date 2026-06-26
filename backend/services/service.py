from http.client import BAD_REQUEST
import logging
import os
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from logging_config import configure_logging
from scripts.francetravail_api_call import get_unique_rome_codes_from_csv_file, search_offres_by_rome
from scripts.import_formations_enriched import import_formations_enriched
from models.correspondance_formation_model import FormationModel
from repositories.correspondance_formation_repository import FormationRepository, RomeCodeRepository
from repositories.francetravail_repository import OffreRepository

configure_logging()
logger = logging.getLogger(__name__)

_DEPARTEMENT_TO_REGION: dict[str, str] = {
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
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane",
    "974": "La Réunion", "976": "Mayotte",
}


def _normalize_region(region: str | None) -> str:
    """Normalise un libellé de région pour les filtres et clés d'agrégation."""
    if not isinstance(region, str):
        return "regioninconnue"

    cleaned_region = region.strip().lower()
    cleaned_region = cleaned_region.replace("-", "").replace("'", "").replace(" ", "")
    return cleaned_region or "regioninconnue"


REGIONS: list[str] = sorted({_normalize_region(region) for region in _DEPARTEMENT_TO_REGION.values()})


class Service():
    """Regroupe les opérations métier exposées par l'API principale."""

    def __init__(self, db: Session):
        """Initialise les repositories utilisés par les traitements métier."""

        self.offre_repository = OffreRepository(db)
        self.formation_repository = FormationRepository(db)
        self.rome_repository = RomeCodeRepository(db)

    @staticmethod
    def _normalize_region(region: str | None) -> str:
        """Retourne un libellé exploitable pour les régions manquantes."""
        return _normalize_region(region)

    def count_formation_entries_by_region_and_quarter(self, region: str | None = None, quarter: str | None = None) -> dict[str, dict[str, dict[str, int] | int] | int]:
        """Retourne le nombre d'entrées de formation par région et par trimestre."""
        if region and region not in REGIONS:
            raise HTTPException(status_code=BAD_REQUEST, detail=f"Région invalide : {region}. Les régions valides sont : {', '.join(REGIONS)}")
        if quarter and not re.fullmatch(r"\d{4}-T[1-4]", quarter):
            raise HTTPException(status_code=BAD_REQUEST, detail=f"Trimestre invalide : {quarter}. Format attendu : YYYY-T1 a YYYY-T4")

        selected_region = region
        selected_quarter = quarter
        nb_offers = self.offre_repository.count_offres()
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
                result[formation_region][quarter_str]["sorties_realisation_partielle"] += flux.sorties_realisation_partielle or 0
                result[formation_region][quarter_str]["sorties_realisation_totale"] += flux.sorties_realisation_totale or 0

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
                    quarter_values["entrees_formation"] for quarter_values in quarters.values()
                ),
                "Total des sorties en réalisation partielle pour les trimestres choisis": sum(
                    quarter_values["sorties_realisation_partielle"] for quarter_values in quarters.values()
                ),
                "Total des sorties en réalisation totale pour les trimestres choisis": sum(
                    quarter_values["sorties_realisation_totale"] for quarter_values in quarters.values()
                ),
                "Nombre d'offres dans la région": offres_by_region.get(region, 0),
            }
            for region, quarters in sorted(result.items())
        }
        if selected_region is None and selected_quarter is None:
            sorted_result["Total des entrées en formation dans toute la France"] = grand_total
            sorted_result["Nombre d'offres trouvées dans toute la France"] = nb_offers
        return sorted_result

    def get_region_by_code_postal(self, code_postal: str) -> str | None:
        """Retourne la région correspondant à un code postal français."""
        code_postal = code_postal.strip().upper()
        # DOM-TOM : codes à 5 chiffres commençant par 971-976
        for prefix in ("971", "972", "973", "974", "976"):
            if code_postal.startswith(prefix):
                return self._normalize_region(_DEPARTEMENT_TO_REGION.get(prefix))
        dept = code_postal[:2]
        return self._normalize_region(_DEPARTEMENT_TO_REGION.get(dept))

    def get_formations_by_offre_id(self, offre_id: str) -> list[FormationModel]:
        """Retourne les formations liées au code ROME d'une offre France Travail."""
        offre = self.offre_repository.get_by_francetravail_id(offre_id)
        if offre is None:
            return { "error": f"Aucune offre trouvée avec l'identifiant {offre_id}" }
        rome_formations = self.rome_repository.list_formations_by_rome(offre.rome_code)
        seen_ids = {f.id for f in offre.formations}
        merged = list(offre.formations) + [f for f in rome_formations if f.id not in seen_ids]
        return merged

    def get_best_skills(self):
        """Retourne les compétences les plus demandées dans les offres France Travail."""
        offres = self.offre_repository.get_all()
        skill_count: dict[str, int] = {}
        for offre in offres:
            for competence in offre.competences:
                if competence:
                    skill_count[competence.libelle] = skill_count.get(competence.libelle, 0) + 1
        return dict(sorted(((k, v) for k, v in skill_count.items() if v > 1), key=lambda x: x[1], reverse=True))

    def populate_database(self):
        """Initialise la base de données avec les données enrichies."""
        logger.info("Stockage des données enrichies dans la base de données sans démarrer l'API.")
        logger.info("=== Import des formations enrichies dans la base de données ===")
        import_formations_enriched()
        logger.info("=== Appel à l'API France Travail ===")
        rome_codes = get_unique_rome_codes_from_csv_file()
        logger.info("Nombre de codes ROME uniques : %s", len(rome_codes))
        for rome_code in rome_codes:
            search_offres_by_rome(rome_code)
        logger.info("Stockage des données terminé.")
