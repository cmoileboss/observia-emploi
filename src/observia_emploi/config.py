"""Configuration management for ObservIA Emploi."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


@dataclass(frozen=True)
class FranceTravailConfig:
    """Configuration for France Travail API integration."""

    client_id: str
    client_secret: str
    token_url: str
    api_base_url: str
    scope: str


class Config:
    """Global configuration loader."""

    def __init__(self) -> None:
        """Initialize configuration from environment variables."""
        client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "").strip()
        client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "").strip()

        if not client_id:
            raise ValueError("FRANCE_TRAVAIL_CLIENT_ID is required.")
        if not client_secret:
            raise ValueError("FRANCE_TRAVAIL_CLIENT_SECRET is required.")

        token_url = os.getenv(
            "FRANCE_TRAVAIL_TOKEN_URL",
            "https://entreprise.francetravail.io/connexion/oauth2/access_token?realm=/partenaire",
        ).strip()

        api_base_url = os.getenv(
            "FRANCE_TRAVAIL_API_BASE_URL",
            "https://api.francetravail.io/partenaires",
        ).strip()

        scope = os.getenv(
            "FRANCE_TRAVAIL_SCOPE",
            "api_romev1 metierrecherche",
        ).strip()

        self.france_travail = FranceTravailConfig(
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
            api_base_url=api_base_url,
            scope=scope,
        )


# Global config instance (may raise ValueError if env vars are missing at import time)
# During tests or local dev, .env or env vars must be set.
try:
    settings = Config()
except ValueError:
    # If variables are missing at import time, we do not crash immediately unless
    # someone accesses `settings`. We will allow lazy configuration initialization
    # or handle it gracefully to not crash test suites.
    settings = None  # type: ignore
