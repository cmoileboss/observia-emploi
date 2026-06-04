
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Table
from sqlalchemy.orm import relationship

from postgres_connection import Base


offre_formation_association = Table(
    "francetravail_offre_formation",
    Base.metadata,
    Column("offre_id", String, ForeignKey("francetravail_offres.id"), primary_key=True),
    Column("formation_id", Integer, ForeignKey("francetravail_formations.id"), primary_key=True),
)


offre_competence_association = Table(
    "francetravail_offre_competence",
    Base.metadata,
    Column("offre_id", String, ForeignKey("francetravail_offres.id"), primary_key=True),
    Column("competence_id", Integer, ForeignKey("francetravail_competences.id"), primary_key=True),
)


class FTOffreModel(Base):
    __tablename__ = "francetravail_offres"

    id = Column(String, primary_key=True)
    intitule = Column(String)
    description = Column(String)
    lieu_code_postal = Column(String)
    rome_code = Column(String)
    rome_libelle = Column(String)
    appellation_libelle = Column(String)
    entreprise_nom = Column(String)

    formations = relationship("FTFormationModel", secondary=offre_formation_association, back_populates="offres")
    competences = relationship("FTCompetenceModel", secondary=offre_competence_association, back_populates="offres")


class FTFormationModel(Base):
    __tablename__ = "francetravail_formations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_formation = Column(String)
    domaine_libelle = Column(String)
    niveau_libelle = Column(String)
    commentaire = Column(String)
    exigence = Column(String)

    offres = relationship("FTOffreModel", secondary=offre_formation_association, back_populates="formations")


class FTCompetenceModel(Base):
    __tablename__ = "francetravail_competences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String)
    libelle = Column(String)
    exigence = Column(String)

    offres = relationship("FTOffreModel", secondary=offre_competence_association, back_populates="competences")