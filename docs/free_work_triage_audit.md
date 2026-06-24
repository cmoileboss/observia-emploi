# Audit du Triage Complet Free-Work vs France Travail

Ce document décrit la méthodologie, les résultats et la structure des fichiers d'audit produits lors du rapprochement du catalogue complet Free-Work (8 457 offres) avec le snapshot France Travail (33 805 offres).

---

## 1. Objectif du Triage

L'objectif métier est d'identifier de manière fiable et hors-ligne les offres issues de Free-Work à importer, en évitant toute pollution de la base de données existante. Le triage classe chaque offre dans l'un des 4 compartiments :
1. **Doublons à forte confiance** : Déjà présents dans France Travail, à exclure de manière préventive pour éviter les imports de doublons.
2. **Nouvelles offres probables** : Prêtes pour un import futur contrôlé.
3. **Cas ambigus** : À soumettre à un arbitrage humain.
4. **Erreurs de traitement** : À analyser en diagnostic technique.

---

## 2. Méthode de Rapprochement : `independent_normalized`

La stratégie retenue pour ce triage est **`independent_normalized`** avec gestion des alias d'entreprises. 
Cette méthode standardise au préalable les champs (titre, entreprise, localisation) via un module de normalisation commun, puis interroge des index inversés indépendants (par code postal, département, code ROME, entreprise, tokens de titre, et jetons rares) pour rassembler des candidats. 

Chaque candidat est ensuite évalué sur un score global de **100 points maximum**, découpé comme suit :
* **Titre (45 pts)** : Mesure la similarité de séquence, Jaccard des tokens, similarité pondérée par IDF et similarité des clés compactes.
* **Description (25 pts)** : Jaccard de tokens et similarité pondérée par IDF (uniquement si la description est présente).
* **Entreprise (10 pts)** : Similarité de chaîne avec correction par dictionnaire d'alias (ex: `experis france` -> `experis`).
* **Géographie (15 pts)** : Code postal exact (15 pts) ou même département (8 pts).
* **ROME (5 pts)** : Bonus si le code ROME correspond aux critères de recherche.

---

## 3. Les Quatre Catégories de Triage

* **`DUPLICATE_HIGH_CONFIDENCE`** : Offre avec une similarité extrême (empreinte exacte de titre, code postal, entreprise et/ou description, ou score > 75 avec entreprise et titre concordants).
* **`PROBABLY_NEW`** : Offre n'ayant généré aucun candidat ou dont le meilleur candidat possède un score inférieur à 30/100.
* **`HUMAN_REVIEW_REQUIRED`** : Offre dont la décision est trop incertaine pour être automatisée (score intermédiaire ou scores de candidats trop proches créant une ambiguïté).
* **`PROCESSING_ERROR`** : Offre ayant échoué à l'étape de parsing ou de calcul.

---

## 4. Différence entre Candidat et Doublon

* **Candidat** : Une offre France Travail qui partage des caractéristiques (mots-clés, ROME, localisation) avec une offre Free-Work, constituant un match potentiel. Une offre Free-Work peut avoir jusqu'à 20 candidats détaillés.
* **Doublon** : Un candidat dont la similarité et la concordance des métadonnées (titre, entreprise, géographie) sont si fortes qu'il est hautement probable qu'il s'agisse de la **même offre d'emploi réelle**. Les doublons à forte confiance sont écartés préventivement.

---

## 5. Structure des Fichiers d'Audit

Le fichier maître d'audit est **`audit_results.json`**. Il structure les informations de manière uniforme :
* **`free_work`** : Détail complet de l'offre source Free-Work normalisée.
* **`triage`** : Catégorie finale, codes de règles appliquées, couverture des données et explication textuelle en français.
* **`best_france_travail_candidate`** : Détails du meilleur match France Travail trouvé (avec breakdown de score et liste de preuves).
* **`alternative_candidates`** : Liste ordonnée des candidats alternatifs (max 3 pour les doublons/nouvelles, max 5 pour la revue humaine).
* **`human_review`** : Bloc vide réservé à la saisie de l'arbitrage (décision, commentaire, date).
* **`source_trace`** : Métadonnées de traçabilité (fichiers d'entrée, identifiants sources, run IDs, etc.).

Les fichiers `audit_duplicates_high_confidence.json`, `audit_probably_new.json` et `audit_human_review_required.json` sont des sous-ensembles stricts du fichier maître.

---

## 6. Méthode de Revue Humaine Priorisée

Pour faciliter le traitement des 6 397 cas ambigus, la file a été ordonnée par niveau de priorité (`HIGH`, `MEDIUM`, `LOW`) puis par score décroissant :
1. **`HIGH`** (916 offres) : Cas les plus critiques (scores élevés, marge infime entre le top 1 et le top 2, ou conflits d'entreprise/géographie).
2. **`MEDIUM`** (1 565 offres) : Cas intermédiaires avec des indices concordants mais insuffisants pour trancher automatiquement.
3. **`LOW`** (3 916 offres) : Cas à très faible score, classés en revue par simple prudence méthodologique.

La revue peut s'effectuer directement via le fichier CSV priorisé ou dans un outil tiers important le format standardisé.

---

## 7. Absence d'Import PostgreSQL

Conformément aux consignes de sécurité et d'architecture du projet, **aucune modification de base de données (PostgreSQL) n'est effectuée à cette étape**. Le triage produit uniquement des fichiers d'audit statiques et validés, permettant aux formateurs et administrateurs d'analyser le catalogue et de valider les imports avant toute persistance.

---

## 8. Limites Connues

* **Descriptions manquantes** : Pour les offres Free-Work dépourvues de description, le score est recalculé sur une base réduite (75 points max), ce qui peut faire basculer certaines offres en revue humaine par manque d'éléments textuels à comparer.
* **Dépendance au snapshot** : Le triage est réalisé par rapport au snapshot France Travail figé au 24/06/2026. Toute mise à jour majeure de la base France Travail nécessite de régénérer l'indexation.
