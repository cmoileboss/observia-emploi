"""Tests for the ROME referential service."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from observia_emploi.france_travail.client import FranceTravailClient
from observia_emploi.france_travail.referential import RomeReferentialService


def test_referential_fetching_filtering_and_export_success(tmp_path: Path) -> None:
    """Test successful fetching, filtering, and JSON export logic."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client.get.return_value = [
        {"code": "M1801", "libelle": "Admin SI"},
        {"code": "M1802", "libelle": "Expert technique SI"},
        {"code": "M1805", "libelle": "Dév informatique"},
        {"code": "A1201", "libelle": "Sylviculteur"},
    ]

    service = RomeReferentialService(mock_client)
    requested_codes = ["M1801", "M1802", "M1805", "M1806", "M1810"]
    output_file = tmp_path / "processed" / "reference" / "rome_metiers_v1.json"

    # Act
    export_data = service.fetch_and_filter_rome(
        requested_codes=requested_codes,
        scope="v1_test_tech_ia",
    )
    service.export_to_json(export_data, output_file)

    # Assert
    mock_client.get.assert_called_once_with(
        "partenaire/offresdemploi/v2/referentiel/metiers"
    )

    # Verify filtering metadata results
    assert len(export_data.items) == 3
    assert export_data.selection.rome_codes_found == ["M1801", "M1802", "M1805"]
    assert export_data.selection.rome_codes_missing == ["M1806", "M1810"]

    # Verify generated JSON file content and structure
    assert output_file.exists()
    with output_file.open(encoding="utf-8") as f:
        data = json.load(f)

    assert data["source"] == "france_travail_api"
    assert data["dataset"] == "referentiel_metiers_rome"
    assert "generated_at" in data
    assert data["selection"]["scope"] == "v1_test_tech_ia"
    assert data["selection"]["rome_codes_requested"] == requested_codes
    assert data["selection"]["rome_codes_found"] == ["M1801", "M1802", "M1805"]
    assert data["selection"]["rome_codes_missing"] == ["M1806", "M1810"]

    assert len(data["items"]) == 3
    assert data["items"][0]["code_rome"] == "M1801"
    assert data["items"][0]["libelle_rome"] == "Admin SI"
    assert data["items"][0]["source_api"] == "france_travail"
    assert data["items"][0]["is_selected_for_v1"] is True
    assert data["items"][0]["theme"] == "tech"


def test_referential_handling_http_error() -> None:
    """Test that HTTP errors from the client are raised correctly."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client.get.side_effect = requests.exceptions.HTTPError("API error")
    service = RomeReferentialService(mock_client)

    # Act & Assert
    with pytest.raises(requests.exceptions.HTTPError, match="API error"):
        service.fetch_and_filter_rome(["M1805"])


def test_referential_handling_invalid_json() -> None:
    """Test that unexpected non-list responses raise a ValueError."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client.get.return_value = {"error": "unexpected format"}
    service = RomeReferentialService(mock_client)

    # Act & Assert
    with pytest.raises(ValueError, match="Unexpected response format"):
        service.fetch_and_filter_rome(["M1805"])
