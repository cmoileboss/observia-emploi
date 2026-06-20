# -*- coding: utf-8 -*-

"""
Unit tests for services.france_travail.normalizer.
All tests run entirely offline with synthetic data.
No network calls, no PostgreSQL connections, no Pydantic/SQLAlchemy/FastAPI imports.
"""

from __future__ import annotations

import json
import sys
import unittest

from services.france_travail.exceptions import FranceTravailNormalizationError
from services.france_travail.normalizer import (
    NormalizedFranceTravailCompetence,
    NormalizedFranceTravailOffer,
    NormalizedFranceTravailTraining,
    normalize_offer,
    normalized_offer_to_dict,
)


class TestFranceTravailNormalizerNominal(unittest.TestCase):
    """Test case for nominal normalization with full synthetic data."""

    def test_nominal_offer_normalization(self):
        # Full synthetic offer containing all key structures
        raw_offer = {
            "id": "  FT-123456789  ",
            "intitule": "  Ingénieur Python H/F  ",
            "description": "Description secrète de l'offre.",
            "dateCreation": "2026-06-20T10:00:00Z",
            "dateActualisation": "2026-06-20T12:00:00Z",
            "romeCode": "M1805",
            "romeLibelle": "Développement et intégration",
            "appellationlibelle": "Développeur Python",
            "typeContrat": "CDI",
            "typeContratLibelle": "Contrat à durée indéterminée",
            "natureContrat": "Contrat de travail",
            "experienceExige": "E",
            "experienceLibelle": "3 ans d'expérience",
            "dureeTravailLibelle": "35H Horaires normaux",
            "nombrePostes": 2,
            "alternance": False,
            "secteurActivite": "62",
            "secteurActiviteLibelle": "Programmation informatique",
            "lieuTravail": {
                "libelle": "Paris 75001",
                "codePostal": "75001",
                "commune": "75101",
                "latitude": 48.86,
                "longitude": 2.34,
            },
            "entreprise": {
                "nom": "ObservIA Corp",
                "description": "Entreprise innovante",
                "entrepriseAdaptee": False,
            },
            "salaire": {
                "libelle": "35k-45k EUR",
                "commentaire": "Selon profil",
            },
            "origineOffre": {
                "origine": "1",
                "urlOrigine": "https://example.com/job/123",
            },
            "competences": [
                {
                    "code": "C120456",
                    "libelle": "Python language",
                    "exigence": "E",
                },
                # Duplicate competence (should be removed)
                {
                    "code": "C120456",
                    "libelle": "Python language",
                    "exigence": "E",
                },
                # Competence without code
                {
                    "code": None,
                    "libelle": "Git version control",
                    "exigence": "A",
                },
            ],
            "formations": [
                {
                    "codeFormation": "F-999",
                    "domaineLibelle": "Informatique",
                    "niveauLibelle": "Bac+5",
                    "exigence": "E",
                },
                # Duplicate training (should be removed)
                {
                    "codeFormation": "F-999",
                    "domaineLibelle": "Informatique",
                    "niveauLibelle": "Bac+5",
                    "exigence": "E",
                },
                # Training without code
                {
                    "codeFormation": None,
                    "domaineLibelle": "Mathématiques",
                    "niveauLibelle": "Bac+3",
                    "exigence": "A",
                },
            ],
        }

        offer = normalize_offer(raw_offer)

        self.assertEqual(offer.source, "france_travail")
        self.assertEqual(offer.source_offer_id, "FT-123456789")
        self.assertEqual(offer.title, "Ingénieur Python H/F")
        self.assertEqual(offer.description, "Description secrète de l'offre.")
        self.assertEqual(offer.created_at, "2026-06-20T10:00:00Z")
        self.assertEqual(offer.updated_at, "2026-06-20T12:00:00Z")
        self.assertEqual(offer.rome_code, "M1805")
        self.assertEqual(offer.rome_label, "Développement et intégration")
        self.assertEqual(offer.occupation_label, "Développeur Python")
        self.assertEqual(offer.workplace_label, "Paris 75001")
        self.assertEqual(offer.workplace_postal_code, "75001")
        self.assertEqual(offer.workplace_city_code, "75101")
        self.assertEqual(offer.employer_name, "ObservIA Corp")
        self.assertEqual(offer.contract_type, "CDI")
        self.assertEqual(offer.contract_label, "Contrat à durée indéterminée")
        self.assertEqual(offer.contract_nature, "Contrat de travail")
        self.assertEqual(offer.experience_required, "E")
        self.assertEqual(offer.experience_label, "3 ans d'expérience")
        self.assertEqual(offer.work_duration_label, "35H Horaires normaux")
        self.assertEqual(offer.positions_count, 2)
        self.assertEqual(offer.alternance, False)
        self.assertEqual(offer.sector_code, "62")
        self.assertEqual(offer.sector_label, "Programmation informatique")
        self.assertEqual(offer.salary_label, "35k-45k EUR")
        self.assertEqual(offer.origin, "1")
        self.assertEqual(offer.origin_url, "https://example.com/job/123")

        # Competencies validation
        self.assertEqual(len(offer.competencies), 2)
        self.assertEqual(offer.competencies[0].code, "C120456")
        self.assertEqual(offer.competencies[0].label, "Python language")
        self.assertEqual(offer.competencies[0].requirement, "E")
        self.assertEqual(offer.competencies[1].code, None)
        self.assertEqual(offer.competencies[1].label, "Git version control")

        # Trainings validation
        self.assertEqual(len(offer.trainings), 2)
        self.assertEqual(offer.trainings[0].code, "F-999")
        self.assertEqual(offer.trainings[0].domain_label, "Informatique")
        self.assertEqual(offer.trainings[0].level_label, "Bac+5")
        self.assertEqual(offer.trainings[1].code, None)
        self.assertEqual(offer.trainings[1].domain_label, "Mathématiques")


class TestFranceTravailNormalizerValidation(unittest.TestCase):
    """Test validation constraints on the 'id' field."""

    def test_id_absent_raises(self):
        with self.assertRaises(FranceTravailNormalizationError) as ctx:
            normalize_offer({"intitule": "Python Developer"})
        self.assertIn("L'identifiant de l'offre 'id' est absent", str(ctx.exception))

    def test_id_none_raises(self):
        with self.assertRaises(FranceTravailNormalizationError) as ctx:
            normalize_offer({"id": None})
        self.assertIn("L'identifiant de l'offre 'id' est nul", str(ctx.exception))

    def test_id_not_string_raises(self):
        with self.assertRaises(FranceTravailNormalizationError) as ctx:
            normalize_offer({"id": 12345})
        self.assertIn("L'identifiant de l'offre 'id' doit être une chaîne", str(ctx.exception))

    def test_id_empty_raises(self):
        with self.assertRaises(FranceTravailNormalizationError) as ctx:
            normalize_offer({"id": ""})
        self.assertIn("L'identifiant de l'offre 'id' est vide", str(ctx.exception))

    def test_id_spaces_only_raises(self):
        with self.assertRaises(FranceTravailNormalizationError) as ctx:
            normalize_offer({"id": "     "})
        self.assertIn("L'identifiant de l'offre 'id' est vide", str(ctx.exception))


class TestFranceTravailNormalizerOptionalFields(unittest.TestCase):
    """Test handling of missing or None values for optional parameters."""

    def test_minimal_offer(self):
        """Minimal valid offer with only an id."""
        offer = normalize_offer({"id": "MIN-1"})
        self.assertEqual(offer.source_offer_id, "MIN-1")
        self.assertEqual(offer.source, "france_travail")
        self.assertIsNone(offer.title)
        self.assertEqual(offer.competencies, ())
        self.assertEqual(offer.trainings, ())

    def test_workplace_and_employer_variations(self):
        """None or wrong type in structured dicts doesn't raise error."""
        offer_none = normalize_offer({
            "id": "MIN-2",
            "lieuTravail": None,
            "entreprise": None,
            "salaire": None,
            "origineOffre": None,
        })
        self.assertIsNone(offer_none.workplace_label)
        self.assertIsNone(offer_none.employer_name)

        offer_wrong_type = normalize_offer({
            "id": "MIN-3",
            "lieuTravail": "Paris",
            "entreprise": ["Not", "A", "Dict"],
            "salaire": 45000,
            "origineOffre": False,
        })
        self.assertIsNone(offer_wrong_type.workplace_label)
        self.assertIsNone(offer_wrong_type.employer_name)


class TestFranceTravailNormalizerCompetenciesAndTrainings(unittest.TestCase):
    """Test deduplication and normalization of competencies/trainings lists."""

    def test_competence_edge_cases(self):
        raw = {
            "id": "1",
            "competences": [
                # Completely empty (should be skipped)
                {"code": None, "libelle": None, "exigence": None},
                # Duplicate with different spacing (should be distinct or not? standard strip normalizes them)
                {"code": " C1 ", "libelle": " L1 ", "exigence": " E1 "},
                {"code": "C1", "libelle": "L1", "exigence": "E1"},
                # Non-dict item (should be skipped)
                "not-a-dict",
            ]
        }
        offer = normalize_offer(raw)
        self.assertEqual(len(offer.competencies), 1)
        self.assertEqual(offer.competencies[0].code, "C1")
        self.assertEqual(offer.competencies[0].label, "L1")
        self.assertEqual(offer.competencies[0].requirement, "E1")

    def test_training_edge_cases(self):
        raw = {
            "id": "1",
            "formations": [
                # Completely empty (skipped)
                {"codeFormation": "   ", "domaineLibelle": "", "niveauLibelle": None, "exigence": " "},
                # Normal training without code
                {"codeFormation": None, "domaineLibelle": "Domaine", "niveauLibelle": "Licence"},
                # Non-dict
                12345,
            ]
        }
        offer = normalize_offer(raw)
        self.assertEqual(len(offer.trainings), 1)
        self.assertEqual(offer.trainings[0].code, None)
        self.assertEqual(offer.trainings[0].domain_label, "Domaine")
        self.assertEqual(offer.trainings[0].level_label, "Licence")


class TestFranceTravailNormalizerTypes(unittest.TestCase):
    """Test strict type validation for numerical and boolean inputs."""

    def test_positions_count_types(self):
        self.assertIsNone(normalize_offer({"id": "1", "nombrePostes": True}).positions_count)
        self.assertIsNone(normalize_offer({"id": "1", "nombrePostes": -5}).positions_count)
        self.assertIsNone(normalize_offer({"id": "1", "nombrePostes": "3"}).positions_count)
        self.assertEqual(normalize_offer({"id": "1", "nombrePostes": 5}).positions_count, 5)

    def test_alternance_types(self):
        self.assertIsNone(normalize_offer({"id": "1", "alternance": "True"}).alternance)
        self.assertIsNone(normalize_offer({"id": "1", "alternance": 1}).alternance)
        self.assertEqual(normalize_offer({"id": "1", "alternance": True}).alternance, True)


class TestFranceTravailNormalizerDataProtection(unittest.TestCase):
    """Ensure that personal and excluded fields are completely absent from output."""

    def test_data_protection_sentinels(self):
        raw = {
            "id": "1",
            "contact": {
                "nom": "SECRET_CONTACT_NAME",
                "courriel": "SECRET_CONTACT_EMAIL",
                "coordonnees1": "SECRET_CONTACT_COORD",
                "urlPostulation": "SECRET_POSTULATION_URL",
            },
            "agence": {
                "courriel": "SECRET_AGENCY_EMAIL",
            },
            "entreprise": {
                "nom": "Safe Name",
                "description": "SECRET_COMPANY_DESC",
            },
            "lieuTravail": {
                "libelle": "Safe Workplace",
                "latitude": 99.9999,
                "longitude": -99.9999,
            }
        }

        offer = normalize_offer(raw)
        serialized = normalized_offer_to_dict(offer)
        json_str = json.dumps(serialized)

        sentinels = [
            "SECRET_CONTACT_NAME",
            "SECRET_CONTACT_EMAIL",
            "SECRET_CONTACT_COORD",
            "SECRET_POSTULATION_URL",
            "SECRET_AGENCY_EMAIL",
            "SECRET_COMPANY_DESC",
            "99.9999",
        ]

        for s in sentinels:
            # Check in model representation
            self.assertNotIn(s, repr(offer))
            # Check in serialized dict
            self.assertNotIn(s, repr(serialized))
            # Check in JSON string
            self.assertNotIn(s, json_str)


class TestFranceTravailNormalizerImmutability(unittest.TestCase):
    """Test that output is immutable and not affected by external mutations."""

    def test_immutability(self):
        raw = {
            "id": "1",
            "competences": [{"code": "C1"}],
        }
        offer = normalize_offer(raw)

        # Mutating the input dictionary
        raw["id"] = "changed"
        raw["competences"][0]["code"] = "changed"

        self.assertEqual(offer.source_offer_id, "1")
        self.assertEqual(offer.competencies[0].code, "C1")

        # Dataclass field modification attempts should fail
        with self.assertRaises((AttributeError, TypeError)):
            offer.title = "New Title"  # type: ignore[misc]


class TestFranceTravailNormalizerSerialization(unittest.TestCase):
    """Test that serialization results in a plain, JSON-serializable structure."""

    def test_json_serialization(self):
        offer = normalize_offer({
            "id": "1",
            "competences": [{"code": "C1"}],
            "formations": [{"niveauLibelle": "Bac"}],
        })
        serialized = normalized_offer_to_dict(offer)

        # Ensure types are converted to JSON compatible types (list instead of tuple)
        self.assertTrue(isinstance(serialized["competencies"], list))
        self.assertTrue(isinstance(serialized["trainings"], list))

        # json.dumps should succeed without any error
        result = json.dumps(serialized)
        self.assertTrue(isinstance(result, str))


class TestFranceTravailNormalizerAdditionalEdgeCases(unittest.TestCase):
    """Additional edge cases to satisfy audit specifications."""

    def test_id_bool_refused(self):
        with self.assertRaises(FranceTravailNormalizationError):
            normalize_offer({"id": True})
        with self.assertRaises(FranceTravailNormalizationError):
            normalize_offer({"id": False})

    def test_bad_competencies_and_trainings_global_types(self):
        """String or int instead of list should gracefully become empty tuple without iterating on string."""
        offer_str = normalize_offer({"id": "1", "competences": "not-a-list", "formations": "not-a-list"})
        self.assertEqual(offer_str.competencies, ())
        self.assertEqual(offer_str.trainings, ())

        offer_int = normalize_offer({"id": "2", "competences": 12345, "formations": 12345})
        self.assertEqual(offer_int.competencies, ())
        self.assertEqual(offer_int.trainings, ())

    def test_date_edge_cases(self):
        offer_empty_dates = normalize_offer({"id": "1", "dateCreation": "   ", "dateActualisation": ""})
        self.assertIsNone(offer_empty_dates.created_at)
        self.assertIsNone(offer_empty_dates.updated_at)

        offer_non_str_dates = normalize_offer({"id": "2", "dateCreation": 12345, "dateActualisation": True})
        self.assertIsNone(offer_non_str_dates.created_at)
        self.assertIsNone(offer_non_str_dates.updated_at)

    def test_description_non_str(self):
        offer = normalize_offer({"id": "1", "description": 12345})
        self.assertIsNone(offer.description)

        offer_bool = normalize_offer({"id": "2", "description": True})
        self.assertIsNone(offer_bool.description)

    def test_nested_structures_wrong_type(self):
        offer = normalize_offer({
            "id": "1",
            "lieuTravail": "Paris",
            "entreprise": 123,
            "salaire": True,
            "origineOffre": ["list"],
        })
        self.assertIsNone(offer.workplace_label)
        self.assertIsNone(offer.employer_name)
        self.assertIsNone(offer.salary_label)
        self.assertIsNone(offer.origin)

    def test_payload_mutations(self):
        """Modifying the output of normalized_offer_to_dict or original input doesn't mutate normalizer state."""
        raw = {
            "id": "1",
            "competences": [{"code": "C1"}],
        }
        offer = normalize_offer(raw)
        serialized = normalized_offer_to_dict(offer)

        # Mutate serialized dict
        serialized["source_offer_id"] = "mutated"
        serialized["competencies"][0]["code"] = "mutated"

        self.assertEqual(offer.source_offer_id, "1")
        self.assertEqual(offer.competencies[0].code, "C1")


class TestFranceTravailNormalizerIsolation(unittest.TestCase):
    """Test that the module does not import Pydantic, FastAPI, or SQLAlchemy."""

    def test_imports_isolation(self):
        for forbidden in ["pydantic", "fastapi", "sqlalchemy", "main"]:
            self.assertNotIn(forbidden, sys.modules)


if __name__ == "__main__":
    unittest.main()
