"""Réimporte un classeur annoté dans son CSV canonique d'origine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.human_annotation_workbook import (
    import_workbook_annotations,
)


def run_workbook_import(
    template_csv_path: Path,
    workbook_path: Path,
    output_csv_path: Path,
) -> int:
    """Réimporte, valide et écrit le CSV canonique rempli."""
    completed_csv = import_workbook_annotations(
        template_csv_path.read_bytes(),
        workbook_path.read_bytes(),
    )
    output_csv_path.write_bytes(completed_csv)
    return len(completed_csv)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse les trois chemins nécessaires à la réimportation."""
    parser = argparse.ArgumentParser(
        description="Réimporte un classeur XLSX rempli dans son CSV modèle."
    )
    parser.add_argument(
        "--template-csv",
        type=Path,
        required=True,
        help="CSV annotateur original et non modifié.",
    )
    parser.add_argument(
        "--workbook",
        type=Path,
        required=True,
        help="Classeur XLSX rempli par l'annotateur.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        required=True,
        help="Chemin du CSV canonique rempli à produire.",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Réimporte le classeur et signale explicitement les erreurs."""
    args = parse_args()
    try:
        byte_count = run_workbook_import(
            args.template_csv,
            args.workbook,
            args.output_csv,
        )
    except Exception as exc:
        print(f"Réimportation impossible : {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"CSV annoté écrit : {args.output_csv} ({byte_count} octets).")


if __name__ == "__main__":
    main()
