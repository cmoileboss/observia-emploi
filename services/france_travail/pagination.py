"""
Controlled pagination over France Travail job offers.

This module provides ``FranceTravailOffersPaginator``, which wraps
``FranceTravailOffersClient.search_offers_page()`` and iterates page by page
until a natural end condition is reached or a safety limit is hit.

Natural end conditions (no error raised):
    A. The ``results`` list of the returned page is empty.
    B. The number of results is strictly less than ``page_size``.
    C. The ``Content-Range`` header provides a numeric total and the
       last received result index is greater than or equal to that total.

Safety limit:
    D. ``max_pages`` pages have been consumed without any condition A, B, or C
       being detected.  In this case ``FranceTravailPaginationError`` is raised
       *after* yielding the last allowed page, so callers still receive all
       data collected so far.

Errors from the underlying client (``FranceTravailApiError``,
``FranceTravailNetworkError``, ``FranceTravailInvalidResponseError``,
``FranceTravailAuthenticationError``) are propagated without modification.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterator, Mapping, NamedTuple, Optional, Protocol

from services.france_travail.client import FranceTravailOffersPage
from services.france_travail.exceptions import (
    FranceTravailInvalidResponseError,
    FranceTravailPaginationError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol — keeps pagination.py independent of the concrete client class
# ---------------------------------------------------------------------------

# Regex accepting both "offres 0-149/845" and "0-149/845" (and "*" total).
_CONTENT_RANGE_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9_-]*\s+)?(\d+)-(\d+)/(\d+|\*)$"
)


class _OffersClientProtocol(Protocol):
    """Minimal interface required from the HTTP offers client."""

    def search_offers_page(
        self,
        search_params: Optional[Mapping[str, Any]],
        range_start: int,
        range_end: int,
    ) -> FranceTravailOffersPage:
        """Fetch a single page of job offers."""
        ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _ParsedContentRange(NamedTuple):
    """Structured representation of a parsed Content-Range header value."""

    returned_start: int
    returned_end: int
    total: Optional[int]  # None means total is unknown ("*")


def _parse_content_range(raw: str) -> _ParsedContentRange:
    """Parse a Content-Range header value into its component integers.

    Accepted formats::

        offres 0-149/845
        0-149/845
        offres 0-149/*
        0-149/*

    Parameters
    ----------
    raw:
        The raw header string exactly as received from the HTTP response.

    Returns
    -------
    _ParsedContentRange
        Parsed start, end, and optional total.

    Raises
    ------
    FranceTravailInvalidResponseError
        When the header value is present but does not match any recognised
        format, or when numeric fields cannot be converted to integers.
    """
    stripped = raw.strip()
    if not stripped:
        raise FranceTravailInvalidResponseError(
            "Content-Range header is present but empty."
        )

    match = _CONTENT_RANGE_RE.match(stripped)
    if not match:
        raise FranceTravailInvalidResponseError(
            f"Content-Range header has an unrecognised format: {stripped!r}."
        )

    start_str, end_str, total_str = match.group(1), match.group(2), match.group(3)

    # These conversions are safe because the regex already matched \d+, but we
    # guard explicitly to satisfy the "non-numeric" error test cases.
    try:
        returned_start = int(start_str)
    except ValueError as exc:
        raise FranceTravailInvalidResponseError(
            f"Content-Range start is not a valid integer: {start_str!r}."
        ) from exc

    try:
        returned_end = int(end_str)
    except ValueError as exc:
        raise FranceTravailInvalidResponseError(
            f"Content-Range end is not a valid integer: {end_str!r}."
        ) from exc

    if total_str == "*":
        total: Optional[int] = None
    else:
        try:
            total = int(total_str)
        except ValueError as exc:
            raise FranceTravailInvalidResponseError(
                f"Content-Range total is neither a valid integer nor '*': {total_str!r}."
            ) from exc

    return _ParsedContentRange(
        returned_start=returned_start,
        returned_end=returned_end,
        total=total,
    )


def _validate_int_param(value: Any, name: str, *, min_value: int, max_value: Optional[int] = None) -> None:
    """Validate a pagination integer parameter.

    Parameters
    ----------
    value:
        The value to validate.
    name:
        Parameter name used in error messages.
    min_value:
        Minimum accepted value (inclusive).
    max_value:
        Maximum accepted value (inclusive), or ``None`` for no upper bound.

    Raises
    ------
    FranceTravailPaginationError
        When the value is a bool, not an integer, below ``min_value``, or
        above ``max_value``.
    """
    if isinstance(value, bool):
        raise FranceTravailPaginationError(
            f"Invalid type for '{name}': booleans are not allowed."
        )
    if not isinstance(value, int):
        raise FranceTravailPaginationError(
            f"Invalid type for '{name}': must be an integer, got {type(value).__name__}."
        )
    if value < min_value:
        raise FranceTravailPaginationError(
            f"Invalid value for '{name}': must be >= {min_value}, got {value}."
        )
    if max_value is not None and value > max_value:
        raise FranceTravailPaginationError(
            f"Invalid value for '{name}': must be <= {max_value}, got {value}."
        )


# ---------------------------------------------------------------------------
# Main paginator class
# ---------------------------------------------------------------------------


class FranceTravailOffersPaginator:
    """Iterates over France Travail job offers page by page.

    This class wraps an existing ``FranceTravailOffersClient``-compatible object
    and calls ``search_offers_page()`` repeatedly, computing each tranche
    automatically and stopping on the first natural end condition.

    Parameters
    ----------
    offers_client:
        An object implementing ``search_offers_page()``.  No call is made during
        construction.

    Example
    -------
    ::

        paginator = FranceTravailOffersPaginator(client)
        for page in paginator.iter_pages(search_params={"codeROME": "M1805"}):
            process(page.results)
    """

    def __init__(self, offers_client: _OffersClientProtocol) -> None:
        self._client = offers_client

    def iter_pages(
        self,
        search_params: Optional[Mapping[str, Any]] = None,
        start: int = 0,
        page_size: int = 150,
        max_pages: int = 100,
    ) -> Iterator[FranceTravailOffersPage]:
        """Iterate over pages of job offers, yielding each page as it is fetched.

        Parameters
        ----------
        search_params:
            Optional search criteria forwarded unchanged to each
            ``search_offers_page()`` call.  The caller's mapping is never mutated.
        start:
            Index of the first result to retrieve (0-based).
        page_size:
            Number of results per page (1–150 inclusive).
        max_pages:
            Maximum number of pages to fetch.  When this limit is reached
            without any natural stop condition, ``FranceTravailPaginationError``
            is raised after yielding the last page.

        Yields
        ------
        FranceTravailOffersPage
            Each page, including a first page that may be empty.

        Raises
        ------
        FranceTravailPaginationError
            When ``start``, ``page_size``, or ``max_pages`` are invalid, or
            when ``max_pages`` is reached with no natural end detected.
        FranceTravailApiError
            Propagated from the underlying client without modification.
        FranceTravailNetworkError
            Propagated from the underlying client without modification.
        FranceTravailInvalidResponseError
            Propagated from the underlying client or from Content-Range parsing.
        FranceTravailAuthenticationError
            Propagated from the underlying client without modification.
        """
        # --- Parameter validation (before any client call) -------------------
        _validate_int_param(start, "start", min_value=0)
        _validate_int_param(page_size, "page_size", min_value=1, max_value=150)
        _validate_int_param(max_pages, "max_pages", min_value=1)

        # Use a local copy of search_params to avoid mutating the caller's dict.
        frozen_params: Optional[Mapping[str, Any]] = (
            dict(search_params) if search_params is not None else None
        )

        pages_fetched = 0
        range_start = start

        while pages_fetched < max_pages:
            range_end = range_start + page_size - 1

            logger.debug(
                "Fetching page %d/%d: range %d-%d",
                pages_fetched + 1,
                max_pages,
                range_start,
                range_end,
            )

            page = self._client.search_offers_page(
                search_params=frozen_params,
                range_start=range_start,
                range_end=range_end,
            )
            pages_fetched += 1

            # Always yield the page (even if empty — the first empty page is
            # a valid, useful signal to the consumer).
            yield page

            # ------------------------------------------------------------------
            # Condition A: empty results
            # ------------------------------------------------------------------
            if len(page.results) == 0:
                logger.debug("Stop condition A: empty results page.")
                return

            # ------------------------------------------------------------------
            # Condition B: partial page (fewer results than requested)
            # ------------------------------------------------------------------
            if len(page.results) < page_size:
                logger.debug(
                    "Stop condition B: partial page (%d < %d).",
                    len(page.results),
                    page_size,
                )
                return

            # ------------------------------------------------------------------
            # Condition C: Content-Range total reached
            # ------------------------------------------------------------------
            if page.content_range is not None:
                parsed = _parse_content_range(page.content_range)

                # Validate that the server returned the tranche we requested.
                if parsed.returned_start != range_start:
                    raise FranceTravailInvalidResponseError(
                        f"Content-Range start mismatch: expected {range_start}, "
                        f"got {parsed.returned_start}."
                    )
                if parsed.returned_end != range_end:
                    raise FranceTravailInvalidResponseError(
                        f"Content-Range end mismatch: expected {range_end}, "
                        f"got {parsed.returned_end}."
                    )

                if parsed.total is not None and parsed.returned_end >= parsed.total - 1:
                    logger.debug(
                        "Stop condition C: Content-Range total %d reached at end %d.",
                        parsed.total,
                        parsed.returned_end,
                    )
                    return

            # ------------------------------------------------------------------
            # Advance to the next tranche
            # ------------------------------------------------------------------
            range_start += page_size

        # ------------------------------------------------------------------
        # Condition D: max_pages exhausted without natural stop
        # ------------------------------------------------------------------
        raise FranceTravailPaginationError(
            f"Pagination safety limit reached: {max_pages} page(s) fetched "
            f"without a natural end condition (empty page, partial page, or "
            f"Content-Range total). The collected data may be incomplete."
        )
