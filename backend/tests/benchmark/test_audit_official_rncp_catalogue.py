"""Tests du point d'entrée du diagnostic RNCP officiel."""

from types import SimpleNamespace
from unittest.mock import patch

import backend.scripts.audit_official_rncp_catalogue as script_module


def test_run_audit_orchestrates_read_only_catalogue_and_temporary_archive(tmp_path):
    catalogue = SimpleNamespace(
        certifications=[
            SimpleNamespace(code_rncp="37674"),
            SimpleNamespace(code_rncp="RNCP100"),
        ]
    )
    metadata = {"id": "dataset-1", "resources": []}
    resource = SimpleNamespace(schema_version="4.1")
    parse_result = SimpleNamespace(version_flux="4.1")
    expected_report = SimpleNamespace(nombre_codes_locaux=2)
    archive_path = tmp_path / "official-rncp.zip"

    with (
        patch.object(script_module, "SCRATCH_ROOT", tmp_path),
        patch.object(script_module, "load_rncp_catalogue", return_value=catalogue),
        patch.object(
            script_module,
            "fetch_official_dataset_metadata",
            return_value=metadata,
        ),
        patch.object(
            script_module,
            "discover_current_rncp_resource",
            return_value=resource,
        ),
        patch.object(
            script_module,
            "download_official_rncp_archive",
            return_value=archive_path,
        ) as download_mock,
        patch.object(
            script_module,
            "parse_official_rncp_archive",
            return_value=parse_result,
        ) as parse_mock,
        patch.object(
            script_module,
            "calculate_official_rncp_audit",
            return_value=expected_report,
        ) as calculate_mock,
    ):
        report = script_module.run_official_rncp_audit()

    assert report is expected_report
    temporary_directory = download_mock.call_args.args[1]
    assert temporary_directory.parent == tmp_path
    parse_mock.assert_called_once_with(
        archive_path,
        ("37674", "RNCP100"),
        "4.1",
    )
    calculate_mock.assert_called_once_with(
        ("37674", "RNCP100"),
        parse_result,
        resource,
    )
