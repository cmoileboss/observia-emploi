"""
Configuration for the France Travail API service.

Values are loaded from environment variables (or an explicit mapping for
testing). No automatic loading from a ``.env`` file is performed here: the
caller is responsible for loading environment variables before constructing a
``FranceTravailConfig`` instance.

Expected environment variables
-------------------------------
FRANCE_TRAVAIL_CLIENT_ID
    OAuth application identifier (required).
FRANCE_TRAVAIL_CLIENT_SECRET
    OAuth application secret (required). Never logged or displayed.
FRANCE_TRAVAIL_TOKEN_URL
    Full URL of the token endpoint (required).
FRANCE_TRAVAIL_SCOPE
    Space-separated list of OAuth scopes (required).
FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS
    HTTP request timeout in seconds (optional, default 10).
"""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Mapping

from services.france_travail.exceptions import FranceTravailConfigurationError

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FranceTravailConfig:
    """Immutable configuration for the France Travail API service.

    Instances are frozen to prevent accidental mutation at runtime. The
    ``client_secret`` is deliberately excluded from ``__repr__`` so that it
    cannot appear in logs or tracebacks.

    Parameters
    ----------
    client_id:
        OAuth application identifier.
    client_secret:
        OAuth application secret. Never included in ``repr`` output.
    token_url:
        Full URL of the OAuth token endpoint.
    scope:
        Space-separated OAuth scope string.
    offers_search_url:
        Full URL of the job search endpoint.
    request_timeout_seconds:
        Timeout applied to every HTTP request, in seconds.
    """

    client_id: str
    client_secret: str = field(repr=False)
    token_url: str
    scope: str
    offers_search_url: str
    request_timeout_seconds: int

    def __repr__(self) -> str:  # noqa: D105
        return (
            f"FranceTravailConfig("
            f"client_id={self.client_id!r}, "
            f"client_secret=<hidden>, "
            f"token_url={self.token_url!r}, "
            f"scope={self.scope!r}, "
            f"offers_search_url={self.offers_search_url!r}, "
            f"request_timeout_seconds={self.request_timeout_seconds!r}"
            f")"
        )

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> "FranceTravailConfig":
        """Build a config from an arbitrary key-value mapping.

        Useful in tests to avoid touching ``os.environ``.

        Parameters
        ----------
        mapping:
            Any ``Mapping`` whose keys match the expected environment-variable
            names (e.g. a plain ``dict``).

        Returns
        -------
        FranceTravailConfig
            A validated, immutable configuration instance.

        Raises
        ------
        FranceTravailConfigurationError
            If a required value is missing or invalid.
        """
        return _build_config(mapping)

    @classmethod
    def from_environ(cls) -> "FranceTravailConfig":
        """Build a config from ``os.environ``.

        Returns
        -------
        FranceTravailConfig
            A validated, immutable configuration instance.

        Raises
        ------
        FranceTravailConfigurationError
            If a required environment variable is missing or invalid.
        """
        return _build_config(os.environ)



# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_config(mapping: Mapping[str, str]) -> FranceTravailConfig:
    """Validate and construct a ``FranceTravailConfig`` from *mapping*.

    Raises
    ------
    FranceTravailConfigurationError
        With an explicit, secret-free message when validation fails.
    """
    client_id = _require(mapping, "FRANCE_TRAVAIL_CLIENT_ID")
    client_secret = _require(mapping, "FRANCE_TRAVAIL_CLIENT_SECRET")
    token_url = _require(mapping, "FRANCE_TRAVAIL_TOKEN_URL")
    scope = _require(mapping, "FRANCE_TRAVAIL_SCOPE")
    offers_search_url = _require(mapping, "FRANCE_TRAVAIL_OFFERS_SEARCH_URL")

    _validate_url(token_url, "FRANCE_TRAVAIL_TOKEN_URL")
    _validate_url(offers_search_url, "FRANCE_TRAVAIL_OFFERS_SEARCH_URL")

    if "FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS" in mapping:
        raw_timeout = mapping["FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS"]
        request_timeout_seconds = _parse_positive_int(
            raw_timeout, "FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS"
        )
    else:
        request_timeout_seconds = _DEFAULT_TIMEOUT_SECONDS

    return FranceTravailConfig(
        client_id=client_id,
        client_secret=client_secret,
        token_url=token_url,
        scope=scope,
        offers_search_url=offers_search_url,
        request_timeout_seconds=request_timeout_seconds,
    )


def _require(
    mapping: Mapping[str, str],
    key: str,
) -> str:
    """Return the value for *key* or raise ``FranceTravailConfigurationError``.

    If the key is absent, empty, or composed only of spaces, raise.

    Raises
    ------
    FranceTravailConfigurationError
    """
    # We do a safe get. If it's not a string (or absent), we treat it as empty.
    raw = mapping.get(key)
    if not isinstance(raw, str):
        raise FranceTravailConfigurationError(
            f"Missing required configuration variable: {key}. "
            f"Please set it in your environment or .env file."
        )
    value = raw.strip()
    if not value:
        raise FranceTravailConfigurationError(
            f"Missing required configuration variable: {key}. "
            f"Please set it in your environment or .env file."
        )
    return value


def _validate_url(url: str, var_name: str) -> None:
    """Validate *url* to ensure it's a valid HTTPS URL with a hostname.

    Raises
    ------
    FranceTravailConfigurationError
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise FranceTravailConfigurationError(
            f"Invalid URL for {var_name}: {exc}"
        ) from exc

    if not parsed.scheme:
        raise FranceTravailConfigurationError(
            f"Invalid URL for {var_name}: Scheme is missing."
        )
    if parsed.scheme.lower() != "https":
        raise FranceTravailConfigurationError(
            f"Invalid URL for {var_name}: Only HTTPS is supported, got {parsed.scheme!r}."
        )
    if not parsed.netloc:
        raise FranceTravailConfigurationError(
            f"Invalid URL for {var_name}: Hostname is missing."
        )


def _parse_positive_int(raw: any, variable_name: str) -> int:
    """Parse *raw* as a strictly positive integer.

    Raises
    ------
    FranceTravailConfigurationError
    """
    # Explicitly reject boolean type since isinstance(True, int) is True in Python.
    if isinstance(raw, bool):
        raise FranceTravailConfigurationError(
            f"Invalid value for {variable_name}: {raw!r} is not an integer."
        )

    # We support integer type directly or strings representing integers.
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # Reject float numbers even if they are passed as raw values.
        if isinstance(raw, float):
            raise FranceTravailConfigurationError(
                f"Invalid value for {variable_name}: {raw!r} is not an integer."
            )
        value = raw
    elif isinstance(raw, str):
        try:
            # Reject float representations like "10.5" or non-integers by parsing strictly.
            value = int(raw)
        except ValueError:
            raise FranceTravailConfigurationError(
                f"Invalid value for {variable_name}: {raw!r} is not an integer."
            )
    else:
        raise FranceTravailConfigurationError(
            f"Invalid value for {variable_name}: {raw!r} is not an integer."
        )

    if value <= 0:
        raise FranceTravailConfigurationError(
            f"Invalid value for {variable_name}: must be a strictly positive "
            f"integer, got {value}."
        )
    return value
