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
