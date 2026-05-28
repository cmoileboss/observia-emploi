# Intégration API France Travail - Brique ROME et Offres d'Emploi

Ce document spécifie l'intégration technique de la source **API France Travail** (anciennement Pôle Emploi) au sein du projet **ObservIA Emploi**.

---

## 1. Objectif de la brique

L'objectif de ce module (`src/observia_emploi/france_travail/`) est de récupérer et de consolider les données d'emploi issues de France Travail pour alimenter la suite du pipeline d'analyse de données d'ObservIA.

### Lot 1 (Cible Immédiate)
*   Se connecter à l'API via le protocole **OAuth 2.0 (Client Credentials Grant)**.
*   Interroger le **Référentiel des Métiers ROME** pour obtenir la liste officielle des codes métiers.
*   **Filtrer** cette liste par rapport à un ensemble défini de codes ROME d'intérêt pour le projet.
*   Produire un **export JSON structuré et typé**, propre et compatible avec le reste du pipeline.

---

## 2. Endpoints prévus (V1)

| Fonctionnalité | Méthode | URL Endpoint | Description |
|---|---|---|---|
| **Authentification** | `POST` | `{{FRANCE_TRAVAIL_TOKEN_URL}}` | Récupération du jeton OAuth 2.0 (`access_token`) |
| **Référentiel ROME** | `GET` | `{{FRANCE_TRAVAIL_API_BASE_URL}}/partenaire/rome/v1/metiers` | Récupération de tous les métiers du référentiel ROME |
| **Recherche d'offres**| `GET` | `{{FRANCE_TRAVAIL_API_BASE_URL}}/partenaire/offresdemploi/v2/offres/search` | Recherche des offres d'emploi (prévu pour le lot suivant) |

---

## 3. Contraintes techniques & Rate Limiting

L'API France Travail impose des restrictions strictes que notre client doit respecter pour éviter les erreurs HTTP `429 Too Many Requests` :

1.  **Rate Limiting** :
    *   **Maximum 3 requêtes par seconde** sur les services partenaires.
    *   Notre implémentation intégrera une limitation de débit automatique (*rate limiting*) en V1.
2.  **Limite de volume par requête** :
    *   Le service de recherche d'offres retourne au maximum **150 offres par requête**.
3.  **Nécessité de pagination** :
    *   Pour récupérer plus de 150 offres, l'utilisation des en-têtes HTTP `Range` (ex. `Range: offres=0-149`, `Range: offres=150-299`) est obligatoire.
    *   Le client API gérera automatiquement la pagination séquentielle.
4.  **Pas de parallélisme en V1** :
    *   Pour garantir le respect strict des limites de taux et maintenir un code simple et robuste, **aucun parallélisme** (threads/processus multiples) ne sera implémenté dans la V1. Tout sera séquentiel.

---

## 4. Prérequis d'autorisation de l'API

> [!IMPORTANT]
> **Autorisation de l'API dans la console France Travail**
>
> Avant de tenter d'obtenir un token OAuth2 (via le client ou via Postman), vous devez impérativement :
> 1. Vous connecter à votre compte sur le portail développeur de France Travail.
> 2. Aller dans la section de gestion de votre application.
> 3. Ajouter l'API **"Offres d'emploi v2"** dans la liste des **API autorisées**.
> 4. Vérifier qu'elle est bien activée pour cette application.
>
> **En cas d'oubli** : L'API renverra une erreur `invalid_client` lors de l'appel d'authentification, même si votre `client_id` et votre `client_secret` sont parfaitement corrects.

---

## 5. Sécurité des Secrets

> [!CAUTION]
> **Aucun secret (clés API, identifiants client, tokens) ne doit être poussé sur Git.**
>
> Les secrets doivent être stockés uniquement dans le fichier local `.env` (qui est strictement ignoré par Git via `.gitignore`).
> Le fichier `.env.example` sert de modèle pour configurer l'environnement de développement.
>
> Voici le bloc de configuration attendu dans le fichier `.env` local :
> ```env
> FRANCE_TRAVAIL_CLIENT_ID=votre_client_id
> FRANCE_TRAVAIL_CLIENT_SECRET=votre_client_secret
> FRANCE_TRAVAIL_TOKEN_URL=https://entreprise.francetravail.io/connexion/oauth2/access_token?realm=/partenaire
> FRANCE_TRAVAIL_API_BASE_URL=https://api.francetravail.io/partenaires
> FRANCE_TRAVAIL_SCOPE=api_romev1 metierrecherche
> ```

---

## 6. Sortie JSON attendue (Lot 1)

Le service `referential.py` exportera un fichier JSON propre dans le dossier `data/processed/` respectant le format suivant :

```json
{
  "extracted_at": "2026-05-27T15:24:00Z",
  "source": "France Travail ROME",
  "count": 2,
  "metiers": [
    {
      "code_rome": "M1805",
      "libelle": "Études et développement informatique",
      "validated": true
    },
    {
      "code_rome": "M1802",
      "libelle_rome": "Expertise et support technique en systèmes d'information",
      "validated": true
    }
  ]
}
```

---

## 7. Procédure d'exécution locale

Pour exécuter la récupération, le filtrage et la génération du référentiel ROME consolidé, vous pouvez lancer le point d'entrée de l'application via la commande suivante :

```bash
python -m observia_emploi.cli
```

### Options d'exécution :
*   **Mode Production (Réel)** : Assurez-vous d'avoir configuré vos identifiants réels dans votre fichier local `.env`.
*   **Mode Hors-ligne (Mock / Démonstration)** : Si vos variables d'environnement ne sont pas configurées ou si vous souhaitez exécuter le script sans connexion réseau, vous devez utiliser explicitement l'argument `--offline`. Sans cette option, l'application échouera proprement en cas d'identifiants absents.
    ```bash
    python -m observia_emploi.cli --offline
    ```

### Fichier produit :
L'export JSON consolidé et normalisé est sauvegardé à l'adresse suivante :
`data/processed/reference/rome_metiers_v1.json` (ignoré par Git pour éviter le versionnage des fichiers de données).

---

## 8. Tests d'intégration avec Postman

Pour tester les appels réels vers l'API France Travail (authentification OAuth2 et récupération du référentiel ROME), consultez la procédure Postman dédiée :

**→ [`docs/postman_france_travail.md`](postman_france_travail.md)**

Cette procédure décrit :
- la configuration des variables d'environnement Postman (sans jamais exposer de secrets) ;
- la requête POST de récupération du token OAuth2 avec script de capture automatique ;
- la requête GET vers le référentiel ROME métiers ;
- la checklist sécurité avant tout partage de collection.

---

## 9. Lot 2A : Mesure de volume et agrégations des offres par ROME

L'objectif du Lot 2A est de mesurer la volumétrie globale et de récupérer les agrégations de base par code ROME sans réaliser de collecte massive de données (aucun appel d'offres en masse).

### Requête de mesure prioritaire
*   **Méthode** : `GET`
*   **Endpoint** : `{{api_base_url}}/partenaire/offresdemploi/v2/offres/search`
*   **Paramètres obligatoires** :
    - `codeROME` : Le code ROME cible à tester (ex: `M1805`). **Attention** : le paramètre exact attendu par l'API France Travail est bien `codeROME`, et non pas `rome`.
    - `range` (ou en-tête `Range`) : `0-0` pour limiter le retour à la toute première offre et éviter les charges réseau inutiles.
*   **Critère de validation** :
    - La liste de résultats doit contenir au moins une offre, et le champ `romeCode` (dans `resultats[*].romeCode`) de la première offre retournée doit correspondre strictement au code ROME de la demande.

### Rôle du header `Content-Range`
Sur un appel restreint avec `range=0-0`, l'API France Travail renvoie un statut `206 Partial Content`.
Le header de réponse HTTP **`Content-Range`** contient le total exact d'offres disponibles pour ce code ROME.
*   *Exemple de header* : `Content-Range: offres 0-0/4152`
*   *Interprétation* : Il y a un volume total de **4152 offres** valides sur le réseau national pour ce code ROME à l'instant T.

### Commande d'exécution CLI (Lot 2A)

Pour mesurer la volumétrie et les agrégations pour les 5 codes ROME prioritaires (`M1801`, `M1802`, `M1805`, `M1806`, `M1810`) :

*   **En production (réel)** :
    ```bash
    python -m observia_emploi.cli --measure-volume
    ```
*   **En mode hors-ligne (offline / simulé)** :
    ```bash
    python -m observia_emploi.cli --measure-volume --offline
    ```

### Fichier de synthèse généré
Les résultats consolidés de la volumétrie par code ROME sont exportés en UTF-8 dans :
`data/processed/reference/rome_volumes_v1.json`

> [!CAUTION]
> **Règle de versionnage Git**
>
> Le fichier généré `rome_volumes_v1.json` contient des données d'exécution de pipeline. Il est strictement ignoré par Git via le fichier `.gitignore` et **ne doit jamais être commité ou poussé sur le dépôt distant**.


## 10. Lot 2C : Mesure de volume pour tous les codes ROME du référentiel fusionné

L'objectif du Lot 2C est d'étendre la mesure du Lot 2A à l'intégralité des 51 codes ROME extraits des données historiques, en faisant une requête par code ROME.

### Commande d'exécution CLI
* **En production (réel)** :
  ```bash
  python -m observia_emploi.cli --measure-volumes-from-merged
  ```
* **En mode hors-ligne (offline / simulé)** :
  ```bash
  python -m observia_emploi.cli --measure-volumes-from-merged --offline
  ```

### Fichier généré
`data/processed/reference/rome_volumes_from_merged_data.json` (exclu de Git).

---

## 11. Lot 2D : Collecte détaillée des offres France Travail

L'objectif du Lot 2D est de collecter de manière exhaustive et séquentielle les offres d'emploi détaillées depuis l'API de recherche.

### Spécifications de la collecte
* **Endpoint utilisé** : `GET /partenaire/offresdemploi/v2/offres/search`
* **Paramètre de filtrage** : `codeROME` (ex: `M1805`). Ne jamais utiliser `rome`.
* **Pagination** : Envoi séquentiel du paramètre `range` par blocs de **150** résultats maximum par requête (ex. `/search?codeROME=M1805&range=0-149`, `range=150-299`).
* **Rate Limiting** : 5 appels/seconde maximum (pause prudente de `0.25` seconde entre chaque appel). Aucun parallélisme n'est implémenté pour respecter strictement cette limite.
* **Résilience** : En cas de code d'erreur technique lié à la pagination (ex. HTTP 416 lorsque la limite maximale de pagination de l'API est atteinte), le service logue proprement un avertissement et passe automatiquement au code ROME suivant.

### Protection des données personnelles & Anonymisation
Conformément au RGPD et aux règles de conformité :
1. **Exclusion complète** : Les structures `contact` et `agence` de l'API brute sont lues mais marquées avec `Field(..., exclude=True)`. Elles sont **totalement exclues** lors de la sérialisation et ne figurent jamais dans le JSON exporté.
2. **Exclusion de la description brute** : Le champ brut `description` est exclu de l'export.
3. **Description anonymisée (`description_clean`)** : Seule cette description nettoyée est exportée. Un validateur Pydantic masque automatiquement tous les e-mails et numéros de téléphone à l'aide des jetons `[EMAIL MASQUÉ]` et `[TÉLÉPHONE MASQUÉ]`.

### Commande d'exécution CLI
* **En production (réel)** :
  > [!WARNING]
  > Ne lancez pas de collecte réelle complète sans validation.
  ```bash
  python -m observia_emploi.cli --collect-offers-from-merged
  ```
* **En mode hors-ligne (offline / simulé)** :
  ```bash
  python -m observia_emploi.cli --collect-offers-from-merged --offline
  ```

### Fichier produit
`data/processed/offers/france_travail_offers_from_merged_rome.json` (strictement ignoré par Git via `.gitignore` et **ne doit jamais être versionné**).
