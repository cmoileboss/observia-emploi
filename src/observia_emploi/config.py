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
    token_url: str = (
        "https://entreprise.francetravail.io/connexion/oauth2/access_token?realm=/partenaire"
    )
    api_base_url: str = "https://api.francetravail.io/partenaires"


class Config:
    """Global configuration loader."""

    def __init__(self) -> None:
        """Initialize configuration from environment variables."""
        self.france_travail = FranceTravailConfig(
            client_id=os.getenv("FRANCE_TRAVAIL_CLIENT_ID", ""),
            client_secret=os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", ""),
            token_url=os.getenv(
                "FRANCE_TRAVAIL_TOKEN_URL",
                "https://entreprise.francetravail.io/connexion/oauth2/access_token?realm=/partenaire",
            ),
            api_base_url=os.getenv(
                "FRANCE_TRAVAIL_API_BASE_URL",
                "https://api.francetravail.io/partenaires",
            ),
        )


# Global config instance
settings = Config()
