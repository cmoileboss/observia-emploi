"""Tests d'orchestration des paquets d'annotation du lot 6A."""

from types import SimpleNamespace
from unittest.mock import patch

import backend.scripts.build_human_annotation_packages as script_module
from backend.scripts.build_human_annotation_packages import (
    run_annotation_package_build,
)


def test_orchestration_reads_exactly_the_four_lot5_artifacts(tmp_path):
    contents = {
        "sample_manifest.json": b"manifest",
        "evaluation_offers.json": b"offers",
        "candidate_pools.jsonl": b"pools",
        "annotation_template.csv": b"template",
    }
    for name, content in contents.items():
        (tmp_path / name).write_bytes(content)
    loaded_inputs = SimpleNamespace()
    expected_result = SimpleNamespace()

    with (
        patch.object(
            script_module,
            "load_lot5_annotation_inputs",
            return_value=loaded_inputs,
        ) as load_mock,
        patch.object(
            script_module,
            "build_annotation_packages",
            return_value=expected_result,
        ) as build_mock,
    ):
        result = run_annotation_package_build(tmp_path)

    assert result is expected_result
    assert load_mock.call_args.args[0] == contents
    build_mock.assert_called_once_with(loaded_inputs)
