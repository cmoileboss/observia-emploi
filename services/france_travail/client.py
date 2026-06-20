"""
HTTP client for fetching job offers from the France Travail API.

This client handles request construction, Bearer token injection, parameter
validation, range slice management, response parsing, and error mapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Tuple

import requests

from services.france_travail.config import FranceTravailConfig
from services.france_travail.exceptions import (
    FranceTravailApiError,
    FranceTravailInvalidResponseError,
    FranceTravailNetworkError,
)

logger = logging.getLogger(__name__)


class FranceTravailAuthClientProtocol(Protocol):
    """Protocol defining the interface for the OAuth client."""

    def get_access_token(self) -> str:
        """Obtain a valid Bearer token."""
        ...


@dataclass(frozen=True)
class FranceTravailOffersPage:
    """Immutable representation of a single page of France Travail offers.

    Parameters
    ----------
    payload:
        The raw response payload dictionary.
    results:
        A tuple of raw offer dictionaries parsed from payload["resultats"].
    content_range:
        The value of the 'Content-Range' HTTP response header (if present).
    range_start:
        The start index of the requested tranche.
    range_end:
        The end index of the requested tranche.
    """

    payload: dict[str, Any]
    results: Tuple[dict[str, Any], ...]
    content_range: Optional[str]
    range_start: int
    range_end: int


class FranceTravailOffersClient:
    """HTTP client to search job offers using the France Travail API.

    Parameters
    ----------
    config:
        Validated ``FranceTravailConfig`` instance providing endpoints.
    auth_client:
        OAuth client providing ``get_access_token()``.
    session:
        An optional ``requests.Session``. If not provided, a new session is
        created.
    """

    def __init__(
        self,
        config: FranceTravailConfig,
        auth_client: FranceTravailAuthClientProtocol,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._config = config
        self._auth_client = auth_client
        self._session = session if session is not None else requests.Session()

    def search_offers_page(
        self,
        search_params: Optional[Mapping[str, Any]] = None,
        range_start: int = 0,
        range_end: int = 149,
    ) -> FranceTravailOffersPage:
        """Fetch a single page of job offers matching the given parameters and range.

        Parameters
        ----------
        search_params:
            Optional dictionary of search criteria to pass as query parameters.
        range_start:
            The start offset (0-based) of the results tranche.
        range_end:
            The end offset (0-based, inclusive) of the results tranche.

        Returns
        -------
        FranceTravailOffersPage
            The parsed and validated offers page.

        Raises
        ------
        FranceTravailApiError
            When the API endpoint returns an HTTP error.
        FranceTravailNetworkError
            When a network failure or timeout occurs.
        FranceTravailInvalidResponseError
            When the JSON payload structure is invalid or cannot be parsed.
        """
        # Validate ranges
        self._validate_range(range_start, "range_start")
        self._validate_range(range_end, "range_end")

        if range_end < range_start:
            raise FranceTravailInvalidResponseError(
                f"Invalid tranche: range_end ({range_end}) must be greater than or equal to range_start ({range_start})."
            )

        slice_size = range_end - range_start + 1
        if slice_size > 150:
            raise FranceTravailInvalidResponseError(
                f"Invalid tranche size: requested slice has {slice_size} elements (max 150)."
            )

        # Get OAuth token
        token = self._auth_client.get_access_token()
        if not isinstance(token, str) or not token.strip():
            raise FranceTravailInvalidResponseError(
                "Invalid access token returned from auth client: must be a non-empty string."
            )

        # Copy search params to avoid mutating caller's dict, then add range slice.
        # The range parameter is sent as a query parameter, not as an HTTP header.
        params = dict(search_params) if search_params is not None else {}
        params["range"] = f"{range_start}-{range_end}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            response = self._session.get(
                self._config.offers_search_url,
                params=params,
                headers=headers,
                timeout=self._config.request_timeout_seconds,
            )
        except requests.exceptions.Timeout as exc:
            raise FranceTravailNetworkError(
                "Timeout while fetching France Travail job offers."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise FranceTravailNetworkError(
                "Connection error while fetching France Travail job offers."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise FranceTravailNetworkError(
                f"Unexpected network error while fetching France Travail job offers: {type(exc).__name__}."
            ) from exc

        # Process HTTP errors (400, 401, 403, 404, 429, 500, 502, 503, etc.)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            status_code = response.status_code
            raise FranceTravailApiError(
                f"France Travail API returned HTTP {status_code}."
            ) from exc

        # Handle HTTP 204 or empty responses that mean no content
        if response.status_code == 204 or not response.text.strip():
            # Treat empty payload as valid with empty results
            payload: dict[str, Any] = {"resultats": []}
        else:
            try:
                payload = response.json()
            except ValueError as exc:
                raise FranceTravailInvalidResponseError(
                    "France Travail API returned a non-JSON response."
                ) from exc

        # Validate JSON structure
        if not isinstance(payload, dict):
            raise FranceTravailInvalidResponseError(
                "France Travail API response is not a JSON object."
            )

        if "resultats" not in payload:
            raise FranceTravailInvalidResponseError(
                "France Travail API response is missing the 'resultats' key."
            )

        results_list = payload.get("resultats")
        if not isinstance(results_list, list):
            raise FranceTravailInvalidResponseError(
                "France Travail API response 'resultats' key must be a list."
            )

        for i, item in enumerate(results_list):
            if not isinstance(item, dict):
                raise FranceTravailInvalidResponseError(
                    f"France Travail API offer at index {i} is not a JSON object."
                )

        results_tuple = tuple(results_list)
        content_range = response.headers.get("Content-Range")

        return FranceTravailOffersPage(
            payload=payload,
            results=results_tuple,
            content_range=content_range,
            range_start=range_start,
            range_end=range_end,
        )

    def _validate_range(self, val: Any, name: str) -> None:
        """Validate range boundaries to reject invalid types or values."""
        if isinstance(val, bool):
            raise FranceTravailInvalidResponseError(
                f"Invalid type for {name}: booleans are not allowed."
            )
        if not isinstance(val, int):
            raise FranceTravailInvalidResponseError(
                f"Invalid type for {name}: must be an integer."
            )
        if val < 0:
            raise FranceTravailInvalidResponseError(
                f"Invalid value for {name}: must be positive or zero."
            )
