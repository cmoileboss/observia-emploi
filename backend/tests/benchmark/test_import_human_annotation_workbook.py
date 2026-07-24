"""Tests du script de réimportation des classeurs d'annotation."""

from unittest.mock import patch

import backend.scripts.import_human_annotation_workbook as script_module
from backend.scripts.import_human_annotation_workbook import (
    run_workbook_import,
)


def test_workbook_import_reads_inputs_and_writes_validated_csv(tmp_path):
    template_path = tmp_path / "template.csv"
    workbook_path = tmp_path / "annotations.xlsx"
    output_path = tmp_path / "annotations.csv"
    template_path.write_bytes(b"template")
    workbook_path.write_bytes(b"workbook")
    completed_csv = b"\xef\xbb\xbfpair_id,score\n"

    with patch.object(
        script_module,
        "import_workbook_annotations",
        return_value=completed_csv,
    ) as import_mock:
        byte_count = run_workbook_import(
            template_path,
            workbook_path,
            output_path,
        )

    import_mock.assert_called_once_with(b"template", b"workbook")
    assert output_path.read_bytes() == completed_csv
    assert byte_count == len(completed_csv)
