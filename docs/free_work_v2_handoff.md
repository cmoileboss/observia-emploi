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
.\.venv\Scripts\python.exe scripts/normalize_free_work_offers.py
```

### Rejeu du triage V2
```powershell
.\.venv\Scripts\python.exe scripts/replay_free_work_triage_v2.py
```

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

## 5. Volumes finaux validés
* **Total traité** : 8 457 offres Free-Work
* **PRESENT_IN_FT_SNAPSHOT** : 143
* **NOT_FOUND_IN_FT_SNAPSHOT** : 6 846
* **UNCERTAIN** : 1 468
  * **REVIEW_NOW** : 952
  * **DEFER_DATA_INCOMPLETE** : 516
* **Pourcentage de réduction de la file humaine** : **35,15 %** (516 cas différés / 1 468 incertains).

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
* **Arbitrage LLM** : L'intégration finale avec Qwen3 8B pour filtrer les cas de revue reste à faire.

---

## 9. Prochaine étape recommandée
Connecter la table d'import générée (`import_candidates.json`) au script de chargement en base pour l'intégrer au flux général de l'application.
