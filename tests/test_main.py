"""Unit tests for the main.py orchestrator."""

from pathlib import Path
from unittest.mock import patch

import pytest

from main import main


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """Set up temporary project directories with a dummy CSV file."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "data" / "processed" / "offers").mkdir(parents=True)
    (tmp_path / "data" / "reference").mkdir(parents=True)
    csv_file = tmp_path / "data" / "processed" / "merged_data.csv"
    csv_file.write_text("dummy")
    return tmp_path


@patch("sys.argv", ["main.py"])
def test_main_default_noop():
    """Default invocation (no flags) must not regenerate CSV or call services."""
    main()


@patch(
    "sys.argv",
    ["main.py", "--france-travail-offers", "--offline", "--max-pages", "1"],
)
@patch("main.FranceTravailOfferCollectorService")
@patch("main.RomeExtractorService")
def test_main_france_travail_offline(mock_rome, mock_offer, tmp_project):
    """--france-travail-offers --offline uses merged_data.csv without calling
    CsvExtractor, then runs ROME extraction and grouped collection."""
    main()
    mock_rome.return_value.extract_from_csv.assert_called_once()
    mock_offer.return_value.collect_all_offers_grouped_from_file.assert_called_once()


@patch(
    "sys.argv",
    ["main.py", "--france-travail-offers", "--rome-code", "M1805", "--max-pages", "1"],
)
@patch("main.FranceTravailOfferCollectorService")
@patch("main.RomeExtractorService")
@patch("main.Config")
def test_main_france_travail_with_rome_code(
    mock_config, mock_rome, mock_offer, tmp_project
):
    """--rome-code M1805 is passed through to the grouped collector."""
    main()
    mock_offer.return_value.collect_all_offers_grouped_from_file.assert_called_once_with(
        Path("data/reference/rome_codes_from_merged_data.json"),
        rome_code="M1805",
        max_pages=1,
        max_codes=None,
    )


@patch("sys.argv", ["main.py", "--france-travail-offers"])
@patch("main.RomeExtractorService")
def test_main_france_travail_no_max_pages(mock_rome, tmp_project):
    """Guard: --france-travail-offers without --max-pages or
    --confirm-full-collection must exit 1."""
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1


@patch(
    "sys.argv",
    ["main.py", "--france-travail-offers", "--confirm-full-collection"],
)
@patch("main.FranceTravailOfferCollectorService")
@patch("main.RomeExtractorService")
@patch("main.Config")
def test_main_france_travail_with_confirm(
    mock_config, mock_rome, mock_offer, tmp_project
):
    """--confirm-full-collection bypasses the guard and runs the pipeline."""
    main()
    mock_rome.return_value.extract_from_csv.assert_called_once()
    mock_offer.return_value.collect_all_offers_grouped_from_file.assert_called_once()


@patch(
    "sys.argv",
    [
        "main.py",
        "--france-travail-offers",
        "--refresh-rome-reference",
        "--max-pages",
        "1",
    ],
)
@patch("main.FranceTravailOfferCollectorService")
@patch("main.RomeExtractorService")
@patch("main.Config")
def test_main_refresh_rome(mock_config, mock_rome, mock_offer, tmp_project):
    """--refresh-rome-reference forces RomeExtractorService even if file exists."""
    main()
    mock_rome.return_value.extract_from_csv.assert_called_once()


@patch(
    "sys.argv",
    ["main.py", "--france-travail-offers", "--max-pages", "1"],
)
@patch("main.FranceTravailOfferCollectorService")
@patch("main.Config")
def test_main_reuse_rome_reference(mock_config, mock_offer, tmp_project):
    """When rome_codes_from_merged_data.json already exists and
    --refresh-rome-reference is absent, RomeExtractorService is NOT called."""
    ref_dir = tmp_project / "data" / "reference"
    ref_file = ref_dir / "rome_codes_from_merged_data.json"
    ref_file.write_text('{"items": []}')

    with patch("main.RomeExtractorService") as mock_rome:
        main()
        mock_rome.return_value.extract_from_csv.assert_not_called()


@patch(
    "sys.argv",
    ["main.py", "--france-travail-offers"],
)
def test_main_france_travail_missing_csv(tmp_path, monkeypatch):
    """Without merged_data.csv, --france-travail-offers must exit 1."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1


@patch(
    "sys.argv",
    ["main.py", "--france-travail-offers", "--max-pages", "1"],
)
@patch("main.RomeExtractorService")
@patch("main.Config", side_effect=ValueError("Missing configuration"))
def test_main_no_config(mock_config, mock_rome, tmp_project):
    """Without --offline and without .env config, --france-travail-offers exits 1."""
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1


def test_main_direct_execution_without_pythonpath() -> None:
    """Verify main.py can be launched directly without PYTHONPATH set.

    Runs main.py --help as a subprocess with PYTHONPATH stripped from the
    environment. Asserts exit code 0 and absence of ModuleNotFoundError.
    """
    import os
    import subprocess
    import sys as sys_module

    main_py = Path(__file__).parent.parent / "main.py"
    assert main_py.exists(), f"main.py not found at {main_py}"

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    result = subprocess.run(
        [sys_module.executable, str(main_py), "--help"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, (
        f"main.py --help exited with code {result.returncode}\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert (
        "ModuleNotFoundError" not in result.stderr
    ), f"ModuleNotFoundError in stderr:\n{result.stderr}"
    assert (
        "No module named" not in result.stderr
    ), f"Import error in stderr:\n{result.stderr}"
