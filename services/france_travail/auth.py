"""
OAuth 2.0 Client Credentials client for the France Travail API.

Responsibilities
----------------
- Request a Bearer token from the configured token URL.
- Cache the token in memory for its lifetime.
- Renew the token transparently before it expires (with a safety margin).
- Expose a single method ``get_access_token()`` that callers use.

Design constraints
------------------
- No network call is made at import time or at construction time.
- ``client_secret`` and ``access_token`` are never written to logs.
- All HTTP errors and network failures are converted to typed business
  exceptions defined in ``exceptions.py``.
- The ``requests.Session`` is injected at construction time so that tests can
  provide a mock without monkey-patching globals.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from services.france_travail.config import FranceTravailConfig
from services.france_travail.exceptions import (
    FranceTravailAuthenticationError,
    FranceTravailNetworkError,
    FranceTravailInvalidResponseError,
)

logger = logging.getLogger(__name__)


class FranceTravailAuthClient:
    """OAuth 2.0 Client Credentials client for France Travail.

    Parameters
    ----------
    config:
        Validated ``FranceTravailConfig`` instance providing credentials and
        endpoint URL.
    session:
        An optional ``requests.Session`` to use for HTTP calls. When not
        provided, a new session is created in the constructor. Inject a mock
        session in tests to avoid real network calls.

    Examples
    --------
    Production usage (credentials read from environment):

    >>> from services.france_travail.config import FranceTravailConfig
    >>> from services.france_travail.auth import FranceTravailAuthClient
    >>> config = FranceTravailConfig.from_environ()
    >>> client = FranceTravailAuthClient(config)
    >>> token = client.get_access_token()  # triggers an HTTP call on first use

    Test usage (credentials and session injected):

    >>> client = FranceTravailAuthClient(config=mock_config, session=mock_session)
    """

    def __init__(
        self,
        config: FranceTravailConfig,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._config = config
        self._session: requests.Session = session if session is not None else requests.Session()

        # Cached token state — None until the first successful token request.
        self._access_token: Optional[str] = None
        self._refresh_at: float = 0.0  # monotonic clock value

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_access_token(self) -> str:
        """Return a valid Bearer token, fetching or renewing it as needed.

        The token is cached in memory. A new token is requested when:
        - no token has been fetched yet, or
        - the cached token is past its refresh_at threshold.

        Returns
        -------
        str
            A valid OAuth 2.0 access token string.

        Raises
        ------
        FranceTravailAuthenticationError
            When the token endpoint returns an HTTP error or the response body
            does not contain a valid token.
        FranceTravailNetworkError
            When a network-level failure prevents reaching the token endpoint.
        FranceTravailInvalidResponseError
            When the response structure or type is invalid.
        """
        if self._is_token_valid():
            logger.debug("Reusing cached France Travail access token.")
            return self._access_token  # type: ignore[return-value]

        logger.info("Requesting a new France Travail access token.")
        self._fetch_token()
        return self._access_token  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_token_valid(self) -> bool:
        """Return True if the cached token is still valid with safety margin."""
        if self._access_token is None:
            return False
        return time.monotonic() < self._refresh_at

    def _fetch_token(self) -> None:
        """Request a new access token and update the internal cache.

        Raises
        ------
        FranceTravailAuthenticationError
        FranceTravailNetworkError
        FranceTravailInvalidResponseError
        """
        payload = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "scope": self._config.scope,
        }

        try:
            response = self._session.post(
                self._config.token_url,
                data=payload,
                timeout=self._config.request_timeout_seconds,
            )
        except requests.exceptions.Timeout as exc:
            raise FranceTravailNetworkError(
                "Timeout while requesting a France Travail OAuth token."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise FranceTravailNetworkError(
                "Connection error while requesting a France Travail OAuth token."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise FranceTravailNetworkError(
                f"Unexpected network error while requesting a France Travail OAuth token: {type(exc).__name__}."
            ) from exc

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            status_code = response.status_code
            # Do NOT include response body — it may contain credentials.
            raise FranceTravailAuthenticationError(
                f"France Travail token endpoint returned HTTP {status_code}."
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise FranceTravailInvalidResponseError(
                "France Travail token endpoint returned a non-JSON response."
            ) from exc

        if not isinstance(body, dict):
            raise FranceTravailInvalidResponseError(
                "France Travail token response is not a JSON object."
            )

        access_token = body.get("access_token")
        if access_token is None:
            raise FranceTravailInvalidResponseError(
                "France Travail token response does not contain 'access_token'."
            )

        if not isinstance(access_token, str):
            raise FranceTravailInvalidResponseError(
                f"France Travail token response contains an invalid 'access_token' type: {type(access_token).__name__}."
            )

        if not access_token.strip():
            raise FranceTravailInvalidResponseError(
                "France Travail token response contains an empty 'access_token'."
            )

        if "expires_in" not in body:
            raise FranceTravailInvalidResponseError(
                "France Travail token response does not contain 'expires_in'."
            )

        expires_in = body.get("expires_in")

        # Explicitly reject boolean type since isinstance(True, int) is True in Python.
        if isinstance(expires_in, bool):
            raise FranceTravailInvalidResponseError(
                f"France Travail token response contains an invalid 'expires_in' type: {type(expires_in).__name__}."
            )

        if not isinstance(expires_in, (int, float)):
            raise FranceTravailInvalidResponseError(
                f"France Travail token response contains an invalid 'expires_in' type: {type(expires_in).__name__}."
            )

        if expires_in <= 0:
            raise FranceTravailInvalidResponseError(
                f"France Travail token response contains an invalid 'expires_in' value: {expires_in!r}."
            )

        # Update cache — never log the token value itself.
        self._access_token = access_token

        safety_margin = min(30.0, float(expires_in) / 10.0)

        self._refresh_at = time.monotonic() + float(expires_in) - safety_margin

        logger.info(
            "France Travail access token obtained successfully "
            "(expires in %s seconds).",
            expires_in,
        )
