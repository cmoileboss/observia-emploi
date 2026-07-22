"""Valide un fichier rempli contre son paquet d'annotation d'origine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.services.human_annotation_protocol import (
    validate_completed_annotation,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse les chemins du paquet attendu et du fichier rempli."""
    parser = argparse.ArgumentParser(
        description="Valide un paquet humain rempli sans calculer d'accord."
    )
    parser.add_argument(
        "--template",
        type=Path,
        required=True,
        help="Paquet CSV vierge généré par le lot 6A.",
    )
    parser.add_argument(
        "--annotated",
        type=Path,
        required=True,
        help="Copie remplie du même paquet CSV.",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Valide le fichier rempli et affiche uniquement son nombre de couples."""
    args = parse_args()
    try:
        result = validate_completed_annotation(
            args.template.read_bytes(),
            args.annotated.read_bytes(),
        )
    except Exception as exc:
        print(f"Annotation invalide : {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Annotation valide : {result.pair_count} couples.")


if __name__ == "__main__":
    main()
