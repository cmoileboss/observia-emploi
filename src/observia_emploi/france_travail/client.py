"""France Travail API client."""

import logging
from typing import Any

from observia_emploi.config import FranceTravailConfig

logger = logging.getLogger(__name__)


class FranceTravailClient:
    """HTTP client for France Travail API (OAuth2, rate limits, request wrappers)."""

    def __init__(self, config: FranceTravailConfig) -> None:
        """Initialize client with configuration."""
        self.config = config
        self._access_token: str | None = None

    def get_access_token(self) -> str:
        """Obtain OAuth2 token using Client Credentials.

        Placeholder implementation that does not execute a real network call
        unless stubbed or explicitly enabled.
        """
        if self._access_token:
            return self._access_token

        # Check configuration
        if not self.config.client_id or not self.config.client_secret:
            raise ValueError(
                "Missing FRANCE_TRAVAIL_CLIENT_ID or FRANCE_TRAVAIL_CLIENT_SECRET."
            )

        # In a real environment, this would perform a POST requests call to
        # config.token_url
        logger.info("Requesting access token from France Travail (placeholder)...")

        # Mock token for Lot 0 validation
        self._access_token = "mock_access_token"
        return self._access_token

    def _get_headers(self) -> dict[str, str]:
        """Generate headers with authorization token."""
        token = self.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Wrapper around requests.get with authentication and mock response logic.

        Placeholder implementation.
        """
        # Construction of URL
        url = f"{self.config.api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.info(f"Performing GET request to {url} (placeholder)...")

        # In V1, this would call:
        # response = requests.get(url, headers=self._get_headers(), params=params)
        # response.raise_for_status()
        # return response.json()

        # Mock responses to allow safe tests without internet connection
        if "partenaire/rome/v1/metiers" in url:
            return [
                {"code": "M1805", "libelle": "Études et développement informatique"},
                {"code": "M1802", "libelle": "Expertise et support IT"},
                {"code": "A1201", "libelle": "Bûcheronnage"},
            ]

        return {}
