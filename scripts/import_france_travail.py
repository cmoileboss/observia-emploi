#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
CLI Script to import France Travail normalized job offers.
Supports dry-run validation and transactional applying.
"""

import argparse
import sys
from pathlib import Path

# Make project root importable when executing the script directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.france_travail.exceptions import FranceTravailError
from services.france_travail.importer import prepare_import, persist_prepared_import


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import France Travail normalized job offers."
    )
    parser.add_argument(
        "--input-file",
        type=str,
        required=True,
        help="Path to the offers_normalized.json file.",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the file and prepare import without database access.",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="Apply the import to the database.",
    )

    args = parser.parse_args()
    input_path = Path(args.input_file)

    try:
        # 1. Prepare and validate (dry-run/apply common path)
        prepared = prepare_import(input_path)

        if args.dry_run:
            print("VALIDATION IMPORT FRANCE TRAVAIL REUSSIE")
            print(f"Run source : {prepared.source_run_id}")
            print(f"Fichier source : {prepared.input_file}")
            print(f"Offres en entree : {prepared.input_offer_count}")
            print(f"Offres mappees : {prepared.mapped_offer_count}")
            print(f"Competences mappees : {prepared.mapped_competency_count}")
            print(f"Competences sans code ignorees : {prepared.skipped_competency_without_code_count}")
            print(f"Formations mappees : {prepared.mapped_training_count}")
            print(f"Formations sans code ignorees : {prepared.skipped_training_without_code_count}")
            print(f"Doublons de competence ignores : {prepared.duplicate_competency_code_count}")
            print(f"Doublons de formation ignores : {prepared.duplicate_training_code_count}")
            print("Base de donnees contactee : non")
            return 0

        # 2. Apply to database (deferred import of SessionLocal)
        from postgres_connection import SessionLocal

        session = SessionLocal()
        try:
            result = persist_prepared_import(prepared, session)
            print("IMPORT FRANCE TRAVAIL REUSSI")
            print(f"Run source : {result.source_run_id}")
            print(f"Fichier source : {result.input_file}")
            print(f"Offres en entree : {result.input_offer_count}")
            print(f"Offres inserees : {result.inserted_offer_count}")
            print(f"Offres deja presentes : {result.existing_offer_count}")
            print(f"Competences rattachees : {result.attached_competency_count}")
            print(f"Formations rattachees : {result.attached_training_count}")
            print(f"Competences sans code ignorees : {result.skipped_competency_without_code_count}")
            print(f"Formations sans code ignorees : {result.skipped_training_without_code_count}")
            print("Transaction validee : oui")
            return 0
        finally:
            session.close()

    except FranceTravailError as exc:
        print(f"Erreur: {exc.args[0] if exc.args else 'Une erreur est survenue.'}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Erreur inattendue: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
