# -*- coding: utf-8 -*-

"""
Unit tests for FranceTravailOffersClient.get_rome_referentiel (§16).

All HTTP calls are mocked with unittest.mock. No real network connection is
made. No database is contacted. main.py is not imported.

The existing tests for search_offers_page are in test_client.py and are NOT
modified here. This file only tests the new get_rome_referentiel method and
verifies there is no regression on the existing method.
"""

import sys
import unittest
from unittest.mock import MagicMock

import requests


# ---------------------------------------------------------------------------
# Isolation helpers
# ---------------------------------------------------------------------------

_MODULES_TO_CLEAN = [
    "services.france_travail.client",
]


def _import_fresh():
    for name in list(sys.modules.keys()):
        if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
            sys.modules.pop(name, None)

    from services.france_travail.client import (  # noqa: PLC0415
        FranceTravailOffersClient,
        FranceTravailOffersPage,
    )
    from services.france_travail.config import FranceTravailConfig  # noqa: PLC0415
    from services.france_travail.exceptions import (  # noqa: PLC0415
        FranceTravailApiError,
        FranceTravailInvalidResponseError,
        FranceTravailNetworkError,
        FranceTravailError,
    )
    return (
        FranceTravailOffersClient,
        FranceTravailOffersPage,
        FranceTravailConfig,
        FranceTravailApiError,
        FranceTravailInvalidResponseError,
        FranceTravailNetworkError,
        FranceTravailError,
    )


# ---------------------------------------------------------------------------
# Helpers (mirror test_client.py helpers to stay self-contained)
# ---------------------------------------------------------------------------

_BASE_OFFERS_URL = "https://example.com/partenaire/offresdemploi/v2/offres/search"
_EXPECTED_REFERENTIEL_URL = (
    "https://example.com/partenaire/offresdemploi/v2/referentiel/metiers"
)


def _make_config(**overrides):
    from services.france_travail.config import FranceTravailConfig

    base = {
        "FRANCE_TRAVAIL_CLIENT_ID": "test_id",
        "FRANCE_TRAVAIL_CLIENT_SECRET": "super_secret",
        "FRANCE_TRAVAIL_TOKEN_URL": "https://example.com/token",
        "FRANCE_TRAVAIL_SCOPE": "api_offresdemploiv2",
        "FRANCE_TRAVAIL_OFFERS_SEARCH_URL": _BASE_OFFERS_URL,
        "FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS": "10",
    }
    base.update(overrides)
    return FranceTravailConfig.from_mapping(base)


class _MockAuthClient:
    def __init__(self, token="tok_abc"):
        self.token = token
        self.call_count = 0

    def get_access_token(self):
        self.call_count += 1
        return self.token


def _make_ok_response(json_body=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status.return_value = None
    if isinstance(json_body, Exception):
        response.json.side_effect = json_body
    else:
        response.json.return_value = json_body if json_body is not None else []
    return response


def _make_error_response(status_code):
    response = MagicMock()
    response.status_code = status_code
    http_error = requests.exceptions.HTTPError(response=response)
    response.raise_for_status.side_effect = http_error
    return response


# ---------------------------------------------------------------------------
# §16 — Tests for get_rome_referentiel
# ---------------------------------------------------------------------------


class TestGetRomeReferentiel(unittest.TestCase):
    """Tests for FranceTravailOffersClient.get_rome_referentiel (§16)."""

    def setUp(self):
        (
            self.FranceTravailOffersClient,
            self.FranceTravailOffersPage,
            self.FranceTravailConfig,
            self.FranceTravailApiError,
            self.FranceTravailInvalidResponseError,
            self.FranceTravailNetworkError,
            self.FranceTravailError,
        ) = _import_fresh()

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules.keys()):
            if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
                sys.modules.pop(name, None)

    def _make_client(self, session, token="tok_abc"):
        auth = _MockAuthClient(token=token)
        return self.FranceTravailOffersClient(_make_config(), auth, session), auth

    # --- Exact path called ---

    def test_calls_referentiel_metiers_path(self):
        """get_rome_referentiel calls the /referentiel/metiers path."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=[])
        client, _ = self._make_client(session)

        client.get_rome_referentiel()

        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertEqual(args[0], _EXPECTED_REFERENTIEL_URL)

    # --- GET method ---

    def test_uses_get_method(self):
        """get_rome_referentiel uses the HTTP GET method."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=[])
        client, _ = self._make_client(session)

        client.get_rome_referentiel()

        session.get.assert_called_once()
        # Verify it's .get() and not .post() etc.
        session.post.assert_not_called()

    # --- Accept header ---

    def test_accept_json_header_sent(self):
        """get_rome_referentiel sends Accept: application/json."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=[])
        client, _ = self._make_client(session)

        client.get_rome_referentiel()

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["headers"]["Accept"], "application/json")

    # --- Authorization header is sent (token mechanism works) ---

    def test_authorization_header_sent(self):
        """get_rome_referentiel sends Authorization: Bearer <token>."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=[])
        client, auth = self._make_client(session, token="test_token_xyz")

        client.get_rome_referentiel()

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test_token_xyz")
        self.assertEqual(auth.call_count, 1)

    # --- Token NOT in exception messages ---

    def test_token_not_in_network_exception(self):
        """The token value does not appear in FranceTravailNetworkError messages."""
        session = MagicMock()
        session.get.side_effect = requests.exceptions.Timeout("timeout")
        client, _ = self._make_client(session, token="SECRET_TOKEN_VAL")

        try:
            client.get_rome_referentiel()
        except self.FranceTravailError as exc:
            self.assertNotIn("SECRET_TOKEN_VAL", str(exc))

    # --- Timeout transmitted ---

    def test_timeout_transmitted(self):
        """The configured timeout is passed to the HTTP call."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=[])
        auth = _MockAuthClient()
        config = _make_config(FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS="15")
        client = self.FranceTravailOffersClient(config, auth, session)

        client.get_rome_referentiel()

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["timeout"], 15)

    # --- Valid JSON list ---

    def test_valid_json_list_returned(self):
        """A valid list JSON response is returned as-is."""
        payload = [
            {"code": "M1805", "libelle": "Informatique"},
            {"code": "A1401", "libelle": "Agri"},
        ]
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=payload)
        client, _ = self._make_client(session)

        result = client.get_rome_referentiel()

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["code"], "M1805")

    # --- HTTP error ---

    def test_http_error_raises_api_error(self):
        """An HTTP error raises FranceTravailApiError."""
        session = MagicMock()
        session.get.return_value = _make_error_response(500)
        client, _ = self._make_client(session)

        with self.assertRaises(self.FranceTravailApiError) as ctx:
            client.get_rome_referentiel()
        self.assertIn("500", str(ctx.exception))

    def test_http_401_raises_api_error(self):
        """HTTP 401 raises FranceTravailApiError."""
        session = MagicMock()
        session.get.return_value = _make_error_response(401)
        client, _ = self._make_client(session)

        with self.assertRaises(self.FranceTravailApiError):
            client.get_rome_referentiel()

    # --- Invalid JSON ---

    def test_invalid_json_raises_invalid_response_error(self):
        """A non-JSON response raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body=ValueError("Not JSON"))
        client, _ = self._make_client(session)

        with self.assertRaises(self.FranceTravailInvalidResponseError):
            client.get_rome_referentiel()

    # --- Non-list JSON ---

    def test_dict_json_raises_invalid_response_error(self):
        """A JSON dict root raises FranceTravailInvalidResponseError."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={"code": "M1805"})
        client, _ = self._make_client(session)

        with self.assertRaises(self.FranceTravailInvalidResponseError):
            client.get_rome_referentiel()

    # --- Network errors ---

    def test_timeout_raises_network_error(self):
        """A timeout raises FranceTravailNetworkError."""
        session = MagicMock()
        session.get.side_effect = requests.exceptions.Timeout("t")
        client, _ = self._make_client(session)

        with self.assertRaises(self.FranceTravailNetworkError):
            client.get_rome_referentiel()

    def test_connection_error_raises_network_error(self):
        """A connection error raises FranceTravailNetworkError."""
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("c")
        client, _ = self._make_client(session)

        with self.assertRaises(self.FranceTravailNetworkError):
            client.get_rome_referentiel()

    def test_generic_request_exception_raises_network_error(self):
        """A generic requests exception raises FranceTravailNetworkError."""
        session = MagicMock()
        session.get.side_effect = requests.exceptions.RequestException("r")
        client, _ = self._make_client(session)

        with self.assertRaises(self.FranceTravailNetworkError):
            client.get_rome_referentiel()

    # --- No regression on search_offers_page ---

    def test_search_offers_page_still_works(self):
        """search_offers_page still works after adding get_rome_referentiel."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(
            json_body={"resultats": [{"id": "1"}]}
        )
        client, _ = self._make_client(session)

        page = client.search_offers_page()

        self.assertIsInstance(page, self.FranceTravailOffersPage)
        self.assertEqual(len(page.results), 1)

    def test_search_offers_page_calls_different_url_than_referentiel(self):
        """search_offers_page still calls the offers search URL, not the referentiel URL."""
        session = MagicMock()
        session.get.return_value = _make_ok_response(json_body={"resultats": []})
        client, _ = self._make_client(session)

        client.search_offers_page()

        _, kwargs = session.get.call_args
        args_pos, _ = session.get.call_args
        self.assertIn("/offres/search", args_pos[0])
        self.assertNotIn("/referentiel/metiers", args_pos[0])


# ---------------------------------------------------------------------------
# Tests for _build_referentiel_url (URL construction robustness)
# ---------------------------------------------------------------------------


class TestBuildReferentielUrl(unittest.TestCase):
    """Unit tests for the _build_referentiel_url helper function.

    These tests verify that the URL construction is immune to variations
    in the offers_search_url and does not rely on a fragile string replace.
    """

    def setUp(self):
        _import_fresh()
        from services.france_travail.client import _build_referentiel_url  # noqa: PLC0415
        self._build = _build_referentiel_url

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules.keys()):
            if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
                sys.modules.pop(name, None)

    def test_standard_url_produces_exact_referentiel_url(self):
        """Standard offers search URL produces the exact referentiel URL."""
        result = self._build(
            "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
        )
        self.assertEqual(
            result,
            "https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/metiers",
        )

    def test_url_with_trailing_slash(self):
        """offers_search_url with a trailing slash produces the same referentiel URL."""
        result = self._build(
            "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search/"
        )
        self.assertEqual(
            result,
            "https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/metiers",
        )

    def test_url_without_offres_search_segment(self):
        """URL that does not contain /offres/search still produces the correct referentiel URL."""
        result = self._build(
            "https://api.francetravail.io/some/other/endpoint"
        )
        self.assertEqual(
            result,
            "https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/metiers",
        )

    def test_referentiel_path_is_always_absolute(self):
        """The referentiel path segment is always /partenaire/offresdemploi/v2/referentiel/metiers."""
        for search_url in [
            "https://example.com/a/b/c",
            "https://example.com/",
            "https://example.com/offres/search/extra",
        ]:
            with self.subTest(search_url=search_url):
                result = self._build(search_url)
                self.assertTrue(
                    result.endswith("/partenaire/offresdemploi/v2/referentiel/metiers"),
                    msg=f"Expected referentiel path suffix, got: {result}",
                )

    def test_scheme_and_host_preserved(self):
        """The scheme and host from offers_search_url are preserved."""
        result = self._build("https://my-custom-host.example.org/v2/offres/search")
        self.assertTrue(result.startswith("https://my-custom-host.example.org/"))

    def test_no_replace_dependency(self):
        """URL containing /offres/search multiple times is handled correctly."""
        # If the construction used str.replace(), it would replace all occurrences.
        # With urlparse-based construction, the path is always replaced entirely.
        url_with_double_occurrence = (
            "https://example.com/offres/search/offres/search"
        )
        result = self._build(url_with_double_occurrence)
        # The result must be scheme://host + absolute referentiel path only.
        self.assertEqual(
            result,
            "https://example.com/partenaire/offresdemploi/v2/referentiel/metiers",
        )

    def test_example_config_url_produces_expected_url(self):
        """The test suite config URL produces the expected test referentiel URL."""
        result = self._build(_BASE_OFFERS_URL)
        self.assertEqual(result, _EXPECTED_REFERENTIEL_URL)

    def test_referentiel_url_different_from_search_url(self):
        """The referentiel URL is always different from the search URL."""
        result = self._build(_BASE_OFFERS_URL)
        self.assertNotEqual(result, _BASE_OFFERS_URL)
        self.assertNotIn("/offres/search", result)
        self.assertIn("/referentiel/metiers", result)


if __name__ == "__main__":
    unittest.main()
