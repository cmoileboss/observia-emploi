"""
Unit tests for services.france_travail.client.

All HTTP calls are mocked with unittest.mock. No real network connection is
made. No database is contacted. main.py is not imported.
"""

import unittest
from unittest.mock import MagicMock

import requests

from services.france_travail.client import FranceTravailOffersClient, FranceTravailOffersPage
from services.france_travail.config import FranceTravailConfig
from services.france_travail.exceptions import (
    FranceTravailError,
    FranceTravailApiError,
    FranceTravailInvalidResponseError,
    FranceTravailNetworkError,
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


def _make_ok_response(json_body: any = None, status_code: int = 200, headers: dict = None) -> MagicMock:
    """Return a mock HTTP response simulating a successful offers endpoint reply."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.raise_for_status.return_value = None
    if json_body is not None:
        if isinstance(json_body, Exception):
            response.json.side_effect = json_body
        else:
            response.json.return_value = json_body
    else:
        response.json.return_value = {"resultats": [{"id": "123"}]}
    return response


def _make_error_response(status_code: int) -> MagicMock:
    """Return a mock HTTP response simulating an HTTP error."""
    response = MagicMock()
    response.status_code = status_code
    http_error = requests.exceptions.HTTPError(response=response)
    response.raise_for_status.side_effect = http_error
    return response


class MockAuthClient:
    """Mock auth client implementing the protocol."""

    def __init__(self, token: any = "tok_abc") -> None:
        self.token = token
        self.call_count = 0

    def get_access_token(self) -> str:
        self.call_count += 1
        return self.token


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestFranceTravailOffersClientConstruction(unittest.TestCase):
    """Tests covering object creation and dependency injection."""

    def test_construction_does_not_call_network_or_oauth(self):
        """Object construction does not trigger any network or token request."""
        session = MagicMock()
        auth = MockAuthClient()
        config = _make_config()

        FranceTravailOffersClient(config, auth, session)

        session.get.assert_not_called()
        self.assertEqual(auth.call_count, 0)

    def test_session_injection(self):
        """Constructing the client with a session injects it correctly."""
        session = MagicMock()
        auth = MockAuthClient()
        config = _make_config()

        client = FranceTravailOffersClient(config, auth, session)
        self.assertEqual(client._session, session)


class TestFranceTravailOffersClientSuccess(unittest.TestCase):
    """Tests covering successful offers page retrieval."""

    def test_search_offers_page_success_all_params(self):
        """Verify successful page retrieval with correct headers and params."""
        session = MagicMock()
        headers = {"Content-Range": "offres 0-49/2000"}
        session.get.return_value = _make_ok_response(
            json_body={"resultats": [{"id": "1"}, {"id": "2"}]},
            headers=headers
        )

        auth = MockAuthClient(token="valid_token")
        config = _make_config(FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS="20")
        client = FranceTravailOffersClient(config, auth, session)

        search_params = {"codeROME": "M1805"}
        page = client.search_offers_page(
            search_params=search_params,
            range_start=0,
            range_end=49
        )

        # Verify OAuth token request
        self.assertEqual(auth.call_count, 1)

        # Verify requests call
        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertEqual(args[0], config.offers_search_url)
        self.assertEqual(kwargs["timeout"], 20)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer valid_token")
        self.assertEqual(kwargs["headers"]["Accept"], "application/json")
        self.assertNotIn("Range", kwargs["headers"])
        self.assertEqual(kwargs["params"]["codeROME"], "M1805")
        self.assertEqual(kwargs["params"]["range"], "0-49")

        # Verify caller's dict was not modified
        self.assertEqual(search_params, {"codeROME": "M1805"})

        # Verify return structure
        self.assertIsInstance(page, FranceTravailOffersPage)
        self.assertEqual(page.range_start, 0)
        self.assertEqual(page.range_end, 49)
        self.assertEqual(page.content_range, "offres 0-49/2000")
        self.assertEqual(page.results, ({"id": "1"}, {"id": "2"}))
        self.assertEqual(page.payload["resultats"], [{"id": "1"}, {"id": "2"}])

    def test_search_offers_page_without_content_range(self):
        """Verify client works when Content-Range is not in response headers."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={"resultats": []})
        auth = MockAuthClient()
        client = FranceTravailOffersClient(_make_config(), auth, session)

        page = client.search_offers_page()
        self.assertIsNone(page.content_range)
        self.assertEqual(page.results, ())

    def test_range_is_sent_as_query_parameter_not_header(self):
        """The range slice must be sent as query param 'range', not as HTTP header 'Range'."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={"resultats": []})
        auth = MockAuthClient()
        client = FranceTravailOffersClient(_make_config(), auth, session)

        original_params = {"codeROME": "M1805"}
        client.search_offers_page(
            search_params=original_params,
            range_start=0,
            range_end=149,
        )

        _, kwargs = session.get.call_args
        # Range must be a query parameter, not an HTTP header
        self.assertIn("range", kwargs["params"])
        self.assertEqual(kwargs["params"]["range"], "0-149")
        self.assertNotIn("Range", kwargs["headers"])
        # The caller's original dict must not be mutated
        self.assertNotIn("range", original_params)
        self.assertEqual(original_params, {"codeROME": "M1805"})

    def test_search_offers_page_with_empty_resultats_list(self):
        """Verify client handles a valid response with no offers."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={"resultats": []})
        auth = MockAuthClient()
        client = FranceTravailOffersClient(_make_config(), auth, session)

        page = client.search_offers_page()
        self.assertEqual(page.results, ())


class TestFranceTravailOffersClientRangeValidation(unittest.TestCase):
    """Tests covering validation of range offsets."""

    def test_range_start_bool_refused(self):
        """range_start as boolean raises FranceTravailInvalidResponseError."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), MagicMock())
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page(range_start=True)  # type: ignore

    def test_range_end_bool_refused(self):
        """range_end as boolean raises FranceTravailInvalidResponseError."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), MagicMock())
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page(range_end=False)  # type: ignore

    def test_negative_ranges_refused(self):
        """Negative start or end raises FranceTravailInvalidResponseError."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), MagicMock())
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page(range_start=-1)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page(range_end=-5)

    def test_range_end_less_than_range_start_refused(self):
        """range_end less than range_start raises FranceTravailInvalidResponseError."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), MagicMock())
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page(range_start=10, range_end=9)

    def test_tranche_greater_than_150_refused(self):
        """Tranche sizes > 150 raise FranceTravailInvalidResponseError."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), MagicMock())
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page(range_start=0, range_end=150)  # size = 151

    def test_single_result_tranche_accepted(self):
        """Tranche of exactly 1 item (start=0, end=0) is accepted."""
        session = MagicMock()
        session.get.return_value = _make_ok_response()
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        page = client.search_offers_page(range_start=0, range_end=0)
        self.assertEqual(page.range_start, 0)
        self.assertEqual(page.range_end, 0)

    def test_150_result_tranche_accepted(self):
        """Tranche of exactly 150 items (start=0, end=149) is accepted."""
        session = MagicMock()
        session.get.return_value = _make_ok_response()
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        page = client.search_offers_page(range_start=0, range_end=149)
        self.assertEqual(page.range_start, 0)
        self.assertEqual(page.range_end, 149)


class TestFranceTravailOffersClientTokenValidation(unittest.TestCase):
    """Tests covering validation of the retrieved OAuth token."""

    def test_empty_token_refused(self):
        """An empty token raises FranceTravailInvalidResponseError."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(""), MagicMock())
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page()

    def test_spaces_token_refused(self):
        """A token composed of spaces raises FranceTravailInvalidResponseError."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient("   "), MagicMock())
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page()

    def test_non_string_token_refused(self):
        """A non-string token raises FranceTravailInvalidResponseError."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(1234), MagicMock())  # type: ignore
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page()

    def test_token_absent_from_error_messages(self):
        """If token validation fails, the token value must not leak in error message."""
        client = FranceTravailOffersClient(_make_config(), MockAuthClient("SECRET_VAL"), MagicMock())
        try:
            client.search_offers_page(range_start=True)  # type: ignore
        except FranceTravailError as exc:
            self.assertNotIn("SECRET_VAL", str(exc))


class TestFranceTravailOffersClientJsonValidation(unittest.TestCase):
    """Tests covering response JSON validation."""

    def test_non_json_response_raises(self):
        """A non-JSON response raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=ValueError("Not JSON"))
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page()

    def test_list_json_response_raises(self):
        """A response consisting of a JSON list raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=[{"id": "123"}])
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page()

    def test_resultats_key_absent_raises(self):
        """A response missing 'resultats' raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={"filtresPossibles": []})
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page()

    def test_resultats_non_list_raises(self):
        """A response where 'resultats' is not a list raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={"resultats": "not a list"})
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page()

    def test_offer_element_non_dict_raises(self):
        """A response where a resultats element is not a dict raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={"resultats": [123]})
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailInvalidResponseError):
            client.search_offers_page()

    def test_payload_with_filtres_possibles(self):
        """A response with 'filtresPossibles' along with resultats is successfully processed."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={
            "resultats": [{"id": "1"}],
            "filtresPossibles": [{"rom": "M1805"}]
        })
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        page = client.search_offers_page()
        self.assertEqual(page.results, ({"id": "1"},))
        self.assertIn("filtresPossibles", page.payload)


class TestFranceTravailOffersClientHttpErrors(unittest.TestCase):
    """Tests covering conversion of HTTP error status codes."""

    def _test_http_status_raises_api_error(self, code: int):
        session = MagicMock()
        session.get.return_value = _make_error_response(code)
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailApiError) as ctx:
            client.search_offers_page()
        self.assertIn(str(code), str(ctx.exception))

    def test_http_400(self):
        self._test_http_status_raises_api_error(400)

    def test_http_401(self):
        self._test_http_status_raises_api_error(401)

    def test_http_403(self):
        self._test_http_status_raises_api_error(403)

    def test_http_404(self):
        self._test_http_status_raises_api_error(404)

    def test_http_429(self):
        self._test_http_status_raises_api_error(429)

    def test_http_500(self):
        self._test_http_status_raises_api_error(500)

    def test_http_502(self):
        self._test_http_status_raises_api_error(502)

    def test_http_503(self):
        self._test_http_status_raises_api_error(503)

    def test_no_secret_or_body_in_exception(self):
        """Ensure exceptions do not leak tokens, secrets, or response body text."""
        session = MagicMock()
        err_resp = _make_error_response(500)
        err_resp.text = "RAW_SECRET_ERROR_BODY"
        session.get.return_value = err_resp

        config = _make_config(FRANCE_TRAVAIL_CLIENT_SECRET="secret_key")
        client = FranceTravailOffersClient(config, MockAuthClient(token="token_val"), session)

        try:
            client.search_offers_page()
        except FranceTravailApiError as exc:
            self.assertNotIn("secret_key", str(exc))
            self.assertNotIn("token_val", str(exc))
            self.assertNotIn("RAW_SECRET_ERROR_BODY", str(exc))


class TestFranceTravailOffersClientNetworkErrors(unittest.TestCase):
    """Tests covering requests network error mapping."""

    def test_timeout_raises_network_error(self):
        """A timeout raises FranceTravailNetworkError."""
        session = MagicMock()
        session.get.side_effect = requests.exceptions.Timeout("timeout")
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailNetworkError) as ctx:
            client.search_offers_page()
        self.assertIn("Timeout", str(ctx.exception))

    def test_connection_error_raises_network_error(self):
        """A connection error raises FranceTravailNetworkError."""
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("conn")
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailNetworkError):
            client.search_offers_page()

    def test_generic_request_exception_raises_network_error(self):
        """A generic requests exception raises FranceTravailNetworkError."""
        session = MagicMock()
        session.get.side_effect = requests.exceptions.RequestException("err")
        client = FranceTravailOffersClient(_make_config(), MockAuthClient(), session)
        with self.assertRaises(FranceTravailNetworkError):
            client.search_offers_page()


if __name__ == "__main__":
    unittest.main()
