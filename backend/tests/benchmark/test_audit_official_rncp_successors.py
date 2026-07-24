"""Tests du point d'entrée du diagnostic des successeurs RNCP."""

from types import SimpleNamespace
from unittest.mock import patch

import backend.scripts.audit_official_rncp_successors as script_module


def test_orchestration_downloads_official_archive_once(tmp_path):
    catalogue = SimpleNamespace(
        certifications=[SimpleNamespace(code_rncp="RNCP100")]
    )
    metadata = {"id": "dataset-1", "resources": []}
    resource = SimpleNamespace(schema_version="4.1")
    local_parse_result = SimpleNamespace(certifications=())
    expected_report = SimpleNamespace(analyses=())
    archive_path = tmp_path / "rncp.zip"

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
            return_value=local_parse_result,
        ) as parse_mock,
        patch.object(
            script_module,
            "resolve_official_rncp_successors",
            return_value=expected_report,
        ) as resolve_mock,
    ):
        returned_resource, returned_report = (
            script_module.run_official_rncp_successor_audit()
        )

    assert returned_resource is resource
    assert returned_report is expected_report
    download_mock.assert_called_once()
    parse_mock.assert_called_once_with(archive_path, ("RNCP100",), "4.1")
    resolve_mock.assert_called_once_with(
        archive_path,
        local_parse_result,
        ("RNCP100",),
        "4.1",
    )
