"""Tests for the CLI entry point."""

from unittest.mock import MagicMock, patch

import pytest

from observia_emploi.cli import main


@patch("sys.argv", ["cli.py"])
@patch("observia_emploi.cli.FranceTravailClient")
@patch("observia_emploi.cli.Config")
@patch("observia_emploi.cli.RomeReferentialService")
def test_cli_default_uses_real_client_with_config(
    mock_service_class: MagicMock,
    mock_config_class: MagicMock,
    mock_client_class: MagicMock,
) -> None:
    """Test that CLI by default loads configuration and instantiates the real client."""
    # Arrange
    mock_config = MagicMock()
    mock_config_class.return_value = mock_config
    mock_service = MagicMock()
    mock_service_class.return_value = mock_service

    # Act
    main()

    # Assert
    mock_config_class.assert_called_once()
    mock_client_class.assert_called_once_with(mock_config.france_travail)
    mock_service_class.assert_called_once()
    mock_service.fetch_and_filter_rome.assert_called_once()


@patch("sys.argv", ["cli.py", "--offline"])
@patch("observia_emploi.cli.MockFranceTravailClient")
@patch("observia_emploi.cli.RomeReferentialService")
def test_cli_offline_uses_mock_client(
    mock_service_class: MagicMock,
    mock_mock_client_class: MagicMock,
) -> None:
    """Test that CLI with --offline instantiates Mock client and runs successfully."""
    # Arrange
    mock_service = MagicMock()
    mock_service_class.return_value = mock_service

    # Act
    main()

    # Assert
    mock_mock_client_class.assert_called_once()
    mock_service_class.assert_called_once()
    mock_service.fetch_and_filter_rome.assert_called_once()


@patch("sys.argv", ["cli.py"])
@patch("observia_emploi.cli.Config")
def test_cli_missing_config_in_production_exits_with_error(
    mock_config_class: MagicMock,
) -> None:
    """Test that missing config in production mode exits cleanly with error."""
    # Arrange
    mock_config_class.side_effect = ValueError("Missing configuration variables")

    # Act & Assert
    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1


@patch("sys.argv", ["cli.py", "--extract-rome"])
@patch("observia_emploi.cli.RomeExtractorService")
def test_cli_extract_rome_calls_extractor_service(
    mock_extractor_class: MagicMock,
) -> None:
    """Test that --extract-rome flag runs RomeExtractorService and exits cleanly."""
    # Arrange
    mock_extractor = MagicMock()
    mock_extractor_class.return_value = mock_extractor

    # Act
    with pytest.raises(SystemExit) as excinfo:
        main()

    # Assert
    assert excinfo.value.code == 0
    mock_extractor_class.assert_called_once()
    mock_extractor.extract_from_csv.assert_called_once()
    mock_extractor.export_to_json.assert_called_once()
