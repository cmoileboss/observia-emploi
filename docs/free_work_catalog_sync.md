# Synchronisation differentielle du catalogue Free-Work

Ce document decrit la premiere version exploitable de synchronisation differentielle hors ligne du catalogue Free-Work normalise.

Le traitement est porte par :

```text
scripts/sync_free_work_catalog.py
```

Il ne fait aucun appel reseau, aucun acces PostgreSQL, aucun import metier, aucun matching, aucun triage V2 et aucune classification ROME. Il compare uniquement un nouveau `offers_normalized.json` a l'etat courant local du catalogue Free-Work.

## Commande

```powershell
.\.venv\Scripts\python.exe scripts\sync_free_work_catalog.py `
  --normalized-input "data\processed\free_work\full_catalog\<BATCH_ID>\offers_normalized.json" `
  --collection-batch-dir "data\raw\free_work\full_catalog\batches\<BATCH_ID>" `
  --catalog-root "data\processed\free_work\catalog" `
  --run-id "<SYNC_RUN_ID>"
```

La commande refuse un dossier `catalog\runs\<SYNC_RUN_ID>` deja non vide.

## Entrees

- `offers_normalized.json` : snapshot Free-Work normalise.
- `collection-batch-dir` : dossier brut de collecte exhaustive du meme batch.
- `catalog-root` : racine du catalogue local differentiel.
- `run-id` : identifiant unique du run de synchronisation.

La racine de `offers_normalized.json` doit etre une liste JSON. Chaque offre doit posseder un `source_id` Free-Work unique.

## Condition de completude

Les inactivations ne sont autorisees que si la collecte exhaustive est prouvee complete. Le script verifie les artefacts reels suivants avant toute promotion du catalogue courant :

```text
collection_manifest.json :
- status = COMPLETED
- pages_failed = 0
- pages_requested = pages_succeeded

failed_pages.json :
- tableau vide

resume_state.json :
- next_page_url = null
```

Si cette condition n'est pas satisfaite, le run echoue, `sync_progress.json` passe en `FAILED`, et `catalog/current` reste inchange.

## Etats produits

| Etat | Regle |
| :--- | :--- |
| `NEW` | Identifiant Free-Work jamais observe dans le catalogue courant. |
| `UPDATED` | Identifiant connu, actif, avec hash metier modifie. |
| `UNCHANGED` | Identifiant connu, actif, avec hash metier identique. |
| `REACTIVATED` | Identifiant connu inactif, present a nouveau dans le snapshot complet. |
| `INACTIVATED` | Identifiant precedemment actif, absent du nouveau snapshot complet. |

Une offre disparue n'est jamais supprimee : elle reste dans `catalog_state.json` avec `is_active = false` et `inactive_since`.

## Hash metier

La version de hash est :

```text
free_work_catalog_business_v1
```

Les champs inclus dans la projection metier sont :

- `title`
- `description`
- `candidate_profile`
- `company_description`
- `company_name`
- `location`
- `contracts`
- `skills`
- `soft_skills`
- `remote_mode`
- `experience_level`
- `salary`
- `published_at`
- `updated_at`
- `expires_at`

Les listes et objets imbriques sont canonicalises avant hash afin que l'ordre des competences ou contrats ne provoque pas de faux `UPDATED`.

Les champs techniques exclus du hash sont :

- `source`
- `source_id`
- `source_url`
- `source_url_raw`
- `source_url_resolution_method`
- `matched_rome_queries`
- `raw_payload_sha256`

Pour `UPDATED`, le journal de changements expose uniquement les champs metier de premier niveau modifies dans `changed_fields`, sans recopier les descriptions completes.

## Securite de promotion (Coherence)

La promotion de `catalog_state.json`, `offers_active.json` et `catalog_manifest.json` s'effectue de maniere atomique fichier par fichier. Afin de garantir l'absence d'incoherence due a une execution interrompue (promotion partielle) :
- Un identifiant de generation commun (`generation_id` ou `current_run_id`) est attribue a l'ensemble des fichiers produits par un meme run.
- Des hashes croises (`catalog_state_sha256` et `offers_active_sha256`) de l'etat des objets serialized sont enregistres dans `catalog_manifest.json`.
- A chaque chargement de l'etat (via `load_current_state`), une validation systematique recalcule ces hashes et leve une exception explicite en cas de divergence ou de fichier manquant.

## Hash metier et gestion de `updated_at`

Le champ `updated_at` a ete conserve au sein du hash metier (version `free_work_catalog_business_v1`). Deux options s'offraient :
1. **Conserver `updated_at` (Option retenue)** : Toute modification temporelle source re-declare l'offre comme `UPDATED`, garantissant que le systeme de traitement aval soit notifie de la fraicheur ou du rafraichissement de l'offre.
2. **Exclure `updated_at`** : Evite les faux `UPDATED` si le site re-publie l'offre sans modifications textuelles metier.

## Artefacts

Etat courant :

- `catalog/current/catalog_state.json`
- `catalog/current/offers_active.json`
- `catalog/current/catalog_manifest.json`

Run de synchronisation :

- `catalog/runs/<SYNC_RUN_ID>/new_offers.json`
- `catalog/runs/<SYNC_RUN_ID>/updated_offers.json`
- `catalog/runs/<SYNC_RUN_ID>/reactivated_offers.json`
- `catalog/runs/<SYNC_RUN_ID>/unchanged_offer_ids.json`
- `catalog/runs/<SYNC_RUN_ID>/inactivated_offers.json`
- `catalog/runs/<SYNC_RUN_ID>/offers_to_process.json`
- `catalog/runs/<SYNC_RUN_ID>/offers_to_deactivate.json`
- `catalog/runs/<SYNC_RUN_ID>/change_log.jsonl`
- `catalog/runs/<SYNC_RUN_ID>/sync_manifest.json`
- `catalog/runs/<SYNC_RUN_ID>/sync_progress.json`

### Structure enrichie de `sync_manifest.json`

Le manifeste contient desormais :
- `sync_schema_version` / `schema_version` : version de structure (1)
- `mode` : `BOOTSTRAP` (premier run) ou `INCREMENTAL` (si un etat existe deja)
- `status` : statut de fin (`COMPLETED`)
- `duration_seconds` : duree precise mesuree avec une horloge monotone (`time.perf_counter()`)
- `collection_input_hashes` : hashes SHA-256 de `collection_manifest.json`, `failed_pages.json`, `resume_state.json` et `normalization_manifest.json` (si disponible)
- `unique_active_offer_ids` : nombre d'identifiants actifs uniques apres synchronisation.
- Compteurs avant/apres : `active_offers_before`, `active_offers_after`, `known_offers_before`, `known_offers_after`, `inactive_offers_after`.

## Validation sur le batch de reference (V2)

Commandes executees sur le batch `20260624_081715` dans le catalogue `catalog_sync_validation_v2` :

```powershell
# 1. Passage de bootstrap
.\.venv\Scripts\python.exe scripts\sync_free_work_catalog.py `
  --normalized-input "data\processed\free_work\full_catalog\20260624_081715\offers_normalized.json" `
  --collection-batch-dir "data\raw\free_work\full_catalog\batches\20260624_081715" `
  --catalog-root "data\processed\free_work\catalog_sync_validation_v2" `
  --run-id "sync_bootstrap_20260625_validation"

# 2. Passage incremental identique
.\.venv\Scripts\python.exe scripts\sync_free_work_catalog.py `
  --normalized-input "data\processed\free_work\full_catalog\20260624_081715\offers_normalized.json" `
  --collection-batch-dir "data\raw\free_work\full_catalog\batches\20260624_081715" `
  --catalog-root "data\processed\free_work\catalog_sync_validation_v2" `
  --run-id "sync_repeat_20260625_validation"
```

Resultats V2 valides :
* `sync_bootstrap_20260625_validation` :
  - `mode` = `BOOTSTRAP`
  - `NEW` = 8457, `UNCHANGED` = 0, `active_offers` = 8457
* `sync_repeat_20260625_validation` :
  - `mode` = `INCREMENTAL`
  - `NEW` = 0, `UNCHANGED` = 8457, `active_offers` = 8457

## Limites

- Le catalogue synchronise reste un artefact fichier hors ligne.
- Aucun import PostgreSQL n'est effectue.
- Les offres inactives ne sont pas encore propagees vers une table metier.
- Le paquet pre-import combinant synchronisation, triage V2, ROME et competences reste a construire.
- La correction du controle `robots.txt` bloquant reste independante de cette synchronisation.
