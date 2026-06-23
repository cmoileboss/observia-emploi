import hashlib
import json
import os
import sys
from pathlib import Path
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from postgres_connection import engine


def ecriture_atomique(dest_path: Path, content_bytes: bytes) -> str:
    """
    Écrit de manière atomique le contenu dans dest_path après comparaison.
    """
    if dest_path.exists():
        if dest_path.read_bytes() == content_bytes:
            return "inchangé"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_name(dest_path.name + ".tmp")
    try:
        temp_path.write_bytes(content_bytes)
        temp_path.replace(dest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return "mis à jour"


def export_snapshot() -> None:
    output_dir = PROJECT_ROOT / "data" / "processed" / "france_travail" / "snapshots" / "current"
    offers_file_path = output_dir / "france_travail_offers_snapshot.json"
    manifest_file_path = output_dir / "snapshot_manifest.json"

    connection = engine.connect()
    trans = connection.begin()
    try:
        # Enforce read-only transaction
        connection.execute(text("SET TRANSACTION READ ONLY"))

        # Select all offers ordered by id
        result = connection.execute(text("""
            SELECT id, intitule, description, entreprise_nom, lieu_code_postal, rome_code
            FROM francetravail_offres
            ORDER BY id
        """))

        offers = []
        seen_ids = set()
        duplicate_count = 0
        null_id_count = 0

        # Columns expected
        columns = ["id", "intitule", "description", "entreprise_nom", "lieu_code_postal", "rome_code"]

        for row in result:
            # Map row to dictionary
            row_dict = dict(zip(columns, row))

            # Validation
            o_id = row_dict.get("id")
            if o_id is None:
                null_id_count += 1
                raise ValueError("Identifiant (id) manquant ou nul dans une offre.")

            o_id_str = str(o_id).strip()
            if not o_id_str:
                raise ValueError("Identifiant (id) vide détecté.")

            if o_id_str in seen_ids:
                duplicate_count += 1
                raise ValueError(f"Identifiant (id) dupliqué détecté : {o_id_str}")
            seen_ids.add(o_id_str)

            title = row_dict.get("intitule")
            if not title or not str(title).strip():
                raise ValueError(f"Titre (intitule) vide ou absent pour l'offre {o_id_str}.")

            desc = row_dict.get("description")
            if not desc or not str(desc).strip():
                raise ValueError(f"Description vide ou absente pour l'offre {o_id_str}.")

            rome = row_dict.get("rome_code")
            if not rome or not str(rome).strip():
                raise ValueError(f"Code ROME vide ou absent pour l'offre {o_id_str}.")

            # Format structure
            offers.append({
                "france_travail_id": o_id_str,
                "title": str(title),
                "description": str(desc),
                "company_name": str(row_dict.get("entreprise_nom")) if row_dict.get("entreprise_nom") is not None else None,
                "postal_code": str(row_dict.get("lieu_code_postal")) if row_dict.get("lieu_code_postal") is not None else None,
                "rome_code": str(rome)
            })

    except Exception:
        # Rollback in case of error
        trans.rollback()
        raise
    else:
        # Always rollback because it's a read-only snapshot
        trans.rollback()
    finally:
        connection.close()

    # Double check list length matches rows
    rows_exported = len(offers)

    # Stable serialization
    output_bytes = json.dumps(
        offers,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8") + b"\n"

    snapshot_sha256 = hashlib.sha256(output_bytes).hexdigest()

    # Manifest
    manifest = {
        "snapshot_schema_version": 1,
        "source_table": "francetravail_offres",
        "rows_exported": rows_exported,
        "columns_exported": [
            "id",
            "intitule",
            "description",
            "entreprise_nom",
            "lieu_code_postal",
            "rome_code"
        ],
        "snapshot_file": "france_travail_offers_snapshot.json",
        "snapshot_sha256": snapshot_sha256,
        "distinct_ids": len(seen_ids),
        "null_ids": null_id_count,
        "duplicate_ids": duplicate_count
    }

    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8") + b"\n"

    status_offers = ecriture_atomique(offers_file_path, output_bytes)
    status_manifest = ecriture_atomique(manifest_file_path, manifest_bytes)

    if status_offers == "inchangé" and status_manifest == "inchangé":
        print("inchangé")
    else:
        print("mis à jour")


if __name__ == "__main__":
    try:
        export_snapshot()
    except Exception as e:
        print(f"Erreur d'export : {e}", file=sys.stderr)
        sys.exit(1)
