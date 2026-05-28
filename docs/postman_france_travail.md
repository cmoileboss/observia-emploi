# Postman — France Travail API: Procedure Guide

This document describes how to configure and use Postman to test the France Travail
API endpoints used by ObservIA Emploi.

> ⚠️ **Security rule**: Never enter real credentials directly in a Postman request.
> Always use Postman variables. Never commit your Postman environment file if it
> contains real secrets.

## 0. Prerequisite: API Authorization in France Travail Portal

Before configuring Postman or running any token request:
1. Log in to your developer account on the **France Travail** developer portal.
2. Navigate to your application dashboard.
3. In the **"API autorisées"** (Authorized APIs) section, ensure that the **"Offres d'emploi v2"** API is explicitly added.
4. Verify that it appears with an active/authorized status.
5. ⚠️ **Important Troubleshooting**: If this API is not added, any token request will fail with an `invalid_client` error, even if your `client_id` and `client_secret` are perfectly valid.

---

## 1. Create a Postman Environment

In Postman, create a new environment named **`FranceTravail - Dev`** with the
following variables:

| Variable        | Type    | Initial value (example)                                  | Current value |
|-----------------|---------|-----------------------------------------------------------|---------------|
| `client_id`     | secret  | *(your app client_id)*                                    | *(fill in)*   |
| `client_secret` | secret  | *(your app client_secret)*                                | *(fill in)*   |
| `token_url`     | default | `https://entreprise.francetravail.fr/connexion/oauth2/access_token` | *(copy)* |
| `api_base_url`  | default | `https://api.francetravail.io`                            | *(copy)*      |
| `scope`         | default | `api_offresdemploiv2 o2dsoffre`                           | *(copy)*      |
| `access_token`  | secret  | *(leave empty — set automatically by the pre-request script)* | *(auto)* |

> **Important**: Set the **Current value** for `client_id` and `client_secret` only.
> Never set the **Initial value** for secrets — Postman syncs initial values to the
> cloud if you use a Postman account.

---

## 2. OAuth2 Token Request (POST)

### Request

- **Method**: `POST`
- **URL**: `{{token_url}}?realm=%2Fpartenaire`

### Headers

| Key            | Value                               |
|----------------|-------------------------------------|
| `Content-Type` | `application/x-www-form-urlencoded` |

### Body (x-www-form-urlencoded)

| Key             | Value              |
|-----------------|--------------------|
| `grant_type`    | `client_credentials` |
| `client_id`     | `{{client_id}}`    |
| `client_secret` | `{{client_secret}}`|
| `scope`         | `{{scope}}`        |

### Tests script (to capture the token automatically)

In the **Tests** tab of this request, add:

```javascript
const response = pm.response.json();
if (response.access_token) {
    pm.environment.set("access_token", response.access_token);
    console.log("Access token successfully captured.");
} else {
    console.error("Token request failed:", JSON.stringify(response));
}
```

### Expected response

```json
{
    "access_token": "<token>",
    "token_type": "Bearer",
    "expires_in": 1499
}
```

> The token expires in ~25 minutes. Re-run this request when it expires.

---

## 3. GET ROME Referential (Métiers)

### Request

- **Method**: `GET`
- **URL**: `{{api_base_url}}/partenaire/offresdemploi/v2/referentiel/metiers`

### Headers

| Key             | Value                      |
|-----------------|----------------------------|
| `Authorization` | `Bearer {{access_token}}`  |
| `Accept`        | `application/json`         |

### Query Parameters (optional)

This endpoint does not require parameters for a full list. To paginate:

| Key     | Value example |
|---------|---------------|
| `range` | `0-14`        |

### Expected response (excerpt)

```json
[
  {
    "code": "M1801",
    "libelle": "Administration de systèmes d'information"
  },
  {
    "code": "M1802",
    "libelle": "Expertise et support en systèmes d'information"
  }
]
```

---

## 3.2. GET Job Offers Search (Lot 2A)

### Request

- **Method**: `GET`
- **URL**: `{{api_base_url}}/partenaire/offresdemploi/v2/offres/search?codeROME={{rome_code}}&range=0-0`

### Headers

| Key             | Value                      |
|-----------------|----------------------------|
| `Authorization` | `Bearer {{access_token}}`  |
| `Accept`        | `application/json`         |

### Query Parameters

| Key        | Value           | Description |
|------------|-----------------|-------------|
| `codeROME` | `M1805`         | **Obligatoire**. Code ROME ciblé (ex: `M1805`). Ne pas utiliser `rome`. |
| `range`    | `0-0`           | **Restreint**. Utilisé pour capter uniquement la première offre et mesurer le volume total d'offres via `Content-Range`. |

### Validation Criteria
1.  **ROME Code Match**: The returned JSON must contain a `resultats` list, and `resultats[0].romeCode` must match exactly the requested `codeROME` (e.g. `M1805`).
2.  **HTTP Status**: Returns `206 Partial Content` when multiple offers exist, or `200 OK` if there is exactly one offer.
3.  **Volume Header**: The response HTTP header `Content-Range` must be parsed to read the total volume (e.g., `offres 0-0/4152` represents 4152 jobs).

---

## 4. Recommended Test Sequence

1. Select the **`FranceTravail - Dev`** environment.
2. Run **POST Token** → verify `200 OK` and `access_token` in the environment.
3. Run **GET ROME Métiers** → verify `200 OK` and a JSON array of ROME codes.
4. Manually cross-check that codes `M1801`, `M1802`, `M1805`, `M1806`, `M1810`
   are present in the response.

---

## 5. Security Checklist

- [ ] `client_secret` is only in **Current value**, never in **Initial value**.
- [ ] `access_token` is only in **Current value**, never in **Initial value**.
- [ ] The Postman environment export (`.postman_environment.json`) is **not committed**
  to Git (already covered by `.gitignore`).
- [ ] No real credentials appear in any request Body or Header value directly —
  only `{{variables}}`.
- [ ] Token is short-lived (~25 min). Never store it permanently.

---

## 6. Relationship to Unit Tests

| Layer           | Tool    | Network calls | Purpose                          |
|-----------------|---------|---------------|----------------------------------|
| Unit tests      | pytest  | None (mocked) | Business logic, regression       |
| Quality checks  | ruff / black | None     | Code style & lint                |
| Integration API | Postman | Real API      | Validate real API behavior       |
| CLI offline     | `--offline` flag | None  | Local end-to-end with mock data  |
