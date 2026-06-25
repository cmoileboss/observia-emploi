# Classification ROME déterministe Free-Work

Ce document décrit la première version exploitable de l'affectation ROME déterministe des offres Free-Work.

## Statut

Le traitement est implémenté par `scripts/classify_free_work_rome.py`.

Il est déterministe, paramétrable par chemins d'entrée et de sortie, sans LLM, sans accès réseau, sans accès PostgreSQL et sans import applicatif.

## Commande finale validée

```powershell
.\.venv\Scripts\python.exe scripts\classify_free_work_rome.py `
  --free-work-input "data\processed\free_work\full_catalog\20260624_081715\offers_normalized.json" `
  --france-travail-input "data\processed\france_travail\snapshots\current\france_travail_offers_snapshot.json" `
  --triage-input "data\processed\matching\free_work_vs_france_travail\run_triage_v2_handoff_20260624\triage_decisions.jsonl" `
  --output-dir "data\processed\free_work\rome_classification\run_rome_deterministic_v1_final_20260625_133121"
```

## Baseline conservée

Le run initial `run_rome_deterministic_v1_20260624` reste la baseline de comparaison :

| Indicateur | Valeur |
| :--- | ---: |
| Offres traitées | 8 457 |
| `CONFIRMED_FROM_FT_MATCH` | 143 |
| `CANDIDATE_ONLY` | 3 086 |
| `REVIEW_REQUIRED` | 5 039 |
| `UNASSIGNED` | 189 |
| Top-1 accuracy | 0,4685 |
| Top-3 recall | 0,6084 |

Ce benchmark initial utilisait les profils construits sur tout le snapshot France Travail. Les offres France Travail appariées aux 143 références pouvaient donc contribuer aux profils évalués.

## Benchmark sans fuite

La V1 finale utilise un holdout global de référence pour éviter la fuite : les 143 offres France Travail appariées sont retirées simultanément des profils utilisés pour mesurer les 143 correspondances.

Les 143 correspondances restent un jeu de référence pratique, pas une vérité métier parfaite.

La séparation calibration / validation est déterministe, stratifiée par code ROME lorsque le volume le permet, avec la graine :

```text
observia-free-work-rome-v1-20260625
```

| Sous-ensemble | Taille | Auto-affectées | Précision observée | Couverture |
| :--- | ---: | ---: | ---: | ---: |
| Calibration | 97 | 10 | 1,0000 | 0,1031 |
| Validation | 46 | 6 | 1,0000 | 0,1304 |
| 143 références holdout | 143 | 16 | 1,0000 | 0,1119 |

## Configurations comparées

| Configuration | Top-1 holdout | Top-3 holdout | Décision |
| :--- | ---: | ---: | :--- |
| `BASELINE` | 0,4336 | 0,6014 | Conservée comme référence historique. |
| `DETERMINISTIC_V1_A` | 0,5175 | 0,6783 | Retenue. |
| `DETERMINISTIC_V1_B` | 0,4895 | 0,6783 | Rejetée : Top-1 inférieur à couverture Top-3 identique. |

`DETERMINISTIC_V1_A` est retenue parce qu'elle améliore le Top-1 et le Top-3 par rapport à la baseline, puis atteint 100 % de précision observée sur calibration et validation avec des seuils stricts.

## Score final

Formule :

```text
score = 65 * signal_titre + 10 * signal_compétences + 25 * signal_description + bonus_titre_exact
```

Paramètres retenus :

| Paramètre | Valeur |
| :--- | ---: |
| Poids titre | 65 |
| Poids compétences | 10 |
| Poids description | 25 |
| Bonus titre exact | 8 |
| Seuil score auto | 50 |
| Seuil marge auto | 20 |
| Ratio de filtrage des tokens communs | 0,35 |

Audit du score :

- le snapshot France Travail de référence ne fournit pas de compétences détaillées exploitables ;
- les compétences Free-Work sont donc comparées surtout à des tokens métier issus des libellés ROME/RNCP et des titres observés ;
- le poids des compétences est abaissé de 30 à 10 pour éviter de survaloriser un signal non symétrique ;
- les termes présents dans trop de profils ROME sont filtrés ;
- l'entreprise, la localisation, le salaire et le type de contrat ne sont jamais utilisés pour choisir le métier ROME ;
- les descriptions longues restent un signal secondaire et ne suffisent pas seules à affecter automatiquement un code.

## Statuts V1

| Statut | Signification |
| :--- | :--- |
| `CONFIRMED_FROM_FT_MATCH` | L'offre Free-Work fait partie des 143 correspondances certaines et reprend le code ROME France Travail apparié. |
| `AUTO_ASSIGNED_HIGH_CONFIDENCE` | Le premier candidat dépasse les seuils de score et de marge avec un signal discriminant. |
| `UNASSIGNED_AMBIGUOUS` | Plusieurs codes restent plausibles et trop proches ; `assigned_rome_code = null`. |
| `UNASSIGNED_INSUFFICIENT_SIGNAL` | Les signaux disponibles sont trop faibles ou trop génériques ; `assigned_rome_code = null`. |
| `PROCESSING_ERROR` | Traitement impossible pour l'offre. |

## Résultat final

| Indicateur | Valeur |
| :--- | ---: |
| Offres lues | 8 457 |
| Résultats produits | 8 457 |
| Identifiants uniques | 8 457 |
| Codes ROME candidats | 52 |
| `CONFIRMED_FROM_FT_MATCH` | 143 |
| `AUTO_ASSIGNED_HIGH_CONFIDENCE` | 664 |
| `UNASSIGNED_AMBIGUOUS` | 1 366 |
| `UNASSIGNED_INSUFFICIENT_SIGNAL` | 6 284 |
| `PROCESSING_ERROR` | 0 |
| Total avec ROME | 807 |
| Total sans ROME | 7 650 |
| Couverture finale | 0,0954 |

## Artefacts

| Artefact | Contenu |
| :--- | :--- |
| `rome_assignments_deterministic_v1.jsonl` | Fichier exploitable pour un futur import, une ligne par offre Free-Work. |
| `rome_classification_results.jsonl` | Copie compatible des résultats complets. |
| `rome_classification_manifest.json` | Version, configuration, hashes d'entrée, compteurs, seuils, précision et couverture. |
| `rome_classification_benchmark.json` | Comparaison des configurations, holdout, calibration, validation et confusions. |
| `rome_review_queue.csv` | Offres ambiguës, insuffisantes ou en erreur. |
| `rome_profiles_summary.json` | Synthèse des profils ROME construits. |
| `rome_classification_progress.json` | Progression, vitesse, ETA et heartbeat. |

Chaque ligne de `rome_assignments_deterministic_v1.jsonl` contient notamment `free_work_id`, `assignment_status`, `assigned_rome_code`, `assigned_rome_label`, `assignment_method`, `confidence_score`, `top_score`, `second_score`, `margin`, `independent_prediction`, `candidates`, `reasons` et `processing_error`.

## Limites

- Le classifieur reste hors ligne et ne décide pas l'import PostgreSQL.
- La précision mesurée repose sur seulement 143 correspondances de référence.
- Les 52 codes candidats proviennent des codes présents dans le snapshot France Travail local.
- Le snapshot France Travail actuel ne contient pas les compétences détaillées des offres.
- Les offres ambiguës ou insuffisamment documentées restent volontairement sans code ROME.
