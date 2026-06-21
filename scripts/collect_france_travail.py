#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script to collect France Travail job offers and archive them locally.

Two collection modes are supported:

Legacy mode (single-page, keyword params):

    .venv\\Scripts\\python.exe scripts\\collect_france_travail.py \\
        --param motsCles=python \\
        --range-start 0 --range-end 9 \\
        --output-directory data/raw

ROME mode (multi-code, paginated):

    .venv\\Scripts\\python.exe scripts\\collect_france_travail.py \\
        --codes-file formations_enriched.csv \\
        --column code_rome \\
        --max-codes 2 \\
        --max-pages 1 \\
        --output-directory data/raw

The two modes are mutually exclusive.  --codes-file triggers ROME mode;
the legacy --param/--range-start/--range-end options trigger legacy mode.
--help works without .env and without any network call.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

# Make project root importable when executing the script directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from services.france_travail.auth import FranceTravailAuthClient
from services.france_travail.client import FranceTravailOffersClient
from services.france_travail.config import FranceTravailConfig
from services.france_travail.exceptions import (
    FranceTravailCollectionError,
    FranceTravailError,
    FranceTravailRomeError,
)
from services.france_travail.raw_storage import FranceTravailRawStorage
from services.france_travail.pagination import FranceTravailOffersPaginator
from services.france_travail.rome import read_local_rome_codes
from services.france_travail.rome_collector import collect_offers_by_rome_codes

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_OK: int = 0
EXIT_ERROR: int = 1
EXIT_UNEXPECTED: int = 2

# ---------------------------------------------------------------------------
# Sensitive keys guard (for legacy --param mode)
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "access_token",
        "token",
        "client_secret",
        "secret",
        "client_id",
        "password",
    }
)


def parse_param(param_str: str) -> tuple[str, str]:
    """Parse a CLE=VALEUR parameter string.

    Parameters
    ----------
    param_str:
        The argument string to split on '='.

    Returns
    -------
    tuple[str, str]
        Key and value.
    """
    if "=" not in param_str:
        raise ValueError(
            f"Paramètre invalide: '{param_str}'. Le format attendu est CLE=VALEUR."
        )
    key, val = param_str.split("=", 1)
    key_stripped = key.strip()
    val_stripped = val.strip()

    if not key_stripped:
        raise ValueError(
            f"Paramètre invalide: '{param_str}'. La clé ne doit pas être vide."
        )
    if not val_stripped:
        raise ValueError(
            f"Paramètre invalide: '{param_str}'. La valeur ne doit pas être vide."
        )

    return key_stripped, val_stripped


def build_search_params(params_list: Sequence[str] | None) -> dict[str, str]:
    """Convert CLI --param parameters into a validated dictionary.

    Parameters
    ----------
    params_list:
        A list of parameter strings.

    Returns
    -------
    dict[str, str]
        A mapping of non-sensitive query filters.
    """
    if not params_list:
        return {}

    search_params: dict[str, str] = {}
    seen_keys_lower: set[str] = set()

    for param_str in params_list:
        key, val = parse_param(param_str)
        normalized_key = key.strip().lower()

        if normalized_key in _SENSITIVE_KEYS:
            raise ValueError(
                f"Paramètre interdit car sensible: '{key}'."
            )

        if normalized_key in seen_keys_lower:
            raise ValueError(
                f"Paramètre dupliqué: '{key}'."
            )

        seen_keys_lower.add(normalized_key)
        search_params[key] = val

    return search_params


# ---------------------------------------------------------------------------
# CLI builder (deferred so --help works without imports)
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="collect_france_travail",
        description=(
            "Collect France Travail job offers and archive them locally. "
            "Deux modes : legacy (--param) ou ROME par fichier (--codes-file)."
        ),
    )

    # ---- Output ----
    parser.add_argument(
        "--output-directory",
        type=str,
        default=None,
        help="Répertoire de sortie pour les archives. Défaut : LOCALAPPDATA/Observia/FranceTravail/raw.",
    )

    # ---- ROME mode ----
    rome_group = parser.add_argument_group(
        "Mode ROME",
        "Collecte paginée par codes ROME (mutuellement exclusif avec le mode legacy).",
    )
    rome_group.add_argument(
        "--codes-file",
        metavar="CHEMIN",
        default=None,
        help="Fichier CSV contenant les codes ROME à collecter.",
    )
    rome_group.add_argument(
        "--column",
        metavar="COLONNE",
        default="code_rome",
        help="Colonne CSV des codes ROME (défaut : code_rome).",
    )
    rome_group.add_argument(
        "--max-codes",
        metavar="N",
        default=None,
        help="Nombre maximum de codes à collecter après déduplication.",
    )
    rome_group.add_argument(
        "--max-pages",
        metavar="N",
        default="10",
        help="Nombre maximum de pages par code ROME (défaut : 10).",
    )

    # ---- Legacy mode ----
    legacy_group = parser.add_argument_group(
        "Mode legacy",
        "Collecte d'une seule page (mutuellement exclusif avec le mode ROME).",
    )
    legacy_group.add_argument(
        "--range-start",
        type=int,
        default=0,
        help="Début de la tranche de résultats (défaut : 0).",
    )
    legacy_group.add_argument(
        "--range-end",
        type=int,
        default=9,
        help="Fin de la tranche de résultats (défaut : 9).",
    )
    legacy_group.add_argument(
        "--param",
        action="append",
        default=None,
        help="Paramètre de recherche au format CLE=VALEUR. Répétable.",
    )

    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_output_directory(output_directory: str | None) -> Path | None:
    """Return the output directory Path, or None if it cannot be determined."""
    if output_directory is not None:
        return Path(output_directory)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data) / "Observia" / "FranceTravail" / "raw"


def _load_config_from_env():  # type: ignore[return]
    """Load FranceTravailConfig from the .env file.

    Returns the config or ``None`` on failure (after printing an error).
    """
    from services.france_travail.config import FranceTravailConfig  # noqa: PLC0415

    dotenv_path = PROJECT_ROOT / ".env"
    if not dotenv_path.is_file():
        print(
            "Erreur : Le fichier de configuration .env est manquant à la racine du projet.",
            file=sys.stderr,
        )
        return None

    load_dotenv(dotenv_path=dotenv_path, override=False)

    try:
        return FranceTravailConfig.from_environ()
    except Exception:
        print(
            "Erreur : La configuration de France Travail est invalide ou incomplète dans le fichier .env.",
            file=sys.stderr,
        )
        return None


def _validate_positive_int(raw: str | None, name: str) -> int | None:
    """Parse and validate a strictly positive integer CLI argument.

    Parameters
    ----------
    raw:
        The raw string value from argparse (may be ``None``).
    name:
        Argument name used in error messages.

    Returns
    -------
    int | None
        Parsed integer, or ``None`` if *raw* is ``None``.

    Raises
    ------
    ValueError
        When the value is not a valid strictly positive integer.
    """
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"--{name} doit être un entier strictement positif, reçu: {raw!r}.")
    if value < 1:
        raise ValueError(f"--{name} doit être >= 1, reçu: {value}.")
    return value


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Run France Travail offer collection.

    Parameters
    ----------
    argv:
        Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns
    -------
    int
        Exit code.
    """
    raw_args = argv if argv is not None else sys.argv[1:]

    if not any(arg in ("--help", "-h") for arg in raw_args):
        # 1. ROME options used without --codes-file must be rejected immediately
        has_codes_file = any(arg.startswith("--codes-file") for arg in raw_args)
        has_rome_options = any(
            arg.startswith(("--column", "--max-codes", "--max-pages"))
            for arg in raw_args
        )
        if has_rome_options and not has_codes_file:
            print(
                "Erreur : --column, --max-codes et --max-pages ne peuvent être "
                "utilisés qu'avec --codes-file (mode ROME).",
                file=sys.stderr,
            )
            return EXIT_ERROR

        # 2. Refuse mixtures of --codes-file and legacy options
        if has_codes_file:
            has_legacy_options = any(
                arg.startswith(("--param", "--range-start", "--range-end"))
                for arg in raw_args
            )
            if has_legacy_options:
                print(
                    "Erreur : --codes-file (mode ROME) et les options legacy "
                    "(--param, --range-start, --range-end) sont mutuellement exclusifs.",
                    file=sys.stderr,
                )
                return EXIT_ERROR

    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- Mode detection -------------------------------------------------------
    is_rome_mode = args.codes_file is not None
    is_legacy_mode = args.param is not None

    if is_rome_mode and is_legacy_mode:
        print(
            "Erreur : --codes-file (mode ROME) et --param (mode legacy) sont mutuellement exclusifs.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    # --- Output directory -----------------------------------------------------
    output_dir = _resolve_output_directory(args.output_directory)
    if output_dir is None:
        print(
            "Erreur : La variable d'environnement LOCALAPPDATA est absente "
            "et aucun répertoire de sortie (--output-directory) n'a été fourni.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    # =========================================================================
    # ROME MODE
    # =========================================================================
    if is_rome_mode:
        # --- Validate --max-codes and --max-pages ---
        try:
            max_codes = _validate_positive_int(args.max_codes, "max-codes")
            max_pages = _validate_positive_int(args.max_pages, "max-pages")
        except ValueError as exc:
            print(f"Erreur d'arguments : {exc}", file=sys.stderr)
            return EXIT_ERROR

        if max_pages is None:
            max_pages = 10  # Default already applied by argparse default, but explicit here.

        # --- Read local codes ---
        codes_path = Path(args.codes_file)
        try:
            all_codes = read_local_rome_codes(codes_path, column=args.column)
        except Exception as exc:
            if isinstance(exc, FranceTravailRomeError):
                print(f"Erreur lecture codes ROME : {exc}", file=sys.stderr)
            else:
                print(f"Erreur inattendue lecture codes : {type(exc).__name__}", file=sys.stderr)
            return EXIT_ERROR

        # --- Apply --max-codes (after deduplication, order preserved) ---
        if max_codes is not None:
            selected_codes = all_codes[:max_codes]
        else:
            selected_codes = all_codes

        if not selected_codes:
            print("Erreur : aucun code ROME sélectionné après déduplication/limitation.", file=sys.stderr)
            return EXIT_ERROR

        # --- Load config ---
        config = _load_config_from_env()
        if config is None:
            return EXIT_ERROR

        # --- Build clients ---
        auth_client = FranceTravailAuthClient(config=config)
        offers_client = FranceTravailOffersClient(config=config, auth_client=auth_client)
        paginator = FranceTravailOffersPaginator(offers_client=offers_client)

        # --- Collect ---
        try:
            result = collect_offers_by_rome_codes(
                rome_codes=selected_codes,
                offers_client=offers_client,
                paginator=paginator,
                output_directory=output_dir,
                max_pages=max_pages,
            )
        except Exception as exc:
            if isinstance(exc, FranceTravailCollectionError):
                print(f"Erreur de collecte ROME : {type(exc).__name__}", file=sys.stderr)
                print(exc.args[0] if exc.args else "Erreur de collecte.", file=sys.stderr)
            elif isinstance(exc, FranceTravailError):
                print(f"Erreur France Travail : {type(exc).__name__}", file=sys.stderr)
            else:
                print(f"Erreur inattendue : {type(exc).__name__}", file=sys.stderr)
            return EXIT_ERROR

        # --- Summary ---
        status = "COMPLETE" if result.complete else "INCOMPLETE"
        print(f"COLLECTE ROME FRANCE TRAVAIL — {status}")
        print(f"Run ID       : {result.run_id}")
        print(f"Répertoire   : {result.run_directory}")
        print(f"Codes validés : {len(result.codes_results)}")
        print(f"Pages totales : {result.total_page_count}")
        print(f"Offres totales : {result.total_offer_count}")
        for code_res in result.codes_results:
            status_str = "OK" if code_res.success else f"ERREUR ({code_res.error})"
            print(
                f"  {code_res.rome_code} : {code_res.page_count} page(s), "
                f"{code_res.offer_count} offre(s) — {status_str}"
            )

        return EXIT_OK

    # =========================================================================
    # LEGACY MODE
    # =========================================================================

    # Parse and validate --param
    try:
        search_params = build_search_params(args.param)
    except ValueError as exc:
        print(f"Erreur d'arguments : {exc}", file=sys.stderr)
        return EXIT_ERROR

    config = _load_config_from_env()
    if config is None:
        return EXIT_ERROR

    try:
        auth_client = FranceTravailAuthClient(config=config)
        offers_client = FranceTravailOffersClient(config=config, auth_client=auth_client)

        page = offers_client.search_offers_page(
            search_params=search_params,
            range_start=args.range_start,
            range_end=args.range_end,
        )

        storage = FranceTravailRawStorage(root_directory=output_dir)
        archive = storage.archive_pages(pages=[page], search_params=search_params)

        print("COLLECTE FRANCE TRAVAIL REUSSIE")
        print(f"Archive : {archive.directory}")
        print("Pages archivees : 1")
        print(f"Offres archivees : {archive.offer_count}")
        if page.content_range:
            print(f"Content-Range : {page.content_range}")
        else:
            print("Content-Range : absent")

        return EXIT_OK

    except FranceTravailError as exc:
        print(type(exc).__name__, file=sys.stderr)
        print(exc.args[0] if exc.args else "Une erreur s'est produite.", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:
        print(f"Erreur inattendue: {type(exc).__name__}", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
