"""Unit tests for the RomeExtractorService in referentials."""

import json
from pathlib import Path

import pytest

from observia_emploi.referentials.rome_extractor import (
    RomeExtractedExport,
    RomeExtractorService,
)


@pytest.fixture
def temp_csv_file(tmp_path: Path) -> Path:
    """Create a temporary valid merged_data.csv for testing."""
    csv_content = (
        "annee;mois;code_rncp;intitule_certification;entrees_formation;"
        "sorties_realisation_partielle;sorties_realisation_totale;code_rome;"
        "intitule_rome;niveau_rncp\n"
        "2025;2;37674;TP Développeur web;10;2;1;M1805;"
        "Études et développement informatique;NIV5\n"
        "2025;9;38862;Licence Pro;5;0;3;K1102;Aide aux bénéficiaires;NIV6\n"
        "2025;9;37674;TP Développeur web;4;1;2;M1805;"
        "Études et développement informatique;NIV5\n"
        "2025;9;39261;Concepteur;0;0;0;M1805;"
        "Études et développement informatique;NIV6\n"
    )
    file_path = tmp_path / "temp_merged_data.csv"
    file_path.write_text(csv_content, encoding="utf-8")
    return file_path


@pytest.fixture
def temp_invalid_csv_file(tmp_path: Path) -> Path:
    """Create a temporary invalid CSV (missing required headers)."""
    csv_content = (
        "annee;mois;code_rncp;intitule_certification;entrees_formation;code_rome\n"
        "2025;2;37674;TP Développeur;10;M1805\n"
    )
    file_path = tmp_path / "temp_invalid_data.csv"
    file_path.write_text(csv_content, encoding="utf-8")
    return file_path


def test_extract_from_csv_success(temp_csv_file: Path) -> None:
    """Test successful extraction and aggregation of ROME codes from a valid CSV."""
    service = RomeExtractorService()
    export = service.extract_from_csv(temp_csv_file)

    assert isinstance(export, RomeExtractedExport)
    assert export.total_unique_rome_codes == 2
    assert export.source == "merged_data.csv"
    assert export.dataset == "rome_codes_from_training_mapping"

    # Items should be sorted by code_rome
    assert export.items[0].code_rome == "K1102"
    assert export.items[0].intitule_rome == "Aide aux bénéficiaires"
    assert export.items[0].rncp_count == 1
    assert export.items[0].total_entrees_formation == 5
    assert export.items[0].total_sorties_realisation_partielle == 0
    assert export.items[0].total_sorties_realisation_totale == 3

    assert export.items[1].code_rome == "M1805"
    assert export.items[1].intitule_rome == "Études et développement informatique"
    # M1805 has RNCP codes: 37674 and 39261 -> unique count of 2
    assert export.items[1].rncp_count == 2
    # M1805 total entries: 10 + 4 + 0 = 14
    assert export.items[1].total_entrees_formation == 14
    # M1805 total partial: 2 + 1 + 0 = 3
    assert export.items[1].total_sorties_realisation_partielle == 3
    # M1805 total total: 1 + 2 + 0 = 3
    assert export.items[1].total_sorties_realisation_totale == 3


def test_extract_from_csv_missing_file() -> None:
    """Test that extractor raises FileNotFoundError if CSV file is missing."""
    service = RomeExtractorService()
    with pytest.raises(FileNotFoundError):
        service.extract_from_csv(Path("non_existent_file.csv"))


def test_extract_from_csv_missing_columns(temp_invalid_csv_file: Path) -> None:
    """Test that extractor raises ValueError when required columns are missing."""
    service = RomeExtractorService()
    with pytest.raises(ValueError, match="Missing required CSV column"):
        service.extract_from_csv(temp_invalid_csv_file)


def test_export_to_json(temp_csv_file: Path, tmp_path: Path) -> None:
    """Test exporting extracted data to a lightweight JSON file with proper encoding."""
    service = RomeExtractorService()
    export = service.extract_from_csv(temp_csv_file)

    output_json = tmp_path / "rome_reference.json"
    service.export_to_json(export, output_json)

    assert output_json.exists()

    # Load and verify JSON structure and UTF-8 encoding
    with output_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["total_unique_rome_codes"] == 2
    assert data["source"] == "merged_data.csv"
    assert data["items"][0]["code_rome"] == "K1102"
    assert (
        data["items"][0]["intitule_rome"] == "Aide aux bénéficiaires"
    )  # accent preserved
