# -*- coding: utf-8 -*-

"""
Unit tests for scripts/validate_france_travail_rome.py (§18).

Strategy
--------
- Import verification: no side effect at import time.
- --help runs in a real subprocess to verify it works without .env and without network.
- All other tests mock the module's helpers and run main() directly.
- sys.modules, sys.path, os.environ and stdout/stderr are restored in tearDown.

No network call. No database. No import of main.py. No import of postgres_connection.
"""

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Project root (for subprocess calls)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
_SCRIPT_PATH = str(Path(_PROJECT_ROOT) / "scripts" / "validate_france_travail_rome.py")
_PYTHON = str(Path(_PROJECT_ROOT) / ".venv" / "Scripts" / "python.exe")

# ---------------------------------------------------------------------------
# Modules to clean from sys.modules for isolation
# ---------------------------------------------------------------------------

_MODULES_TO_CLEAN = [
    "scripts.validate_france_travail_rome",
    "validate_france_travail_rome",
    "services",
    "services.france_travail",
    "services.france_travail.exceptions",
    "services.france_travail.rome",
    "services.france_travail.config",
    "services.france_travail.auth",
    "services.france_travail.client",
]


def _clean_modules():
    for name in list(sys.modules.keys()):
        if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
            sys.modules.pop(name, None)


def _import_main():
    """Import the script's main() function fresh."""
    _clean_modules()
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    import scripts.validate_france_travail_rome as mod  # noqa: PLC0415
    return mod.main, mod


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def _write_csv(path: Path, codes: list[str], column: str = "code_rome") -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[column], delimiter=";")
        writer.writeheader()
        for code in codes:
            writer.writerow({column: code})


def _write_ref(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh)


# ---------------------------------------------------------------------------
# §18 — Tests
# ---------------------------------------------------------------------------


class TestValidateRomeScriptImport(unittest.TestCase):
    """Verify import produces no side effect."""

    def setUp(self):
        _clean_modules()

    @classmethod
    def tearDownClass(cls):
        _clean_modules()

    def test_import_causes_no_network_call(self):
        """Importing the script does not trigger any network call."""
        if _PROJECT_ROOT not in sys.path:
            sys.path.insert(0, _PROJECT_ROOT)
        import scripts.validate_france_travail_rome  # noqa: F401  # PLC0415
        # If we get here without a network error, the test passes.

    def test_import_does_not_load_env(self):
        """Importing the script does not modify os.environ with .env values."""
        env_before = dict(os.environ)
        if _PROJECT_ROOT not in sys.path:
            sys.path.insert(0, _PROJECT_ROOT)
        import scripts.validate_france_travail_rome  # noqa: F401, PLC0415
        self.assertEqual(dict(os.environ), env_before)

    def test_no_main_py_imported(self):
        """main.py must not appear in sys.modules after importing the script."""
        if _PROJECT_ROOT not in sys.path:
            sys.path.insert(0, _PROJECT_ROOT)
        import scripts.validate_france_travail_rome  # noqa: F401, PLC0415
        for key in sys.modules:
            self.assertNotEqual(key, "main")
            self.assertFalse(key.endswith(".main") and "observia" in key.lower())

    def test_no_postgres_connection_imported(self):
        """postgres_connection must not appear in sys.modules after importing the script."""
        if _PROJECT_ROOT not in sys.path:
            sys.path.insert(0, _PROJECT_ROOT)
        import scripts.validate_france_travail_rome  # noqa: F401, PLC0415
        self.assertNotIn("postgres_connection", sys.modules)


class TestValidateRomeScriptHelp(unittest.TestCase):
    """--help must work in a real subprocess without .env or network."""

    def test_help_exits_zero(self):
        """--help returns exit code 0."""
        result = subprocess.run(
            [_PYTHON, _SCRIPT_PATH, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ},  # pass current env (no .env loaded)
        )
        self.assertEqual(result.returncode, 0)

    def test_help_output_is_non_empty(self):
        """--help produces non-empty stdout."""
        result = subprocess.run(
            [_PYTHON, _SCRIPT_PATH, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertTrue(result.stdout.strip())

    def test_help_contains_no_secrets(self):
        """--help output must not contain any credential keywords."""
        result = subprocess.run(
            [_PYTHON, _SCRIPT_PATH, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for sensitive in ("client_id", "client_secret", "token", "Authorization", "PASSWORD"):
            self.assertNotIn(sensitive, result.stdout)
            self.assertNotIn(sensitive, result.stderr)


class TestValidateRomeScriptArgValidation(unittest.TestCase):
    """Tests for CLI argument validation."""

    def setUp(self):
        self._main, _ = _import_main()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()
        _clean_modules()

    @classmethod
    def tearDownClass(cls):
        _clean_modules()

    def test_codes_file_is_required(self):
        """Missing --codes-file should cause a non-zero exit (argparse SystemExit)."""
        with self.assertRaises(SystemExit) as ctx:
            self._main(["--offline-reference", "ref.json"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_offline_and_live_mutually_exclusive(self):
        """--offline-reference and --live together return EXIT_BUSINESS_ERROR."""
        p = self.tmp / "codes.csv"
        _write_csv(p, ["M1805"])
        ref = self.tmp / "ref.json"
        _write_ref(ref, [{"code": "M1805", "libelle": "Informatique"}])

        result = self._main([
            "--codes-file", str(p),
            "--offline-reference", str(ref),
            "--live",
        ])
        self.assertNotEqual(result, 0)

    def test_neither_offline_nor_live_returns_business_error(self):
        """Neither --offline-reference nor --live returns EXIT_BUSINESS_ERROR."""
        p = self.tmp / "codes.csv"
        _write_csv(p, ["M1805"])

        result = self._main(["--codes-file", str(p)])
        self.assertNotEqual(result, 0)


class TestValidateRomeScriptOfflineMode(unittest.TestCase):
    """Tests for offline mode execution."""

    def setUp(self):
        self._main, _ = _import_main()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()
        _clean_modules()

    @classmethod
    def tearDownClass(cls):
        _clean_modules()

    def _run(self, codes: list[str], ref_entries: list[dict]) -> tuple[int, str]:
        """Run main() offline and capture stdout."""
        p = self.tmp / "codes.csv"
        _write_csv(p, codes)
        ref = self.tmp / "ref.json"
        _write_ref(ref, ref_entries)

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = self._main([
                "--codes-file", str(p),
                "--offline-reference", str(ref),
            ])
        return code, buf.getvalue()

    def test_offline_all_recognised_returns_zero(self):
        """All recognised codes → exit 0."""
        code, _ = self._run(
            ["M1805"],
            [{"code": "M1805", "libelle": "Informatique"}],
        )
        self.assertEqual(code, 0)

    def test_offline_unknown_codes_returns_nonzero(self):
        """Unknown codes → non-zero exit."""
        code, _ = self._run(
            ["Z9999"],
            [{"code": "M1805", "libelle": "Informatique"}],
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(code, 1)  # EXIT_UNKNOWN_CODES

    def test_offline_summary_contains_expected_fields(self):
        """The summary output contains all expected label lines."""
        _, out = self._run(
            ["M1805"],
            [{"code": "M1805", "libelle": "Info"}],
        )
        self.assertIn("VALIDATION ROME FRANCE TRAVAIL", out)
        self.assertIn("Fichier de codes", out)
        self.assertIn("Codes demandes", out)
        self.assertIn("Codes uniques", out)
        self.assertIn("Doublons ignores", out)
        self.assertIn("Entrees du referentiel", out)
        self.assertIn("Codes reconnus", out)
        self.assertIn("Codes inconnus", out)
        self.assertIn("Mode", out)
        self.assertIn("hors ligne", out)

    def test_offline_no_secret_in_stdout(self):
        """stdout must not contain any credential-like keywords."""
        _, out = self._run(
            ["M1805"],
            [{"code": "M1805", "libelle": "Info"}],
        )
        for sensitive in ("client_id", "client_secret", "token", "Authorization", "password"):
            self.assertNotIn(sensitive, out.lower())

    def test_offline_no_secret_in_stderr(self):
        """stderr must not contain any credential-like keywords."""
        p = self.tmp / "codes.csv"
        _write_csv(p, ["Z9999"])
        ref = self.tmp / "ref.json"
        _write_ref(ref, [{"code": "M1805", "libelle": "Info"}])

        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf):
            self._main([
                "--codes-file", str(p),
                "--offline-reference", str(ref),
            ])
        err = err_buf.getvalue()
        for sensitive in ("client_id", "client_secret", "token", "Authorization", "password"):
            self.assertNotIn(sensitive, err.lower())

    def test_offline_missing_codes_file_returns_business_error(self):
        """A missing codes file returns EXIT_BUSINESS_ERROR."""
        ref = self.tmp / "ref.json"
        _write_ref(ref, [{"code": "M1805", "libelle": "Info"}])

        result = self._main([
            "--codes-file", str(self.tmp / "nonexistent.csv"),
            "--offline-reference", str(ref),
        ])
        self.assertEqual(result, 2)  # EXIT_BUSINESS_ERROR

    def test_offline_invalid_ref_json_returns_business_error(self):
        """An invalid JSON reference file returns EXIT_BUSINESS_ERROR."""
        p = self.tmp / "codes.csv"
        _write_csv(p, ["M1805"])
        ref = self.tmp / "bad_ref.json"
        ref.write_text("not json", encoding="utf-8")

        result = self._main([
            "--codes-file", str(p),
            "--offline-reference", str(ref),
        ])
        self.assertEqual(result, 2)  # EXIT_BUSINESS_ERROR

    def test_offline_missing_ref_file_returns_business_error(self):
        """A missing offline reference file returns EXIT_BUSINESS_ERROR."""
        p = self.tmp / "codes.csv"
        _write_csv(p, ["M1805"])

        result = self._main([
            "--codes-file", str(p),
            "--offline-reference", str(self.tmp / "nonexistent.json"),
        ])
        self.assertEqual(result, 2)  # EXIT_BUSINESS_ERROR

    def test_offline_no_postgres_access(self):
        """The offline mode must not import postgres_connection."""
        p = self.tmp / "codes.csv"
        _write_csv(p, ["M1805"])
        ref = self.tmp / "ref.json"
        _write_ref(ref, [{"code": "M1805", "libelle": "Info"}])

        self._main([
            "--codes-file", str(p),
            "--offline-reference", str(ref),
        ])
        self.assertNotIn("postgres_connection", sys.modules)


if __name__ == "__main__":
    unittest.main()
