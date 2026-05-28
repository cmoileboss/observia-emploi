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


def test_offer_collector_datetime_serialization_non_regression(tmp_path: Path) -> None:
    """Test datetime serialization to ISO strings and exclusions."""
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

    raw_offer = {
        "id": "OFFRE_DATE_TEST",
        "intitule": "Ingénieur",
        "description": "Contact: contact@test.com ou 06 11 22 33 44.",
        "dateCreation": "2026-05-28T14:38:25.000Z",
        "dateActualisation": "2026-05-28T14:39:12.000Z",
        "contact": {"email": "contact@test.com"},
        "agence": {"courriel": "agence@test.com"},
        "formations": None,  # Optional absent field
    }

    mock_client.get_raw.return_value = MockResponse(
        status_code=200,
        json_data={"resultats": [raw_offer]},
        headers={"Content-Range": "offres 0-0/1"},
    )

    service = FranceTravailOfferCollectorService(mock_client)
    output_json = tmp_path / "exported_offers.json"

    # Act
    payload = service.collect_all_offers_from_file(ref_file)
    # Asserts that this does not raise TypeError (not JSON serializable)
    service.export_offers_to_json(payload, output_json)

    # Assert
    assert output_json.exists()
    with output_json.open("r", encoding="utf-8") as f:
        exported_data = json.load(f)

    offer = exported_data["offers"][0]
    # Check that dates are serialized as strings
    assert isinstance(offer.get("dateCreation"), str)
    assert offer.get("dateCreation").startswith("2026-05-28")
    assert isinstance(offer.get("dateActualisation"), str)

    # Check exclusions and clean field
    assert "description" not in offer
    assert "contact" not in offer
    assert "agence" not in offer
    assert offer.get("description_clean") == (
        "Contact: [EMAIL MASQUÉ] ou [TÉLÉPHONE MASQUÉ]."
    )

    # Check optional fields are preserved as null or default lists
    assert "formations" in offer
    assert offer["formations"] is None  # Preserved as null instead of disappearing


def test_collect_all_offers_grouped_structure(tmp_path: Path) -> None:
    """Test grouped payload structure: keys code_rome, intitule_rome,
    offers_count, offers, input_csv, rome_reference_file."""
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client._is_mock_client = True

    ref_data = {
        "items": [
            {"code_rome": "M1805", "intitule_rome": "Développement informatique"},
        ]
    }
    ref_file = tmp_path / "merged_rome.json"
    with ref_file.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f)

    mock_client.get_raw.return_value = MockResponse(
        status_code=200,
        json_data={"resultats": [{"id": "OFFRE_1"}]},
        headers={"Content-Range": "offres 0-0/1"},
    )

    service = FranceTravailOfferCollectorService(mock_client)

    payload = service.collect_all_offers_grouped_from_file(
        ref_file, input_csv="data/processed/merged_data.csv"
    )

    assert payload["source"] == "france_travail_api"
    assert payload["dataset"] == "offres_par_code_rome"
    assert "generated_at" in payload
    assert payload["input_csv"] == "data/processed/merged_data.csv"
    assert payload["rome_reference_file"] == str(ref_file)
    assert payload["total_rome_codes"] == 1
    assert len(payload["items"]) == 1

    group = payload["items"][0]
    assert group["code_rome"] == "M1805"
    assert group["intitule_rome"] == "Développement informatique"
    assert group["offers_count"] == 1
    assert len(group["offers"]) == 1
    assert group["offers"][0]["id"] == "OFFRE_1"


def test_collect_all_offers_grouped_multiple_romes(tmp_path: Path) -> None:
    """Test that 2 ROME codes produce 2 groups with offers split across them."""
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client._is_mock_client = True

    ref_data = {
        "items": [
            {"code_rome": "M1805", "intitule_rome": "Développement"},
            {"code_rome": "M1802", "intitule_rome": "Expertise technique"},
        ]
    }
    ref_file = tmp_path / "merged_rome.json"
    with ref_file.open("w", encoding="utf-8") as f:
        json.dump(ref_data, f)

    def mock_get_raw(
        endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> MockResponse:
        params = params or {}
        rome = params.get("codeROME", "M1805")
        if rome == "M1805":
            return MockResponse(
                status_code=200,
                json_data={
                    "resultats": [
                        {"id": "M1805_OFFRE"},
                        {"id": "M1805_OFFRE_2"},
                    ]
                },
                headers={"Content-Range": "offres 0-1/2"},
            )
        else:
            return MockResponse(
                status_code=200,
                json_data={"resultats": [{"id": "M1802_OFFRE"}]},
                headers={"Content-Range": "offres 0-0/1"},
            )

    mock_client.get_raw.side_effect = mock_get_raw
    service = FranceTravailOfferCollectorService(mock_client)

    payload = service.collect_all_offers_grouped_from_file(ref_file)

    assert payload["total_rome_codes"] == 2
    assert len(payload["items"]) == 2

    m1805_group = next(g for g in payload["items"] if g["code_rome"] == "M1805")
    assert m1805_group["intitule_rome"] == "Développement"
    assert m1805_group["offers_count"] == 2
    assert len(m1805_group["offers"]) == 2

    m1802_group = next(g for g in payload["items"] if g["code_rome"] == "M1802")
    assert m1802_group["intitule_rome"] == "Expertise technique"
    assert m1802_group["offers_count"] == 1
    assert len(m1802_group["offers"]) == 1


def test_collect_all_offers_grouped_filters(tmp_path: Path) -> None:
    """Test that rome_code and max_codes filters work on grouped collection."""
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client._is_mock_client = True

    ref_data = {
        "items": [
            {"code_rome": "M1805", "intitule_rome": "Développement"},
            {"code_rome": "M1802", "intitule_rome": "Expertise"},
            {"code_rome": "M1801", "intitule_rome": "Administration"},
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
            json_data={"resultats": [{"id": f"OFFRE_{params.get('codeROME')}"}]},
            headers={"Content-Range": "offres 0-0/1"},
        )

    mock_client.get_raw.side_effect = mock_get_raw
    service = FranceTravailOfferCollectorService(mock_client)

    payload = service.collect_all_offers_grouped_from_file(ref_file, rome_code="M1802")

    assert payload["total_rome_codes"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["code_rome"] == "M1802"
    assert len(codes_requested) == 1
    assert codes_requested[0] == "M1802"

    payload2 = service.collect_all_offers_grouped_from_file(ref_file, max_codes=2)

    assert payload2["total_rome_codes"] == 2
    codes_in_payload2 = [g["code_rome"] for g in payload2["items"]]
    assert codes_in_payload2 == ["M1805", "M1802"]
