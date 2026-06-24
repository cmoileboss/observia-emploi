# Rapport de Rapprochement Expérimental Free-Work / France Travail

Ce document synthétise les résultats des expérimentations de rapprochement menées le 24/06/2026.

## 1. Statut du Lot Free-Work
* **Statut de l'intégration** : `SOURCE3_STATUS_UNKNOWN` (Prototype Expérimental).
* **Description** : L'intégration définitive de Free-Work en tant que Source 3 reste soumise à validation officielle. Le code et les tests associés sont livrés sous forme de prototype.

## 2. Données testées
* **Lot historique Free-Work** : 3 386 offres
* **Catalogue public collecté** (24/06/2026) : 8 457 offres uniques
* **Échantillon de benchmark stratifié** : 150 offres
* **Snapshot France Travail** : 33 805 offres

## 3. Résultats du Benchmark Stratifié (Valeurs Médianes avec Alias, S=150)

| Stratégie | Temps médian | Offres sans candidat |
| :--- | :---: | :---: |
| `independent_normalized` | **27,31 s** | **0 / 150 (0 %)** |
| `strict_chain` | **18,47 s** | **132 / 150 (88 %)** |
| `hybrid_cascade` | **23,97 s** | **0 / 150 (0 %)** |

## 4. Analyse de la Cascade et du Fallback (hybrid_cascade)
* **Attrition entreprise** : **113 offres sur 150** (75,33 %) perdent l'intégralité de leurs candidats dès le filtre entreprise (dû aux variations de saisie ou l'absence de noms d'entreprise).
* **Déclenchement du fallback** : **148 offres sur 150** (98,67 %) ont nécessité l'activation du fallback pour récupérer des candidats.
* **Accord de Top 1** : L'accord sur le meilleur candidat (Top 1) entre `independent_normalized` et `hybrid_cascade` s'élève à **96,0 %**.

## 5. Non-Régression (Cas de Calibration)
* **SAP SD/MM / Signe+** : Retrouvé au **rang 1** (Score : 85,14) dans toutes les stratégies.
* **Econocom** : Retrouvé au **rang 1** (Score : 92,23 avec alias, 86,33 sans alias).
* **Experis** : Retrouvé au **rang 1** (Score : 97,04) dans toutes les stratégies.
* **Faux positif IAM / comptabilité** : Exclu dans `strict_chain` et relégué au score de **37,05** (`WEAK_CANDIDATE`) dans `independent_normalized` et `hybrid_cascade`.

## 6. Limites de l'Évaluation
* **Effectif d'évaluation** : Seulement 3 cas positifs et 1 cas négatif ont été annotés manuellement.
* **Absence de métriques globales** : Il n'existe pas de preuve statistique d'un rappel ou d'une précision globale de 100 % sur l'ensemble du corpus.
* **Recommandation opérationnelle** : La chaîne stricte (`strict_chain`) est beaucoup trop restrictive pour être utilisée seule. La cascade hybride (`hybrid_cascade`) est intéressante pour les gains de vitesse mais reste expérimentale. La stratégie `independent_normalized` constitue le choix par défaut le plus robuste et le plus simple.

## 7. Décision technique
```text
KEEP_INDEPENDENT_NORMALIZED_AS_DEFAULT
KEEP_HYBRID_CASCADE_AS_EXPERIMENTAL
KEEP_STRICT_CHAIN_FOR_INTERNAL_DIAGNOSTICS_ONLY
```
*Note : Les outils de benchmark (`run_benchmarks.py`) et les fichiers de progression/sorties intermédiaires ont été exclus du versionnage et conservés uniquement en local.*
