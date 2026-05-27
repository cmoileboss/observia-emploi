"""Tests for the France Travail API client."""

import pytest

from observia_emploi.config import FranceTravailConfig
from observia_emploi.france_travail.client import FranceTravailClient


def test_client_initialization() -> None:
    """Test that the client initializes correctly with config."""
    config = FranceTravailConfig(
        client_id="test_id",
        client_secret="test_secret",
        token_url="http://token.com",
        api_base_url="http://api.com",
    )
    client = FranceTravailClient(config)

    assert client.config.client_id == "test_id"
    assert client.config.client_secret == "test_secret"


def test_client_missing_credentials_raises_error() -> None:
    """Test that missing credentials raise ValueError when getting token."""
    config = FranceTravailConfig(client_id="", client_secret="")
    client = FranceTravailClient(config)

    with pytest.raises(ValueError, match="Missing FRANCE_TRAVAIL_CLIENT_ID"):
        client.get_access_token()


def test_client_mock_token_retrieval() -> None:
    """Test that the client retrieves a token successfully (mock)."""
    config = FranceTravailConfig(
        client_id="test_id",
        client_secret="test_secret",
    )
    client = FranceTravailClient(config)
    token = client.get_access_token()

    assert token == "mock_access_token"
    # Verify token caching
    assert client.get_access_token() == "mock_access_token"
