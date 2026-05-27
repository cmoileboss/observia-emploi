"""Tests for the ROME referential service."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from observia_emploi.france_travail.client import FranceTravailClient
from observia_emploi.france_travail.referential import RomeReferentialService


def test_fetch_and_filter_rome_filtering() -> None:
    """Test that the service correctly filters ROME codes."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    mock_client.get.return_value = [
        {"code": "M1805", "libelle": "Développeur"},
        {"code": "M1802", "libelle": "Expert IT"},
        {"code": "A1201", "libelle": "Bûcheron"},
    ]

    service = RomeReferentialService(mock_client)
    validated_codes = {"M1805", "M1802"}

    # Act
    filtered_metiers = service.fetch_and_filter_rome(validated_codes)

    # Assert
    assert len(filtered_metiers) == 2
    assert {m.code_rome for m in filtered_metiers} == validated_codes
    assert all(m.validated for m in filtered_metiers)
    mock_client.get.assert_called_once_with("partenaire/rome/v1/metiers")


def test_export_to_json(tmp_path: Path) -> None:
    """Test that the service exports filtered ROME codes to JSON correctly."""
    # Arrange
    mock_client = MagicMock(spec=FranceTravailClient)
    service = RomeReferentialService(mock_client)

    validated_codes = {"M1805"}
    mock_client.get.return_value = [
        {"code": "M1805", "libelle": "Développeur"},
    ]
    filtered_metiers = service.fetch_and_filter_rome(validated_codes)
    output_file = tmp_path / "data" / "processed" / "rome_export.json"

    # Act
    service.export_to_json(filtered_metiers, output_file)

    # Assert
    assert output_file.exists()

    with output_file.open(encoding="utf-8") as f:
        data = json.load(f)

    assert data["source"] == "France Travail ROME"
    assert data["count"] == 1
    assert len(data["metiers"]) == 1
    assert data["metiers"][0]["code_rome"] == "M1805"
    assert data["metiers"][0]["libelle"] == "Développeur"
    assert data["metiers"][0]["validated"] is True
    assert "extracted_at" in data
