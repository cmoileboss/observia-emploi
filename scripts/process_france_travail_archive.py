#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
CLI Script to process offline France Travail raw archives.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

# Make project root importable when executing the script directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.france_travail.exceptions import FranceTravailError
from services.france_travail.processor import process_archive


def main(argv: Sequence[str] | None = None) -> int:
    """Run the France Travail raw archive processing.

    Parameters
    ----------
    argv:
        Command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for error).
    """
    parser = argparse.ArgumentParser(
        description="Process raw France Travail job offer archives."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--archive-directory",
        type=str,
        help="Path to the raw archive directory (containing manifest.json).",
    )
    group.add_argument(
        "--run-directory",
        type=str,
        help="Path to the raw archive directory (containing manifest.json).",
    )
    parser.add_argument(
        "--output-directory",
        type=str,
        default=None,
        help="Optional destination path for the normalized JSON output.",
    )

    args = parser.parse_args(argv)

    # Resolve output directory
    if args.output_directory is not None:
        output_dir = Path(args.output_directory)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            print(
                "Erreur: La variable d'environnement LOCALAPPDATA est absente "
                "et aucun répertoire de sortie (--output-directory) n'a été fourni.",
                file=sys.stderr,
            )
            return 1
        output_dir = Path(local_app_data) / "Observia" / "FranceTravail" / "processed"

    archive_dir_str = args.archive_directory or args.run_directory
    archive_path = Path(archive_dir_str)

    try:
        result = process_archive(
            archive_directory=archive_path,
            output_root_directory=output_dir,
        )

        print("TRAITEMENT FRANCE TRAVAIL REUSSI")
        print(f"Run source : {result.source_run_id}")
        print(f"Archive source : {result.input_directory}")
        print(f"Fichier traite : {result.output_file}")
        print(f"Pages brutes : {result.raw_page_count}")
        print(f"Offres brutes : {result.raw_offer_count}")
        print(f"Offres normalisees : {result.normalized_offer_count}")
        print(f"Doublons ignores : {result.duplicate_offer_count}")
        print("Erreurs de normalisation : 0")

        return 0

    except FranceTravailError as exc:
        print(type(exc).__name__, file=sys.stderr)
        print(exc.args[0] if exc.args else "Une erreur s'est produite.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Erreur inattendue: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
