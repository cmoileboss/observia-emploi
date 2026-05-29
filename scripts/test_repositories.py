from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.correspondance_formation_model import CorrespondanceFormationModel
from models.francetravail_model import CompetenceModel, FormationModel, FranceTravailModel
from postgres_connection import Base, SessionLocal, engine
from repositories.correspondance_formation_repository import CorrespondanceFormationRepository
from repositories.francetravail_repository import FranceTravailRepository


def main() -> None:
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        offre_repository = FranceTravailRepository(db)
        correspondance_repository = CorrespondanceFormationRepository(db)

        offre = FranceTravailModel(
            id=f"test-offre-{uuid4()}",
            intitule="Developpeur Python",
            description="Offre de test repository",
            lieu_code_postal="35000",
            rome_code="M1805",
            rome_libelle="Etudes et developpement informatique",
            appellation_libelle="Developpeur Python",
            entreprise_nom="Observia",
        )

        correspondance = CorrespondanceFormationModel(
            annee=2025,
            mois=5,
            code_rncp="RNCP37674",
            intitule_certification="Developpeur web et web mobile",
            siret_of_contractant="00000000000000",
            raison_sociale_of_contractant="Observia Formation",
            entrees_formation=10,
            sorties_realisation_partielle=1,
            sorties_realisation_totale=8,
            code_rome="M1805",
            intitule_rome="Etudes et developpement informatique",
            niveau_rncp="NIV5",
            nom_entreprise="Observia",
            code_postal="35000",
            region="Bretagne",
            modalite="presentiel",
        )

        formation = FormationModel(
            code_formation=f"RNCP-{uuid4()}",
            domaine_libelle="Informatique",
            niveau_libelle="Niveau 5",
            commentaire="Formation de test",
            exigence="souhaitee",
        )

        competence = CompetenceModel(
            code=f"COMP-{uuid4()}",
            libelle="Python",
            exigence="exigee",
        )

        offre_repository.create_offre(offre)
        correspondance_repository.create_correspondance(correspondance)
        offre_repository.attach_or_create_formation(offre, formation)
        offre_repository.attach_or_create_competence(offre, competence)

        print(f"Offre creee : {offre.id}")
        print(f"Correspondance creee : {correspondance.id}")
        print(f"Formation attachee : {offre.formations[0].code_formation}")
        print(f"Competence attachee : {offre.competences[0].code}")
    finally:
        db.close()


if __name__ == "__main__":
    main()