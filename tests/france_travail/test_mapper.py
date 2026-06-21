# -*- coding: utf-8 -*-

import unittest
from copy import deepcopy

from services.france_travail.exceptions import FranceTravailMappingError


class TestFranceTravailMapper(unittest.TestCase):

    def setUp(self):
        global map_normalized_offer, FranceTravailPersistenceBundle
        from services.france_travail.mapper import map_normalized_offer, FranceTravailPersistenceBundle

    def test_nominal_offer_mapping(self):
        raw = {
            "source_offer_id": "FT-12345",
            "title": "Ingénieur Python",
            "description": "Un super poste",
            "workplace_postal_code": "75001",
            "rome_code": "M1805",
            "rome_label": "Etudes et dev",
            "occupation_label": "Dev Python",
            "employer_name": "ObservIA",
            "competencies": [
                {"code": "C123", "label": "Python", "requirement": "E"},
                {"code": "C456", "label": "SQL", "requirement": "A"},
            ],
            "trainings": [
                {"code": "F999", "domain_label": "Informatique", "level_label": "Bac+5", "requirement": "E"}
            ]
        }
        bundle = map_normalized_offer(raw)

        self.assertIsInstance(bundle, FranceTravailPersistenceBundle)
        self.assertEqual(bundle.offer.id, "FT-12345")
        self.assertEqual(bundle.offer.intitule, "Ingénieur Python")
        self.assertEqual(bundle.offer.description, "Un super poste")
        self.assertEqual(bundle.offer.lieu_code_postal, "75001")
        self.assertEqual(bundle.offer.rome_code, "M1805")
        self.assertEqual(bundle.offer.rome_libelle, "Etudes et dev")
        self.assertEqual(bundle.offer.appellation_libelle, "Dev Python")
        self.assertEqual(bundle.offer.entreprise_nom, "ObservIA")

        self.assertEqual(len(bundle.competencies), 2)
        self.assertEqual(bundle.competencies[0].code, "C123")
        self.assertEqual(bundle.competencies[0].libelle, "Python")
        self.assertEqual(bundle.competencies[0].exigence, "E")

        self.assertEqual(len(bundle.trainings), 1)
        self.assertEqual(bundle.trainings[0].code_formation, "F999")
        self.assertEqual(bundle.trainings[0].commentaire, None)

        self.assertEqual(bundle.skipped_competency_without_code_count, 0)
        self.assertEqual(bundle.skipped_training_without_code_count, 0)
        self.assertEqual(bundle.duplicate_competency_code_count, 0)
        self.assertEqual(bundle.duplicate_training_code_count, 0)

    def test_minimal_offer_mapping(self):
        raw = {
            "source_offer_id": "  FT-MINIMAL  "
        }
        bundle = map_normalized_offer(raw)
        self.assertEqual(bundle.offer.id, "FT-MINIMAL")
        self.assertIsNone(bundle.offer.intitule)
        self.assertEqual(bundle.competencies, ())
        self.assertEqual(bundle.trainings, ())

    def test_invalid_offer_id(self):
        invalid_cases = [
            {},
            {"source_offer_id": None},
            {"source_offer_id": 12345},
            {"source_offer_id": "   "},
            {"source_offer_id": ""},
        ]
        for case in invalid_cases:
            with self.assertRaises(FranceTravailMappingError):
                map_normalized_offer(case)

    def test_invalid_input_type(self):
        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer("not-a-mapping")

    def test_type_conversions_to_none(self):
        raw = {
            "source_offer_id": "FT-1",
            "title": 1234,  # not a string
            "description": "",  # empty string
            "employer_name": True
        }
        bundle = map_normalized_offer(raw)
        self.assertIsNone(bundle.offer.intitule)
        self.assertIsNone(bundle.offer.description)
        self.assertIsNone(bundle.offer.entreprise_nom)

    def test_no_extra_attributes(self):
        raw = {
            "source_offer_id": "FT-1",
            "title": "Dev",
            "non_existent_column": "value"
        }
        bundle = map_normalized_offer(raw)
        self.assertFalse(hasattr(bundle.offer, "non_existent_column"))

    def test_competency_edge_cases(self):
        raw = {
            "source_offer_id": "FT-1",
            "competencies": [
                {"code": "C1", "label": "L1"},
                {"code": None, "label": "L2"},
                {"code": "", "label": "L3"},
                {"code": "   ", "label": "L4"},
                {"code": "C1", "label": "L1-dup"}, # duplicate
                {"code": "  C2  ", "label": "L5"}, # needs strip
            ]
        }
        bundle = map_normalized_offer(raw)
        self.assertEqual(len(bundle.competencies), 2)
        self.assertEqual(bundle.competencies[0].code, "C1")
        self.assertEqual(bundle.competencies[0].libelle, "L1")
        self.assertEqual(bundle.competencies[1].code, "C2")
        self.assertEqual(bundle.competencies[1].libelle, "L5")

        self.assertEqual(bundle.skipped_competency_without_code_count, 3)
        self.assertEqual(bundle.duplicate_competency_code_count, 1)

    def test_competency_bad_types(self):
        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer({"source_offer_id": "FT-1", "competencies": "not-a-list"})

        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer({"source_offer_id": "FT-1", "competencies": ["not-a-mapping"]})

    def test_training_edge_cases(self):
        raw = {
            "source_offer_id": "FT-1",
            "trainings": [
                {"code": "F1", "domain_label": "D1"},
                {"code": None, "domain_label": "D2"},
                {"code": "", "domain_label": "D3"},
                {"code": "   ", "domain_label": "D4"},
                {"code": "F1", "domain_label": "D1-dup"}, # duplicate
                {"code": "  F2  ", "domain_label": "D5"}, # needs strip
            ]
        }
        bundle = map_normalized_offer(raw)
        self.assertEqual(len(bundle.trainings), 2)
        self.assertEqual(bundle.trainings[0].code_formation, "F1")
        self.assertEqual(bundle.trainings[0].domaine_libelle, "D1")
        self.assertEqual(bundle.trainings[1].code_formation, "F2")
        self.assertEqual(bundle.trainings[1].domaine_libelle, "D5")

        self.assertEqual(bundle.skipped_training_without_code_count, 3)
        self.assertEqual(bundle.duplicate_training_code_count, 1)

    def test_training_bad_types(self):
        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer({"source_offer_id": "FT-1", "trainings": "not-a-list"})

        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer({"source_offer_id": "FT-1", "trainings": ["not-a-mapping"]})

    def test_input_mutation_isolation(self):
        raw = {
            "source_offer_id": "FT-MUT",
            "title": "Original Title",
            "competencies": [{"code": "C1", "label": "Orig"}]
        }
        raw_copy = deepcopy(raw)
        bundle = map_normalized_offer(raw)

        # Mutating the input dictionary
        raw["title"] = "Mutated Title"
        raw["competencies"][0]["label"] = "Mutated"

        self.assertEqual(bundle.offer.intitule, "Original Title")
        self.assertEqual(bundle.competencies[0].libelle, "Orig")

    def test_extra_validations_from_audit(self):
        # source_offer_id bool refusé
        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer({"source_offer_id": True})

        # source_offer_id uniquement des espaces
        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer({"source_offer_id": "      "})

        # chaîne optionnelle uniquement composée d'espaces devient None
        raw = {
            "source_offer_id": "FT-ESPACES",
            "title": "   ",
            "description": "  Valid Description  "
        }
        bundle = map_normalized_offer(raw)
        self.assertIsNone(bundle.offer.intitule)
        self.assertEqual(bundle.offer.description, "Valid Description") # spaces stripped

        # compétences None, formations None
        raw_none = {
            "source_offer_id": "FT-NONE",
            "competencies": None,
            "trainings": None
        }
        bundle_none = map_normalized_offer(raw_none)
        self.assertEqual(bundle_none.competencies, ())
        self.assertEqual(bundle_none.trainings, ())

        # mauvais type global et éléments non-Mapping
        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer({"source_offer_id": "FT-1", "competencies": "string_not_list"})
        with self.assertRaises(FranceTravailMappingError):
            map_normalized_offer({"source_offer_id": "FT-1", "competencies": ["string_not_mapping"]})

        # code composé d'espaces ignoré
        raw_code_spaces = {
            "source_offer_id": "FT-CODE-SPACES",
            "competencies": [{"code": "   ", "label": "Java"}]
        }
        bundle_cs = map_normalized_offer(raw_code_spaces)
        self.assertEqual(len(bundle_cs.competencies), 0)
        self.assertEqual(bundle_cs.skipped_competency_without_code_count, 1)

        # doublon après nettoyage des espaces
        raw_dup_spaces = {
            "source_offer_id": "FT-DUP-SPACES",
            "competencies": [
                {"code": " C1 ", "label": "Java"},
                {"code": "C1", "label": "Java Dup"}
            ]
        }
        bundle_ds = map_normalized_offer(raw_dup_spaces)
        self.assertEqual(len(bundle_ds.competencies), 1)
        self.assertEqual(bundle_ds.competencies[0].code, "C1")
        self.assertEqual(bundle_ds.duplicate_competency_code_count, 1)

    @classmethod
    def tearDownClass(cls):
        import sys
        to_remove = [
            mod for mod in list(sys.modules.keys())
            if mod.startswith("sqlalchemy") or "postgres_connection" in mod or "models" in mod or "repositories" in mod
        ]
        for mod in to_remove:
            sys.modules.pop(mod, None)


if __name__ == "__main__":
    unittest.main()
