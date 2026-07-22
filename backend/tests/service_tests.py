"""Tests pytest pour les méthodes de services/service.py."""
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=redefined-outer-name,too-many-public-methods
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from services.service import REGIONS, Service, _normalize_region


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _flux(mois: int, annee: int, entrees: int, sp: int = 0, st: int = 0):
    """Crée un flux mensuel factice."""
    return SimpleNamespace(
        mois=mois,
        annee=annee,
        entrees_formation=entrees,
        sorties_realisation_partielle=sp,
        sorties_realisation_totale=st,
    )


def _formation(region: str, flux_list: list):
    """Crée une formation factice."""
    return SimpleNamespace(region=region, flux_mensuels=flux_list)


def _competence(libelle: str):
    return SimpleNamespace(libelle=libelle)


def _offre(competences: list, formations: list | None = None, rome_code: str = "A1234"):
    return SimpleNamespace(
        competences=competences, formations=formations or [], rome_code=rome_code
    )


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def service():
    """Service avec repositories entièrement mockés."""
    svc = Service(MagicMock())
    svc.offre_repository = MagicMock()
    svc.formation_repository = MagicMock()
    svc.rome_repository = MagicMock()
    svc.offre_repository.count_offres.return_value = 0
    svc.offre_repository.count_offres_by_code_postal.return_value = []
    svc.offre_repository.get_all.return_value = []
    svc.formation_repository.get_all.return_value = []
    return svc


# ─── _normalize_region ────────────────────────────────────────────────────────


class TestNormalizeRegion:
    def test_none_returns_sentinel(self):
        assert _normalize_region(None) == "regioninconnue"

    def test_non_string_returns_sentinel(self):
        assert _normalize_region(42) == "regioninconnue"  # type: ignore[arg-type]

    def test_empty_string_returns_sentinel(self):
        assert _normalize_region("") == "regioninconnue"

    def test_whitespace_only_returns_sentinel(self):
        assert _normalize_region("   ") == "regioninconnue"

    def test_simple_region_lowercased(self):
        assert _normalize_region("Bretagne") == "bretagne"

    def test_strips_surrounding_whitespace(self):
        assert _normalize_region("  Bretagne  ") == "bretagne"

    def test_removes_hyphens(self):
        assert _normalize_region("Île-de-France") == "îledefrance"

    def test_removes_internal_spaces(self):
        assert _normalize_region("Centre-Val de Loire") == "centrevaldeloire"

    def test_removes_apostrophes(self):
        # "Provence-Alpes-Côte d'Azur" → "provencealpescôtedazur"
        assert _normalize_region("Provence-Alpes-Côte d'Azur") == "provencealpescôtedazur"


# ─── REGIONS ──────────────────────────────────────────────────────────────────


class TestRegions:
    def test_is_sorted(self):
        assert REGIONS == sorted(REGIONS)

    def test_no_duplicates(self):
        assert len(REGIONS) == len(set(REGIONS))

    def test_contains_known_regions(self):
        assert "bretagne" in REGIONS
        assert "îledefrance" in REGIONS
        assert "occitanie" in REGIONS

    def test_all_entries_are_lowercase_strings(self):
        assert all(isinstance(r, str) and r == r.lower() for r in REGIONS)


# ─── Service._normalize_region ────────────────────────────────────────────────


class TestServiceNormalizeRegion:
    def test_delegates_to_module_function(self):
        assert Service._normalize_region("Bretagne") == "bretagne"

    def test_none_returns_sentinel(self):
        assert Service._normalize_region(None) == "regioninconnue"


# ─── Service.get_region_by_code_postal ────────────────────────────────────────


class TestGetRegionByCodePostal:
    def test_metropolitan_department(self, service):
        assert service.get_region_by_code_postal("75001") == "îledefrance"

    def test_bretagne(self, service):
        assert service.get_region_by_code_postal("35000") == "bretagne"

    def test_normandie(self, service):
        assert service.get_region_by_code_postal("76000") == "normandie"

    def test_domtom_971_guadeloupe(self, service):
        assert service.get_region_by_code_postal("97100") == "guadeloupe"

    def test_domtom_972_martinique(self, service):
        assert service.get_region_by_code_postal("97200") == "martinique"

    def test_domtom_974_reunion(self, service):
        assert service.get_region_by_code_postal("97400") == "laréunion"

    def test_strips_whitespace(self, service):
        assert service.get_region_by_code_postal("  75001  ") == "îledefrance"

    def test_unknown_department_returns_sentinel(self, service):
        assert service.get_region_by_code_postal("99999") == "regioninconnue"


# ─── Service.count_formation_entries_by_region_and_quarter ────────────────────


class TestCountFormationEntries:
    def test_invalid_region_raises_400(self, service):
        with pytest.raises(HTTPException) as exc_info:
            service.count_formation_entries_by_region_and_quarter(region="pays_imaginaire")
        assert exc_info.value.status_code == 400

    def test_invalid_quarter_t5_raises_400(self, service):
        with pytest.raises(HTTPException) as exc_info:
            service.count_formation_entries_by_region_and_quarter(quarter="2024-T5")
        assert exc_info.value.status_code == 400

    def test_invalid_quarter_no_year_raises_400(self, service):
        with pytest.raises(HTTPException) as exc_info:
            service.count_formation_entries_by_region_and_quarter(quarter="T1")
        assert exc_info.value.status_code == 400

    def test_invalid_quarter_wrong_separator_raises_400(self, service):
        with pytest.raises(HTTPException) as exc_info:
            service.count_formation_entries_by_region_and_quarter(quarter="2024/T1")
        assert exc_info.value.status_code == 400

    def test_no_data_returns_zero_totals(self, service):
        result = service.count_formation_entries_by_region_and_quarter()
        assert result["Total des entrées en formation dans toute la France"] == 0
        assert result["Nombre d'offres trouvées dans toute la France"] == 0

    def test_offer_count_from_repository(self, service):
        service.offre_repository.count_offres.return_value = 42
        result = service.count_formation_entries_by_region_and_quarter()
        assert result["Nombre d'offres trouvées dans toute la France"] == 42

    def test_global_totals_absent_when_region_filter(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(1, 2024, 5)])
        ]
        result = service.count_formation_entries_by_region_and_quarter(region="bretagne")
        assert "Total des entrées en formation dans toute la France" not in result
        assert "Nombre d'offres trouvées dans toute la France" not in result

    def test_global_totals_absent_when_quarter_filter(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(1, 2024, 5)])
        ]
        result = service.count_formation_entries_by_region_and_quarter(quarter="2024-T1")
        assert "Total des entrées en formation dans toute la France" not in result

    def test_mois_1_maps_to_t1(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(mois=1, annee=2024, entrees=1)])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert "2024-T1" in result["bretagne"]

    def test_mois_3_maps_to_t1(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(mois=3, annee=2024, entrees=1)])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert "2024-T1" in result["bretagne"]

    def test_mois_4_maps_to_t2(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(mois=4, annee=2024, entrees=1)])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert "2024-T2" in result["bretagne"]

    def test_mois_12_maps_to_t4(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(mois=12, annee=2024, entrees=1)])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert "2024-T4" in result["bretagne"]

    def test_filter_by_quarter_excludes_other_quarters(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(1, 2024, 5), _flux(4, 2024, 8)])
        ]
        result = service.count_formation_entries_by_region_and_quarter(quarter="2024-T1")
        assert "2024-T1" in result.get("bretagne", {})
        assert "2024-T2" not in result.get("bretagne", {})

    def test_filter_by_region_excludes_other_regions(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(1, 2024, 5)]),
            _formation("Normandie", [_flux(1, 2024, 3)]),
        ]
        result = service.count_formation_entries_by_region_and_quarter(region="bretagne")
        assert "bretagne" in result
        assert "normandie" not in result

    def test_flux_with_none_mois_is_skipped(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [
                SimpleNamespace(mois=None, annee=2024, entrees_formation=10,
                                sorties_realisation_partielle=0, sorties_realisation_totale=0)
            ])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert "bretagne" not in result

    def test_flux_with_none_entrees_is_skipped(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [
                SimpleNamespace(mois=1, annee=2024, entrees_formation=None,
                                sorties_realisation_partielle=0, sorties_realisation_totale=0)
            ])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert "bretagne" not in result

    def test_sorties_partielles_accumulated(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(1, 2024, entrees=0, sp=3, st=0)])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert result["bretagne"]["2024-T1"]["sorties_realisation_partielle"] == 3

    def test_sorties_totales_accumulated(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(1, 2024, entrees=0, sp=0, st=7)])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert result["bretagne"]["2024-T1"]["sorties_realisation_totale"] == 7

    def test_offres_counted_per_region(self, service):
        service.offre_repository.count_offres_by_code_postal.return_value = [("35000", 4)]
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(1, 2024, 1)])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert result["bretagne"]["Nombre d'offres dans la région"] == 4

    def test_quarters_sorted_within_region(self, service):
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(7, 2024, 1), _flux(1, 2024, 1), _flux(1, 2023, 1)])
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        quarter_keys = [k for k in result["bretagne"] if k[:4].isdigit()]
        assert quarter_keys == sorted(quarter_keys)

    def test_region_normalized_for_grouping(self, service):
        """Deux formations avec la même région en casse différente → même bucket."""
        service.formation_repository.get_all.return_value = [
            _formation("Bretagne", [_flux(1, 2024, 1)]),
            _formation("BRETAGNE", [_flux(1, 2024, 1)]),
        ]
        result = service.count_formation_entries_by_region_and_quarter()
        assert "bretagne" in result
        assert "BRETAGNE" not in result


# ─── Service.get_formations_by_offre_id ───────────────────────────────────────


class TestGetFormationsByOffreId:
    def test_unknown_offre_returns_error_dict(self, service):
        service.offre_repository.get_by_francetravail_id.return_value = None
        result = service.get_formations_by_offre_id("FT_INCONNU")
        assert isinstance(result, dict)
        assert "error" in result
        assert "FT_INCONNU" in result["error"]

    def test_offre_formations_returned(self, service):
        f1 = SimpleNamespace(id=1)
        service.offre_repository.get_by_francetravail_id.return_value = SimpleNamespace(
            rome_code="A1234", formations=[f1]
        )
        service.rome_repository.list_formations_by_rome.return_value = []
        result = service.get_formations_by_offre_id("FT1")
        assert f1 in result

    def test_rome_formations_merged(self, service):
        f1 = SimpleNamespace(id=1)
        f2 = SimpleNamespace(id=2)
        service.offre_repository.get_by_francetravail_id.return_value = SimpleNamespace(
            rome_code="A1234", formations=[f1]
        )
        service.rome_repository.list_formations_by_rome.return_value = [f2]
        result = service.get_formations_by_offre_id("FT1")
        assert f1 in result
        assert f2 in result

    def test_duplicate_rome_formations_deduplicated(self, service):
        f1 = SimpleNamespace(id=1)
        service.offre_repository.get_by_francetravail_id.return_value = SimpleNamespace(
            rome_code="A1234", formations=[f1]
        )
        # f1 est aussi dans les formations ROME → ne doit apparaître qu'une fois
        service.rome_repository.list_formations_by_rome.return_value = [f1]
        result = service.get_formations_by_offre_id("FT1")
        assert result.count(f1) == 1

    def test_offre_without_direct_formations(self, service):
        f_rome = SimpleNamespace(id=10)
        service.offre_repository.get_by_francetravail_id.return_value = SimpleNamespace(
            rome_code="B5678", formations=[]
        )
        service.rome_repository.list_formations_by_rome.return_value = [f_rome]
        result = service.get_formations_by_offre_id("FT2")
        assert result == [f_rome]


# ─── Service.get_best_skills ──────────────────────────────────────────────────


class TestGetBestSkills:
    def test_no_offres_returns_empty(self, service):
        assert service.get_best_skills() == {}

    def test_skill_appearing_once_excluded(self, service):
        service.offre_repository.get_all.return_value = [_offre([_competence("Python")])]
        assert "Python" not in service.get_best_skills()

    def test_skill_appearing_twice_included(self, service):
        service.offre_repository.get_all.return_value = [
            _offre([_competence("Python")]),
            _offre([_competence("Python")]),
        ]
        assert service.get_best_skills()["Python"] == 2

    def test_skills_sorted_by_count_descending(self, service):
        service.offre_repository.get_all.return_value = [
            _offre([_competence("SQL"), _competence("Python")]),
            _offre([_competence("SQL"), _competence("Python")]),
            _offre([_competence("SQL")]),
        ]
        counts = list(service.get_best_skills().values())
        assert counts == sorted(counts, reverse=True)

    def test_multiple_skills_per_offre_all_counted(self, service):
        service.offre_repository.get_all.return_value = [
            _offre([_competence("Docker"), _competence("Git")]),
            _offre([_competence("Docker"), _competence("Git")]),
        ]
        result = service.get_best_skills()
        assert result == {"Docker": 2, "Git": 2}

    def test_offre_with_no_competences(self, service):
        service.offre_repository.get_all.return_value = [_offre([])]
        assert service.get_best_skills() != {}
