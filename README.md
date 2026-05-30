# observia-emploi

## Préparation du projet

### Environnement

Version Python utilisée : `3.13.13`

#### Création et activation d'un environnement virtuel

Sous PowerShell :

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

#### Définition des variables d'environnements

Créer le fichier `.env` à partir de l'exemple :

```powershell
Copy-Item .env.example .env
```

Il faut s'inscrire à l'API France Travail : https://www.francetravail.io et créer une application dans l'API offres-emploi.

Variables à renseigner dans `.env` :

- `CLIENT_ID` : identifiant de l'application créée dans l'API France Travail
- `SECRET_KEY` : clé secrète de l'application créée dans l'API France Travail
- `X-INSEE-Api-Key-Integration` : clé API utilisée pour récupérer les localisations des entreprises à partir de leur SIRET
- `RAW_DATA_FOLDER` : dossier contenant les données brutes, par défaut `data\raw` ; ce dossier doit être créé manuellement
- `PROCESSED_DATA_FOLDER` : dossier contenant les données traitées, par défaut `data\processed` ; ce dossier doit être créé manuellement
- `PROCESSED_DATA_FILE` : nom du fichier contenant la fusion des fichiers CSV de départ, par défaut `merged_data.csv`
- `DATABASE_NAME` : nom de la base de données PostgreSQL, par défaut `observia_emploi_db`
- `DATABASE_USER` : utilisateur PostgreSQL utilisé pour accéder à la base de données
- `DATABASE_PASSWORD` : mot de passe de l'utilisateur PostgreSQL utilisé pour accéder à la base de données

### Préparation des données

Mettre dans le dossier `RAW_DATA_FOLDER` les fichiers :
- `correspondance-rome-rncp-tech-6a16c0f17343f806639940.csv` et
- `entree_sortie_formation.csv`.

### Lancement du projet

En cours d'amélioration
Il faudrait dans l'ordre :
- lancer le script de nettoyage et de fusion des deux fichiers de départ,
- lancer le script d'enrichissement avec les localisations supposées des formations,
- lancer le script de récupération des offres France Travail (API France Travail),
- lancer le programme avec python main.py.

## Sources de données

### API France Travail

Lien : https://www.francetravail.io
Doc API : https://francetravail.io/produits-partages/catalogue/offres-emploi/documentation#/api-reference/

### Mon Compte Formation

Fichiers CSV exportés depuis Mon Compte Formation (data.gouv.fr).

#### `correspondance-rome-rncp-tech-*.csv`

Table de correspondance entre les référentiels métiers et certifications. Colonnes :

- `code_rome` - code du métier dans le référentiel ROME (France Travail)
- `intitule_rome` - libellé du métier ROME
- `code_rncp` - code de la certification dans le Répertoire National des Certifications Professionnelles
- `intitule_rncp` - intitulé de la certification
- `niveau_rncp` - niveau de qualification (cf. NiveauRNCPEnum)

#### `entree_sortie_formation.csv`

Statistiques mensuelles d'entrées et sorties en formation par certification. Colonnes :

- `annee_mois`, `annee`, `mois` - période concernée
- `type_referentiel` - type de référentiel (`RNCP` ou `RS`)
- `code_rncp`, `code_rs`, `code_certifinfo` - identifiants de la certification selon le référentiel - `code_rncp` est à -1 dans un référentiel `RS` et inversement
- `intitule_certification` - nom de la certification
- `siret_of_contractant`, `raison_sociale_of_contractant` - organisme de formation
- `entrees_formation` - nombre d'entrées en formation sur la période
- `sorties_realisation_partielle` - nombre de sorties avant la fin de la formation
- `sorties_realisation_totale` - nombre de sorties après complétion de la formation
- `date_chargement` - date de mise à jour de la donnée

### Welcome To The Jungle

Site : https://www.welcometothejungle.com/fr

## Welcome To The Jungle

### robots.txt

Règles relevées :

```txt
User-agent: *
Disallow: /me/*
Disallow: /settings/*
Disallow: /users/*
Disallow: */jobs?query=*
Disallow: /*?
Allow: /*.css$
Allow: /*.js$
```

Sitemap : https://www.welcometothejungle.com/sitemaps/index.xml.gz

### CGU

Lien : https://www.welcometothejungle.com/fr/pages/terms

## Nettoyage des données

### Fichiers csv

#### `entree_sortie_formation.csv`

| Règle | Détail |
|---|---|
| Suppression des colonnes inutiles | `annee_mois` (redondant avec `annee` + `mois`), `type_referentiel`, `code_rs`, `code_certifinfo`, `date_chargement` (valeur unique) |
| Filtre sur le référentiel | Suppression des lignes `type_referentiel = RS` (code_rncp = -1), non joinables avec la table de correspondance |
| Filtre sur l'activité | Suppression des lignes avec `entrees_formation = 0` (aucune entrée en formation) |

#### `correspondance-rome-rncp-tech-*.csv`

| Règle | Détail |
|---|---|
| Normalisation de `code_rncp` | Suppression du préfixe `RNCP` pour uniformisation avec `entree_sortie_formation` |

#### Merge

Jointure `inner` sur `code_rncp` : seules les certifications du secteur tech (présentes dans les deux fichiers) sont conservées.

**Réduction du volume de données :** > 749 000 lignes → 4 997 lignes après nettoyage et merge.

### France Travail

Points d'attention :

- Les fichiers CSV stockent les niveaux sous forme d'entiers, tandis que l'API France Travail les expose sous forme de chaînes de caractères. Une conversion sera donc nécessaire pour aligner les données. Voir l'enum `NiveauRNCP`.
- Les champs gardés en base de données seront limités. Voir le schéma de la base de données.