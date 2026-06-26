import json
from unittest.mock import MagicMock, patch

import pytest

import backend.scripts.export_france_travail_snapshot as snapshot_module
from backend.scripts.export_france_travail_snapshot import export_snapshot


def mock_row(
    francetravail_id,
    intitule,
    description,
    entreprise_nom,
    lieu_code_postal,
    rome_code,
):
    return {
        "francetravail_id": francetravail_id,
        "intitule": intitule,
        "description": description,
        "entreprise_nom": entreprise_nom,
        "lieu_code_postal": lieu_code_postal,
        "rome_code": rome_code,
    }


@pytest.fixture
def mock_db():
    mock_engine = MagicMock()
    mock_connection = MagicMock()
    mock_transaction = MagicMock()

    mock_engine.connect.return_value = mock_connection
    mock_connection.begin.return_value = mock_transaction

    with patch("backend.scripts.export_france_travail_snapshot.engine", mock_engine):
        yield mock_engine, mock_connection, mock_transaction


def _run_export(tmp_path, rows):
    processed_data_root = tmp_path / "backend" / "data" / "processed"
    with patch.object(snapshot_module, "PROCESSED_DATA_ROOT", processed_data_root):
        export_snapshot()

    snapshot_path = processed_data_root / "france_travail" / "snapshots" / "current" / "france_travail_offers_snapshot.json"
    manifest_path = processed_data_root / "france_travail" / "snapshots" / "current" / "snapshot_manifest.json"
    return snapshot_path, manifest_path


def test_export_reads_public_offres_with_read_only_filter_and_mapping(tmp_path, mock_db):
    _, mock_connection, mock_transaction = mock_db
    rows = [
        mock_row("FT-1", "Titre 1", "Desc 1", "Entreprise 1", "31000", "M1803"),
        mock_row("FT-2", "Titre 2", "Desc 2", None, None, "M1804"),
    ]
    mock_connection.execute.side_effect = [None, rows]

    snapshot_path, manifest_path = _run_export(tmp_path, rows)

    assert snapshot_path.exists()
    assert manifest_path.exists()
    assert not (tmp_path / "data").exists()

    offers = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert offers == [
        {
            "france_travail_id": "FT-1",
            "title": "Titre 1",
            "description": "Desc 1",
            "company_name": "Entreprise 1",
            "postal_code": "31000",
            "work_place_name": None,
            "rome_code": "M1803",
        },
        {
            "france_travail_id": "FT-2",
            "title": "Titre 2",
            "description": "Desc 2",
            "company_name": None,
            "postal_code": None,
            "work_place_name": None,
            "rome_code": "M1804",
        },
    ]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_table"] == "public.offres"
    assert manifest["source_filter"] == "francetravail_id IS NOT NULL"
    assert manifest["source_order_by"] == "francetravail_id"
    assert manifest["transaction_mode"] == "READ ONLY"
    assert manifest["rows_exported"] == 2
    assert manifest["distinct_ids"] == 2
    assert manifest["duplicate_ids"] == 0
    assert manifest["freework_rows_exported"] == 0
    assert manifest["missing_optional_counts"] == {
        "company_name": 1,
        "postal_code": 1,
        "work_place_name": 2,
    }

    mock_connection.begin.assert_called_once()
    mock_transaction.rollback.assert_called_once()

    executed_queries = [str(call.args[0]) for call in mock_connection.execute.call_args_list]
    assert "SET TRANSACTION READ ONLY" in executed_queries[0]
    assert "FROM public.offres" in executed_queries[1]
    assert "WHERE francetravail_id IS NOT NULL" in executed_queries[1]
    assert "ORDER BY francetravail_id" in executed_queries[1]
    assert "francetravail_offres" not in executed_queries[1]
    for query_text in executed_queries:
        upper_query = query_text.upper()
        assert "INSERT" not in upper_query
        assert "UPDATE" not in upper_query
        assert "DELETE" not in upper_query
        assert "CREATE" not in upper_query


def test_export_rejects_duplicate_france_travail_ids(tmp_path, mock_db):
    _, mock_connection, mock_transaction = mock_db
    rows = [
        mock_row("FT-1", "Titre 1", "Desc 1", "Entreprise", "31000", "M1803"),
        mock_row("FT-1", "Titre 2", "Desc 2", "Entreprise", "31000", "M1803"),
    ]
    mock_connection.execute.side_effect = [None, rows]

    with patch.object(snapshot_module, "PROCESSED_DATA_ROOT", tmp_path / "backend" / "data" / "processed"):
        with pytest.raises(ValueError, match="francetravail_id duplique detecte"):
            export_snapshot()

    mock_transaction.rollback.assert_called_once()
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "row,error_match",
    [
        (mock_row(None, "Titre", "Desc", "Entreprise", "31000", "M1803"), "Identifiant France Travail manquant"),
        (mock_row("   ", "Titre", "Desc", "Entreprise", "31000", "M1803"), "francetravail_id.*vide"),
        (mock_row("FT-1", "", "Desc", "Entreprise", "31000", "M1803"), "intitule.*vide"),
        (mock_row("FT-1", "Titre", "   ", "Entreprise", "31000", "M1803"), "description.*vide"),
        (mock_row("FT-1", "Titre", "Desc", "Entreprise", "31000", ""), "rome_code.*vide"),
    ],
)
def test_export_rejects_missing_required_fields(tmp_path, mock_db, row, error_match):
    _, mock_connection, mock_transaction = mock_db
    mock_connection.execute.side_effect = [None, [row]]

    with patch.object(snapshot_module, "PROCESSED_DATA_ROOT", tmp_path / "backend" / "data" / "processed"):
        with pytest.raises(ValueError, match=error_match):
            export_snapshot()

    mock_transaction.rollback.assert_called_once()
    assert not (tmp_path / "data").exists()


def test_export_idempotency(tmp_path, mock_db, capsys):
    _, mock_connection, _ = mock_db
    rows = [
        mock_row("FT-1", "Titre 1", "Desc 1", "Entreprise 1", "31000", "M1803"),
    ]

    mock_connection.execute.side_effect = [None, rows]
    _run_export(tmp_path, rows)
    captured = capsys.readouterr()
    assert "updated" in captured.out

    mock_connection.execute.side_effect = [None, rows]
    _run_export(tmp_path, rows)
    captured = capsys.readouterr()
    assert "unchanged" in captured.out
