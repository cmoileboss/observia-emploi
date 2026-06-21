#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script de validation croisée des codes ROME France Travail.

Usage
-----
Offline (référentiel JSON local) :

    .venv\\Scripts\\python.exe scripts\\validate_france_travail_rome.py \\
        --codes-file path/to/codes.csv \\
        --offline-reference path/to/referentiel.json

Live (appel réel à l'API France Travail) :

    .venv\\Scripts\\python.exe scripts\\validate_france_travail_rome.py \\
        --codes-file path/to/codes.csv \\
        --live

Les options --offline-reference et --live sont mutuellement exclusives.
L'une des deux est obligatoire.

--help fonctionne sans .env et sans réseau.

Codes de sortie
---------------
0   Tous les codes demandés sont reconnus (ou aucun code n'a été demandé).
1   Certains codes sont inconnus dans le référentiel.
2   Erreur métier ou technique (fichier absent, format invalide, etc.).
3   Erreur inattendue.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

# Make project root importable when executing the script directly.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Exit codes (documented constants)
# ---------------------------------------------------------------------------

EXIT_OK: int = 0
EXIT_UNKNOWN_CODES: int = 1
EXIT_BUSINESS_ERROR: int = 2
EXIT_UNEXPECTED_ERROR: int = 3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser.

    Called at import time only to construct the object — does NOT trigger
    any network call or environment loading.
    """
    parser = argparse.ArgumentParser(
        prog="validate_france_travail_rome",
        description=(
            "Valide des codes ROME locaux contre le référentiel France Travail. "
            "Utilise --offline-reference pour un JSON local, ou --live pour un appel réel."
        ),
    )
    parser.add_argument(
        "--codes-file",
        required=True,
        metavar="CHEMIN",
        help="Chemin vers le fichier CSV contenant les codes ROME à valider.",
    )
    parser.add_argument(
        "--column",
        default=None,
        metavar="COLONNE",
        help=(
            "Nom de la colonne CSV contenant les codes ROME. "
            "Si absent, la valeur par défaut du lecteur local est utilisée."
        ),
    )
    parser.add_argument(
        "--offline-reference",
        metavar="CHEMIN_JSON",
        default=None,
        help=(
            "Chemin vers un fichier JSON local contenant le référentiel ROME "
            "(liste d'objets {code, libelle}). "
            "Mutuellement exclusif avec --live."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help=(
            "Effectue un appel réel à l'API France Travail pour récupérer le référentiel. "
            "Requiert un fichier .env valide. "
            "Mutuellement exclusif avec --offline-reference."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Offline reference loader
# ---------------------------------------------------------------------------


def _load_offline_reference(ref_path: Path) -> list[dict]:
    """Load a local JSON referentiel file.

    Parameters
    ----------
    ref_path:
        Path to the JSON file.

    Returns
    -------
    list[dict]
        Parsed JSON content (expected to be a list).

    Raises
    ------
    ValueError
        On any read or parse error. The caller (main) converts this to
        EXIT_BUSINESS_ERROR and prints a safe message to stderr.
    """
    if not ref_path.exists():
        raise ValueError(
            f"le fichier de référentiel offline est introuvable : {ref_path.name}"
        )

    if not ref_path.is_file():
        raise ValueError(
            f"le chemin du référentiel offline n'est pas un fichier : {ref_path.name}"
        )

    try:
        with ref_path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        raise ValueError(
            f"erreur de lecture du fichier de référentiel offline '{ref_path.name}': "
            f"{exc.strerror}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"erreur de décodage JSON du fichier de référentiel offline "
            f"'{ref_path.name}': {exc.msg}"
        ) from exc

    return raw


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ROME validation script.

    Parameters
    ----------
    argv:
        Command-line arguments (defaults to sys.argv[1:]).

    Returns
    -------
    int
        Exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- Validate mutual exclusivity of --offline-reference and --live ---
    if args.offline_reference and args.live:
        print(
            "Erreur : --offline-reference et --live sont mutuellement exclusifs.",
            file=sys.stderr,
        )
        return EXIT_BUSINESS_ERROR

    if not args.offline_reference and not args.live:
        print(
            "Erreur : vous devez spécifier --offline-reference ou --live.",
            file=sys.stderr,
        )
        return EXIT_BUSINESS_ERROR

    # --- Lazy imports (after arg parsing so --help works without .env) ---
    from services.france_travail.exceptions import FranceTravailError, FranceTravailRomeError
    from services.france_travail.rome import (
        DEFAULT_ROME_COLUMN,
        parse_rome_referentiel,
        read_local_rome_codes,
        validate_rome_codes,
    )

    codes_path = Path(args.codes_file)
    column = args.column if args.column is not None else DEFAULT_ROME_COLUMN

    # --- Step 1: read local codes ---
    try:
        local_codes = read_local_rome_codes(codes_path, column=column)
    except FranceTravailRomeError as exc:
        print(f"Erreur lecture codes locaux : {exc}", file=sys.stderr)
        return EXIT_BUSINESS_ERROR
    except Exception as exc:
        print(f"Erreur inattendue lors de la lecture des codes : {type(exc).__name__}", file=sys.stderr)
        return EXIT_UNEXPECTED_ERROR

    original_count = len(local_codes)

    # --- Step 2: obtain referentiel ---
    mode_label: str

    if args.live:
        # Defer .env loading and authentication to this branch only.
        mode_label = "reel"
        try:
            import os
            from dotenv import load_dotenv

            dotenv_path = _PROJECT_ROOT / ".env"
            if not dotenv_path.is_file():
                print(
                    "Erreur : le fichier .env est manquant à la racine du projet.",
                    file=sys.stderr,
                )
                return EXIT_BUSINESS_ERROR

            load_dotenv(dotenv_path=dotenv_path, override=False)

            from services.france_travail.auth import FranceTravailAuthClient
            from services.france_travail.client import FranceTravailOffersClient
            from services.france_travail.config import FranceTravailConfig

            try:
                config = FranceTravailConfig.from_environ()
            except Exception:
                print(
                    "Erreur : la configuration France Travail est invalide ou incomplète.",
                    file=sys.stderr,
                )
                return EXIT_BUSINESS_ERROR

            auth_client = FranceTravailAuthClient(config=config)
            offers_client = FranceTravailOffersClient(config=config, auth_client=auth_client)
            raw_referentiel = offers_client.get_rome_referentiel()

        except FranceTravailError as exc:
            print(f"Erreur API France Travail : {type(exc).__name__}", file=sys.stderr)
            return EXIT_BUSINESS_ERROR
        except Exception as exc:
            print(
                f"Erreur inattendue lors de l'appel au référentiel : {type(exc).__name__}",
                file=sys.stderr,
            )
            return EXIT_UNEXPECTED_ERROR

    else:
        # Offline mode — no network.
        mode_label = "hors ligne"
        ref_path = Path(args.offline_reference)
        try:
            raw_referentiel = _load_offline_reference(ref_path)
        except ValueError as exc:
            print(f"Erreur référentiel offline : {exc}", file=sys.stderr)
            return EXIT_BUSINESS_ERROR

    # --- Step 3: parse referentiel ---
    try:
        reference_entries = parse_rome_referentiel(raw_referentiel)
    except FranceTravailRomeError as exc:
        print(f"Erreur parsing référentiel : {exc}", file=sys.stderr)
        return EXIT_BUSINESS_ERROR
    except Exception as exc:
        print(
            f"Erreur inattendue lors du parsing du référentiel : {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED_ERROR

    # --- Step 4: validate ---
    try:
        result = validate_rome_codes(local_codes, reference_entries)
    except FranceTravailRomeError as exc:
        print(f"Erreur validation : {exc}", file=sys.stderr)
        return EXIT_BUSINESS_ERROR
    except Exception as exc:
        print(
            f"Erreur inattendue lors de la validation : {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED_ERROR

    # --- Step 5: display summary ---
    unknown_display = (
        " ".join(result.unknown_codes) if result.unknown_codes else "aucun"
    )

    print("VALIDATION ROME FRANCE TRAVAIL")
    print(f"Fichier de codes     : {codes_path.name}")
    print(f"Codes demandes       : {original_count}")
    print(f"Codes uniques        : {len(result.requested_codes)}")
    print(f"Doublons ignores     : {result.duplicate_requested_count}")
    print(f"Entrees du referentiel : {result.reference_entry_count}")
    print(f"Codes reconnus       : {len(result.valid_codes)}")
    print(f"Codes inconnus       : {len(result.unknown_codes)}")
    print(f"Liste des codes inconnus : {unknown_display}")
    print(f"Mode                 : {mode_label}")

    if result.unknown_codes:
        return EXIT_UNKNOWN_CODES

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
