
from sqlalchemy import Column, ForeignKey, Integer, String

from postgres_connection import Base


class CorrespondanceFormationModel(Base):
    __tablename__ = "correspondance_formation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    annee = Column(Integer)
    mois = Column(Integer)
    code_rncp = Column(String)
    intitule_certification = Column(String)
    siret_of_contractant = Column(String)
    raison_sociale_of_contractant = Column(String)
    entrees_formation = Column(Integer)
    sorties_realisation_partielle = Column(Integer)
    sorties_realisation_totale = Column(Integer)
    code_rome = Column(String)
    intitule_rome = Column(String)
    niveau_rncp = Column(String)
    nom_entreprise = Column(String)
    code_postal = Column(String)
    region = Column(String)
    modalite = Column(String)
