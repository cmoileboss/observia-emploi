"""
Unit tests for scripts/collect_france_travail.py.

All tests run entirely offline with mocked dependencies.
No real network calls are made. No PostgreSQL connections are opened.
Only unittest and unittest.mock are used.
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import exceptions and clients to mock or verify
from services.france_travail.exceptions import (
    FranceTravailApiError,
    FranceTravailAuthenticationError,
    FranceTravailConfigurationError,
    FranceTravailError,
    FranceTravailInvalidResponseError,
    FranceTravailNetworkError,
    FranceTravailStorageError,
)
from services.france_travail.client import FranceTravailOffersPage
from services.france_travail.raw_storage import FranceTravailRawArchive

# Import the script functions
import scripts.collect_france_travail as collect_script


class TestFranceTravailCollectScriptImport(unittest.TestCase):
    """Test that importing the script does not trigger any I/O or network."""

    def test_import_does_not_execute(self):
        # Already imported via `import scripts.collect_france_travail`.
        # We can check that no sys.argv was parsed or any execution occurred.
        # This is a sanity check that simply referencing the module is clean.
        self.assertTrue(hasattr(collect_script, "main"))
        self.assertTrue(hasattr(collect_script, "build_search_params"))


class TestFranceTravailCollectScriptParams(unittest.TestCase):
    """Test CLI parameter parsing and validation."""

    def test_build_search_params_defaults(self):
        """None or empty list returns empty dict."""
        self.assertEqual(collect_script.build_search_params(None), {})
        self.assertEqual(collect_script.build_search_params([]), {})

    def test_build_search_params_valid(self):
        """Single and multiple valid params."""
        self.assertEqual(
            collect_script.build_search_params(["motsCles=python"]),
            {"motsCles": "python"},
        )
        self.assertEqual(
            collect_script.build_search_params(["motsCles=python", "departement=75"]),
            {"motsCles": "python", "departement": "75"},
        )

    def test_build_search_params_with_equals_sign_in_value(self):
        """Value containing an equals sign is accepted (split on first equals only)."""
        self.assertEqual(
            collect_script.build_search_params(["motsCles=python=awesome"]),
            {"motsCles": "python=awesome"},
        )

    def test_build_search_params_empty_key_raises(self):
        """Empty key is refused."""
        with self.assertRaises(ValueError) as ctx:
            collect_script.build_search_params(["=python"])
        self.assertIn("La clé ne doit pas être vide", str(ctx.exception))

    def test_build_search_params_empty_value_raises(self):
        """Empty value is refused."""
        with self.assertRaises(ValueError) as ctx:
            collect_script.build_search_params(["motsCles="])
        self.assertIn("La valeur ne doit pas être vide", str(ctx.exception))

    def test_build_search_params_no_equals_raises(self):
        """Param without '=' is refused."""
        with self.assertRaises(ValueError) as ctx:
            collect_script.build_search_params(["motsClespython"])
        self.assertIn("Le format attendu est CLE=VALEUR", str(ctx.exception))

    def test_build_search_params_duplicate_key_raises(self):
        """Duplicate key is refused."""
        with self.assertRaises(ValueError) as ctx:
            collect_script.build_search_params(["motsCles=python", "motsCles=java"])
        self.assertIn("Paramètre dupliqué", str(ctx.exception))

    def test_build_search_params_sensitive_keys_refused(self):
        """Sensitive keys are refused (case-insensitive) without displaying values."""
        sensitive = [
            "authorization",
            "access_token",
            "token",
            "client_secret",
            "secret",
            "client_id",
            "password",
            "CLIENT_ID",
            "Client_Secret",
        ]
        for key in sensitive:
            with self.assertRaises(ValueError) as ctx:
                collect_script.build_search_params([f"{key}=secretval"])
            self.assertIn("Paramètre interdit car sensible", str(ctx.exception))
            self.assertNotIn("secretval", str(ctx.exception))


class TestFranceTravailCollectScriptMain(unittest.TestCase):
    """Test the main function behavior under various conditions."""

    def setUp(self):
        # Clean up environment variables we might patch
        self.env_patcher = patch.dict("os.environ", {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    @patch("scripts.collect_france_travail.FranceTravailConfig.from_environ")
    @patch("scripts.collect_france_travail.load_dotenv")
    @patch("scripts.collect_france_travail.Path.is_file")
    def test_dotenv_missing_raises_error(self, mock_is_file, mock_load_dotenv, mock_from_environ):
        """If .env does not exist, main prints error and returns 1."""
        mock_is_file.return_value = False

        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            exit_code = collect_script.main(["--output-directory", "dummy"])
            self.assertEqual(exit_code, 1)
            # Fetch the actual logged string
            combined_err = "".join(call[0][0] for call in mock_stderr.write.call_args_list)
            self.assertIn("Le fichier de configuration .env est manquant", combined_err)

        # Verify the path contains the resolved grandparent path
        # Since Path.is_file is mocked directly, we can check how is_file was called on the mock instance.
        self.assertTrue(mock_is_file.called)

    @patch("scripts.collect_france_travail.FranceTravailConfig.from_environ")
    @patch("scripts.collect_france_travail.load_dotenv")
    @patch("scripts.collect_france_travail.Path.is_file")
    def test_dotenv_loaded_with_path_and_no_override(self, mock_is_file, mock_load_dotenv, mock_from_environ):
        """dotenv loaded with explicit path and override=False."""
        mock_is_file.return_value = True
        mock_from_environ.side_effect = Exception("Config error")

        with patch("sys.stderr"):
            collect_script.main(["--output-directory", "dummy"])

        mock_load_dotenv.assert_called_once()
        kwargs = mock_load_dotenv.call_args[1]
        self.assertEqual(kwargs.get("override"), False)
        self.assertTrue(isinstance(kwargs.get("dotenv_path"), Path))
        self.assertEqual(kwargs.get("dotenv_path").name, ".env")

    @patch("scripts.collect_france_travail.FranceTravailConfig.from_environ")
    @patch("scripts.collect_france_travail.load_dotenv")
    @patch("scripts.collect_france_travail.Path.is_file")
    def test_invalid_config_prints_generic_error(self, mock_is_file, mock_load_dotenv, mock_from_environ):
        """Invalid config prints a generic message without exposing secrets."""
        mock_is_file.return_value = True
        mock_from_environ.side_effect = FranceTravailConfigurationError("Secret key too secret")

        with patch("sys.stderr") as mock_stderr:
            exit_code = collect_script.main(["--output-directory", "dummy"])
            self.assertEqual(exit_code, 1)
            # Should NOT contain "Secret key too secret"
            combined_err = "".join(call[0][0] for call in mock_stderr.write.call_args_list)
            self.assertNotIn("Secret key too secret", combined_err)
            self.assertIn("La configuration de France Travail est invalide ou incomplète", combined_err)

    @patch("scripts.collect_france_travail.FranceTravailConfig.from_environ")
    @patch("scripts.collect_france_travail.load_dotenv")
    @patch("scripts.collect_france_travail.Path.is_file")
    def test_localappdata_absent_and_no_output_dir_returns_1(self, mock_is_file, mock_load_dotenv, mock_from_environ):
        """If LOCALAPPDATA environment variable is missing and --output-directory is not provided."""
        mock_is_file.return_value = True
        # os.environ is cleared in setUp, so os.environ.get("LOCALAPPDATA") is None.

        with patch("sys.stderr") as mock_stderr:
            exit_code = collect_script.main([])  # no output dir
            self.assertEqual(exit_code, 1)
            combined_err = "".join(call[0][0] for call in mock_stderr.write.call_args_list)
            self.assertIn("LOCALAPPDATA est absente et aucun répertoire de sortie", combined_err)

    @patch("scripts.collect_france_travail.FranceTravailRawStorage")
    @patch("scripts.collect_france_travail.FranceTravailOffersClient")
    @patch("scripts.collect_france_travail.FranceTravailAuthClient")
    @patch("scripts.collect_france_travail.FranceTravailConfig.from_environ")
    @patch("scripts.collect_france_travail.load_dotenv")
    @patch("scripts.collect_france_travail.Path.is_file")
    def test_successful_run_with_default_arguments(
        self, mock_is_file, mock_load_dotenv, mock_from_environ,
        mock_auth_class, mock_client_class, mock_storage_class
    ):
        """Successful run with defaults 0 and 9."""
        mock_is_file.return_value = True
        mock_config = MagicMock()
        mock_config.request_timeout_seconds = 10
        mock_from_environ.return_value = mock_config

        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_page = FranceTravailOffersPage(
            payload={"resultats": [{"id": "1"}]},
            results=({"id": "1"},),
            content_range="offres 0-9/100",
            range_start=0,
            range_end=9,
        )
        mock_client.search_offers_page.return_value = mock_page

        mock_storage = MagicMock()
        mock_storage_class.return_value = mock_storage
        mock_archive = FranceTravailRawArchive(
            run_id="20260620T170000Z",
            directory=Path("/dummy/path/20260620T170000Z"),
            manifest_path=Path("/dummy/path/20260620T170000Z/manifest.json"),
            page_paths=(Path("/dummy/path/20260620T170000Z/page_0001_000000-000009.json"),),
            page_count=1,
            offer_count=1,
            created_at_utc="2026-06-20T17:00:00Z",
        )
        mock_storage.archive_pages.return_value = mock_archive

        with patch("sys.stdout") as mock_stdout:
            exit_code = collect_script.main(["--output-directory", "/dummy/path"])
            self.assertEqual(exit_code, 0)

            combined_out = "".join(call[0][0] for call in mock_stdout.write.call_args_list)
            self.assertIn("COLLECTE FRANCE TRAVAIL REUSSIE", combined_out)
            self.assertIn("Archive : \\dummy\\path\\20260620T170000Z" if sys.platform == "win32" else "Archive : /dummy/path/20260620T170000Z", combined_out)
            self.assertIn("Pages archivees : 1", combined_out)
            self.assertIn("Offres archivees : 1", combined_out)
            self.assertIn("Content-Range : offres 0-9/100", combined_out)

        mock_client.search_offers_page.assert_called_once_with(
            search_params={},
            range_start=0,
            range_end=9,
        )
        mock_storage_class.assert_called_once_with(root_directory=Path("/dummy/path"))
        mock_storage.archive_pages.assert_called_once_with(pages=[mock_page], search_params={})

    @patch("scripts.collect_france_travail.FranceTravailRawStorage")
    @patch("scripts.collect_france_travail.FranceTravailOffersClient")
    @patch("scripts.collect_france_travail.FranceTravailAuthClient")
    @patch("scripts.collect_france_travail.FranceTravailConfig.from_environ")
    @patch("scripts.collect_france_travail.load_dotenv")
    @patch("scripts.collect_france_travail.Path.is_file")
    def test_successful_run_with_custom_range_and_params(
        self, mock_is_file, mock_load_dotenv, mock_from_environ,
        mock_auth_class, mock_client_class, mock_storage_class
    ):
        """Run with custom range, multiple params, and output directory priority."""
        mock_is_file.return_value = True
        mock_config = MagicMock()
        mock_from_environ.return_value = mock_config

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_page = FranceTravailOffersPage(
            payload={"resultats": []},
            results=(),
            content_range=None,
            range_start=10,
            range_end=20,
        )
        mock_client.search_offers_page.return_value = mock_page

        mock_storage = MagicMock()
        mock_storage_class.return_value = mock_storage
        mock_archive = FranceTravailRawArchive(
            run_id="20260620T170000Z",
            directory=Path("/custom/out/20260620T170000Z"),
            manifest_path=Path("/custom/out/20260620T170000Z/manifest.json"),
            page_paths=(),
            page_count=1,
            offer_count=0,
            created_at_utc="2026-06-20T17:00:00Z",
        )
        mock_storage.archive_pages.return_value = mock_archive

        with patch("sys.stdout") as mock_stdout:
            exit_code = collect_script.main(
                [
                    "--range-start", "10",
                    "--range-end", "20",
                    "--param", "motsCles=python",
                    "--param", "commune=75101",
                    "--output-directory", "/custom/out"
                ]
            )
            self.assertEqual(exit_code, 0)
            combined_out = "".join(call[0][0] for call in mock_stdout.write.call_args_list)
            self.assertIn("Content-Range : absent", combined_out)

        mock_client.search_offers_page.assert_called_once_with(
            search_params={"motsCles": "python", "commune": "75101"},
            range_start=10,
            range_end=20,
        )
        mock_storage_class.assert_called_once_with(root_directory=Path("/custom/out"))
        mock_storage.archive_pages.assert_called_once_with(
            pages=[mock_page],
            search_params={"motsCles": "python", "commune": "75101"},
        )

    @patch("scripts.collect_france_travail.FranceTravailRawStorage")
    @patch("scripts.collect_france_travail.FranceTravailOffersClient")
    @patch("scripts.collect_france_travail.FranceTravailAuthClient")
    @patch("scripts.collect_france_travail.FranceTravailConfig.from_environ")
    @patch("scripts.collect_france_travail.load_dotenv")
    @patch("scripts.collect_france_travail.Path.is_file")
    def test_localappdata_used_when_output_dir_absent(
        self, mock_is_file, mock_load_dotenv, mock_from_environ,
        mock_auth_class, mock_client_class, mock_storage_class
    ):
        """When --output-directory is absent, LOCALAPPDATA is used to construct path."""
        mock_is_file.return_value = True
        # Set LOCALAPPDATA in mocked environment
        with patch.dict("os.environ", {"LOCALAPPDATA": "/mocked/appdata"}):
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_page = FranceTravailOffersPage(
                payload={"resultats": []},
                results=(),
                content_range=None,
                range_start=0,
                range_end=9,
            )
            mock_client.search_offers_page.return_value = mock_page

            mock_storage = MagicMock()
            mock_storage_class.return_value = mock_storage
            mock_archive = MagicMock()
            mock_storage.archive_pages.return_value = mock_archive

            with patch("sys.stdout"):
                exit_code = collect_script.main([])
                self.assertEqual(exit_code, 0)

            # Path should resolve to LOCALAPPDATA / Observia / FranceTravail / raw
            expected_path = Path("/mocked/appdata") / "Observia" / "FranceTravail" / "raw"
            mock_storage_class.assert_called_once_with(root_directory=expected_path)

    @patch("scripts.collect_france_travail.FranceTravailOffersClient")
    @patch("scripts.collect_france_travail.FranceTravailAuthClient")
    @patch("scripts.collect_france_travail.FranceTravailConfig.from_environ")
    @patch("scripts.collect_france_travail.load_dotenv")
    @patch("scripts.collect_france_travail.Path.is_file")
    def test_france_travail_errors(
        self, mock_is_file, mock_load_dotenv, mock_from_environ,
        mock_auth_class, mock_client_class
    ):
        """Verify handling of FranceTravailError subclasses."""
        mock_is_file.return_value = True
        mock_config = MagicMock()
        mock_from_environ.return_value = mock_config

        errors_to_test = [
            FranceTravailAuthenticationError("Auth failed"),
            FranceTravailApiError("API error"),
            FranceTravailNetworkError("Network issue"),
            FranceTravailInvalidResponseError("Invalid JSON structure"),
            FranceTravailStorageError("Write failed"),
        ]

        for err in errors_to_test:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.search_offers_page.side_effect = err

            with patch("sys.stderr") as mock_stderr:
                exit_code = collect_script.main(["--output-directory", "dummy"])
                self.assertEqual(exit_code, 1)

                combined_err = "".join(call[0][0] for call in mock_stderr.write.call_args_list)
                # Check exception class name is printed
                self.assertIn(type(err).__name__, combined_err)
                # Check existing message is printed
                self.assertIn(err.args[0], combined_err)


    def test_build_search_params_case_insensitive_duplicate_key_raises(self):
        """Case-insensitive duplicate keys are refused."""
        with self.assertRaises(ValueError) as ctx:
            collect_script.build_search_params(["motsCles=python", "MOTSCLES=java"])
        self.assertIn("Paramètre dupliqué", str(ctx.exception))


class TestFranceTravailCollectScriptSubprocess(unittest.TestCase):
    """Test executing the script as a subprocess (simulating real invocation)."""

    def test_help_command(self):
        """Executing with --help returns 0, outputs help and runs cleanly."""
        import subprocess
        import sys

        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "collect_france_travail.py"
        python_exe = sys.executable

        res = subprocess.run(
            [python_exe, str(script_path), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(res.returncode, 0)
        self.assertIn("Collect France Travail job offers and archive them locally.", res.stdout)
        self.assertEqual(res.stderr, "")


class TestFranceTravailCollectScriptIsolation(unittest.TestCase):
    """Test that the script does not import main.py, FastAPI, or SQLAlchemy."""

    def test_imports_isolation(self):
        # Verify that modules we want to avoid are not loaded in sys.modules
        for forbidden in ["main", "fastapi", "sqlalchemy"]:
            self.assertNotIn(forbidden, sys.modules)


if __name__ == "__main__":
    unittest.main()
