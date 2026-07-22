"""Génère les paquets aveugles d'annotation humaine depuis le lot 5."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.services.human_annotation_protocol import (
    LOT5_ARTIFACT_NAMES,
    AnnotationPackageResult,
    build_annotation_packages,
    export_annotation_packages,
    load_lot5_annotation_inputs,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIRECTORY = BACKEND_ROOT / "data" / "processed" / "evaluation_sample_v1"
DEFAULT_OUTPUT_DIRECTORY = BACKEND_ROOT / "data" / "processed" / "annotation_v1"


def run_annotation_package_build(
    input_directory: Path,
) -> AnnotationPackageResult:
    """Lit exactement les quatre artefacts du lot 5 et construit les paquets."""
    artifact_contents = {
        name: (input_directory / name).read_bytes()
        for name in LOT5_ARTIFACT_NAMES
    }
    return build_annotation_packages(
        load_lot5_annotation_inputs(artifact_contents)
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse les dossiers d'entrée et de sortie du protocole."""
    parser = argparse.ArgumentParser(
        description="Génère les paquets aveugles d'annotation du lot 6A."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIRECTORY,
        help="Dossier contenant les quatre artefacts figés du lot 5.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="Dossier généré recevant les huit artefacts d'annotation.",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Génère les paquets après audit puis affiche leurs compteurs."""
    args = parse_args()
    try:
        result = run_annotation_package_build(args.input_dir)
        export_annotation_packages(result, args.output_dir)
    except Exception as exc:
        print(f"Erreur de génération des paquets d'annotation : {exc}", file=sys.stderr)
        sys.exit(1)

    audit = result.duplicate_audit
    print(f"Doublons exacts inter-splits : {len(audit.exact_duplicates)}")
    print(f"Quasi-doublons inter-splits : {len(audit.near_duplicates)}")
    print(f"Offres du pilote : {len(result.pilot_offer_keys)}")
    for packet_name in (
        "pilot_annotator_1.csv",
        "development_annotator_1.csv",
        "validation_annotator_1.csv",
    ):
        packet_label = packet_name.removesuffix("_annotator_1.csv")
        print(
            f"Lignes {packet_label} par annotateur : "
            f"{result.packet_counts[packet_name]['couples']}"
        )
    print(f"Paquets exportés : {args.output_dir}")


if __name__ == "__main__":
    main()
