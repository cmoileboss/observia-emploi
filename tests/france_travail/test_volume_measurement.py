"""Tests for the ROME volume and aggregation measurement service."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from observia_emploi.france_travail.client import FranceTravailClient, MockResponse
from observia_emploi.france_travail.volume_measurement import (
    RomeVolumeMeasurementService,
)


@pytest.fixture
def temp_referential_file(tmp_path: Path) -> Path:
    """Create a temporary valid ROME referential JSON file."""
    ref_data = {
        "source": "france_travail_api",
        "dataset": "referentiel_metiers_rome",
        "items": [
            {"code_rome": "M1801", "libelle_rome": "Administration de SI"},
            {"code_rome": "M1802", "libelle_rome": "Expertise technique SI"},
            {"code_rome": "M1805", "libelle_rome": "Dév informatique"},
        ],
    }
    file_path = tmp_path / "rome_metiers_v1.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f, ensure_ascii=False)
    return file_path


def test_parse_content_range_valid() -> None:
    """Test standard valid HTTP Content-Range formats."""
    service = RomeVolumeMeasurementService(MagicMock())
    assert service.parse_content_range("offres 0-0/4152") == 4152
    assert service.parse_content_range("offres 0-149/1500") == 1500
    assert service.parse_content_range("something/500") == 500
    assert service.parse_content_range(None) == 0
    assert service.parse_content_range("invalid format") == 0


def test_extract_aggregations_nominal() -> None:
    """Test nominal extraction of aggregates with legacy format."""
    service = RomeVolumeMeasurementService(MagicMock())
    raw_data = {
        "filtresPossibles": [
            {
                "filtre": "typeContrat",
                "valeurs": [
                    {"valeur": "CDI", "nb": 10},
                    {"valeur": "CDD", "nb": 5},
                ],
            },
            {
                "filtre": "experience",
                "valeurs": [
                    {"valeur": "1 an", "nb": 8},
                ],
            },
        ]
    }
    contracts = service.extract_aggregations(raw_data, "typeContrat")
    assert contracts == {"CDI": 10, "CDD": 5}

    exp = service.extract_aggregations(raw_data, "experience")
    assert exp == {"1 an": 8}

    qual = service.extract_aggregations(raw_data, "qualification")
    assert qual == {}


def test_extract_aggregations_real_api_format() -> None:
    """Test extraction with real API structure (agregation, valeurPossible)."""
    service = RomeVolumeMeasurementService(MagicMock())
    raw_data = {
        "filtresPossibles": [
            {
                "filtre": "typeContrat",
                "agregation": [
                    {"valeurPossible": "CDI", "nbResultats": 10},
                    {"valeurPossible": "CDD", "nbResultats": 5},
                ],
            },
            {
                "filtre": "experience",
                "agregation": [{"valeurPossible": "0", "nbResultats": 3}],
            },
            {
                "filtre": "qualification",
                "agregation": [{"valeurPossible": "9", "nbResultats": 2}],
            },
            {
                "filtre": "natureContrat",
                "agregation": [{"valeurPossible": "E1", "nbResultats": 8}],
            },
        ]
    }
    assert service.extract_aggregations(raw_data, "typeContrat") == {
        "CDI": 10,
        "CDD": 5,
    }
    assert service.extract_aggregations(raw_data, "experience") == {"0": 3}
    assert service.extract_aggregations(raw_data, "qualification") == {"9": 2}
    assert service.extract_aggregations(raw_data, "natureContrat") == {"E1": 8}


def test_measure_single_rome_success() -> None:
    """Test volume query with first_result_rome_valid == True."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_json = {
        "resultats": [
            {
                "id": "OFFRE_1",
                "romeCode": "M1805",
            }
        ],
        "filtresPossibles": [
            {
                "filtre": "typeContrat",
                "agregation": [{"valeurPossible": "CDI", "nbResultats": 10}],
            }
        ],
    }
    mock_client.get_raw.return_value = MockResponse(
        status_code=206,
        json_data=mock_json,
        headers={"Content-Range": "offres 0-0/100"},
    )

    service = RomeVolumeMeasurementService(mock_client)

    # Act
    measure = service.measure_single_rome("M1805", "Dév informatique")

    # Assert
    assert measure.code_rome == "M1805"
    assert measure.libelle_rome == "Dév informatique"
    assert measure.total_offres_disponibles == 100
    assert measure.http_status == 206
    assert measure.content_range == "offres 0-0/100"
    assert measure.contract_aggregations == {"CDI": 10}
    assert measure.first_result_rome_code == "M1805"
    assert measure.first_result_id == "OFFRE_1"
    assert measure.first_result_rome_valid is True


def test_measure_single_rome_rome_invalid() -> None:
    """Test volume query with first_result_rome_valid == False."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_json = {
        "resultats": [
            {
                "id": "OFFRE_OTHER",
                "romeCode": "M1802",
            }
        ]
    }
    mock_client.get_raw.return_value = MockResponse(
        status_code=200,
        json_data=mock_json,
        headers={"Content-Range": "offres 0-0/50"},
    )

    service = RomeVolumeMeasurementService(mock_client)

    # Act
    measure = service.measure_single_rome("M1805", "Dév informatique")

    # Assert
    assert measure.first_result_rome_code == "M1802"
    assert measure.first_result_rome_valid is False


def test_measure_single_rome_no_results_valid_none() -> None:
    """Test volume query returning no results yields first_result_rome_valid == None."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client.get_raw.return_value = MockResponse(
        status_code=204,
        json_data=[],
        headers={"Content-Range": "offres 0-0/0"},
    )
    service = RomeVolumeMeasurementService(mock_client)

    # Act
    measure = service.measure_single_rome("M1806", "Test empty")

    # Assert
    assert measure.total_offres_disponibles == 0
    assert measure.http_status == 204
    assert measure.contract_aggregations == {}
    assert measure.first_result_id is None
    assert measure.first_result_rome_code is None
    assert measure.first_result_rome_valid is None


def test_measure_single_rome_http_error() -> None:
    """Test robustness against server or network exception."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client.get_raw.side_effect = requests.RequestException("Network down")
    service = RomeVolumeMeasurementService(mock_client)

    # Act
    measure = service.measure_single_rome("M1805", "Test error")

    # Assert
    assert measure.total_offres_disponibles == 0
    assert measure.http_status == 500
    assert measure.first_result_id is None
    assert measure.first_result_rome_valid is None


def test_measure_rome_volumes_and_export(
    temp_referential_file: Path, tmp_path: Path
) -> None:
    """Test full measurement workflow from referential loading to JSON export."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)

    def mock_get_raw(
        endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> MockResponse:
        params = params or {}
        rome = params.get("codeROME", "M1801")
        if rome == "M1801":
            tot = 150
        elif rome == "M1802":
            tot = 85
        else:
            tot = 4152

        mock_json = {
            "resultats": [{"id": f"ID_{rome}", "romeCode": rome}],
            "filtresPossibles": [
                {
                    "filtre": "typeContrat",
                    "valeurs": [{"valeur": "CDI", "nb": tot}],
                }
            ],
        }
        return MockResponse(
            status_code=206,
            json_data=mock_json,
            headers={"Content-Range": f"offres 0-0/{tot}"},
        )

    mock_client.get_raw.side_effect = mock_get_raw

    service = RomeVolumeMeasurementService(mock_client)
    output_path = tmp_path / "rome_volumes_v1.json"

    # Act
    report = service.measure_rome_volumes(temp_referential_file)
    service.export_report_to_json(report, output_path)

    # Assert
    assert len(report.measures) == 5
    m1801 = next(m for m in report.measures if m.code_rome == "M1801")
    assert m1801.total_offres_disponibles == 150
    assert m1801.contract_aggregations == {"CDI": 150}
    assert m1801.first_result_rome_code == "M1801"

    # Verify exported file is valid UTF-8
    assert output_path.exists()
    with output_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["source"] == "france_travail_api"
    assert len(data["measures"]) == 5
    assert data["measures"][0]["code_rome"] == "M1801"
    assert data["measures"][0]["total_offres_disponibles"] == 150


def test_measure_all_rome_from_file(tmp_path: Path) -> None:
    """Test measure_all_rome_from_file extracts intitule_rome and calls API."""
    # Arrange
    ref_data = {
        "items": [
            {"code_rome": "A1201", "intitule_rome": "Bûcheronnage"},
            {"code_rome": "A1202", "libelle_rome": "Sylviculture"},
        ]
    }
    file_path = tmp_path / "merged_rome.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f, ensure_ascii=False)

    mock_client = MagicMock(spec=FranceTravailClient)

    def mock_get_raw(
        endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> MockResponse:
        params = params or {}
        # Unused variable rome removed
        return MockResponse(
            status_code=206,
            json_data={"resultats": [], "filtresPossibles": []},
            headers={"Content-Range": "offres 0-0/10"},
        )

    mock_client.get_raw.side_effect = mock_get_raw
    # Pour simuler le rate-limit
    mock_client._is_mock_client = True

    service = RomeVolumeMeasurementService(mock_client)

    # Act
    report = service.measure_all_rome_from_file(file_path)

    # Assert
    assert len(report.measures) == 2
    assert report.measures[0].code_rome == "A1201"
    assert report.measures[0].libelle_rome == "Bûcheronnage"
    assert report.measures[1].code_rome == "A1202"
    assert report.measures[1].libelle_rome == "Sylviculture"
