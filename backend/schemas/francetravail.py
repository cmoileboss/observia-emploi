from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LieuTravailSchema(BaseModel):
    """Décrit le lieu d'exercice d'une offre d'emploi."""

    model_config = ConfigDict(populate_by_name=True)

    libelle: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    code_postal: str | None = Field(None, alias="codePostal")
    commune: str | None = None


class EntrepriseSchema(BaseModel):
    """Décrit l'entreprise associée à une offre d'emploi."""

    model_config = ConfigDict(populate_by_name=True)

    nom: str | None = None
    description: str | None = None
    logo: str | None = None
    url: str | None = None
    entreprise_adaptee: bool | None = Field(None, alias="entrepriseAdaptee")


class SalaireSchema(BaseModel):
    """Décrit les informations de rémunération d'une offre."""

    model_config = ConfigDict(populate_by_name=True)

    libelle: str | None = None
    commentaire: str | None = None
    complement1: str | None = None
    complement2: str | None = None
    liste_complements: list | None = Field(None, alias="listeComplements")


class FormationSchema(BaseModel):
    """Décrit une formation exigée ou souhaitée par une offre."""

    model_config = ConfigDict(populate_by_name=True)

    code_formation: str | None = Field(None, alias="codeFormation")
    domaine_libelle: str | None = Field(None, alias="domaineLibelle")
    niveau_libelle: str | None = Field(None, alias="niveauLibelle")
    commentaire: str | None = None
    exigence: str | None = None


class LangueSchema(BaseModel):
    """Décrit une exigence linguistique d'une offre."""

    model_config = ConfigDict(populate_by_name=True)

    libelle: str | None = None
    exigence: str | None = None


class PermisSchema(BaseModel):
    """Décrit une exigence de permis de conduire."""

    model_config = ConfigDict(populate_by_name=True)

    libelle: str | None = None
    exigence: str | None = None


class CompetenceSchema(BaseModel):
    """Décrit une compétence attendue pour une offre."""

    model_config = ConfigDict(populate_by_name=True)

    code: str | None = None
    libelle: str | None = None
    exigence: str | None = None


class OffreEmploiSchema(BaseModel):
    """Modélise une offre d'emploi renvoyée par l'API France Travail."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    intitule: str | None = None
    description: str | None = None
    date_creation: datetime | None = Field(None, alias="dateCreation")
    date_actualisation: datetime | None = Field(None, alias="dateActualisation")
    lieu_travail: LieuTravailSchema | None = Field(None, alias="lieuTravail")
    rome_code: str | None = Field(None, alias="romeCode")
    rome_libelle: str | None = Field(None, alias="romeLibelle")
    appellation_libelle: str | None = Field(None, alias="appellationLibelle")
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
    duree_travail_libelle_converti: str | None = Field(None, alias="dureeTravailLibelleConverti")
    complement_exercice: str | None = Field(None, alias="complementExercice")
    condition_exercice: str | None = Field(None, alias="conditionExercice")
    alternance: bool | None = None
    contact: dict | None = None
    agence: dict | None = None
    nombre_postes: int | None = Field(None, alias="nombrePostes")
    accessible_th: bool | None = Field(None, alias="accessibleTH")
    deplacement_code: str | None = Field(None, alias="deplacementCode")
    deplacement_libelle: str | None = Field(None, alias="deplacementLibelle")
    qualification_code: str | None = Field(None, alias="qualificationCode")
    qualification_libelle: str | None = Field(None, alias="qualificationLibelle")
    code_naf: str | None = Field(None, alias="codeNAF")
    secteur_activite: str | None = Field(None, alias="secteurActivite")
    secteur_activite_libelle: str | None = Field(None, alias="secteurActiviteLibelle")
    qualites_professionnelles: list[dict] | None = Field(None, alias="qualitesProfessionnelles")
    tranche_effectif_etab: str | None = Field(None, alias="trancheEffectifEtab")
    origine_offre: dict | None = Field(None, alias="origineOffre")
    offres_manque_candidats: bool | None = Field(None, alias="offresManqueCandidats")
    contexte_travail: dict | None = Field(None, alias="contexteTravail")
    entreprise_adaptee: bool | None = Field(None, alias="entrepriseAdaptee")
    employeur_handi_engage: bool | None = Field(None, alias="employeurHandiEngage")


class RechercheOffresResponse(BaseModel):
    """Encapsule la liste des offres renvoyées par une recherche."""

    model_config = ConfigDict(populate_by_name=True)

    resultats: list[OffreEmploiSchema] = []
