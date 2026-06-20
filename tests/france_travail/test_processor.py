# -*- coding: utf-8 -*-

"""
Unit tests for services.france_travail.processor.
All tests run offline using synthetic temporary directories.
No network calls, no PostgreSQL/SQLite connections.
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


class TestFranceTravailProcessor(unittest.TestCase):
    """Test suite for raw archive processor."""

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

    def _write_page(self, filename: str, data: dict):
        page_path = self.input_dir / filename
        page_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_nominal_processing_single_page(self):
        """Nominal run with a single page manifest."""
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 1,
            "offer_count": 2,
            "pages": [
                {
                    "index": 1,
                    "file": "page_0001.json",
                    "result_count": 2,
                }
            ]
        })
        self._write_page("page_0001.json", {
            "resultats": [
                {"id": "1", "intitule": "Job 1"},
                {"id": "2", "intitule": "Job 2"},
            ]
        })

        res = process_archive(self.input_dir, self.output_dir)

        self.assertEqual(res.source_run_id, "20260620T120000Z")
        self.assertEqual(res.raw_page_count, 1)
        self.assertEqual(res.raw_offer_count, 2)
        self.assertEqual(res.normalized_offer_count, 2)
        self.assertEqual(res.duplicate_offer_count, 0)

        # Verify output file
        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        self.assertTrue(expected_file.is_file())

        processed_data = json.loads(expected_file.read_text(encoding="utf-8"))
        self.assertEqual(processed_data["source"], "france_travail")
        self.assertEqual(processed_data["source_run_id"], "20260620T120000Z")
        self.assertEqual(len(processed_data["offers"]), 2)
        self.assertEqual(processed_data["offers"][0]["source_offer_id"], "1")

    def test_nominal_processing_multiple_pages_deterministic_order(self):
        """Deterministic processing order based on manifest indices."""
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 2,
            "offer_count": 3,
            "pages": [
                {
                    "index": 2,
                    "file": "page_0002.json",
                    "result_count": 2,
                },
                {
                    "index": 1,
                    "file": "page_0001.json",
                    "result_count": 1,
                }
            ]
        })
        self._write_page("page_0001.json", {
            "resultats": [
                {"id": "1", "intitule": "Job 1"},
            ]
        })
        self._write_page("page_0002.json", {
            "resultats": [
                {"id": "2", "intitule": "Job 2"},
                {"id": "3", "intitule": "Job 3"},
            ]
        })


        res = process_archive(self.input_dir, self.output_dir)

        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        processed_data = json.loads(expected_file.read_text(encoding="utf-8"))

        # Check order is index 1 first, then index 2
        offers = processed_data["offers"]
        self.assertEqual(offers[0]["source_offer_id"], "1")
        self.assertEqual(offers[1]["source_offer_id"], "2")
        self.assertEqual(offers[2]["source_offer_id"], "3")

    def test_missing_input_directory_raises(self):
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir / "non-existent", self.output_dir)
        self.assertIn("Le répertoire d'archive n'existe pas", str(ctx.exception))

    def test_manifest_missing_raises(self):
        # input_dir has no manifest.json
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Le fichier manifest.json est manquant", str(ctx.exception))

    def test_manifest_invalid_json_raises(self):
        manifest_path = self.input_dir / "manifest.json"
        manifest_path.write_text("invalid json", encoding="utf-8")
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("manifest.json n'est pas un JSON valide", str(ctx.exception))

    def test_manifest_invalid_source_raises(self):
        self._write_manifest({
            "source": "wrong_source",
            "run_id": "20260620T120000Z",
            "page_count": 0,
            "offer_count": 0,
            "pages": []
        })
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("La source déclarée dans le manifeste est invalide", str(ctx.exception))

    def test_manifest_incoherent_page_count_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 2,
            "offer_count": 0,
            "pages": []  # List has size 0, expected 2
        })
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Le nombre de pages déclarées", str(ctx.exception))

    def test_manifest_incoherent_offer_count_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 1,
            "offer_count": 10,  # Expected 10, page only has 2
            "pages": [{"index": 1, "file": "page_0001.json", "result_count": 10}]
        })
        self._write_page("page_0001.json", {"resultats": [{"id": "1"}, {"id": "2"}]})
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Le nombre total d'offres lues", str(ctx.exception))


    def test_page_file_missing_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 1,
            "offer_count": 1,
            "pages": [{"index": 1, "file": "missing.json", "result_count": 1}]
        })
        # missing.json is not written
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Fichier de page manquant", str(ctx.exception))

    def test_directory_traversal_refused(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 1,
            "offer_count": 1,
            "pages": [{"index": 1, "file": "../outside_page.json", "result_count": 1}]
        })
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("sort du répertoire d'archive", str(ctx.exception))

    def test_deduplication(self):
        """Duplicate offers are counted and only first occurrence preserved."""
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 2,
            "offer_count": 4,
            "pages": [
                {"index": 1, "file": "page_0001.json", "result_count": 2},
                {"index": 2, "file": "page_0002.json", "result_count": 2},
            ]
        })
        # page_0001 has id 1 and id 2
        self._write_page("page_0001.json", {
            "resultats": [
                {"id": "1", "intitule": "Job 1"},
                {"id": "2", "intitule": "Job 2"},
            ]
        })
        # page_0002 has id 2 (duplicate) and id 3
        self._write_page("page_0002.json", {
            "resultats": [
                {"id": "2", "intitule": "Job 2 duplicate"},
                {"id": "3", "intitule": "Job 3"},
            ]
        })

        res = process_archive(self.input_dir, self.output_dir)
        self.assertEqual(res.raw_offer_count, 4)
        self.assertEqual(res.normalized_offer_count, 3)
        self.assertEqual(res.duplicate_offer_count, 1)

        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        processed_data = json.loads(expected_file.read_text(encoding="utf-8"))
        offers = processed_data["offers"]
        self.assertEqual(len(offers), 3)
        # Check first occurrence of 2 is preserved (Job 2, not Job 2 duplicate)
        self.assertEqual(offers[1]["title"], "Job 2")

    def test_normalization_error_rolls_back_atomic_write(self):
        """A normalization error fails processing and leaves no partial output files."""
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 1,
            "offer_count": 1,
            "pages": [{"index": 1, "file": "page_0001.json", "result_count": 1}]
        })
        # id is empty (normalization error)
        self._write_page("page_0001.json", {"resultats": [{"id": ""}]})

        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("erreur de normalisation s'est produite", str(ctx.exception))

        # Check no final directory or normalized file is present
        final_dir = self.output_dir / "20260620T120000Z"
        self.assertFalse(final_dir.exists())

    def test_data_protection_sentinels_absent_from_output(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 1,
            "offer_count": 1,
            "pages": [{"index": 1, "file": "page_0001.json", "result_count": 1}]
        })

        self._write_page("page_0001.json", {
            "resultats": [
                {
                    "id": "1",
                    "contact": {"nom": "SECRET_CONTACT_NAME"},
                    "agence": {"courriel": "SECRET_AGENCY_EMAIL"},
                    "entreprise": {"nom": "Corp", "description": "SECRET_COMPANY_DESC"},
                    "lieuTravail": {"libelle": "Paris", "latitude": 99.999},
                }
            ]
        })

        process_archive(self.input_dir, self.output_dir)

        expected_file = self.output_dir / "20260620T120000Z" / "offers_normalized.json"
        content = expected_file.read_text(encoding="utf-8")

        sentinels = [
            "SECRET_CONTACT_NAME",
            "SECRET_AGENCY_EMAIL",
            "SECRET_COMPANY_DESC",
            "99.999",
        ]
        for s in sentinels:
            self.assertNotIn(s, content)

    def test_isolation(self):
        for forbidden in ["pydantic", "fastapi", "sqlalchemy", "main"]:
            self.assertNotIn(forbidden, sys.modules)

    def test_manifest_page_count_bool_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": True,  # bool should be refused
            "offer_count": 0,
            "pages": []
        })
        with self.assertRaises(FranceTravailProcessingError):
            process_archive(self.input_dir, self.output_dir)

    def test_manifest_offer_count_bool_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 0,
            "offer_count": True,  # bool should be refused
            "pages": []
        })
        with self.assertRaises(FranceTravailProcessingError):
            process_archive(self.input_dir, self.output_dir)

    def test_manifest_duplicate_page_index_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 2,
            "offer_count": 2,
            "pages": [
                {"index": 1, "file": "p1.json", "result_count": 1},
                {"index": 1, "file": "p2.json", "result_count": 1},  # duplicate index
            ]
        })
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Index de page dupliqué", str(ctx.exception))

    def test_manifest_duplicate_filename_raises(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 2,
            "offer_count": 2,
            "pages": [
                {"index": 1, "file": "p1.json", "result_count": 1},
                {"index": 2, "file": "p1.json", "result_count": 1},  # duplicate file
            ]
        })
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Fichier de page dupliqué", str(ctx.exception))

    def test_non_dict_offer_raises_processing_error(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 1,
            "offer_count": 1,
            "pages": [{"index": 1, "file": "page_0001.json", "result_count": 1}]
        })
        # Offer is a string instead of dict
        self._write_page("page_0001.json", {"resultats": ["not-a-dict-offer"]})

        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("n'est pas un dictionnaire", str(ctx.exception))

    def test_page_cannot_be_manifest_json_itself(self):
        self._write_manifest({
            "source": "france_travail_offres_emploi",
            "run_id": "20260620T120000Z",
            "page_count": 1,
            "offer_count": 1,
            "pages": [{"index": 1, "file": "manifest.json", "result_count": 1}]
        })
        with self.assertRaises(FranceTravailProcessingError) as ctx:
            process_archive(self.input_dir, self.output_dir)
        self.assertIn("Une page ne peut pas être manifest.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
