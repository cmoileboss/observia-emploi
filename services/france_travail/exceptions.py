"""
Business exceptions for the France Travail pipeline.

Each exception corresponds to a distinct failure mode so that callers can
handle errors selectively without inspecting raw HTTP status codes or generic
exception messages.
"""


class FranceTravailError(Exception):
    """Base exception class for all France Travail pipeline errors.

    Callers can catch this exception to intercept any business or configuration
    failure originating from this module.
    """


class FranceTravailConfigurationError(FranceTravailError):
    """Raised when the France Travail configuration is missing or invalid.

    This exception is raised before any network call is made, when a required
    configuration value (e.g. CLIENT_ID, CLIENT_SECRET) is absent or incorrect.
    """


class FranceTravailAuthenticationError(FranceTravailError):
    """Raised when the OAuth token request fails.

    This covers HTTP errors returned by the token endpoint (e.g. 400, 401) as
    well as malformed responses that do not contain a valid access token.
    """


class FranceTravailNetworkError(FranceTravailError):
    """Raised when a network-level failure occurs during an API call.

    Examples: connection refused, DNS resolution failure, read timeout.
    The original requests exception is available as ``__cause__``.
    """


class FranceTravailInvalidResponseError(FranceTravailError):
    """Raised when the API returns an unexpected or unparseable response body.

    This is distinct from HTTP errors: the HTTP status may be 200 but the
    response JSON does not match the expected schema.
    """


class FranceTravailApiError(FranceTravailError):
    """Raised when the France Travail API endpoint returns an HTTP error or functional error."""


class FranceTravailPaginationError(FranceTravailError):
    """Raised when the pagination mechanism encounters an unrecoverable state.

    This exception is distinct from API or network errors.  It is raised when
    the paginator's own safety constraints are violated — for example, when
    ``max_pages`` pages have been consumed without any natural end condition
    (empty page, partial page, or Content-Range total reached) being detected.

    Callers that catch this exception should treat the collected data as
    potentially incomplete and decide explicitly whether to use it or discard it.
    """


class FranceTravailStorageError(FranceTravailError):
    """Raised when the local raw-archive storage mechanism fails.

    This covers the following situations:

    * The root directory or the run directory cannot be created.
    * A page payload cannot be serialised to JSON.
    * A page file or the manifest cannot be written to disk.
    * The temporary directory cannot be renamed to its final name.
    * The iterable of pages is empty (nothing to archive).
    * A ``search_params`` mapping contains a sensitive key that must not be
      persisted (e.g. ``access_token``, ``client_secret``).
    * The ``now_provider`` returns a naive (timezone-unaware) datetime.
    * A page has an invalid or missing ``range_start`` / ``range_end``.

    The temporary work directory is always cleaned up before this exception
    propagates, so no partial archive is left on disk.
    """
