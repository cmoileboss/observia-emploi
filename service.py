from sqlalchemy.orm import Session

from models.correspondance_formation_model import FormationModel
from repositories.correspondance_formation_repository import FormationRepository, RomeCodeRepository
from repositories.francetravail_repository import FTOffreRepository

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


class Service():
    def __init__(self, db: Session):
        self.offre_repository = FTOffreRepository(db)
        self.formation_repository = FormationRepository(db)
        self.rome_repository = RomeCodeRepository(db)

    def count_formation_entries_by_region_and_quarter(self):
        """Retourne le nombre d'entrées de formation par région et par trimestre."""
        nb_offers = self.offre_repository.count_offres()
        formations = self.formation_repository.get_all()
        result = {formation.region: {} for formation in formations}       
        for formation in formations:
            flux_mensuels = formation.flux_mensuels
            for flux in flux_mensuels:
                quarter = (flux.mois - 1) // 3 + 1
                quarter_str = f"{flux.annee}-T{quarter}"
                if quarter_str not in result[formation.region]:
                    result[formation.region][quarter_str] = 0
                result[formation.region][quarter_str] += flux.entrees_formation

        offres_by_region: dict[str, int] = {}
        for code_postal, count in self.offre_repository.count_offres_by_code_postal():
            region = self.get_region_by_code_postal(code_postal)
            if region:
                offres_by_region[region] = offres_by_region.get(region, 0) + count

        grand_total = sum(sum(quarters.values()) for quarters in result.values())
        sorted_result = {
            region: {
                **dict(sorted(quarters.items())),
                "total": sum(quarters.values()),
                "nb_offres_france_travail": offres_by_region.get(region, 0),
            }
            for region, quarters in sorted(result.items())
        }
        sorted_result["Total des entrées en formation"] = grand_total
        sorted_result["Nombre d'offres France Travail trouvées"] = nb_offers
        return sorted_result

    def get_region_by_code_postal(self, code_postal: str) -> str | None:
        """Retourne la région correspondant à un code postal français."""
        code_postal = code_postal.strip().upper()
        # DOM-TOM : codes à 5 chiffres commençant par 971-976
        for prefix in ("971", "972", "973", "974", "976"):
            if code_postal.startswith(prefix):
                return _DEPARTEMENT_TO_REGION.get(prefix)
        dept = code_postal[:2]
        return _DEPARTEMENT_TO_REGION.get(dept)

    def get_formations_by_offre_id(self, offre_id: str) -> list[FormationModel]:
        """Retourne les formations liées au code ROME d'une offre France Travail."""
        offre = self.offre_repository.get_by_id(offre_id)
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
            for offre_competence in offre.offre_competences:
                competence = offre_competence.competence
                if competence:
                    skill_count[competence.libelle] = skill_count.get(competence.libelle, 0) + 1
        return dict(sorted(skill_count.items()))