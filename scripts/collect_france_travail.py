#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script to collect a single page of job offers from the France Travail API
and archive it locally using FranceTravailRawStorage.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

# Make project root importable when executing the script directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from services.france_travail.auth import FranceTravailAuthClient
from services.france_travail.client import FranceTravailOffersClient
from services.france_travail.config import FranceTravailConfig
from services.france_travail.exceptions import FranceTravailError
from services.france_travail.raw_storage import FranceTravailRawStorage


# Sensitive keys that must not be used as parameter keys (case-insensitive)
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
        # Store original key (stripped) or lowercase key? The prompt says "ne pas modifier les valeurs", 
        # but let's preserve the original stripped key name with the value.
        search_params[key] = val

    return search_params



def main(argv: Sequence[str] | None = None) -> int:
    """Run the France Travail API single page collection.

    Parameters
    ----------
    argv:
        Command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success, 1 or other non-zero for error).
    """
    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description="Collect France Travail job offers and archive them locally."
    )
    parser.add_argument(
        "--range-start",
        type=int,
        default=0,
        help="Start offset of the results tranche (default: 0).",
    )
    parser.add_argument(
        "--range-end",
        type=int,
        default=9,
        help="End offset of the results tranche (default: 9).",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=None,
        help="Search query parameter in CLE=VALEUR format. Can be repeated.",
    )
    parser.add_argument(
        "--output-directory",
        type=str,
        default=None,
        help="Optional archive output directory path.",
    )

    args = parser.parse_args(argv)

    # 1. Parse and validate parameters
    try:
        search_params = build_search_params(args.param)
    except ValueError as exc:
        print(f"Erreur d'arguments: {exc}", file=sys.stderr)
        return 1

    # 2. Determine archive output directory
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
        output_dir = Path(local_app_data) / "Observia" / "FranceTravail" / "raw"

    # 3. Load configuration safely
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    dotenv_path = project_root / ".env"

    if not dotenv_path.is_file():
        print(
            "Erreur: Le fichier de configuration .env est manquant à la racine du projet.",
            file=sys.stderr,
        )
        return 1

    # Load environment variables without overriding existing environment variables
    load_dotenv(dotenv_path=dotenv_path, override=False)

    try:
        config = FranceTravailConfig.from_environ()
    except Exception:
        # Generic error message to avoid leaking any potential env values
        print(
            "Erreur: La configuration de France Travail est invalide ou incomplète dans le fichier .env.",
            file=sys.stderr,
        )
        return 1

    # 4. Run collection
    try:
        auth_client = FranceTravailAuthClient(config=config)
        offers_client = FranceTravailOffersClient(config=config, auth_client=auth_client)

        # Single call to search_offers_page (no paginator)
        page = offers_client.search_offers_page(
            search_params=search_params,
            range_start=args.range_start,
            range_end=args.range_end,
        )

        # Archive the page
        storage = FranceTravailRawStorage(root_directory=output_dir)
        archive = storage.archive_pages(pages=[page], search_params=search_params)

        # 5. Output summary
        print("COLLECTE FRANCE TRAVAIL REUSSIE")
        print(f"Archive : {archive.directory}")
        print("Pages archivees : 1")
        print(f"Offres archivees : {archive.offer_count}")
        if page.content_range:
            print(f"Content-Range : {page.content_range}")
        else:
            print("Content-Range : absent")

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
