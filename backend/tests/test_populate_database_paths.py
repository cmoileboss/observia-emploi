"""."""
from pathlib import Path

from backend.scripts import francetravail_api_call
from backend.scripts import import_formations_enriched


def test_formations_csv_path_does_not_depend_on_working_directory(
    monkeypatch,
):
    """."""
    expected_path = (
        Path(import_formations_enriched.__file__).resolve().parents[1]
        / "data"
        / "processed"
        / "formations_enriched.csv"
    )
    monkeypatch.chdir(expected_path.parents[2])

    assert import_formations_enriched.resolve_csv_path() == expected_path
    assert francetravail_api_call.resolve_csv_path() == expected_path
