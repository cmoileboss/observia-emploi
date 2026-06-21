# -*- coding: utf-8 -*-

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


class TestFranceTravailImporter(unittest.TestCase):

    def setUp(self):
        global prepare_import, persist_prepared_import
        global FranceTravailImportError, FranceTravailMappingError
        global CompetenceModel, FormationModel, FranceTravailModel
        global FranceTravailRepository

        from services.france_travail.importer import prepare_import, persist_prepared_import
        from services.france_travail.exceptions import FranceTravailImportError, FranceTravailMappingError
        from models.francetravail_model import CompetenceModel, FormationModel, FranceTravailModel
        from repositories.francetravail_repository import FranceTravailRepository

        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

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

    def _write_json(self, filename: str, data: Any) -> Path:
        file_path = self.dir_path / filename
        file_path.write_text(json.dumps(data), encoding="utf-8")
        return file_path

    def test_prepare_import_valid(self):
        data = {
            "source": "france_travail",
            "source_run_id": "RUN-2026",
            "raw_offer_count": 2,
            "normalized_offer_count": 2,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": [
                {"source_offer_id": "FT-1", "title": "Dev Python"},
                {"source_offer_id": "FT-2", "title": "Dev JS"}
            ]
        }
        f = self._write_json("offers.json", data)
        prepared = prepare_import(f)
        self.assertEqual(prepared.source_run_id, "RUN-2026")
        self.assertEqual(prepared.input_offer_count, 2)
        self.assertEqual(prepared.mapped_offer_count, 2)

    def test_prepare_import_file_absent(self):
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(self.dir_path / "does_not_exist.json")
        self.assertIn("introuvable", str(ctx.exception))

    def test_prepare_import_not_a_file(self):
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(self.dir_path)
        self.assertIn("pas un fichier régulier", str(ctx.exception))

    def test_prepare_import_invalid_json(self):
        f = self.dir_path / "invalid.json"
        f.write_text("{invalid json", encoding="utf-8")
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertIn("JSON valide", str(ctx.exception))

    def test_prepare_import_root_not_dict(self):
        f = self._write_json("list.json", [1, 2, 3])
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertIn("dictionnaire", str(ctx.exception))

    def test_prepare_import_invalid_source(self):
        data = {
            "source": "invalid_source",
            "source_run_id": "RUN-1",
            "raw_offer_count": 0,
            "normalized_offer_count": 0,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": []
        }
        f = self._write_json("offers.json", data)
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertIn("source", str(ctx.exception))

    def test_prepare_import_run_id_invalid(self):
        invalid_run_ids = [None, 1234, "   ", ""]
        for rid in invalid_run_ids:
            data = {
                "source": "france_travail",
                "source_run_id": rid,
                "raw_offer_count": 0,
                "normalized_offer_count": 0,
                "duplicate_offer_count": 0,
                "normalization_error_count": 0,
                "offers": []
            }
            f = self._write_json("offers.json", data)
            with self.assertRaises(FranceTravailImportError) as ctx:
                prepare_import(f)
            self.assertIn("run_id", str(ctx.exception))

    def test_prepare_import_offers_bad_type(self):
        data = {
            "source": "france_travail",
            "source_run_id": "RUN-1",
            "raw_offer_count": 0,
            "normalized_offer_count": 0,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": "not-a-list"
        }
        f = self._write_json("offers.json", data)
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertIn("offers", str(ctx.exception))

    def test_prepare_import_offer_not_mapping(self):
        data = {
            "source": "france_travail",
            "source_run_id": "RUN-1",
            "raw_offer_count": 1,
            "normalized_offer_count": 1,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": ["not-a-mapping"]
        }
        f = self._write_json("offers.json", data)
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertIn("n'est pas un dictionnaire", str(ctx.exception))

    def test_prepare_import_duplicate_offer_id(self):
        data = {
            "source": "france_travail",
            "source_run_id": "RUN-1",
            "raw_offer_count": 2,
            "normalized_offer_count": 2,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": [
                {"source_offer_id": "DUP-1"},
                {"source_offer_id": " DUP-1 "}
            ]
        }
        f = self._write_json("offers.json", data)
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertIn("dupliqué", str(ctx.exception))

    def test_prepare_import_bool_counters_refused(self):
        data = {
            "source": "france_travail",
            "source_run_id": "RUN-1",
            "raw_offer_count": True,  # boolean refused
            "normalized_offer_count": 0,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": []
        }
        f = self._write_json("offers.json", data)
        with self.assertRaises(FranceTravailImportError):
            prepare_import(f)

    def test_prepare_import_negative_counters(self):
        data = {
            "source": "france_travail",
            "source_run_id": "RUN-1",
            "raw_offer_count": -5,
            "normalized_offer_count": 0,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": []
        }
        f = self._write_json("offers.json", data)
        with self.assertRaises(FranceTravailImportError):
            prepare_import(f)

    def test_prepare_import_inconsistent_counters(self):
        # len(offers) != normalized_offer_count
        data_len = {
            "source": "france_travail",
            "source_run_id": "RUN-1",
            "raw_offer_count": 1,
            "normalized_offer_count": 1,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": []
        }
        f = self._write_json("offers.json", data_len)
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertIn("correspond pas à normalized_offer_count", str(ctx.exception))

        # normalized_offer_count + duplicate_offer_count != raw_offer_count
        data_sum = {
            "source": "france_travail",
            "source_run_id": "RUN-1",
            "raw_offer_count": 5,
            "normalized_offer_count": 1,
            "duplicate_offer_count": 1,
            "normalization_error_count": 0,
            "offers": [{"source_offer_id": "FT-1"}]
        }
        f = self._write_json("offers.json", data_sum)
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertIn("Incohérence", str(ctx.exception))

    def test_mapping_error_secure(self):
        data = {
            "source": "france_travail",
            "source_run_id": "RUN-1",
            "raw_offer_count": 1,
            "normalized_offer_count": 1,
            "duplicate_offer_count": 0,
            "normalization_error_count": 0,
            "offers": [
                {
                    "source_offer_id": "", # mapping error
                    "description": "SECRET_DESC",
                    "employer_name": "SECRET_COMPANY"
                }
            ]
        }
        f = self._write_json("offers.json", data)
        with self.assertRaises(FranceTravailImportError) as ctx:
            prepare_import(f)
        self.assertNotIn("SECRET_DESC", str(ctx.exception))
        self.assertNotIn("SECRET_COMPANY", str(ctx.exception))


class MockQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, criterion):
        return self

    def first(self):
        return self.session.query_results.get(self.model)

    def limit(self, val):
        return self

    def all(self):
        return []


class MockSession:
    def __init__(self):
        self.committed_count = 0
        self.rolled_back_count = 0
        self.closed_count = 0
        self.added_objects = []
        self.refreshed_objects = []
        self.query_results = {}
        self.get_results = {}
        self.fail_on_commit = False

    def add(self, obj):
        self.added_objects.append(obj)

    def commit(self):
        if self.fail_on_commit:
            raise Exception("DB Commit Failed")
        self.committed_count += 1

    def rollback(self):
        self.rolled_back_count += 1

    def refresh(self, obj):
        self.refreshed_objects.append(obj)

    def close(self):
        self.closed_count += 1

    def query(self, model):
        return MockQuery(self, model)

    def get(self, model, ident):
        return self.get_results.get(ident)


class TestFranceTravailImporterPersistence(unittest.TestCase):

    def setUp(self):
        global prepare_import, persist_prepared_import
        global FranceTravailImportError, FranceTravailMappingError
        global CompetenceModel, FormationModel, FranceTravailModel
        global FranceTravailRepository

        from services.france_travail.importer import prepare_import, persist_prepared_import
        from services.france_travail.exceptions import FranceTravailImportError, FranceTravailMappingError
        from models.francetravail_model import CompetenceModel, FormationModel, FranceTravailModel
        from repositories.francetravail_repository import FranceTravailRepository

        self.session = MockSession()

        # Create a mock prepared import
        from services.france_travail.mapper import FranceTravailPersistenceBundle
        from services.france_travail.importer import FranceTravailPreparedImport

        offer1 = FranceTravailModel(id="FT-NEW", intitule="Python Dev")
        comp1 = CompetenceModel(code="C1", libelle="Python")
        train1 = FormationModel(code_formation="F1", domaine_libelle="Info")
        bundle1 = FranceTravailPersistenceBundle(
            offer=offer1,
            competencies=(comp1,),
            trainings=(train1,),
            skipped_competency_without_code_count=0,
            skipped_training_without_code_count=0,
            duplicate_competency_code_count=0,
            duplicate_training_code_count=0,
        )

        self.prepared = FranceTravailPreparedImport(
            source_run_id="RUN-1",
            input_file=Path("fake.json"),
            bundles=(bundle1,),
            input_offer_count=1,
            mapped_offer_count=1,
            mapped_competency_count=1,
            mapped_training_count=1,
            skipped_competency_without_code_count=0,
            skipped_training_without_code_count=0,
            duplicate_competency_code_count=0,
            duplicate_training_code_count=0,
        )

    @classmethod
    def tearDownClass(cls):
        import sys
        to_remove = [
            mod for mod in list(sys.modules.keys())
            if mod.startswith("sqlalchemy") or "postgres_connection" in mod or "models" in mod or "repositories" in mod
        ]
        for mod in to_remove:
            sys.modules.pop(mod, None)

    def test_persist_new_offer(self):
        # Offer does not exist in DB
        self.session.get_results["FT-NEW"] = None
        self.session.query_results[CompetenceModel] = None
        self.session.query_results[FormationModel] = None

        result = persist_prepared_import(self.prepared, self.session)

        self.assertEqual(result.inserted_offer_count, 1)
        self.assertEqual(result.existing_offer_count, 0)
        self.assertEqual(result.attached_competency_count, 1)
        self.assertEqual(result.attached_training_count, 1)
        self.assertEqual(self.session.committed_count, 1)
        self.assertEqual(self.session.rolled_back_count, 0)
        self.assertEqual(self.session.closed_count, 0) # Session should not be closed by persist

    def test_persist_existing_offer_ignored(self):
        # Offer already exists
        existing_offer = FranceTravailModel(id="FT-NEW", intitule="Python Dev Existing")
        self.session.get_results["FT-NEW"] = existing_offer

        result = persist_prepared_import(self.prepared, self.session)

        # Should be ignored (existing_offer_count = 1, inserted = 0)
        self.assertEqual(result.inserted_offer_count, 0)
        self.assertEqual(result.existing_offer_count, 1)
        self.assertEqual(self.session.committed_count, 1) # Still commits (empty transaction)
        self.assertEqual(len(self.session.added_objects), 0)

    def test_persist_error_triggers_rollback(self):
        self.session.get_results["FT-NEW"] = None
        self.session.fail_on_commit = True

        with self.assertRaises(FranceTravailImportError) as ctx:
            persist_prepared_import(self.prepared, self.session)

        self.assertEqual(self.session.committed_count, 0)
        self.assertEqual(self.session.rolled_back_count, 1)
        self.assertNotIn("SECRET", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
