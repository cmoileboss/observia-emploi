# -*- coding: utf-8 -*-

"""
Unit tests for offline processing of France Travail multi-ROME archives.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from services.france_travail.exceptions import FranceTravailProcessingError
from services.france_travail.processor import process_archive
import scripts.process_france_travail_archive as cli_script


class TestFranceTravailProcessorMultiRome(unittest.TestCase):
    """Test suite for multi-ROME archive processor."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.input_dir = Path(self.temp_dir.name) / "raw_archive"
        self.input_dir.mkdir()

        self.output_dir = Path(self.temp_dir.name) / "processed"
        self.output_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_manifest(self, data: dict):
        manifest_path = self.input_dir / "manifest.json"
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _write_rome_page(self, rome_code: str, filename: str, data: dict):
        rome_dir = self.input_dir / "rome" / rome_code
        rome_dir.mkdir(parents=True, exist_ok=True)
        page_path = rome_dir / filename
        page_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_nominal_multi_rome_one_code_one_page(self):
        """Test nominal multi-ROME processing with one code and one page."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 1,
            "total_offer_count": 2,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 2,
                    "success": True
                }
            ]
        })
        self._write_rome_page("M1805", "page_0001.json", {
            "resultats": [
                {"id": "1", "intitule": "Dev Senior"},
                {"id": "2", "intitule": "Dev Junior"},
            ]
        })

        res = process_archive(self.input_dir, self.output_dir)

        self.assertEqual(res.source_run_id, "20260620T120000Z")
        self.assertEqual(res.raw_page_count, 1)
        self.assertEqual(res.raw_offer_count, 2)
        self.assertEqual(res.normalized_offer_count, 2)
        self.assertEqual(res.duplicate_offer_count, 0)

        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        self.assertTrue(expected_file.is_file())
        processed_data = json.loads(expected_file.read_text(encoding="utf-8"))
        self.assertEqual(processed_data["source"], "france_travail")
        self.assertEqual(processed_data["source_run_id"], "20260620T120000Z")
        self.assertEqual(len(processed_data["offers"]), 2)

    def test_nominal_multi_rome_two_codes_one_page_each(self):
        """Test nominal multi-ROME processing with two codes and one page each."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 2,
            "total_offer_count": 3,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 2,
                    "success": True
                },
                {
                    "rome_code": "A1401",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        self._write_rome_page("M1805", "page_0001.json", {
            "resultats": [
                {"id": "1", "intitule": "Job 1"},
                {"id": "2", "intitule": "Job 2"},
            ]
        })
        self._write_rome_page("A1401", "page_0001.json", {
            "resultats": [
                {"id": "3", "intitule": "Job 3"},
            ]
        })

        res = process_archive(self.input_dir, self.output_dir)
        self.assertEqual(res.raw_page_count, 2)
        self.assertEqual(res.raw_offer_count, 3)
        self.assertEqual(res.normalized_offer_count, 3)

        # Check order of codes is preserved
        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        processed_data = json.loads(expected_file.read_text(encoding="utf-8"))
        offers = processed_data["offers"]
        self.assertEqual(offers[0]["source_offer_id"], "1")
        self.assertEqual(offers[1]["source_offer_id"], "2")
        self.assertEqual(offers[2]["source_offer_id"], "3")

    def test_nominal_multi_rome_two_codes_multiple_pages(self):
        """Test multiple pages per code, ordered alphabetically by filename."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 3,
            "total_offer_count": 4,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 2,
                    "offer_count": 3,
                    "success": True
                },
                {
                    "rome_code": "A1401",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        # M1805 pages: order should be page_0001.json then page_0002.json
        self._write_rome_page("M1805", "page_0002.json", {
            "resultats": [
                {"id": "2", "intitule": "Job 2"},
            ]
        })
        self._write_rome_page("M1805", "page_0001.json", {
            "resultats": [
                {"id": "1", "intitule": "Job 1"},
                {"id": "3", "intitule": "Job 3"},
            ]
        })
        self._write_rome_page("A1401", "page_0001.json", {
            "resultats": [
                {"id": "4", "intitule": "Job 4"},
            ]
        })

        res = process_archive(self.input_dir, self.output_dir)
        self.assertEqual(res.raw_page_count, 3)
        self.assertEqual(res.raw_offer_count, 4)

        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        processed_data = json.loads(expected_file.read_text(encoding="utf-8"))
        offers = processed_data["offers"]
        self.assertEqual(offers[0]["source_offer_id"], "1")
        self.assertEqual(offers[1]["source_offer_id"], "3")
        self.assertEqual(offers[2]["source_offer_id"], "2")
        self.assertEqual(offers[3]["source_offer_id"], "4")

    def test_multi_rome_empty_page(self):
        """Test page with empty resultats list."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 1,
            "total_offer_count": 0,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 0,
                    "success": True
                }
            ]
        })
        self._write_rome_page("M1805", "page_0001.json", {"resultats": []})

        res = process_archive(self.input_dir, self.output_dir)
        self.assertEqual(res.raw_offer_count, 0)
        self.assertEqual(res.normalized_offer_count, 0)

    def test_multi_rome_deduplication_between_codes(self):
        """An offer present in two different codes must be deduplicated globally, first kept, duplicate counted."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 2,
            "total_offer_count": 3,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 2,
                    "success": True
                },
                {
                    "rome_code": "A1401",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        # Offer 2 is in both M1805 and A1401
        self._write_rome_page("M1805", "page_0001.json", {
            "resultats": [
                {"id": "1", "intitule": "Job 1"},
                {"id": "2", "intitule": "Job 2 (M1805)"},
            ]
        })
        self._write_rome_page("A1401", "page_0001.json", {
            "resultats": [
                {"id": "2", "intitule": "Job 2 (A1401)"},
            ]
        })

        res = process_archive(self.input_dir, self.output_dir)
        self.assertEqual(res.raw_offer_count, 3)
        self.assertEqual(res.normalized_offer_count, 2)
        self.assertEqual(res.duplicate_offer_count, 1)

        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        processed_data = json.loads(expected_file.read_text(encoding="utf-8"))
        offers = processed_data["offers"]
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0]["source_offer_id"], "1")
        self.assertEqual(offers[1]["source_offer_id"], "2")
        # Kept the first one encountered (Job 2 (M1805))
        self.assertEqual(offers[1]["title"], "Job 2 (M1805)")

    def test_multi_rome_incomplete_refused(self):
        """If complete is False or missing, processing is refused."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": False,
            "total_page_count": 1,
            "total_offer_count": 1,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        self._write_rome_page("M1805", "page_0001.json", {"resultats": [{"id": "1"}]})

        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("incomplète ou en échec", str(ctx.exception))

    def test_multi_rome_missing_page_file_raises(self):
        """If page count is 1 but file is missing, raises."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 1,
            "total_offer_count": 1,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        # Create empty directory M1805 but no files
        (self.input_dir / "rome" / "M1805").mkdir(parents=True, exist_ok=True)

        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("ne correspond pas à page_count", str(ctx.exception))

    def test_multi_rome_invalid_json_page_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 1,
            "total_offer_count": 1,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        # Write invalid JSON
        rome_dir = self.input_dir / "rome" / "M1805"
        rome_dir.mkdir(parents=True, exist_ok=True)
        (rome_dir / "page_0001.json").write_text("invalid-json", encoding="utf-8")

        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("n'est pas un JSON valide", str(ctx.exception))

    def test_multi_rome_invalid_page_structure_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 1,
            "total_offer_count": 1,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        self._write_rome_page("M1805", "page_0001.json", {"resultats": "not-a-list"})

        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("doit être une liste", str(ctx.exception))

    def test_multi_rome_directory_traversal_path_injection_refused(self):
        """ROME codes with path traversal like '..' are rejected by format validation."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 1,
            "total_offer_count": 1,
            "codes": [
                {
                    "rome_code": "../M18",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Format de code ROME invalide", str(ctx.exception))

    def test_multi_rome_duplicate_rome_code_in_manifest_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 0,
            "total_offer_count": 0,
            "codes": [
                {"rome_code": "M1805", "page_count": 0, "offer_count": 0, "success": True},
                {"rome_code": "M1805", "page_count": 0, "offer_count": 0, "success": True},
            ]
        })
        (self.input_dir / "rome" / "M1805").mkdir(parents=True, exist_ok=True)
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Code ROME dupliqué dans le manifeste", str(ctx.exception))

    def test_cli_script_run_directory_multi_rome(self):
        """CLI script supports --run-directory for a multi-ROME archive."""
        self._write_manifest({
            "source": "france_travail_offres_emploi_rome",
            "run_id": "20260620T120000Z",
            "complete": True,
            "total_page_count": 1,
            "total_offer_count": 1,
            "codes": [
                {
                    "rome_code": "M1805",
                    "page_count": 1,
                    "offer_count": 1,
                    "success": True
                }
            ]
        })
        self._write_rome_page("M1805", "page_0001.json", {"resultats": [{"id": "1", "intitule": "Job 1"}]})

        exit_code = cli_script.main([
            "--run-directory", str(self.input_dir),
            "--output-directory", str(self.output_dir)
        ])
        self.assertEqual(exit_code, 0)

        # Check output is created correctly
        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        self.assertTrue(expected_file.is_file())


if __name__ == "__main__":
    unittest.main()
