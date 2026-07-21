
"""Modèles SQLAlchemy liés aux formations et aux codes ROME."""

from sqlalchemy import Column, ForeignKey, Integer, String, Table, UniqueConstraint
from sqlalchemy.orm import relationship

from postgres_connection import Base


formation_rome_association = Table(
    "formation_rome",
    Base.metadata,
    Column("formation_id", Integer, ForeignKey("formations.id"), primary_key=True),
    Column("code_rome", String, ForeignKey("rome_code.code_rome"), primary_key=True),
)


class FormationModel(Base):
    """Représente une formation enrichie et ses métadonnées principales."""

    __tablename__ = "formations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    intitule_certification = Column(String)
    siret_of_contractant = Column(String)
    code_rncp = Column(String)
    raison_sociale_of_contractant = Column(String)
    niveau_rncp = Column(String)
    modalite = Column(String)
    nom_entreprise = Column(String)
    code_postal = Column(String)
    region = Column(String)
    commentaire = Column(String)

    __table_args__ = (
        UniqueConstraint(
            "intitule_certification",
            "siret_of_contractant",
            name="uq_formation_intitule_siret",
        ),
    )

    flux_mensuels = relationship(
        "FormationFluxMensuelModel",
        back_populates="formation",
        cascade="all, delete-orphan",
    )
    codes_rome = relationship(
        "RomeCodeModel",
        secondary=formation_rome_association,
        back_populates="formations",
    )
    offres = relationship("OffreModel", secondary="offre_formation", back_populates="formations")


class FormationFluxMensuelModel(Base):
    """Stocke les indicateurs mensuels associés à une formation."""

    __tablename__ = "formation_flux_mensuel"

    id = Column(Integer, primary_key=True, autoincrement=True)
    formation_id = Column(Integer, ForeignKey("formations.id"))
    annee = Column(Integer)
    mois = Column(Integer)
    entrees_formation = Column(Integer)
    sorties_realisation_partielle = Column(Integer)
    sorties_realisation_totale = Column(Integer)

    formation = relationship("FormationModel", back_populates="flux_mensuels")


class RomeCodeModel(Base):
    """Décrit un code ROME et les relations métier qui y sont rattachées."""

    __tablename__ = "rome_code"

    code_rome = Column(String, primary_key=True)
    intitule_rome = Column(String)

    formations = relationship(
        "FormationModel",
        secondary=formation_rome_association,
        back_populates="codes_rome",
    )
    offres = relationship("OffreModel", back_populates="rome")
