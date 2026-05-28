"""France Travail API client."""

import logging
import time
from typing import Any

import requests

from observia_emploi.config import FranceTravailConfig

logger = logging.getLogger(__name__)


class FranceTravailClient:
    """HTTP client for France Travail API (OAuth2, rate limits, request wrappers)."""

    def __init__(self, config: FranceTravailConfig) -> None:
        """Initialize client with configuration."""
        self.config = config
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def get_access_token(self) -> str:
        """Obtain OAuth2 token using Client Credentials flow.

        The token is cached locally until it expires.
        """
        # Return cached token if still valid (with a 10 seconds safety buffer)
        if self._access_token and time.time() < self._token_expires_at - 10.0:
            return self._access_token

        logger.info("Requesting new access token from France Travail API...")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "scope": self.config.scope,
        }

        try:
            # Actual POST request to retrieve the OAuth2 access token
            response = requests.post(
                self.config.token_url,
                headers=headers,
                data=data,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            # Ensure no secrets or sensitive parameters leak into log messages
            logger.error("Authentication failed: unable to retrieve access token.")
            raise requests.HTTPError(
                "Authentication failed with France Travail API."
            ) from e

        try:
            token_data = response.json()
            access_token = token_data["access_token"]
            expires_in = int(token_data.get("expires_in", 3600))
        except (KeyError, ValueError) as e:
            logger.error("Failed to parse token response from France Travail.")
            raise ValueError("Invalid token response from API.") from e

        self._access_token = access_token
        self._token_expires_at = time.time() + expires_in

        logger.info("Successfully authenticated with France Travail API.")
        return self._access_token

    def _get_headers(self) -> dict[str, str]:
        """Generate headers with authorization token."""
        token = self.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Wrapper around requests.get with authentication."""
        response = self.get_raw(endpoint, params=params)
        response.raise_for_status()
        return response.json()

    def get_raw(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """Wrapper around requests.get returning the full response."""
        url = f"{self.config.api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.info("Performing GET request to France Travail API...")

        merged_headers = self._get_headers()
        if headers:
            merged_headers.update(headers)

        try:
            response = requests.get(
                url,
                headers=merged_headers,
                params=params,
                timeout=15,
            )
            return response
        except requests.RequestException:
            logger.error("GET request to France Travail API failed.")
            raise


class MockResponse:
    """Mock of requests.Response for offline testing."""

    def __init__(
        self, status_code: int, json_data: Any, headers: dict[str, str]
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"Mock HTTP Error: {self.status_code}")


class MockFranceTravailClient(FranceTravailClient):
    """Mock client for local and offline testing of France Travail API."""

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Mock GET requests returning JSON data."""
        response = self.get_raw(endpoint, params=params)
        response.raise_for_status()
        return response.json()

    def get_raw(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Mock GET requests returning a MockResponse."""
        url = f"{self.config.api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.info("Performing mock GET request to France Travail API...")

        # Case 1: ROME Métiers Referential
        if "partenaire/offresdemploi/v2/referentiel/metiers" in url:
            data = [
                {
                    "code": "M1801",
                    "libelle": "Administration de systèmes d'information",
                },
                {
                    "code": "M1802",
                    "libelle": "Expertise et support technique en SI",
                },
                {
                    "code": "M1805",
                    "libelle": "Études et développement informatique",
                },
                {"code": "A1201", "libelle": "Bûcheronnage / Sylviculture"},
            ]
            return MockResponse(200, data, {"Content-Type": "application/json"})

        # Case 2: Job Offers Search API (v2)
        if "partenaire/offresdemploi/v2/offres/search" in url:
            code_rome = "M1805"
            if params and "codeROME" in params:
                code_rome = params["codeROME"]
            elif (
                headers and "codeROME" in headers
            ):  # fallback or fallback in URL/headers
                code_rome = headers.get("codeROME", "M1805")

            # Determine simulation volumes depending on ROME code for variation in tests
            volumes = {
                "M1801": 150,
                "M1802": 85,
                "M1805": 4152,
                "M1806": 0,
                "M1810": 0,
            }
            total = volumes.get(code_rome, 10)

            if total == 0:
                # Return empty list or 204/404 depending on how search behaves
                return MockResponse(
                    204,
                    [],
                    {
                        "Content-Type": "application/json",
                        "Content-Range": "offres 0-0/0",
                    },
                )

            # Return mock single offer for range=0-0 and mock aggregations
            mock_data = {
                "resultats": [
                    {
                        "id": f"OFFRE_{code_rome}_001",
                        "intitule": f"Mock Job for {code_rome}",
                        "romeCode": code_rome,
                    }
                ],
                "filtresPossibles": [
                    {
                        "filtre": "typeContrat",
                        "valeurs": [
                            {"valeur": "CDI", "nb": int(total * 0.7)},
                            {"valeur": "CDD", "nb": int(total * 0.3)},
                        ],
                    },
                    {
                        "filtre": "experience",
                        "valeurs": [
                            {"valeur": "Débutant accepté", "nb": int(total * 0.2)},
                            {"valeur": "De 1 à 3 ans", "nb": int(total * 0.8)},
                        ],
                    },
                ],
            }
            return MockResponse(
                206,
                mock_data,
                {
                    "Content-Type": "application/json",
                    "Content-Range": f"offres 0-0/{total}",
                },
            )

        return MockResponse(404, {"error": "Not Found"}, {})
