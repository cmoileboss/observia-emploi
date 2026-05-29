"""Pydantic schemas for normalising France Travail API job offers.

All fields use ``by_alias=True`` during serialisation so that the
camelCase API keys (e.g. ``romeCode``, ``dateCreation``) are preserved
in the exported JSON.

Security / privacy:
- ``description`` (raw), ``contact``, and ``agence`` are excluded from
  ``model_dump()`` via ``Field(exclude=True)``.
- ``description_clean`` holds an anonymised copy of the description with
  emails and phone numbers masked.
"""

import re
from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class LieuTravailSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    libelle: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    code_postal: str | None = Field(None, alias="codePostal")
    commune: str | None = None


class EntrepriseSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nom: str | None = None
    description: str | None = None
    logo: str | None = None
    url: str | None = None
    entreprise_adaptee: bool | None = Field(None, alias="entrepriseAdaptee")


class SalaireSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    libelle: str | None = None
    commentaire: str | None = None
    complement1: str | None = None
    complement2: str | None = None
    liste_complements: list | None = Field(None, alias="listeComplements")


class FormationSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code_formation: str | None = Field(None, alias="codeFormation")
    domaine_libelle: str | None = Field(None, alias="domaineLibelle")
    niveau_libelle: str | None = Field(None, alias="niveauLibelle")
    commentaire: str | None = None
    exigence: str | None = None


class LangueSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    libelle: str | None = None
    exigence: str | None = None


class PermisSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    libelle: str | None = None
    exigence: str | None = None


class CompetenceSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str | None = None
    libelle: str | None = None
    exigence: str | None = None


class OffreEmploiSchema(BaseModel):
    """Normalised representation of a single France Travail job offer.

    Fields excluded from export (will not appear in ``model_dump()``):
    - ``description`` — raw description (replaced by ``description_clean``)
    - ``contact`` — recruiter contact details
    - ``agence`` — agency metadata

    Dates are serialised as ISO-8601 strings via ``mode="json"``.
    Optional fields that are absent in the API response are preserved as
    ``null`` (``exclude_unset=False``, the Pydantic default).
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    intitule: str | None = None
    description: str | None = Field(None, exclude=True)
    description_clean: str | None = None
    date_creation: datetime | None = Field(None, alias="dateCreation")
    date_actualisation: datetime | None = Field(None, alias="dateActualisation")
    lieu_travail: LieuTravailSchema | None = Field(None, alias="lieuTravail")
    rome_code: str | None = Field(None, alias="romeCode")
    rome_libelle: str | None = Field(None, alias="romeLibelle")
    appellation_libelle: str | None = Field(
        None,
        validation_alias=AliasChoices("appellationlibelle", "appellationLibelle"),
        serialization_alias="appellationLibelle",
    )
    entreprise: EntrepriseSchema | None = None
    type_contrat: str | None = Field(None, alias="typeContrat")
    type_contrat_libelle: str | None = Field(None, alias="typeContratLibelle")
    nature_contrat: str | None = Field(None, alias="natureContrat")
    experience_exige: str | None = Field(None, alias="experienceExige")
    experience_libelle: str | None = Field(None, alias="experienceLibelle")
    experience_commentaire: str | None = Field(None, alias="experienceCommentaire")
    formations: list[FormationSchema] | None = None
    langues: list[LangueSchema] | None = None
    permis: list[PermisSchema] | None = None
    outils_bureautiques: list[str] | None = Field(None, alias="outilsBureautiques")
    competences: list[CompetenceSchema] | None = None
    salaire: SalaireSchema | None = None
    duree_travail_libelle: str | None = Field(None, alias="dureeTravailLibelle")
    duree_travail_libelle_converti: str | None = Field(
        None, alias="dureeTravailLibelleConverti"
    )
    complement_exercice: str | None = Field(None, alias="complementExercice")
    condition_exercice: str | None = Field(None, alias="conditionExercice")
    alternance: bool | None = None
    contact: dict | None = Field(None, exclude=True)
    agence: dict | None = Field(None, exclude=True)
    nombre_postes: int | None = Field(None, alias="nombrePostes")
    accessible_th: bool | None = Field(None, alias="accessibleTH")
    deplacement_code: str | None = Field(None, alias="deplacementCode")
    deplacement_libelle: str | None = Field(None, alias="deplacementLibelle")
    qualification_code: str | None = Field(None, alias="qualificationCode")
    qualification_libelle: str | None = Field(None, alias="qualificationLibelle")
    code_naf: str | None = Field(None, alias="codeNAF")
    secteur_activite: str | None = Field(None, alias="secteurActivite")
    secteur_activite_libelle: str | None = Field(None, alias="secteurActiviteLibelle")
    qualites_professionnelles: list[dict] | None = Field(
        None, alias="qualitesProfessionnelles"
    )
    tranche_effectif_etab: str | None = Field(None, alias="trancheEffectifEtab")
    origine_offre: dict | None = Field(None, alias="origineOffre")
    offres_manque_candidats: bool | None = Field(None, alias="offresManqueCandidats")
    contexte_travail: dict | None = Field(None, alias="contexteTravail")
    entreprise_adaptee: bool | None = Field(None, alias="entrepriseAdaptee")
    employeur_handi_engage: bool | None = Field(None, alias="employeurHandiEngage")

    @model_validator(mode="after")
    def anonymize_description(self) -> "OffreEmploiSchema":
        """Anonymise personally identifiable information in the raw description.

        Email addresses and phone numbers are replaced with masked placeholders.
        The unchanged description is kept in ``description`` (excluded from
        serialisation) and the sanitised version is stored in ``description_clean``.
        """
        if self.description:
            email_pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
            clean_text = re.sub(email_pattern, "[EMAIL MASQUÉ]", self.description)

            phone_pattern = (
                r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{1,4}\)?(?:[-.\s]?\d{2,4}){3,5}\b"
            )
            clean_text = re.sub(phone_pattern, "[TÉLÉPHONE MASQUÉ]", clean_text)

            self.description_clean = clean_text
        else:
            self.description_clean = None
        return self


class RechercheOffresResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    resultats: list[OffreEmploiSchema] = []
