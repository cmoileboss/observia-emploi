# -*- coding: utf-8 -*-

"""
Unit tests for scripts/process_france_travail_archive.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.france_travail.exceptions import FranceTravailProcessingError
from services.france_travail.processor import FranceTravailProcessingResult
import scripts.process_france_travail_archive as cli_script


class TestFranceTravailProcessArchiveScript(unittest.TestCase):
    """Test suite for CLI processing script."""

    def test_import_does_not_execute(self):
        self.assertTrue(hasattr(cli_script, "main"))

    def test_help_command(self):
        """Executing with --help returns 0, outputs help and runs cleanly."""
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "process_france_travail_archive.py"
        python_exe = sys.executable

        res = subprocess.run(
            [python_exe, str(script_path), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(res.returncode, 0)
        self.assertIn("Process raw France Travail job offer archives.", res.stdout)
        self.assertEqual(res.stderr, "")

    @patch("scripts.process_france_travail_archive.process_archive")
    def test_cli_success(self, mock_process):
        """Verify stdout content on successful process run."""
        mock_result = FranceTravailProcessingResult(
            source_run_id="20260620T120000Z",
            input_directory=Path("/dummy/input"),
            output_file=Path("/dummy/output/20260620T120000Z/offers_normalized.json"),
            raw_page_count=2,
            raw_offer_count=10,
            normalized_offer_count=8,
            duplicate_offer_count=2,
            normalization_error_count=0,
        )
        mock_process.return_value = mock_result

        with patch("sys.stdout") as mock_stdout:
            exit_code = cli_script.main(["--archive-directory", "/dummy/input", "--output-directory", "/dummy/output"])
            self.assertEqual(exit_code, 0)

            combined_out = "".join(call[0][0] for call in mock_stdout.write.call_args_list)
            self.assertIn("TRAITEMENT FRANCE TRAVAIL REUSSI", combined_out)
            self.assertIn("Run source : 20260620T120000Z", combined_out)
            self.assertIn("Pages brutes : 2", combined_out)
            self.assertIn("Offres brutes : 10", combined_out)
            self.assertIn("Offres normalisees : 8", combined_out)
            self.assertIn("Doublons ignores : 2", combined_out)

    @patch("scripts.process_france_travail_archive.process_archive")
    def test_cli_error(self, mock_process):
        """Verify stderr content and exit code on FranceTravailError."""
        mock_process.side_effect = FranceTravailProcessingError("L'archive est corrompue.")

        with patch("sys.stderr") as mock_stderr:
            exit_code = cli_script.main(["--archive-directory", "/dummy/input", "--output-directory", "/dummy/output"])
            self.assertEqual(exit_code, 1)

            combined_err = "".join(call[0][0] for call in mock_stderr.write.call_args_list)
            self.assertIn("FranceTravailProcessingError", combined_err)
            self.assertIn("L'archive est corrompue.", combined_err)

    @patch("scripts.process_france_travail_archive.process_archive")
    def test_cli_missing_localappdata_error(self, mock_process):
        """LOCALAPPDATA environment variable missing returns 1."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stderr") as mock_stderr:
                exit_code = cli_script.main(["--archive-directory", "/dummy/input"])
                self.assertEqual(exit_code, 1)
                combined_err = "".join(call[0][0] for call in mock_stderr.write.call_args_list)
                self.assertIn("LOCALAPPDATA est absente", combined_err)

    @patch("scripts.process_france_travail_archive.process_archive")
    def test_cli_default_output_root_resolved(self, mock_process):
        """LOCALAPPDATA is resolved to Observia/FranceTravail/processed."""
        mock_result = FranceTravailProcessingResult(
            source_run_id="run-123",
            input_directory=Path("/dummy/input"),
            output_file=Path("/dummy/output"),
            raw_page_count=1,
            raw_offer_count=1,
            normalized_offer_count=1,
            duplicate_offer_count=0,
            normalization_error_count=0,
        )
        mock_process.return_value = mock_result

        with patch.dict("os.environ", {"LOCALAPPDATA": "/mocked/appdata"}):
            with patch("sys.stdout"):
                exit_code = cli_script.main(["--archive-directory", "/dummy/input"])
                self.assertEqual(exit_code, 0)
                # Verify mock_process was called with the default path
                mock_process.assert_called_once_with(
                    archive_directory=Path("/dummy/input"),
                    output_root_directory=Path("/mocked/appdata") / "Observia" / "FranceTravail" / "processed"
                )

    def test_cli_missing_mandatory_arg_raises_system_exit(self):
        """Parser exits with error if mandatory --archive-directory is missing."""
        with self.assertRaises(SystemExit):
            with patch("sys.stderr"):
                cli_script.main([])


if __name__ == "__main__":
    unittest.main()
