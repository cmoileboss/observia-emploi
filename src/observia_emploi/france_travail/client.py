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
        url = f"{self.config.api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.info("Performing GET request to France Travail API...")

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            logger.error("GET request to France Travail API failed.")
            raise


class MockFranceTravailClient(FranceTravailClient):
    """Mock client for local and offline testing of France Travail API."""

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Mock GET requests without hitting the network."""
        url = f"{self.config.api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.info("Performing mock GET request to France Travail API...")

        if "partenaire/rome/v1/metiers" in url:
            return [
                {"code": "M1805", "libelle": "Études et développement informatique"},
                {"code": "M1802", "libelle": "Expertise et support IT"},
                {"code": "A1201", "libelle": "Bûcheronnage"},
            ]
        return {}
