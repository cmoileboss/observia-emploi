# observia-emploi

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

User-agent : *
disallow: /me/*
disallow: /settings/*
disallow: /users/*
disallow: */jobs?query=*
Disallow: /*?
Allow: /*.css$
Allow: /*.js$

Sitemap: https://www.welcometothejungle.com/sitemaps/index.xml.gz

### CGU

https://www.welcometothejungle.com/fr/pages/terms

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
| Suppression de `intitule_rncp` | Redondant avec `intitule_certification` de `entree_sortie_formation` |
| Normalisation de `code_rncp` | Suppression du préfixe `RNCP` pour uniformisation avec `entree_sortie_formation` |

#### Merge

Jointure `inner` sur `code_rncp` : seules les certifications du secteur tech (présentes dans les deux fichiers) sont conservées.

**Réduction du volume de données :** > 749 000 lignes → ~4 700 lignes après nettoyage et merge.

### France Travail

Comme les fichiers csv contiennent les niveaux en entier mais l'API France Travail string, il faudra les convertir en entier. Cf l'enum NiveauRNCP.
A déterminer : les champs que l'on gardera.