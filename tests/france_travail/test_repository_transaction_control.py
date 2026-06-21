# -*- coding: utf-8 -*-

import unittest
from unittest.mock import MagicMock


class MockQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model
        self._filter_val = None

    def filter(self, criterion):
        # simple mock filter that stores the criterion or just returns self
        return self

    def first(self):
        # check what model we are querying
        return self.session.query_results.get(self.model)

    def limit(self, val):
        return self

    def all(self):
        return []


class MockSession:
    def __init__(self):
        self.committed_count = 0
        self.refreshed_objects = []
        self.added_objects = []
        self.query_results = {}

    def add(self, obj):
        self.added_objects.append(obj)

    def commit(self):
        self.committed_count += 1

    def refresh(self, obj):
        self.refreshed_objects.append(obj)

    def query(self, model):
        return MockQuery(self, model)

    def get(self, model, ident):
        return None


class TestRepositoryTransactionControl(unittest.TestCase):

    def setUp(self):
        global CompetenceModel, FormationModel, FranceTravailModel
        global FranceTravailRepository, CompetenceRepository, FormationRepository
        from models.francetravail_model import CompetenceModel, FormationModel, FranceTravailModel
        from repositories.francetravail_repository import FranceTravailRepository, CompetenceRepository, FormationRepository

        self.session = MockSession()
        self.repo = FranceTravailRepository(self.session)
        self.comp_repo = CompetenceRepository(self.session)
        self.form_repo = FormationRepository(self.session)

    def test_create_offre_with_commit_true(self):
        offre = FranceTravailModel(id="FT-1", intitule="Dev")
        self.repo.create_offre(offre, commit=True)

        self.assertEqual(self.session.committed_count, 1)
        self.assertIn(offre, self.session.added_objects)
        self.assertIn(offre, self.session.refreshed_objects)

    def test_create_offre_with_commit_false(self):
        offre = FranceTravailModel(id="FT-1", intitule="Dev")
        self.repo.create_offre(offre, commit=False)

        self.assertEqual(self.session.committed_count, 0)
        self.assertIn(offre, self.session.added_objects)
        self.assertEqual(len(self.session.refreshed_objects), 0)

    def test_create_competence_with_commit_true(self):
        comp = CompetenceModel(code="C1", libelle="L1")
        self.comp_repo.create_competence(comp, commit=True)
        self.assertEqual(self.session.committed_count, 1)
        self.assertIn(comp, self.session.refreshed_objects)

    def test_create_competence_with_commit_false(self):
        comp = CompetenceModel(code="C1", libelle="L1")
        self.comp_repo.create_competence(comp, commit=False)
        self.assertEqual(self.session.committed_count, 0)
        self.assertEqual(len(self.session.refreshed_objects), 0)

    def test_create_formation_with_commit_true(self):
        form = FormationModel(code_formation="F1", domaine_libelle="D1")
        self.form_repo.create_formation(form, commit=True)
        self.assertEqual(self.session.committed_count, 1)
        self.assertIn(form, self.session.refreshed_objects)

    def test_create_formation_with_commit_false(self):
        form = FormationModel(code_formation="F1", domaine_libelle="D1")
        self.form_repo.create_formation(form, commit=False)
        self.assertEqual(self.session.committed_count, 0)
        self.assertEqual(len(self.session.refreshed_objects), 0)

    def test_attach_or_create_competence_new_with_commit_false(self):
        offre = FranceTravailModel(id="FT-1")
        comp = CompetenceModel(code="C1", libelle="L1")

        # Mock that competence does not exist in DB
        self.session.query_results[CompetenceModel] = None

        self.repo.attach_or_create_competence(offre, comp, commit=False)

        # Competence should be created (added to session) and attached, but NO commit or refresh
        self.assertIn(comp, self.session.added_objects)
        self.assertIn(comp, offre.competences)
        self.assertEqual(self.session.committed_count, 0)
        self.assertEqual(len(self.session.refreshed_objects), 0)

    def test_attach_or_create_competence_existing_with_commit_false(self):
        offre = FranceTravailModel(id="FT-1")
        comp = CompetenceModel(code="C1", libelle="L1")

        existing_comp = CompetenceModel(id=10, code="C1", libelle="L1")
        self.session.query_results[CompetenceModel] = existing_comp

        self.repo.attach_or_create_competence(offre, comp, commit=False)

        # Existing competence should be attached, but NO new competence created in session, NO commit/refresh
        self.assertNotIn(comp, self.session.added_objects)
        self.assertIn(existing_comp, offre.competences)
        self.assertEqual(self.session.committed_count, 0)
        self.assertEqual(len(self.session.refreshed_objects), 0)

    def test_attach_or_create_competence_new_with_commit_true(self):
        offre = FranceTravailModel(id="FT-1")
        comp = CompetenceModel(code="C1", libelle="L1")
        self.session.query_results[CompetenceModel] = None

        self.repo.attach_or_create_competence(offre, comp, commit=True)

        self.assertIn(comp, self.session.added_objects)
        self.assertIn(comp, offre.competences)
        self.assertGreaterEqual(self.session.committed_count, 1) # one or more commits (history commits on creation + attachment)
        self.assertIn(offre, self.session.refreshed_objects)

    def test_attach_or_create_formation_new_with_commit_false(self):
        offre = FranceTravailModel(id="FT-1")
        form = FormationModel(code_formation="F1")
        self.session.query_results[FormationModel] = None

        self.repo.attach_or_create_formation(offre, form, commit=False)

        self.assertIn(form, self.session.added_objects)
        self.assertIn(form, offre.formations)
        self.assertEqual(self.session.committed_count, 0)
        self.assertEqual(len(self.session.refreshed_objects), 0)

    def test_attach_or_create_formation_existing_with_commit_false(self):
        offre = FranceTravailModel(id="FT-1")
        form = FormationModel(code_formation="F1")

        existing_form = FormationModel(id=20, code_formation="F1")
        self.session.query_results[FormationModel] = existing_form

        self.repo.attach_or_create_formation(offre, form, commit=False)

        self.assertNotIn(form, self.session.added_objects)
        self.assertIn(existing_form, offre.formations)
        self.assertEqual(self.session.committed_count, 0)
        self.assertEqual(len(self.session.refreshed_objects), 0)

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
