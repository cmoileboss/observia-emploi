"""
Unit tests for services.france_travail.config.

All tests run entirely offline without network calls, database connections,
or imports of main.py. Only the standard library (unittest) is used.
"""

import os
import unittest
from unittest.mock import patch

from services.france_travail.config import FranceTravailConfig
from services.france_travail.exceptions import FranceTravailConfigurationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_mapping(**overrides: str) -> dict:
    """Return a minimal valid environment mapping, with optional overrides."""
    base = {
        "FRANCE_TRAVAIL_CLIENT_ID": "test_client_id",
        "FRANCE_TRAVAIL_CLIENT_SECRET": "test_client_secret",
        "FRANCE_TRAVAIL_TOKEN_URL": "https://example.com/oauth/token",
        "FRANCE_TRAVAIL_SCOPE": "api_offresdemploiv2 o2dsoffre",
        "FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS": "10",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestFranceTravailConfigValid(unittest.TestCase):
    """Tests covering valid configuration inputs."""

    def test_config_created_with_all_values(self):
        """A mapping with all required keys produces a valid config object."""
        cfg = FranceTravailConfig.from_mapping(_valid_mapping())

        self.assertEqual(cfg.client_id, "test_client_id")
        self.assertEqual(cfg.token_url, "https://example.com/oauth/token")
        self.assertEqual(cfg.scope, "api_offresdemploiv2 o2dsoffre")
        self.assertEqual(cfg.request_timeout_seconds, 10)

    def test_config_uses_default_timeout_when_absent(self):
        """When FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS is absent, 10 is used."""
        mapping = _valid_mapping()
        del mapping["FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS"]
        cfg = FranceTravailConfig.from_mapping(mapping)
        self.assertEqual(cfg.request_timeout_seconds, 10)

    def test_config_is_frozen(self):
        """The config object must be immutable (frozen dataclass)."""
        cfg = FranceTravailConfig.from_mapping(_valid_mapping())
        with self.assertRaises((AttributeError, TypeError)):
            cfg.client_id = "changed"  # type: ignore[misc]

    def test_from_environ_with_os_environ_simulated(self):
        """from_environ factory successfully parses variables from os.environ."""
        env_vars = _valid_mapping()
        with patch.dict(os.environ, env_vars, clear=True):
            cfg = FranceTravailConfig.from_environ()
            self.assertEqual(cfg.client_id, "test_client_id")
            self.assertEqual(cfg.token_url, "https://example.com/oauth/token")


class TestFranceTravailConfigMissingRequired(unittest.TestCase):
    """Tests covering missing required configuration variables."""

    def test_missing_client_id_raises(self):
        """Absent FRANCE_TRAVAIL_CLIENT_ID raises FranceTravailConfigurationError."""
        mapping = _valid_mapping()
        del mapping["FRANCE_TRAVAIL_CLIENT_ID"]
        with self.assertRaises(FranceTravailConfigurationError) as ctx:
            FranceTravailConfig.from_mapping(mapping)
        self.assertIn("FRANCE_TRAVAIL_CLIENT_ID", str(ctx.exception))

    def test_empty_client_id_raises(self):
        """Empty FRANCE_TRAVAIL_CLIENT_ID raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_CLIENT_ID=""))

    def test_spaces_client_id_raises(self):
        """Spaces-only FRANCE_TRAVAIL_CLIENT_ID raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_CLIENT_ID="   "))

    def test_missing_client_secret_raises(self):
        """Absent FRANCE_TRAVAIL_CLIENT_SECRET raises FranceTravailConfigurationError."""
        mapping = _valid_mapping()
        del mapping["FRANCE_TRAVAIL_CLIENT_SECRET"]
        with self.assertRaises(FranceTravailConfigurationError) as ctx:
            FranceTravailConfig.from_mapping(mapping)
        self.assertIn("FRANCE_TRAVAIL_CLIENT_SECRET", str(ctx.exception))

    def test_empty_client_secret_raises(self):
        """Empty FRANCE_TRAVAIL_CLIENT_SECRET raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_CLIENT_SECRET=""))

    def test_missing_token_url_raises(self):
        """Absent FRANCE_TRAVAIL_TOKEN_URL raises FranceTravailConfigurationError."""
        mapping = _valid_mapping()
        del mapping["FRANCE_TRAVAIL_TOKEN_URL"]
        with self.assertRaises(FranceTravailConfigurationError) as ctx:
            FranceTravailConfig.from_mapping(mapping)
        self.assertIn("FRANCE_TRAVAIL_TOKEN_URL", str(ctx.exception))

    def test_empty_token_url_raises(self):
        """Empty FRANCE_TRAVAIL_TOKEN_URL raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_TOKEN_URL=""))

    def test_spaces_token_url_raises(self):
        """Spaces-only FRANCE_TRAVAIL_TOKEN_URL raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_TOKEN_URL="    "))

    def test_missing_scope_raises(self):
        """Absent FRANCE_TRAVAIL_SCOPE raises FranceTravailConfigurationError."""
        mapping = _valid_mapping()
        del mapping["FRANCE_TRAVAIL_SCOPE"]
        with self.assertRaises(FranceTravailConfigurationError) as ctx:
            FranceTravailConfig.from_mapping(mapping)
        self.assertIn("FRANCE_TRAVAIL_SCOPE", str(ctx.exception))

    def test_empty_scope_raises(self):
        """Empty FRANCE_TRAVAIL_SCOPE raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_SCOPE=""))

    def test_spaces_scope_raises(self):
        """Spaces-only FRANCE_TRAVAIL_SCOPE raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_SCOPE="    "))


class TestFranceTravailConfigUrlValidation(unittest.TestCase):
    """Tests covering URL syntax validation for token_url."""

    def test_token_url_without_scheme_raises(self):
        """A URL without a scheme (e.g. 'example.com') raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError) as ctx:
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_TOKEN_URL="example.com/oauth/token"))
        self.assertIn("Scheme is missing", str(ctx.exception))

    def test_token_url_http_instead_of_https_raises(self):
        """A URL with HTTP scheme instead of HTTPS raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError) as ctx:
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_TOKEN_URL="http://example.com/oauth/token"))
        self.assertIn("Only HTTPS is supported", str(ctx.exception))

    def test_token_url_without_hostname_raises(self):
        """A URL without a hostname (e.g. 'https:///oauth/token') raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError) as ctx:
            FranceTravailConfig.from_mapping(_valid_mapping(FRANCE_TRAVAIL_TOKEN_URL="https:///oauth/token"))
        self.assertIn("Hostname is missing", str(ctx.exception))


class TestFranceTravailConfigTimeout(unittest.TestCase):
    """Tests covering timeout validation."""

    def test_timeout_zero_raises(self):
        """Timeout of 0 raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError) as ctx:
            FranceTravailConfig.from_mapping(
                _valid_mapping(FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS="0")
            )
        self.assertIn("FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS", str(ctx.exception))

    def test_timeout_negative_raises(self):
        """Negative timeout raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(
                _valid_mapping(FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS="-5")
            )

    def test_timeout_non_integer_raises(self):
        """Non-integer timeout string raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(
                _valid_mapping(FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS="abc")
            )

    def test_timeout_float_string_raises(self):
        """Float string timeout raises FranceTravailConfigurationError."""
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(
                _valid_mapping(FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS="10.5")
            )

    def test_timeout_bool_true_raises(self):
        """Boolean timeout value (e.g. True) raises FranceTravailConfigurationError."""
        # Note: True evaluates as 1 in basic int checks, but must be explicitly rejected.
        mapping = _valid_mapping()
        # Pass a boolean value to mapping
        mapping["FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS"] = True  # type: ignore
        with self.assertRaises(FranceTravailConfigurationError):
            FranceTravailConfig.from_mapping(mapping)

    def test_timeout_valid_positive(self):
        """A valid positive integer timeout is accepted."""
        cfg = FranceTravailConfig.from_mapping(
            _valid_mapping(FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS="30")
        )
        self.assertEqual(cfg.request_timeout_seconds, 30)


class TestFranceTravailConfigRepr(unittest.TestCase):
    """Tests ensuring the secret never appears in the string representation."""

    def test_repr_does_not_contain_secret(self):
        """repr() must not reveal the client_secret value."""
        cfg = FranceTravailConfig.from_mapping(_valid_mapping())
        representation = repr(cfg)
        self.assertNotIn("test_client_secret", representation)

    def test_repr_contains_hidden_marker(self):
        """repr() must contain a marker indicating the secret is hidden."""
        cfg = FranceTravailConfig.from_mapping(_valid_mapping())
        self.assertIn("<hidden>", repr(cfg))

    def test_str_does_not_contain_secret(self):
        """str() must not reveal the client_secret value."""
        cfg = FranceTravailConfig.from_mapping(_valid_mapping())
        self.assertNotIn("test_client_secret", str(cfg))


if __name__ == "__main__":
    unittest.main()
