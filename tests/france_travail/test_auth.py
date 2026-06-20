"""
Unit tests for services.france_travail.auth.

All HTTP calls are mocked with unittest.mock. No real network connection is
made. No database is contacted. main.py is not imported.

Every test that exercises ``FranceTravailAuthClient`` injects a
``unittest.mock.MagicMock`` as the ``requests.Session`` so that no outbound
request is possible.
"""

import time
import unittest
from unittest.mock import MagicMock

import requests

from services.france_travail.auth import FranceTravailAuthClient
from services.france_travail.config import FranceTravailConfig
from services.france_travail.exceptions import (
    FranceTravailError,
    FranceTravailAuthenticationError,
    FranceTravailNetworkError,
    FranceTravailInvalidResponseError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: str) -> FranceTravailConfig:
    """Return a minimal valid FranceTravailConfig, with optional overrides."""
    base = {
        "FRANCE_TRAVAIL_CLIENT_ID": "test_id",
        "FRANCE_TRAVAIL_CLIENT_SECRET": "super_secret",
        "FRANCE_TRAVAIL_TOKEN_URL": "https://example.com/token",
        "FRANCE_TRAVAIL_SCOPE": "api_offresdemploiv2",
        "FRANCE_TRAVAIL_OFFERS_SEARCH_URL": "https://example.com/offers/search",
        "FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS": "10",
    }
    base.update(overrides)
    return FranceTravailConfig.from_mapping(base)



def _make_ok_response(access_token: any = "tok_abc", expires_in: any = 3600) -> MagicMock:
    """Return a mock HTTP response simulating a successful token endpoint reply."""
    response = MagicMock()
    response.status_code = 200

    # Simulate a dictionary JSON body response
    body = {}

    if access_token is not None:
        body["access_token"] = access_token
    if expires_in is not None:
        body["expires_in"] = expires_in

    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


def _make_error_response(status_code: int) -> MagicMock:
    """Return a mock HTTP response simulating an HTTP error."""
    response = MagicMock()
    response.status_code = status_code
    http_error = requests.exceptions.HTTPError(response=response)
    response.raise_for_status.side_effect = http_error
    return response


def _make_client(session: MagicMock, config: FranceTravailConfig | None = None) -> FranceTravailAuthClient:
    """Shortcut for building a client with the given mock session."""
    return FranceTravailAuthClient(config=config or _make_config(), session=session)


# ---------------------------------------------------------------------------
# Test cases — successful flows
# ---------------------------------------------------------------------------


class TestFranceTravailAuthClientTokenSuccess(unittest.TestCase):
    """Tests covering successful token acquisition and caching."""

    def test_get_access_token_returns_token(self):
        """get_access_token() returns the value from the mocked endpoint."""
        session = MagicMock()
        session.post.return_value = _make_ok_response(access_token="my_token")

        client = _make_client(session)
        token = client.get_access_token()

        self.assertEqual(token, "my_token")

    def test_token_is_cached_on_second_call(self):
        """Second call to get_access_token() must NOT trigger a new HTTP request."""
        session = MagicMock()
        session.post.return_value = _make_ok_response()

        client = _make_client(session)
        client.get_access_token()
        client.get_access_token()

        session.post.assert_called_once()

    def test_timeout_is_passed_to_session_post(self):
        """The configured timeout is forwarded to session.post()."""
        session = MagicMock()
        session.post.return_value = _make_ok_response()
        config = _make_config(FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS="15")

        client = FranceTravailAuthClient(config=config, session=session)
        client.get_access_token()

        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["timeout"], 15)

    def test_client_credentials_grant_type_is_sent(self):
        """The OAuth payload must include grant_type=client_credentials."""
        session = MagicMock()
        session.post.return_value = _make_ok_response()

        client = _make_client(session)
        client.get_access_token()

        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["data"]["grant_type"], "client_credentials")

    def test_client_id_and_secret_and_scope_sent(self):
        """The OAuth payload must include client_id, client_secret and scope."""
        session = MagicMock()
        session.post.return_value = _make_ok_response()
        config = _make_config(
            FRANCE_TRAVAIL_CLIENT_ID="my_app_id",
            FRANCE_TRAVAIL_CLIENT_SECRET="secret_val",
            FRANCE_TRAVAIL_SCOPE="my_scope",
        )

        client = FranceTravailAuthClient(config=config, session=session)
        client.get_access_token()

        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["data"]["client_id"], "my_app_id")
        self.assertEqual(kwargs["data"]["client_secret"], "secret_val")
        self.assertEqual(kwargs["data"]["scope"], "my_scope")

    def test_no_network_call_at_construction(self):
        """Constructing the client must not trigger any HTTP call."""
        session = MagicMock()
        FranceTravailAuthClient(config=_make_config(), session=session)
        session.post.assert_not_called()


# ---------------------------------------------------------------------------
# Test cases — token renewal
# ---------------------------------------------------------------------------


class TestFranceTravailAuthClientTokenRenewal(unittest.TestCase):
    """Tests covering token expiry and renewal logic."""

    def test_token_short_life_reused_immediately(self):
        """A token with a short expires_in (e.g. 10s) is reused if called before safety margin."""
        session = MagicMock()
        # expires_in = 10 -> safety margin is min(30, 10/10) = 1.0s.
        session.post.return_value = _make_ok_response(expires_in=10)

        client = _make_client(session)
        token1 = client.get_access_token()
        token2 = client.get_access_token()

        self.assertEqual(token1, "tok_abc")
        self.assertEqual(token2, "tok_abc")
        session.post.assert_called_once()

    def test_token_short_life_renewed_after_refresh_at(self):
        """A token with a short expires_in is renewed after its refresh_at threshold."""
        session = MagicMock()
        session.post.return_value = _make_ok_response(expires_in=10)

        client = _make_client(session)
        client.get_access_token()

        # refresh_at was set to monotonic + 10 - 1 = monotonic + 9.
        # Force current monotonic to exceed refresh_at.
        client._refresh_at = time.monotonic() - 1

        client.get_access_token()
        self.assertEqual(session.post.call_count, 2)

    def test_token_long_life_renewed_with_max_safety_margin(self):
        """A token with a long expires_in is renewed using the maximum safety margin (30s)."""
        session = MagicMock()
        # expires_in = 3600 -> safety margin is min(30, 360) = 30.0s.
        session.post.return_value = _make_ok_response(expires_in=3600)

        client = _make_client(session)
        client.get_access_token()

        # refresh_at is monotonic + 3600 - 30 = monotonic + 3570.
        # Set refresh_at to just in the past.
        client._refresh_at = time.monotonic() - 1

        client.get_access_token()
        self.assertEqual(session.post.call_count, 2)


# ---------------------------------------------------------------------------
# Test cases — HTTP errors
# ---------------------------------------------------------------------------


class TestFranceTravailAuthClientHttpErrors(unittest.TestCase):
    """Tests covering HTTP error responses from the token endpoint."""

    def test_http_400_raises_authentication_error(self):
        """HTTP 400 from the token endpoint raises FranceTravailAuthenticationError."""
        session = MagicMock()
        session.post.return_value = _make_error_response(400)

        client = _make_client(session)
        with self.assertRaises(FranceTravailAuthenticationError) as ctx:
            client.get_access_token()

        self.assertIn("400", str(ctx.exception))

    def test_http_401_raises_authentication_error(self):
        """HTTP 401 from the token endpoint raises FranceTravailAuthenticationError."""
        session = MagicMock()
        session.post.return_value = _make_error_response(401)

        client = _make_client(session)
        with self.assertRaises(FranceTravailAuthenticationError) as ctx:
            client.get_access_token()

        self.assertIn("401", str(ctx.exception))

    def test_http_429_raises_authentication_error(self):
        """HTTP 429 from the token endpoint raises FranceTravailAuthenticationError."""
        session = MagicMock()
        session.post.return_value = _make_error_response(429)

        client = _make_client(session)
        with self.assertRaises(FranceTravailAuthenticationError) as ctx:
            client.get_access_token()

        self.assertIn("429", str(ctx.exception))

    def test_http_500_raises_authentication_error(self):
        """HTTP 500 from the token endpoint raises FranceTravailAuthenticationError."""
        session = MagicMock()
        session.post.return_value = _make_error_response(500)

        client = _make_client(session)
        with self.assertRaises(FranceTravailAuthenticationError) as ctx:
            client.get_access_token()

        self.assertIn("500", str(ctx.exception))

    def test_http_error_message_does_not_contain_secret_or_body(self):
        """The exception message for an HTTP error must not expose the secret or response body."""
        session = MagicMock()
        # Mock error response and ensure text is set but not leaked
        response = _make_error_response(401)
        response.text = "SECRET_RESPONSE_BODY_WITH_CREDENTIALS"
        session.post.return_value = response

        config = _make_config(FRANCE_TRAVAIL_CLIENT_SECRET="ultra_secret_value")

        client = FranceTravailAuthClient(config=config, session=session)
        try:
            client.get_access_token()
        except FranceTravailAuthenticationError as exc:
            self.assertNotIn("ultra_secret_value", str(exc))
            self.assertNotIn("SECRET_RESPONSE_BODY_WITH_CREDENTIALS", str(exc))


# ---------------------------------------------------------------------------
# Test cases — network errors
# ---------------------------------------------------------------------------


class TestFranceTravailAuthClientNetworkErrors(unittest.TestCase):
    """Tests covering network-level failures."""

    def test_timeout_raises_network_error(self):
        """A requests.Timeout raises FranceTravailNetworkError."""
        session = MagicMock()
        session.post.side_effect = requests.exceptions.Timeout()

        client = _make_client(session)
        with self.assertRaises(FranceTravailNetworkError) as ctx:
            client.get_access_token()

        self.assertIn("Timeout", str(ctx.exception))

    def test_connection_error_raises_network_error(self):
        """A requests.ConnectionError raises FranceTravailNetworkError."""
        session = MagicMock()
        session.post.side_effect = requests.exceptions.ConnectionError()

        client = _make_client(session)
        with self.assertRaises(FranceTravailNetworkError):
            client.get_access_token()

        # Check that we can catch it using FranceTravailError
        session.post.side_effect = requests.exceptions.ConnectionError()
        with self.assertRaises(FranceTravailError):
            client.get_access_token()

    def test_generic_request_exception_raises_network_error(self):
        """Any other requests.RequestException raises FranceTravailNetworkError."""
        session = MagicMock()
        session.post.side_effect = requests.exceptions.RequestException("boom")

        client = _make_client(session)
        with self.assertRaises(FranceTravailNetworkError):
            client.get_access_token()


# ---------------------------------------------------------------------------
# Test cases — malformed responses
# ---------------------------------------------------------------------------


class TestFranceTravailAuthClientMalformedResponse(unittest.TestCase):
    """Tests covering invalid or unexpected response bodies."""

    def test_non_json_response_raises(self):
        """A non-JSON response raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = MagicMock()
        bad_response.status_code = 200
        bad_response.raise_for_status.return_value = None
        bad_response.json.side_effect = ValueError("Not JSON")

        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_list_json_response_raises(self):
        """A response which is a JSON list instead of a dict raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = MagicMock()
        bad_response.status_code = 200
        bad_response.raise_for_status.return_value = None
        bad_response.json.return_value = [{"access_token": "tok", "expires_in": 3600}]

        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_string_json_response_raises(self):
        """A response which is a JSON string instead of a dict raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = MagicMock()
        bad_response.status_code = 200
        bad_response.raise_for_status.return_value = None
        bad_response.json.return_value = "just a string"

        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_missing_access_token_field_raises(self):
        """A response without 'access_token' raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(access_token=None)
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError) as ctx:
            client.get_access_token()

        self.assertIn("access_token", str(ctx.exception))

    def test_non_string_access_token_raises(self):
        """A response where 'access_token' is not a string raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(access_token=123)
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_empty_access_token_raises(self):
        """A response with an empty 'access_token' raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(access_token="")
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_spaces_access_token_raises(self):
        """A response with a spaces-only 'access_token' raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(access_token="    ")
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_missing_expires_in_raises(self):
        """A response without 'expires_in' raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(expires_in=None)
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError) as ctx:
            client.get_access_token()

        self.assertIn("expires_in", str(ctx.exception))

    def test_zero_expires_in_raises(self):
        """A response with 'expires_in' equal to 0 raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(expires_in=0)
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_negative_expires_in_raises(self):
        """A response with a negative 'expires_in' raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(expires_in=-10)
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_bool_expires_in_raises(self):
        """A response with boolean 'expires_in' raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(expires_in=True)
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_string_expires_in_raises(self):
        """A response with a string expires_in raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        bad_response = _make_ok_response(expires_in="3600")
        session.post.return_value = bad_response

        client = _make_client(session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.get_access_token()

    def test_error_message_does_not_contain_token(self):
        """Exception messages must never contain the access_token value."""
        session = MagicMock()
        bad_response = _make_ok_response(access_token="SECRET_TOKEN_VALUE", expires_in=None)
        session.post.return_value = bad_response

        client = _make_client(session)
        try:
            client.get_access_token()
        except FranceTravailInvalidResponseError as exc:
            self.assertNotIn("SECRET_TOKEN_VALUE", str(exc))


if __name__ == "__main__":
    unittest.main()
