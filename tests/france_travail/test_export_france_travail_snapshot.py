import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Patch PROJECT_ROOT inside the script so it uses tmp_path instead of the real data folder
from scripts.export_france_travail_snapshot import export_snapshot


def mock_row(id_val, intitule, description, entreprise_nom, lieu_code_postal, rome_code):
    return (id_val, intitule, description, entreprise_nom, lieu_code_postal, rome_code)


@pytest.fixture
def mock_db():
    mock_engine = MagicMock()
    mock_connection = MagicMock()
    mock_transaction = MagicMock()

    mock_engine.connect.return_value = mock_connection
    mock_connection.begin.return_value = mock_transaction

    with patch("scripts.export_france_travail_snapshot.engine", mock_engine):
        yield mock_engine, mock_connection, mock_transaction


def test_export_nominal(tmp_path, mock_db):
    mock_session, mock_connection, mock_transaction = mock_db

    # Custom project root path mock
    tmp_project_root = tmp_path / "project_root"
    tmp_project_root.mkdir()

    # Mock data rows (already sorted by ID)
    rows = [
        mock_row("1", "Titre 1", "Desc 1", "E1", "31000", "M1803"),
        mock_row("2", "Titre 2", "Desc 2", None, None, "M1804"),
    ]

    mock_connection.execute.side_effect = [
        None,  # SET TRANSACTION READ ONLY
        rows,  # SELECT query
    ]

    with patch("scripts.export_france_travail_snapshot.PROJECT_ROOT", tmp_project_root):
        export_snapshot()

    # Check files created
    snapshot_path = tmp_project_root / "data" / "processed" / "france_travail" / "snapshots" / "current" / "france_travail_offers_snapshot.json"
    manifest_path = tmp_project_root / "data" / "processed" / "france_travail" / "snapshots" / "current" / "snapshot_manifest.json"

    assert snapshot_path.exists()
    assert manifest_path.exists()

    # Check snapshot content
    offers = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert len(offers) == 2
    assert offers[0]["france_travail_id"] == "1"
    assert offers[0]["company_name"] == "E1"
    assert offers[0]["postal_code"] == "31000"

    # Check nullables
    assert offers[1]["france_travail_id"] == "2"
    assert offers[1]["company_name"] is None
    assert offers[1]["postal_code"] is None

    # Check manifest content
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["rows_exported"] == 2
    assert manifest["distinct_ids"] == 2
    assert manifest["null_ids"] == 0
    assert manifest["duplicate_ids"] == 0

    # Verify transaction management
    mock_connection.begin.assert_called_once()
    mock_transaction.rollback.assert_called_once()
    # Verify no writing commands were executed
    for call in mock_connection.execute.call_args_list:
        query_text = str(call[0][0])
        assert "INSERT" not in query_text.upper()
        assert "UPDATE" not in query_text.upper()
        assert "DELETE" not in query_text.upper()
        assert "CREATE" not in query_text.upper()


def test_export_validation_failures(tmp_path, mock_db):
    mock_session, mock_connection, mock_transaction = mock_db
    tmp_project_root = tmp_path / "project_root"
    tmp_project_root.mkdir()

    # Test cases for failures
    cases = [
        # Empty/None ID
        ([mock_row(None, "Titre", "Desc", "E", "31000", "M1803")], r"Identifiant \(id\) manquant ou nul"),
        # Empty/Blank ID
        ([mock_row("  ", "Titre", "Desc", "E", "31000", "M1803")], r"Identifiant \(id\) vide"),
        # Duplicate ID
        ([mock_row("1", "Titre", "Desc", "E", "31000", "M1803"), mock_row("1", "Titre 2", "Desc 2", "E", "31000", "M1803")], r"Identifiant \(id\) dupliqué"),
        # Empty Title
        ([mock_row("1", "", "Desc", "E", "31000", "M1803")], r"Titre \(intitule\) vide ou absent"),
        # Empty Description
        ([mock_row("1", "Titre", "   ", "E", "31000", "M1803")], "Description vide ou absente"),
        # Empty ROME code
        ([mock_row("1", "Titre", "Desc", "E", "31000", "")], "Code ROME vide ou absent"),
    ]

    for rows, error_match in cases:
        mock_connection.execute.side_effect = [
            None,  # SET TRANSACTION READ ONLY
            rows,  # SELECT query
        ]

        with patch("scripts.export_france_travail_snapshot.PROJECT_ROOT", tmp_project_root):
            with pytest.raises(ValueError, match=error_match):
                export_snapshot()

        # Verify rollback was called even during exception
        mock_transaction.rollback.assert_called()
        mock_transaction.rollback.reset_mock()


def test_export_idempotency(tmp_path, mock_db, capsys):
    mock_session, mock_connection, mock_transaction = mock_db
    tmp_project_root = tmp_path / "project_root"
    tmp_project_root.mkdir()

    rows = [
        mock_row("1", "Titre 1", "Desc 1", "E1", "31000", "M1803"),
    ]

    # First run (creates snapshot)
    mock_connection.execute.side_effect = [
        None,
        rows,
    ]
    with patch("scripts.export_france_travail_snapshot.PROJECT_ROOT", tmp_project_root):
        export_snapshot()
    captured = capsys.readouterr()
    assert "mis à jour" in captured.out

    # Second run with same data (no modifications)
    mock_connection.execute.side_effect = [
        None,
        rows,
    ]
    with patch("scripts.export_france_travail_snapshot.PROJECT_ROOT", tmp_project_root):
        export_snapshot()
    captured = capsys.readouterr()
    assert "inchangé" in captured.out
