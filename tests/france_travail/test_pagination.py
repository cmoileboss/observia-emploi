"""
Unit tests for services.france_travail.pagination.

All tests are strictly offline:
- No real HTTP calls.
- No real OAuth tokens.
- No PostgreSQL connection.
- main.py, FastAPI, and SQLAlchemy are NOT imported.
"""

import unittest
from typing import Any, Mapping, Optional
from unittest.mock import MagicMock, call

from services.france_travail.client import FranceTravailOffersPage
from services.france_travail.exceptions import (
    FranceTravailApiError,
    FranceTravailAuthenticationError,
    FranceTravailInvalidResponseError,
    FranceTravailNetworkError,
    FranceTravailPaginationError,
)
from services.france_travail.pagination import FranceTravailOffersPaginator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(
    results: list[dict],
    content_range: Optional[str] = None,
    range_start: int = 0,
    range_end: int = 149,
) -> FranceTravailOffersPage:
    """Build a FranceTravailOffersPage for testing."""
    return FranceTravailOffersPage(
        payload={"resultats": results},
        results=tuple(results),
        content_range=content_range,
        range_start=range_start,
        range_end=range_end,
    )


def _make_offers(n: int) -> list[dict]:
    """Return a list of n minimal offer dicts."""
    return [{"id": str(i)} for i in range(n)]


def _make_client(*pages: FranceTravailOffersPage) -> MagicMock:
    """Return a mock client whose search_offers_page returns pages in order."""
    client = MagicMock()
    client.search_offers_page.side_effect = list(pages)
    return client


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------


class TestFranceTravailOffersPaginatorConstruction(unittest.TestCase):
    """Paginator construction must not trigger any client call."""

    def test_construction_does_not_call_client(self):
        client = MagicMock()
        FranceTravailOffersPaginator(client)
        client.search_offers_page.assert_not_called()

    def test_construction_stores_client(self):
        client = MagicMock()
        pag = FranceTravailOffersPaginator(client)
        # We access the private attribute only in tests to verify injection.
        self.assertIs(pag._client, client)


# ---------------------------------------------------------------------------
# 2. Parameter validation
# ---------------------------------------------------------------------------


class TestFranceTravailOffersPaginatorValidation(unittest.TestCase):
    """Invalid parameters must raise FranceTravailPaginationError before any call."""

    def setUp(self):
        self.client = MagicMock()
        self.pag = FranceTravailOffersPaginator(self.client)

    def _collect(self, **kwargs):
        """Exhaust the iterator to trigger validation."""
        list(self.pag.iter_pages(**kwargs))

    # --- start ---

    def test_start_bool_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(start=True)  # type: ignore
        self.client.search_offers_page.assert_not_called()

    def test_start_negative_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(start=-1)
        self.client.search_offers_page.assert_not_called()

    def test_start_zero_accepted(self):
        self.client.search_offers_page.return_value = _make_page([])
        list(self.pag.iter_pages(start=0))  # must not raise

    def test_start_positive_accepted(self):
        self.client.search_offers_page.return_value = _make_page([], range_start=50, range_end=199)
        list(self.pag.iter_pages(start=50, page_size=150))  # must not raise

    # --- page_size ---

    def test_page_size_bool_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(page_size=True)  # type: ignore
        self.client.search_offers_page.assert_not_called()

    def test_page_size_zero_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(page_size=0)
        self.client.search_offers_page.assert_not_called()

    def test_page_size_negative_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(page_size=-10)
        self.client.search_offers_page.assert_not_called()

    def test_page_size_151_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(page_size=151)
        self.client.search_offers_page.assert_not_called()

    def test_page_size_1_accepted(self):
        self.client.search_offers_page.return_value = _make_page([], range_start=0, range_end=0)
        list(self.pag.iter_pages(page_size=1))  # must not raise

    def test_page_size_150_accepted(self):
        self.client.search_offers_page.return_value = _make_page([], range_start=0, range_end=149)
        list(self.pag.iter_pages(page_size=150))  # must not raise

    # --- max_pages ---

    def test_max_pages_bool_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(max_pages=True)  # type: ignore
        self.client.search_offers_page.assert_not_called()

    def test_max_pages_zero_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(max_pages=0)
        self.client.search_offers_page.assert_not_called()

    def test_max_pages_negative_refused(self):
        with self.assertRaises(FranceTravailPaginationError):
            self._collect(max_pages=-5)
        self.client.search_offers_page.assert_not_called()

    def test_no_client_call_on_any_invalid_param(self):
        """None of the three invalid-param cases should call the client."""
        cases = [
            {"start": True},
            {"start": -1},
            {"page_size": True},
            {"page_size": 0},
            {"page_size": 151},
            {"max_pages": True},
            {"max_pages": 0},
            {"max_pages": -1},
        ]
        for kwargs in cases:
            with self.subTest(**kwargs):
                with self.assertRaises(FranceTravailPaginationError):
                    self._collect(**kwargs)
        self.client.search_offers_page.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Pagination — stop conditions
# ---------------------------------------------------------------------------


class TestFranceTravailOffersPaginatorStopConditions(unittest.TestCase):
    """Verify each natural stop condition."""

    # --- Condition A: empty first page ---

    def test_empty_first_page_is_yielded_then_stops(self):
        client = _make_client(_make_page([]))
        pag = FranceTravailOffersPaginator(client)
        pages = list(pag.iter_pages())
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].results, ())
        client.search_offers_page.assert_called_once()

    # --- Condition B: partial page ---

    def test_partial_first_page_is_yielded_then_stops(self):
        client = _make_client(_make_page(_make_offers(50), range_start=0, range_end=149))
        pag = FranceTravailOffersPaginator(client)
        pages = list(pag.iter_pages(page_size=150))
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0].results), 50)
        client.search_offers_page.assert_called_once()

    def test_full_page_then_partial_page(self):
        page1 = _make_page(_make_offers(150), range_start=0, range_end=149)
        page2 = _make_page(_make_offers(30), range_start=150, range_end=299)
        client = _make_client(page1, page2)
        pag = FranceTravailOffersPaginator(client)
        pages = list(pag.iter_pages(page_size=150))
        self.assertEqual(len(pages), 2)
        self.assertEqual(client.search_offers_page.call_count, 2)

    def test_full_page_then_empty_page(self):
        page1 = _make_page(_make_offers(150), range_start=0, range_end=149)
        page2 = _make_page([], range_start=150, range_end=299)
        client = _make_client(page1, page2)
        pag = FranceTravailOffersPaginator(client)
        pages = list(pag.iter_pages(page_size=150))
        self.assertEqual(len(pages), 2)

    # --- Range arithmetic ---

    def test_first_tranche_is_0_to_149_with_default_page_size(self):
        client = _make_client(_make_page([]))
        FranceTravailOffersPaginator(client).iter_pages().__next__()
        client.search_offers_page.assert_called_once_with(
            search_params=None,
            range_start=0,
            range_end=149,
        )

    def test_second_tranche_is_150_to_299(self):
        page1 = _make_page(_make_offers(150), range_start=0, range_end=149)
        page2 = _make_page([], range_start=150, range_end=299)
        client = _make_client(page1, page2)
        list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))
        calls = client.search_offers_page.call_args_list
        self.assertEqual(calls[0], call(search_params=None, range_start=0, range_end=149))
        self.assertEqual(calls[1], call(search_params=None, range_start=150, range_end=299))

    def test_custom_start_is_respected(self):
        client = _make_client(_make_page([], range_start=200, range_end=349))
        list(FranceTravailOffersPaginator(client).iter_pages(start=200, page_size=150))
        client.search_offers_page.assert_called_once_with(
            search_params=None,
            range_start=200,
            range_end=349,
        )

    def test_multiple_pages_with_correct_increments(self):
        pages = [
            _make_page(_make_offers(10), range_start=i * 10, range_end=i * 10 + 9)
            for i in range(3)
        ]
        pages.append(_make_page([], range_start=30, range_end=39))
        client = _make_client(*pages)
        list(FranceTravailOffersPaginator(client).iter_pages(page_size=10))
        expected_calls = [
            call(search_params=None, range_start=0, range_end=9),
            call(search_params=None, range_start=10, range_end=19),
            call(search_params=None, range_start=20, range_end=29),
            call(search_params=None, range_start=30, range_end=39),
        ]
        self.assertEqual(client.search_offers_page.call_args_list, expected_calls)

    # --- search_params forwarding and immutability ---

    def test_search_params_forwarded_to_each_call(self):
        page1 = _make_page(_make_offers(10), range_start=0, range_end=9)
        page2 = _make_page([], range_start=10, range_end=19)
        client = _make_client(page1, page2)
        params = {"codeROME": "M1805"}
        list(FranceTravailOffersPaginator(client).iter_pages(search_params=params, page_size=10))
        for c in client.search_offers_page.call_args_list:
            forwarded = c.kwargs["search_params"]
            self.assertEqual(forwarded["codeROME"], "M1805")

    def test_caller_search_params_not_mutated(self):
        client = _make_client(_make_page([]))
        original = {"codeROME": "M1805"}
        list(FranceTravailOffersPaginator(client).iter_pages(search_params=original))
        self.assertEqual(original, {"codeROME": "M1805"})
        self.assertNotIn("range", original)

    def test_none_search_params_forwarded_as_none(self):
        client = _make_client(_make_page([]))
        list(FranceTravailOffersPaginator(client).iter_pages(search_params=None))
        client.search_offers_page.assert_called_once_with(
            search_params=None,
            range_start=0,
            range_end=149,
        )


# ---------------------------------------------------------------------------
# 4. Content-Range stop condition (C)
# ---------------------------------------------------------------------------


class TestFranceTravailOffersPaginatorContentRange(unittest.TestCase):
    """Tests for Content-Range-based stop logic."""

    def test_no_content_range_accepted(self):
        """Absence of Content-Range must not raise; stop relies on conditions A/B/D."""
        page1 = _make_page(_make_offers(150), range_start=0, range_end=149)
        page2 = _make_page(_make_offers(50), range_start=150, range_end=299)
        client = _make_client(page1, page2)
        pages = list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))
        self.assertEqual(len(pages), 2)

    def test_numeric_total_stops_pagination(self):
        """Content-Range with numeric total causes stop when end >= total - 1."""
        page = _make_page(
            _make_offers(150),
            content_range="offres 0-149/150",
            range_start=0,
            range_end=149,
        )
        client = _make_client(page)
        pages = list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))
        self.assertEqual(len(pages), 1)
        client.search_offers_page.assert_called_once()

    def test_unknown_total_does_not_stop(self):
        """Content-Range '*' total does not trigger stop; relies on conditions A/B/D."""
        page1 = _make_page(
            _make_offers(150),
            content_range="offres 0-149/*",
            range_start=0,
            range_end=149,
        )
        page2 = _make_page(
            _make_offers(50),
            content_range="offres 150-299/*",
            range_start=150,
            range_end=299,
        )
        client = _make_client(page1, page2)
        pages = list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))
        self.assertEqual(len(pages), 2)

    def test_prefix_offres_accepted(self):
        """'offres 0-149/845' format is parsed correctly."""
        page1 = _make_page(
            _make_offers(150),
            content_range="offres 0-149/845",
            range_start=0,
            range_end=149,
        )
        page2 = _make_page([], range_start=150, range_end=299)
        client = _make_client(page1, page2)
        pages = list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))
        self.assertEqual(len(pages), 2)

    def test_no_prefix_format_accepted(self):
        """'0-149/845' format (without prefix) is parsed correctly."""
        page1 = _make_page(
            _make_offers(150),
            content_range="0-149/845",
            range_start=0,
            range_end=149,
        )
        page2 = _make_page([], range_start=150, range_end=299)
        client = _make_client(page1, page2)
        pages = list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))
        self.assertEqual(len(pages), 2)

    def test_numeric_total_not_yet_reached_continues(self):
        """Content-Range total not yet reached: pagination continues."""
        page1 = _make_page(
            _make_offers(150),
            content_range="offres 0-149/845",
            range_start=0,
            range_end=149,
        )
        page2 = _make_page(_make_offers(50), range_start=150, range_end=299)
        client = _make_client(page1, page2)
        pages = list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))
        self.assertEqual(len(pages), 2)

    def test_partial_last_page_with_shorter_content_range_is_accepted(self):
        """A partial last page with Content-Range end < requested end must be accepted.

        Scenario:
            - Requested tranche: 150-299 (page_size=150, start=150)
            - API returns 31 offers (indices 150-180)
            - Content-Range: offres 150-180/181

        Expected behaviour:
            - No exception of any kind.
            - Exactly one page produced.
            - search_offers_page called exactly once with range_start=150, range_end=299.
            - Stop condition B (len(results) < page_size) fires before Content-Range
              is ever inspected, so the shorter returned_end causes no error.
        """
        page = _make_page(
            _make_offers(31),
            content_range="offres 150-180/181",
            range_start=150,
            range_end=299,
        )
        client = _make_client(page)
        pag = FranceTravailOffersPaginator(client)

        pages = list(pag.iter_pages(start=150, page_size=150, max_pages=2))

        self.assertEqual(len(pages), 1, "Expected exactly one page")
        self.assertIs(pages[0], page, "The yielded page must be the one from the client")
        client.search_offers_page.assert_called_once_with(
            search_params=None,
            range_start=150,
            range_end=299,
        )


# ---------------------------------------------------------------------------
# 5. Content-Range invalid formats → FranceTravailInvalidResponseError
# ---------------------------------------------------------------------------


class TestFranceTravailOffersPaginatorInvalidContentRange(unittest.TestCase):
    """Malformed Content-Range headers must raise FranceTravailInvalidResponseError."""

    def _run_with_content_range(self, raw: str, range_start: int = 0, range_end: int = 149):
        """Fetch one full page with the given Content-Range value and collect all pages."""
        page = _make_page(
            _make_offers(150),
            content_range=raw,
            range_start=range_start,
            range_end=range_end,
        )
        client = _make_client(page)
        return list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))

    def test_empty_content_range_raises(self):
        with self.assertRaises(FranceTravailInvalidResponseError):
            self._run_with_content_range("")

    def test_unrecognised_format_raises(self):
        with self.assertRaises(FranceTravailInvalidResponseError):
            self._run_with_content_range("NOT_A_VALID_FORMAT")

    def test_start_mismatch_raises(self):
        """Content-Range start different from requested tranche start must raise."""
        page = _make_page(
            _make_offers(150),
            content_range="offres 5-154/845",  # start=5 but we requested 0
            range_start=0,
            range_end=149,
        )
        client = _make_client(page)
        with self.assertRaises(FranceTravailInvalidResponseError):
            list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))

    def test_end_mismatch_raises(self):
        """Content-Range end different from requested tranche end must raise."""
        page = _make_page(
            _make_offers(150),
            content_range="offres 0-148/845",  # end=148 but we requested 149
            range_start=0,
            range_end=149,
        )
        client = _make_client(page)
        with self.assertRaises(FranceTravailInvalidResponseError):
            list(FranceTravailOffersPaginator(client).iter_pages(page_size=150))

    def test_non_numeric_total_raises(self):
        """A non-numeric, non-'*' total must raise."""
        with self.assertRaises(FranceTravailInvalidResponseError):
            self._run_with_content_range("offres 0-149/UNKNOWN")


# ---------------------------------------------------------------------------
# 6. max_pages guard-rail (Condition D)
# ---------------------------------------------------------------------------


class TestFranceTravailOffersPaginatorMaxPages(unittest.TestCase):
    """When max_pages is exhausted without a natural stop, FranceTravailPaginationError is raised."""

    def test_max_pages_1_raises_after_first_full_page(self):
        full_page = _make_page(_make_offers(150), range_start=0, range_end=149)
        client = _make_client(full_page)
        pag = FranceTravailOffersPaginator(client)
        with self.assertRaises(FranceTravailPaginationError):
            list(pag.iter_pages(page_size=150, max_pages=1))
        # The limit page must still have been yielded.
        client.search_offers_page.assert_called_once()

    def test_max_pages_raises_pagination_error_not_api_error(self):
        full_pages = [
            _make_page(_make_offers(10), range_start=i * 10, range_end=i * 10 + 9)
            for i in range(3)
        ]
        client = _make_client(*full_pages)
        pag = FranceTravailOffersPaginator(client)
        with self.assertRaises(FranceTravailPaginationError):
            list(pag.iter_pages(page_size=10, max_pages=3))

    def test_no_call_after_max_pages(self):
        """No additional client call must be made once max_pages is exhausted."""
        full_pages = [
            _make_page(_make_offers(10), range_start=i * 10, range_end=i * 10 + 9)
            for i in range(5)
        ]
        client = MagicMock()
        client.search_offers_page.side_effect = full_pages
        pag = FranceTravailOffersPaginator(client)
        try:
            list(pag.iter_pages(page_size=10, max_pages=3))
        except FranceTravailPaginationError:
            pass
        self.assertEqual(client.search_offers_page.call_count, 3)

    def test_max_pages_not_raised_when_natural_stop_occurs(self):
        """If a partial page occurs at max_pages boundary, no error is raised."""
        partial_page = _make_page(_make_offers(5), range_start=0, range_end=9)
        client = _make_client(partial_page)
        pag = FranceTravailOffersPaginator(client)
        # Must NOT raise — partial page is a natural stop (condition B).
        pages = list(pag.iter_pages(page_size=10, max_pages=1))
        self.assertEqual(len(pages), 1)

    def test_voluntary_limit_one_page_full_success(self):
        """With voluntary_limit=True, reaching max_pages=1 on full page does not raise."""
        full_page = _make_page(_make_offers(150), range_start=0, range_end=149)
        client = _make_client(full_page)
        pag = FranceTravailOffersPaginator(client)
        pages = list(pag.iter_pages(page_size=150, max_pages=1, voluntary_limit=True))
        self.assertEqual(len(pages), 1)
        client.search_offers_page.assert_called_once()

    def test_voluntary_limit_two_pages_full_success(self):
        """With voluntary_limit=True, reaching max_pages=2 on full pages does not raise."""
        p1 = _make_page(_make_offers(150), range_start=0, range_end=149)
        p2 = _make_page(_make_offers(150), range_start=150, range_end=299)
        client = _make_client(p1, p2)
        pag = FranceTravailOffersPaginator(client)
        pages = list(pag.iter_pages(page_size=150, max_pages=2, voluntary_limit=True))
        self.assertEqual(len(pages), 2)
        self.assertEqual(client.search_offers_page.call_count, 2)

    def test_voluntary_limit_natural_stop_before_limit(self):
        """With voluntary_limit=True, natural stop before limit works normally."""
        p1 = _make_page(_make_offers(150), range_start=0, range_end=149)
        p2 = _make_page(_make_offers(50), range_start=150, range_end=299)
        client = _make_client(p1, p2)
        pag = FranceTravailOffersPaginator(client)
        pages = list(pag.iter_pages(page_size=150, max_pages=5, voluntary_limit=True))
        self.assertEqual(len(pages), 2)
        self.assertEqual(client.search_offers_page.call_count, 2)

    def test_voluntary_limit_content_range_total_reached(self):
        """With voluntary_limit=True, natural stop via Content-Range total works normally."""
        p1 = _make_page(_make_offers(150), content_range="offres 0-149/150", range_start=0, range_end=149)
        client = _make_client(p1)
        pag = FranceTravailOffersPaginator(client)
        pages = list(pag.iter_pages(page_size=150, max_pages=5, voluntary_limit=True))
        self.assertEqual(len(pages), 1)
        client.search_offers_page.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Error propagation
# ---------------------------------------------------------------------------


class TestFranceTravailOffersPaginatorErrorPropagation(unittest.TestCase):
    """Client exceptions must propagate without wrapping."""

    def _make_raising_client(self, exc: Exception) -> MagicMock:
        client = MagicMock()
        client.search_offers_page.side_effect = exc
        return client

    def test_api_error_propagated(self):
        client = self._make_raising_client(FranceTravailApiError("HTTP 429"))
        pag = FranceTravailOffersPaginator(client)
        with self.assertRaises(FranceTravailApiError):
            list(pag.iter_pages())

    def test_network_error_propagated(self):
        client = self._make_raising_client(FranceTravailNetworkError("Timeout"))
        pag = FranceTravailOffersPaginator(client)
        with self.assertRaises(FranceTravailNetworkError):
            list(pag.iter_pages())

    def test_invalid_response_error_propagated(self):
        client = self._make_raising_client(FranceTravailInvalidResponseError("Bad JSON"))
        pag = FranceTravailOffersPaginator(client)
        with self.assertRaises(FranceTravailInvalidResponseError):
            list(pag.iter_pages())

    def test_authentication_error_propagated(self):
        client = self._make_raising_client(FranceTravailAuthenticationError("401"))
        pag = FranceTravailOffersPaginator(client)
        with self.assertRaises(FranceTravailAuthenticationError):
            list(pag.iter_pages())

    def test_client_error_is_not_wrapped_in_pagination_error(self):
        """Client exceptions must NOT be wrapped in FranceTravailPaginationError."""
        client = self._make_raising_client(FranceTravailApiError("HTTP 500"))
        pag = FranceTravailOffersPaginator(client)
        try:
            list(pag.iter_pages())
            self.fail("Expected FranceTravailApiError")
        except FranceTravailPaginationError:
            self.fail("Client error must not be wrapped in FranceTravailPaginationError")
        except FranceTravailApiError:
            pass  # correct


# ---------------------------------------------------------------------------
# 8. Isolation guarantees (static checks)
# ---------------------------------------------------------------------------


class TestFranceTravailOffersPaginatorIsolation(unittest.TestCase):
    """Verify that no forbidden modules are imported by pagination.py."""

    def test_requests_not_imported_directly(self):
        """pagination.py must not import 'requests' directly."""
        import services.france_travail.pagination as mod
        self.assertFalse(
            hasattr(mod, "requests"),
            "pagination.py must not expose 'requests' at module level",
        )

    def test_fastapi_not_imported(self):
        import services.france_travail.pagination as mod
        self.assertFalse(hasattr(mod, "fastapi"))

    def test_sqlalchemy_not_imported(self):
        import services.france_travail.pagination as mod
        self.assertFalse(hasattr(mod, "sqlalchemy"))


if __name__ == "__main__":
    unittest.main()
