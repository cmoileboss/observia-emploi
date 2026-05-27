# observia-emploi

## Sources de données

### API France Travail

Lien : https://www.francetravail.io

### Mon Compte Formation

Fichiers CSV exportés depuis Mon Compte Formation (data.gouv.fr).

#### `correspondance-rome-rncp-tech-*.csv`

Table de correspondance entre les référentiels métiers et certifications. Colonnes :

- `code_rome` — code du métier dans le référentiel ROME (France Travail)
- `intitule_rome` — libellé du métier ROME
- `code_rncp` — code de la certification dans le Répertoire National des Certifications Professionnelles
- `intitule_rncp` — intitulé de la certification
- `niveau_rncp` — niveau de qualification (NIV3 = CAP/BEP → NIV8 = Doctorat)

#### `entree_sortie_formation.csv`

Statistiques mensuelles d'entrées et sorties en formation par certification. Colonnes :

- `annee_mois`, `annee`, `mois` — période concernée
- `type_referentiel` — type de référentiel (`RNCP` ou `RS`)
- `code_rncp`, `code_rs`, `code_certifinfo` — identifiants de la certification selon le référentiel
- `intitule_certification` — nom de la certification
- `siret_of_contractant`, `raison_sociale_of_contractant` — organisme de formation
- `entrees_formation` — nombre d'entrées en formation sur la période
- `sorties_realisation_partielle` — nombre de sorties avant la fin de la formation
- `sorties_realisation_totale` — nombre de sorties après complétion de la formation
- `date_chargement` — date de mise à jour de la donnée

### Welcome To The Jungle

Site :https://www.welcometothejungle.com/fr

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