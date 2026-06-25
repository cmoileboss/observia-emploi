# Passation — Triage Free-Work V2 (Source 3)

Ce document décrit le pipeline expérimental de traitement, rapprochement et triage des offres Free-Work (Source 3) vis-à-vis des offres France Travail.

## 1. Statut expérimental
Le traitement de Free-Work en tant que Source 3 est actuellement dans une phase expérimentale hors ligne (offline). Aucun rattachement automatique en base de données PostgreSQL ou arbitrage par LLM (ex: Qwen3) n'a été implémenté en production.

## 2. Architecture du flux
Le pipeline se déroule selon les étapes suivantes :
1. **Collecte** : Récupération des offres brutes Free-Work.
2. **Normalisation** : Nettoyage et structuration des titres, descriptions, localisations, entreprises, URL et propagation des compétences/soft skills.
3. **Matching** : Recherche des correspondances potentielles dans le snapshot France Travail via un moteur de rapprochement hybride.
4. **Triage V2** : Analyse des signaux (scores, chevauchement, contradictions) pour statuer sur la présence de l'offre dans France Travail.
5. **Revue / Import** : Sélection des offres incertaines pour validation humaine (`REVIEW_NOW`) et des offres non trouvées pour import direct.

---

## 3. Commandes utiles

### Normalisation des offres
```powershell
.\.venv\Scripts\python.exe scripts\normalize_free_work_offers.py `
  --input "data\raw\free_work\full_catalog\batches\<BATCH_ID>\offers_deduplicated.json"
```

### Run V2 frais recommandé
```powershell
.\.venv\Scripts\python.exe scripts/run_free_work_triage_v2.py `
  --free-work-input "data\processed\free_work\full_catalog\<BATCH_ID>\offers_normalized.json" `
  --france-travail-input "data\processed\france_travail\snapshots\current\france_travail_offers_snapshot.json" `
  --candidate-matches-input "data\processed\matching\free_work_vs_france_travail\<MATCH_RUN>\candidate_matches.json" `
  --output-dir "data\processed\matching\free_work_vs_france_travail\<V2_RUN>"
```

Cette commande ne dépend pas d'un `source-run-id`, ne demande pas de `triage_results.json` historique et ne contient pas de chemin de batch figé. Elle refuse par défaut d'écrire dans un dossier de sortie non vide.

Entrées obligatoires :
* `offers_normalized.json`
* `france_travail_offers_snapshot.json`
* `candidate_matches.json`
* dossier de sortie

Artefacts produits :
* `run_manifest.json`
* `triage_decisions.jsonl`
* `import_candidates.json`
* `review_queue.csv`
* `triage_progress.json`

Le fichier de progression contient `status`, `stage`, `current`, `total`, `percent`, `elapsed_seconds`, `speed_offers_per_second`, `eta_seconds` et `heartbeat`.

### Rejeu historique du triage V2
```powershell
.\.venv\Scripts\python.exe scripts/replay_free_work_triage_v2.py
```

Cette commande est conservée pour reproduire un ancien run. Elle dépend d'un run source historique contenant `candidate_matches.json` et `triage_results.json`.

### Exécution des tests unitaires
```powershell
.\.venv\Scripts\python.exe -m pytest tests/matching/test_free_work_triage_v2.py
```

---

## 4. Run de validation final local
* **ID du Run** : `run_triage_v2_handoff_20260624`
* **Chemin** : `data/processed/matching/free_work_vs_france_travail/run_triage_v2_handoff_20260624/`

Il contient exactement 4 artefacts :
* `run_manifest.json` : Synthèse globale du run, métriques et distributions.
* `triage_decisions.jsonl` : Décisions détaillées par offre Free-Work.
* `import_candidates.json` : Liste des offres éligibles à l'import automatique.
* `review_queue.csv` : File de revue humaine ordonnée (uniquement les cas `REVIEW_NOW`).

---

## 4 bis. Run frais paramétrable validé
Commande exécutée :

```powershell
.\.venv\Scripts\python.exe scripts\run_free_work_triage_v2.py `
  --free-work-input "data\processed\free_work\full_catalog\20260624_081715\offers_normalized.json" `
  --france-travail-input "data\processed\france_travail\snapshots\current\france_travail_offers_snapshot.json" `
  --candidate-matches-input "data\processed\matching\free_work_vs_france_travail\run_triage_full_20260624\candidate_matches.json" `
  --output-dir "data\processed\matching\free_work_vs_france_travail\run_triage_v2_fresh_20260625_140527"
```

Résultats :
* **Total traité** : 8 457
* **Identifiants uniques** : 8 457
* **PRESENT_IN_FT_SNAPSHOT** : 143
* **NOT_FOUND_IN_FT_SNAPSHOT** : 6 846
* **UNCERTAIN** : 1 468
* **PROCESSING_ERROR** : 0
* **NO_MANUAL_REVIEW** : 6 989
* **REVIEW_NOW** : 952
* **DEFER_DATA_INCOMPLETE** : 516
* **import_candidates.json** : 6 846 lignes
* **review_queue.csv** : 952 lignes métier
* **DEFER dans review_queue.csv** : 0
* **Durée** : 13,54 secondes

Le run frais reproduit les compteurs du run V2 de référence sans accès réseau, sans PostgreSQL et sans import.

---

## 5. Volumes finaux validés
* **Total traité** : 8 457 offres Free-Work
* **PRESENT_IN_FT_SNAPSHOT** : 143
* **NOT_FOUND_IN_FT_SNAPSHOT** : 6 846
* **UNCERTAIN** : 1 468
  * **REVIEW_NOW** : 952
  * **DEFER_DATA_INCOMPLETE** : 516
* **Part des cas `UNCERTAIN` différés faute de données suffisantes** : **35,15 %** (516 cas sur 1 468). La file `REVIEW_NOW` contient encore 952 cas.

---

## 6. Signification des décisions et actions
* `PRESENT_IN_FT_SNAPSHOT` : Offre déjà présente dans France Travail (ex: empreinte exacte ou signaux concordants très forts). Pas d'import.
* `NOT_FOUND_IN_FT_SNAPSHOT` : Offre non retrouvée. Éligible à l'import direct.
* `UNCERTAIN` : Cas ambigu nécessitant une revue ou un différé.
* `REVIEW_NOW` : Revue humaine immédiate (car score >= 50, ancien doublon V1 réel, intermédiaire explicite, ou titre fort avec signal complémentaire).
* `DEFER_DATA_INCOMPLETE` : Différé de la revue humaine (les données sont trop incomplètes pour qu'un humain puisse conclure de manière fiable et aucun signal fort n'a été détecté).

---

## 7. Compétences Free-Work conservées
Les compétences structurées (`skills` et `soft_skills`) sont normalisées et propagées à chaque étape. Elles restent visibles dans la file de revue CSV (`competences_free_work`) et dans les candidats à l'import JSON.

---

## 8. Limites connues
* **URL historiques** : Les anciennes URL pointant vers `/job_postings/` sont invalides ou non résolues. Seules les URL reconstruites fiables sont exposées.
* **Intégration PostgreSQL** : Les tables d'importation et de décisions ne sont pas encore reliées à la base PostgreSQL de production.
* **Arbitrage LLM** : LLM non intégré au projet et non utilisé dans cette première version.

---

## 9. Prochaine étape recommandée

Mettre en place la synchronisation différentielle du catalogue Free-Work afin de distinguer les offres :

* nouvelles ;
* modifiées ;
* réactivées ;
* inchangées ;
* disparues et donc à désactiver sans suppression physique.

Construire ensuite un paquet pré-import consolidé, sans écrire dans PostgreSQL.

Ce paquet devra combiner :

* les décisions du triage V2 ;
* les affectations ROME disponibles ;
* les compétences et soft skills Free-Work ;
* les 6 846 offres `NOT_FOUND_IN_FT_SNAPSHOT` ;
* les 952 offres `UNCERTAIN` avec `REVIEW_NOW`, conformément à la politique d’import décidée ;
* les 143 correspondances `PRESENT_IN_FT_SNAPSHOT` à enrichir sans créer de doublon ;
* les 516 offres `DEFER_DATA_INCOMPLETE` à exclure des tables métier.

L’import PostgreSQL ne sera développé qu’après validation de ce paquet pré-import.
