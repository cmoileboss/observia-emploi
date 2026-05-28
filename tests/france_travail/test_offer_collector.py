"""Tests for France Travail detailed offer collection and Pydantic schemas."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from observia_emploi.france_travail.client import FranceTravailClient, MockResponse
from observia_emploi.france_travail.offer_collector import (
    FranceTravailOfferCollectorService,
)
from observia_emploi.france_travail.schemas import OffreEmploiSchema


def test_offre_emploi_schema_anonymization_and_exclusion() -> None:
    """Test OffreEmploiSchema removes personal details and cleans description."""
    raw_payload = {
        "id": "12345XYZ",
        "intitule": "Développeur Python H/F",
        "description": (
            "Rejoignez-nous! Contact: jean.dupont@societe.fr ou 06 12 34 56 78."
        ),
        "appellationLibelle": "Développeur d'applications",
        "contact": {"nom": "Jean Dupont", "telephone": "0612345678"},
        "agence": {
            "nom": "France Travail Rennes",
            "courriel": "agence@francetravail.fr",
        },
    }

    # Validate
    schema_instance = OffreEmploiSchema.model_validate(raw_payload)

    # Convert to dict
    serialized = schema_instance.model_dump(by_alias=True)

    # Assert clean description is populated and raw description is excluded
    assert "description" not in serialized
    assert serialized.get("description_clean") == (
        "Rejoignez-nous! Contact: [EMAIL MASQUÉ] ou [TÉLÉPHONE MASQUÉ]."
    )

    # Assert contact and agence are fully excluded from serialized output
    assert "contact" not in serialized
    assert "agence" not in serialized

    # Check alias choices logic
    assert serialized.get("appellationLibelle") == "Développeur d'applications"


def test_offre_emploi_schema_alias_choices() -> None:
    """Test appellation_libelle resolves properly with both casing variants."""
    payload_camel = {
        "id": "1",
        "appellationLibelle": "Ingénieur IA",
    }
    payload_lower = {
        "id": "2",
        "appellationlibelle": "Expert Data",
    }

    instance_camel = OffreEmploiSchema.model_validate(payload_camel)
    instance_lower = OffreEmploiSchema.model_validate(payload_lower)

    assert instance_camel.appellation_libelle == "Ingénieur IA"
    assert instance_lower.appellation_libelle == "Expert Data"


def test_offer_collector_pagination_and_rate_limit(tmp_path: Path) -> None:
    """Test collector aggregates results, paginates properly, and exits on 204."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client._is_mock_client = True  # Avoid time.sleep during tests

    ref_data = {
        "items": [
            {"code_rome": "M1805", "intitule_rome": "Dév"},
        ]
    }
    ref_file = tmp_path / "merged_rome.json"
    with ref_file.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f)

    def mock_get_raw(
        endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> MockResponse:
        params = params or {}
        range_str = params.get("range", "0-149")

        # Simuler 2 pages
        if range_str == "0-149":
            results = [{"id": f"ID_{i}"} for i in range(150)]
            return MockResponse(
                status_code=206,
                json_data={"resultats": results},
                headers={"Content-Range": "offres 0-149/200"},
            )
        elif range_str == "150-299":
            results = [{"id": f"ID_{i}"} for i in range(150, 200)]
            return MockResponse(
                status_code=200,
                json_data={"resultats": results},
                headers={"Content-Range": "offres 150-199/200"},
            )
        else:
            return MockResponse(
                status_code=204,
                json_data=[],
                headers={"Content-Range": "offres 200-200/200"},
            )

    mock_client.get_raw.side_effect = mock_get_raw
    service = FranceTravailOfferCollectorService(mock_client)

    # Act
    payload = service.collect_all_offers_from_file(ref_file)

    # Assert
    assert payload["offers_count"] == 200
    assert len(payload["offers"]) == 200
    assert payload["offers"][0]["id"] == "ID_0"
    assert payload["offers"][199]["id"] == "ID_199"


def test_offer_collector_resilience_to_errors(tmp_path: Path) -> None:
    """Test collector continues execution and handles API errors gracefully."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client._is_mock_client = True

    ref_data = {
        "items": [
            {"code_rome": "M1805", "intitule_rome": "Dév"},
            {"code_rome": "M1802", "intitule_rome": "Expertise"},
        ]
    }
    ref_file = tmp_path / "merged_rome.json"
    with ref_file.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f)

    def mock_get_raw(
        endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> MockResponse:
        params = params or {}
        rome = params.get("codeROME")
        if rome == "M1805":
            # Simulation of pagination limit / range error on M1805
            return MockResponse(status_code=416, json_data={})
        else:
            # Nominal path for M1802
            return MockResponse(
                status_code=200,
                json_data={"resultats": [{"id": "NOMINAL_OFFRE"}]},
                headers={"Content-Range": "offres 0-0/1"},
            )

    mock_client.get_raw.side_effect = mock_get_raw
    service = FranceTravailOfferCollectorService(mock_client)

    # Act
    payload = service.collect_all_offers_from_file(ref_file)

    # Assert
    assert payload["offers_count"] == 1
    assert payload["offers"][0]["id"] == "NOMINAL_OFFRE"


def test_offer_collector_max_pages(tmp_path: Path) -> None:
    """Test that max_pages controls the page loops for a single code ROME."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client._is_mock_client = True

    ref_data = {
        "items": [
            {"code_rome": "M1805", "intitule_rome": "Dév"},
        ]
    }
    ref_file = tmp_path / "merged_rome.json"
    with ref_file.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f)

    calls = []

    def mock_get_raw(
        endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> MockResponse:
        params = params or {}
        range_str = params.get("range")
        calls.append(range_str)
        return MockResponse(
            status_code=206,
            json_data={"resultats": [{"id": f"ID_{range_str}"} for _ in range(150)]},
            headers={"Content-Range": "offres 0-149/1000"},
        )

    mock_client.get_raw.side_effect = mock_get_raw
    service = FranceTravailOfferCollectorService(mock_client)

    # Act
    payload = service.collect_all_offers_from_file(ref_file, max_pages=1)

    # Assert
    assert len(calls) == 1
    assert calls[0] == "0-149"
    assert payload["offers_count"] == 150


def test_offer_collector_rome_code_filter(tmp_path: Path) -> None:
    """Test that specifying rome_code limits the collection to that single code."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client._is_mock_client = True

    ref_data = {
        "items": [
            {"code_rome": "M1805", "intitule_rome": "Dév"},
            {"code_rome": "M1802", "intitule_rome": "Expertise"},
        ]
    }
    ref_file = tmp_path / "merged_rome.json"
    with ref_file.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f)

    codes_requested = []

    def mock_get_raw(
        endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> MockResponse:
        params = params or {}
        codes_requested.append(params.get("codeROME"))
        return MockResponse(
            status_code=200,
            json_data={"resultats": []},
            headers={"Content-Range": "offres 0-0/0"},
        )

    mock_client.get_raw.side_effect = mock_get_raw
    service = FranceTravailOfferCollectorService(mock_client)

    # Act
    service.collect_all_offers_from_file(ref_file, rome_code="M1802")

    # Assert
    assert len(codes_requested) == 1
    assert codes_requested[0] == "M1802"


def test_offer_collector_max_codes(tmp_path: Path) -> None:
    """Test that max_codes limits the number of ROME codes treated."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client._is_mock_client = True

    ref_data = {
        "items": [
            {"code_rome": "M1805", "intitule_rome": "Dév"},
            {"code_rome": "M1802", "intitule_rome": "Expertise"},
            {"code_rome": "M1801", "intitule_rome": "Admin"},
        ]
    }
    ref_file = tmp_path / "merged_rome.json"
    with ref_file.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f)

    codes_requested = []

    def mock_get_raw(
        endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> MockResponse:
        params = params or {}
        codes_requested.append(params.get("codeROME"))
        return MockResponse(
            status_code=200,
            json_data={"resultats": []},
            headers={"Content-Range": "offres 0-0/0"},
        )

    mock_client.get_raw.side_effect = mock_get_raw
    service = FranceTravailOfferCollectorService(mock_client)

    # Act
    service.collect_all_offers_from_file(ref_file, max_codes=2)

    # Assert
    assert len(codes_requested) == 2
    assert codes_requested == ["M1805", "M1802"]
