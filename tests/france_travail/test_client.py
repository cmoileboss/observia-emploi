"""Tests for the France Travail API client."""

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from observia_emploi.config import Config, FranceTravailConfig
from observia_emploi.france_travail.client import FranceTravailClient


def test_config_missing_client_id_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that missing client_id raises a ValueError during config initialization."""
    monkeypatch.setenv("FRANCE_TRAVAIL_CLIENT_ID", "")
    monkeypatch.setenv("FRANCE_TRAVAIL_CLIENT_SECRET", "some_secret")

    with pytest.raises(ValueError, match="FRANCE_TRAVAIL_CLIENT_ID is required"):
        Config()


def test_config_missing_client_secret_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that missing client_secret raises a ValueError during config."""
    monkeypatch.setenv("FRANCE_TRAVAIL_CLIENT_ID", "some_id")
    monkeypatch.setenv("FRANCE_TRAVAIL_CLIENT_SECRET", "")

    with pytest.raises(ValueError, match="FRANCE_TRAVAIL_CLIENT_SECRET is required"):
        Config()


@patch("requests.post")
def test_client_get_access_token_success(mock_post: MagicMock) -> None:
    """Test successful OAuth2 token retrieval and proper caching."""
    # Arrange
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "access_token": "valid_token_123",
        "expires_in": 3600,
    }
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    config = FranceTravailConfig(
        client_id="test_id",
        client_secret="test_secret",
        token_url="http://mock-token-url.com",
        api_base_url="http://mock-api-url.com",
        scope="api_romev1",
    )
    client = FranceTravailClient(config)

    # Act
    token = client.get_access_token()

    # Assert
    assert token == "valid_token_123"
    mock_post.assert_called_once_with(
        "http://mock-token-url.com",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": "test_id",
            "client_secret": "test_secret",
            "scope": "api_romev1",
        },
        timeout=10,
    )


@patch("requests.post")
def test_client_get_access_token_caching(mock_post: MagicMock) -> None:
    """Test that client retrieves cached token without repeating HTTP requests."""
    # Arrange
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "access_token": "cached_token",
        "expires_in": 3600,
    }
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    config = FranceTravailConfig(
        client_id="test_id",
        client_secret="test_secret",
        token_url="http://mock-token-url.com",
        api_base_url="http://mock-api-url.com",
        scope="api_romev1",
    )
    client = FranceTravailClient(config)

    # Act
    token_1 = client.get_access_token()
    token_2 = client.get_access_token()

    # Assert
    assert token_1 == "cached_token"
    assert token_2 == "cached_token"
    mock_post.assert_called_once()  # Only called once because of caching


@patch("requests.post")
def test_client_get_access_token_expires(mock_post: MagicMock) -> None:
    """Test that the client requests a new token once the cached one expires."""
    # Arrange
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "access_token": "new_token",
        "expires_in": 5,  # Expires in 5 seconds
    }
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    config = FranceTravailConfig(
        client_id="test_id",
        client_secret="test_secret",
        token_url="http://mock-token-url.com",
        api_base_url="http://mock-api-url.com",
        scope="api_romev1",
    )
    client = FranceTravailClient(config)

    # Force immediate expiration by mocking the time
    client._access_token = "old_token"
    client._token_expires_at = time.time() - 10.0  # 10 seconds ago

    # Act
    token = client.get_access_token()

    # Assert
    assert token == "new_token"
    mock_post.assert_called_once()


@patch("requests.post")
def test_client_get_access_token_http_error(mock_post: MagicMock) -> None:
    """Test that HTTP failure raises HTTPError and does not leak secrets."""
    # Arrange
    mock_post.side_effect = requests.exceptions.HTTPError("401 Unauthorized")

    config = FranceTravailConfig(
        client_id="test_id",
        client_secret="secret_highly_confidential",
        token_url="http://mock-token-url.com",
        api_base_url="http://mock-api-url.com",
        scope="api_romev1",
    )
    client = FranceTravailClient(config)

    # Act & Assert
    with pytest.raises(requests.HTTPError, match="Authentication failed"):
        client.get_access_token()


@patch("requests.post")
def test_client_get_access_token_invalid_json(mock_post: MagicMock) -> None:
    """Test that invalid JSON in token response raises a ValueError."""
    # Arrange
    mock_response = MagicMock()
    mock_response.json.return_value = {"not_access_token": "some_value"}
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    config = FranceTravailConfig(
        client_id="test_id",
        client_secret="test_secret",
        token_url="http://mock-token-url.com",
        api_base_url="http://mock-api-url.com",
        scope="api_romev1",
    )
    client = FranceTravailClient(config)

    # Act & Assert
    with pytest.raises(ValueError, match="Invalid token response"):
        client.get_access_token()
