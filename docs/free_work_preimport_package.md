# Paquet pré-import consolidé Free-Work (Source 3)

Ce document décrit le fonctionnement du générateur hors ligne de paquet pré-import consolidé pour les offres Free-Work.

## 1. Concepts des ensembles et partitions d'identifiants

Afin de supporter les synchronisations incrémentales, le générateur classe les identifiants d'offres en quatre ensembles distincts et disjoints :
1. **`active_snapshot_ids`** : Les offres actuellement présentes dans le snapshot normalisé courant (`offers_normalized.json`).
2. **`process_ids`** : Les offres à traiter identifiées par le catalogue différentiel (`offers_to_process.json`), correspondant aux offres `NEW`, `UPDATED` ou `REACTIVATED`.
3. **`unchanged_ids`** : Les offres actives inchangées signalées par le catalogue différentiel (`unchanged_offer_ids.json`), correspondant aux offres `UNCHANGED`.
4. **`deactivation_ids`** : Les offres obsolètes à désactiver du catalogue différentiel (`offers_to_deactivate.json`), correspondant aux offres `INACTIVATED`.

### Invariants et inclusions d'ensembles :
* `process_ids ∩ unchanged_ids = ∅`
* `process_ids ∩ deactivation_ids = ∅`
* `unchanged_ids ∩ deactivation_ids = ∅`
* `process_ids ∪ unchanged_ids = active_snapshot_ids` (Les offres désactivées ne font pas partie de `active_snapshot_ids`).
* `process_ids ⊆ triage_ids` (Seules les offres à traiter requièrent une décision de triage).
* `process_ids ⊆ rome_ids` (Seules les offres à traiter requièrent une classification ROME).
* `triage_ids ⊆ active_snapshot_ids` et `rome_ids ⊆ active_snapshot_ids` (Le triage et le ROME peuvent couvrir tout ou partie du snapshot actif, mais aucune offre extérieure).

---

## 2. CLI

La commande cible s'exécute ainsi :

```powershell
.\.venv\Scripts\python.exe scripts\build_free_work_preimport_package.py `
  --catalog-sync-run-dir "data/processed/free_work/catalog_sync_validation_v2/runs/sync_bootstrap_20260625_validation" `
  --triage-run-dir "data/processed/matching/free_work_vs_france_travail/run_triage_v2_fresh_20260625_140527" `
  --rome-run-dir "data/processed/free_work/rome_classification/run_rome_deterministic_v1_final_20260625_133121" `
  --normalized-input "data/processed/free_work/full_catalog/20260624_081715/offers_normalized.json" `
  --output-dir "data/processed/free_work/preimport/run_preimport_v1_validation_20260625" `
  --run-id "run_preimport_v1_validation_20260625"
```

---

## 3. Matrice de Décision

| Décision de Triage | Action de Revue | Type de changement Catalogue | Action Pré-import Consolidée |
| :--- | :--- | :--- | :--- |
| `PRESENT_IN_FT_SNAPSHOT` | - | - | `ENRICH_EXISTING_FT` |
| `NOT_FOUND_IN_FT_SNAPSHOT` | - | `NEW` | `CREATE_FREE_WORK` |
| `NOT_FOUND_IN_FT_SNAPSHOT` | - | `UPDATED` | `UPDATE_FREE_WORK` |
| `NOT_FOUND_IN_FT_SNAPSHOT` | - | `REACTIVATED` | `REACTIVATE_FREE_WORK` |
| `UNCERTAIN` | `REVIEW_NOW` | `NEW` | `CREATE_FREE_WORK` |
| `UNCERTAIN` | `REVIEW_NOW` | `UPDATED` | `UPDATE_FREE_WORK` |
| `UNCERTAIN` | `REVIEW_NOW` | `REACTIVATED` | `REACTIVATE_FREE_WORK` |
| `UNCERTAIN` | `DEFER_DATA_INCOMPLETE` | - | `DEFER` |
| `PROCESSING_ERROR` | - | - | `REJECT` |
| - | - | `INACTIVATED` | `DEACTIVATE_FREE_WORK` |
| - | - | `UNCHANGED` | `NO_ACTION` |

---

## 4. Fichiers Produits

Le dossier de sortie contient la structure suivante :

* `offers_to_create.json` : Offres destinées à la création d'une publication Free-Work.
* `offers_to_update.json` : Offres destinées à la mise à jour.
* `offers_to_reactivate.json` : Offres destinées à la réactivation.
* `existing_ft_offers_to_enrich.json` : Offres à enrichir (en associant les compétences candidates sans écraser la donnée FT).
* `offers_to_defer.json` : Enregistrements différés pour audit.
* `offers_to_deactivate.json` : Opérations de désactivation (construites depuis `offers_to_deactivate.json` sans exiger de triage ni de ROME).
* `rejected_records.json` : Offres en rejet.
* `unchanged_offer_ids.json` : Liste brute et compacte des identifiants des offres inchangées (`NO_ACTION`).
* `integrity_report.json` : Résultats explicites des contrôles d'intégrité (recouvrements d'ensembles, partitions et équations incrémentales).
* `preimport_manifest.json` : Synthèse globale du run, hashes des entrées, compteurs finaux et invariants vérifiés.
* `preimport_progress.json` : Fichier de progression de l'exécution.
