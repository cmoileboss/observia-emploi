# -*- coding: utf-8 -*-

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestFranceTravailImportScript(unittest.TestCase):

    def setUp(self):
        global import_script_main
        from scripts.import_france_travail import main as import_script_main

        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # Mock JSON data
        self.valid_data = {
            "source": "france_travail",
            "source_run_id": "RUN-TEST-CLI",
            "raw_offer_count": 1,
            "normalized_offer_count": 1,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": [
                {"source_offer_id": "FT-CLI-1", "title": "Dev CLI"}
            ]
        }
        self.input_file = self.dir_path / "offers_normalized.json"
        self.input_file.write_text(json.dumps(self.valid_data), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    @classmethod
    def tearDownClass(cls):
        import sys
        to_remove = [
            mod for mod in list(sys.modules.keys())
            if mod.startswith("sqlalchemy") or "postgres_connection" in mod or "models" in mod or "repositories" in mod
        ]
        for mod in to_remove:
            sys.modules.pop(mod, None)

    def test_cli_help(self):
        # run help in subprocess to test completely offline/no side-effects
        script_path = Path(__file__).resolve().parents[2] / "scripts" / "import_france_travail.py"
        res = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            capture_output=True,
            text=True,
            check=False
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("--input-file", res.stdout)
        self.assertIn("--dry-run", res.stdout)
        self.assertIn("--apply", res.stdout)
        # Ensure postgres_connection was NOT imported by checking stdout/stderr or just verifying subprocess success
        self.assertEqual(res.stderr, "")

    def test_cli_input_file_mandatory(self):
        script_path = Path(__file__).resolve().parents[2] / "scripts" / "import_france_travail.py"
        res = subprocess.run(
            [sys.executable, str(script_path), "--dry-run"],
            capture_output=True,
            text=True,
            check=False
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("required", res.stderr)

    def test_cli_mutually_exclusive_required(self):
        script_path = Path(__file__).resolve().parents[2] / "scripts" / "import_france_travail.py"
        # 1. Neither dry-run nor apply
        res1 = subprocess.run(
            [sys.executable, str(script_path), "--input-file", str(self.input_file)],
            capture_output=True,
            text=True,
            check=False
        )
        self.assertNotEqual(res1.returncode, 0)
        self.assertIn("one of the arguments", res1.stderr)

        # 2. Both dry-run and apply
        res2 = subprocess.run(
            [sys.executable, str(script_path), "--input-file", str(self.input_file), "--dry-run", "--apply"],
            capture_output=True,
            text=True,
            check=False
        )
        self.assertNotEqual(res2.returncode, 0)
        self.assertIn("not allowed with", res2.stderr)

    def test_cli_dry_run_output(self):
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            with patch("sys.argv", ["import_france_travail.py", "--input-file", str(self.input_file), "--dry-run"]):
                code = import_script_main()

        self.assertEqual(code, 0)
        output = stdout_capture.getvalue()
        self.assertIn("VALIDATION IMPORT FRANCE TRAVAIL REUSSIE", output)
        self.assertIn("Run source : RUN-TEST-CLI", output)
        self.assertIn("Base de donnees contactee : non", output)

    @patch("postgres_connection.SessionLocal")
    def test_cli_apply_success(self, mock_session_local):
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            # Patch persists_prepared_import to return a mock result
            from services.france_travail.importer import FranceTravailImportResult
            res = FranceTravailImportResult(
                source_run_id="RUN-TEST-CLI",
                input_file=self.input_file,
                input_offer_count=1,
                inserted_offer_count=1,
                existing_offer_count=0,
                attached_competency_count=0,
                attached_training_count=0,
                skipped_competency_without_code_count=0,
                skipped_training_without_code_count=0,
                duplicate_competency_code_count=0,
                duplicate_training_code_count=0,
                committed=True,
                dry_run=False,
            )
            with patch("scripts.import_france_travail.persist_prepared_import", return_value=res):
                with patch("sys.argv", ["import_france_travail.py", "--input-file", str(self.input_file), "--apply"]):
                    code = import_script_main()

        self.assertEqual(code, 0)
        output = stdout_capture.getvalue()
        self.assertIn("IMPORT FRANCE TRAVAIL REUSSI", output)
        self.assertIn("Transaction validee : oui", output)
        mock_session.close.assert_called_once()

    @patch("postgres_connection.SessionLocal")
    def test_cli_apply_error(self, mock_session_local):
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        from services.france_travail.exceptions import FranceTravailImportError
        with patch("scripts.import_france_travail.persist_prepared_import", side_effect=FranceTravailImportError("Faux echec")):
            stderr_capture = io.StringIO()
            with patch("sys.stderr", stderr_capture):
                with patch("sys.argv", ["import_france_travail.py", "--input-file", str(self.input_file), "--apply"]):
                    code = import_script_main()

        self.assertEqual(code, 1)
        self.assertIn("Faux echec", stderr_capture.getvalue())
        mock_session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
