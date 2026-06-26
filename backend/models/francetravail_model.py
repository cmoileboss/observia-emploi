
from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import relationship

from postgres_connection import Base


offre_formation_association = Table(
    "offre_formation",
    Base.metadata,
    Column("offre_id", Integer, ForeignKey("offres.id"), primary_key=True),
    Column("formation_id", Integer, ForeignKey("formations.id"), primary_key=True),
)

offre_competence_association = Table(
    "offre_competence",
    Base.metadata,
    Column("offre_id", Integer, ForeignKey("offres.id"), primary_key=True),
    Column("competence_id", Integer, ForeignKey("competences.id"), primary_key=True),
)


class OffreModel(Base):
    """Représente une offre d'emploi importée depuis France Travail ou FreeWork."""

    __tablename__ = "offres"

    id = Column(Integer, primary_key=True, autoincrement=True)
    francetravail_id = Column(String, unique=True)
    freework_id = Column(String, unique=True)
    rome_code = Column(String, ForeignKey("rome_code.code_rome"))
    intitule = Column(String)
    description = Column(String)
    lieu_code_postal = Column(String)
    rome_libelle = Column(String)
    appellation_libelle = Column(String)
    entreprise_nom = Column(String)

    formations = relationship("FormationModel", secondary=offre_formation_association, back_populates="offres")
    competences = relationship("CompetenceModel", secondary=offre_competence_association, back_populates="offres")
    rome = relationship("RomeCodeModel", back_populates="offres")


class CompetenceModel(Base):
    """Représente une compétence associable à une offre d'emploi."""

    __tablename__ = "competences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String)
    libelle = Column(String)

    offres = relationship("OffreModel", secondary=offre_competence_association, back_populates="competences")
