import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import text

from backend.postgres_connection import engine


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"

SOURCE_TABLE = "public.offres"
SNAPSHOT_COLUMNS = [
    "francetravail_id",
    "intitule",
    "description",
    "entreprise_nom",
    "lieu_code_postal",
    "rome_code",
]
SNAPSHOT_QUERY = text("""
    SELECT
        francetravail_id,
        intitule,
        description,
        entreprise_nom,
        lieu_code_postal,
        rome_code
    FROM public.offres
    WHERE francetravail_id IS NOT NULL
    ORDER BY francetravail_id
""")


def ecriture_atomique(dest_path: Path, content_bytes: bytes) -> str:
    """Write a file atomically after comparing existing content."""
    if dest_path.exists() and dest_path.read_bytes() == content_bytes:
        return "unchanged"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_name(dest_path.name + ".tmp")
    try:
        temp_path.write_bytes(content_bytes)
        temp_path.replace(dest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return "updated"


def _row_to_dict(row) -> dict:
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(zip(SNAPSHOT_COLUMNS, row))


def _clean_required(value, field_name: str, offer_id: str | None = None) -> str:
    if value is None:
        if offer_id:
            raise ValueError(f"Champ obligatoire '{field_name}' absent pour l'offre {offer_id}.")
        raise ValueError(f"Champ obligatoire '{field_name}' absent.")

    value_str = str(value).strip()
    if not value_str:
        if offer_id:
            raise ValueError(f"Champ obligatoire '{field_name}' vide pour l'offre {offer_id}.")
        raise ValueError(f"Champ obligatoire '{field_name}' vide.")

    return value_str


def _clean_optional(value) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def export_snapshot() -> None:
    output_dir = PROCESSED_DATA_ROOT / "france_travail" / "snapshots" / "current"
    offers_file_path = output_dir / "france_travail_offers_snapshot.json"
    manifest_file_path = output_dir / "snapshot_manifest.json"

    connection = engine.connect()
    trans = connection.begin()
    try:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        result = connection.execute(SNAPSHOT_QUERY)

        offers = []
        seen_ids = set()
        duplicate_count = 0
        null_id_count = 0
        missing_optional_counts = {
            "company_name": 0,
            "postal_code": 0,
            "work_place_name": 0,
        }

        for row in result:
            row_dict = _row_to_dict(row)

            raw_france_travail_id = row_dict.get("francetravail_id")
            if raw_france_travail_id is None:
                null_id_count += 1
                raise ValueError("Identifiant France Travail manquant ou nul dans une offre.")

            france_travail_id = _clean_required(raw_france_travail_id, "francetravail_id")
            if france_travail_id in seen_ids:
                duplicate_count += 1
                raise ValueError(f"francetravail_id duplique detecte : {france_travail_id}")
            seen_ids.add(france_travail_id)

            title = _clean_required(row_dict.get("intitule"), "intitule", france_travail_id)
            description = _clean_required(row_dict.get("description"), "description", france_travail_id)
            rome_code = _clean_required(row_dict.get("rome_code"), "rome_code", france_travail_id)
            company_name = _clean_optional(row_dict.get("entreprise_nom"))
            postal_code = _clean_optional(row_dict.get("lieu_code_postal"))

            if company_name is None:
                missing_optional_counts["company_name"] += 1
            if postal_code is None:
                missing_optional_counts["postal_code"] += 1
            missing_optional_counts["work_place_name"] += 1

            offers.append({
                "france_travail_id": france_travail_id,
                "title": title,
                "description": description,
                "company_name": company_name,
                "postal_code": postal_code,
                "work_place_name": None,
                "rome_code": rome_code,
            })
    except Exception:
        trans.rollback()
        raise
    else:
        trans.rollback()
    finally:
        connection.close()

    output_bytes = json.dumps(
        offers,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8") + b"\n"
    snapshot_sha256 = hashlib.sha256(output_bytes).hexdigest()

    manifest = {
        "snapshot_schema_version": 1,
        "source_table": SOURCE_TABLE,
        "source_filter": "francetravail_id IS NOT NULL",
        "source_order_by": "francetravail_id",
        "transaction_mode": "READ ONLY",
        "rows_exported": len(offers),
        "columns_exported": SNAPSHOT_COLUMNS,
        "snapshot_file": "france_travail_offers_snapshot.json",
        "snapshot_sha256": snapshot_sha256,
        "distinct_ids": len(seen_ids),
        "null_ids": null_id_count,
        "duplicate_ids": duplicate_count,
        "freework_rows_exported": 0,
        "required_fields": [
            "france_travail_id",
            "title",
            "description",
            "rome_code",
        ],
        "optional_fields": [
            "company_name",
            "postal_code",
            "work_place_name",
        ],
        "missing_optional_counts": missing_optional_counts,
    }

    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8") + b"\n"

    status_offers = ecriture_atomique(offers_file_path, output_bytes)
    status_manifest = ecriture_atomique(manifest_file_path, manifest_bytes)

    if status_offers == "unchanged" and status_manifest == "unchanged":
        print("unchanged")
    else:
        print("updated")


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporte un snapshot France Travail local en lecture seule.")
    parser.parse_args()
    try:
        export_snapshot()
    except Exception as e:
        print(f"Erreur d'export : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
