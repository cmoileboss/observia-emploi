"""."""
import argparse
import hashlib
import json
import os
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


SYNC_SCHEMA_VERSION = 1
CONTENT_HASH_VERSION = "free_work_catalog_business_v1"

BUSINESS_FIELDS = [
    "title",
    "description",
    "candidate_profile",
    "company_description",
    "company_name",
    "location",
    "contracts",
    "skills",
    "soft_skills",
    "remote_mode",
    "experience_level",
    "salary",
    "published_at",
    "updated_at",
    "expires_at",
]

TECHNICAL_FIELDS_EXCLUDED_FROM_HASH = [
    "source",
    "source_id",
    "source_url",
    "source_url_raw",
    "source_url_resolution_method",
    "matched_rome_queries",
    "raw_payload_sha256",
]

CHANGE_TYPES = {"NEW", "UPDATED", "UNCHANGED", "REACTIVATED", "INACTIVATED"}


def utc_now_iso():
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json_file(path):
    """Read JSON file with detailed JSONDecodeError reporting."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON file: {path}") from exc


def write_json_atomic(path, payload):
    """Atomically write JSON to file with atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    for attempt in range(5):
        try:
            os.replace(tmp_path, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05)


def write_jsonl_atomic(path, rows):
    """Atomically write JSONL rows to file with atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    for attempt in range(5):
        try:
            os.replace(tmp_path, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05)


def sha256_file(path):
    """Compute SHA256 hash of file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_payload(payload):
    """Compute SHA256 hash of JSON-serialized object."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonicalize(value):
    """Recursively normalize object by sorting dicts and excluding elasticHighlights."""
    if isinstance(value, dict):
        return {key: canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        canonical_items = [canonicalize(item) for item in value]
        return sorted(
            canonical_items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":")),
        )
    return value


def business_projection(offer):
    """Extract and canonicalize business fields from offer."""
    return {field: canonicalize(offer.get(field)) for field in BUSINESS_FIELDS}


def business_hash(offer):
    """Compute SHA256 hash of canonicalized business fields."""
    return sha256_payload(
        {
            "content_hash_version": CONTENT_HASH_VERSION,
            "business_projection": business_projection(offer),
        }
    )


def changed_business_fields(previous_offer, next_offer):
    """List business fields that differ between offers."""
    previous_projection = business_projection(previous_offer)
    next_projection = business_projection(next_offer)
    return [
        field
        for field in BUSINESS_FIELDS
        if previous_projection.get(field) != next_projection.get(field)
    ]


def validate_normalized_offers(offers):
    """Validate normalized offers are list with unique source_ids."""
    if not isinstance(offers, list):
        raise ValueError("Normalized input root must be a JSON list.")

    seen = set()
    for index, offer in enumerate(offers):
        if not isinstance(offer, dict):
            raise ValueError(f"Normalized offer at index {index} must be an object.")
        source_id = offer.get("source_id")
        if source_id is None or str(source_id).strip() == "":
            raise ValueError(f"Normalized offer at index {index} has an empty source_id.")
        free_work_id = str(source_id)
        if free_work_id in seen:
            raise ValueError(f"Duplicate Free-Work source_id refused: {free_work_id}")
        seen.add(free_work_id)


def load_normalized_offers(normalized_input):
    """Load and sort normalized offers by source_id."""
    offers = read_json_file(normalized_input)
    validate_normalized_offers(offers)
    return sorted(deepcopy(offers), key=lambda offer: str(offer["source_id"]))


def validate_collection_complete(collection_batch_dir):
    """Validate collection batch has manifest, failed_pages, and resume_state files."""
    manifest_path = collection_batch_dir / "collection_manifest.json"
    failed_pages_path = collection_batch_dir / "failed_pages.json"
    resume_state_path = collection_batch_dir / "resume_state.json"

    missing = [
        str(path)
        for path in [manifest_path, failed_pages_path, resume_state_path]
        if not path.exists()
    ]
    if missing:
        raise ValueError(
            "Collection completeness cannot be proven; missing files: " +
            ", ".join(missing))

    manifest = read_json_file(manifest_path)
    failed_pages = read_json_file(failed_pages_path)
    resume_state = read_json_file(resume_state_path)

    completeness = {
        "collection_manifest_status": manifest.get("status"),
        "collection_manifest_pages_failed": manifest.get("pages_failed"),
        "collection_manifest_pages_requested": manifest.get("pages_requested"),
        "collection_manifest_pages_succeeded": manifest.get("pages_succeeded"),
        "failed_pages_count": len(failed_pages) if isinstance(failed_pages, list) else None,
        "resume_state_next_page_url": resume_state.get("next_page_url"),
    }

    is_complete = (
        manifest.get("status") == "COMPLETED"
        and manifest.get("pages_failed") == 0
        and manifest.get("pages_requested") == manifest.get("pages_succeeded")
        and isinstance(failed_pages, list)
        and len(failed_pages) == 0
        and resume_state.get("next_page_url") is None
    )

    if not is_complete:
        raise ValueError(
            "Collection is not complete enough to allow differential sync and inactivation: "
            + json.dumps(completeness, ensure_ascii=False, sort_keys=True)
        )

    return {
        "manifest_path": str(manifest_path),
        "failed_pages_path": str(failed_pages_path),
        "resume_state_path": str(resume_state_path),
        "collection_manifest": manifest,
        "completeness": completeness,
    }


def verify_catalog_coherence(catalog_root):
    """Verify catalog state files exist and hashes match manifest."""
    current_dir = Path(catalog_root) / "current"
    manifest_path = current_dir / "catalog_manifest.json"
    state_path = current_dir / "catalog_state.json"
    active_path = current_dir / "offers_active.json"

    # If none of the files exist, it is a fresh catalog.
    if not manifest_path.exists() and not state_path.exists() and not active_path.exists():
        return

    # If some files exist but not all, it's incoherent
    if not (manifest_path.exists() and state_path.exists() and active_path.exists()):
        raise ValueError(
            "Incoherent catalog state: one or more current files are missing (partial promotion detected)."  # pylint: disable=line-too-long
        )

    try:
        manifest = read_json_file(manifest_path)
        state = read_json_file(state_path)
        active = read_json_file(active_path)
    except Exception as exc:
        raise ValueError(f"Incoherent catalog state: failed to read JSON files: {exc}") from exc

    # Cross-verify hashes
    calculated_state_sha = sha256_payload(state)
    calculated_active_sha = sha256_payload(active)

    if manifest.get("catalog_state_sha256") != calculated_state_sha:
        raise ValueError(
            "Incoherent catalog state: catalog_state.json hash mismatch against manifest.")

    if manifest.get("offers_active_sha256") != calculated_active_sha:
        raise ValueError(
            "Incoherent catalog state: offers_active.json hash mismatch against manifest.")


def get_collection_input_hashes(collection_batch_dir, normalized_input_path):
    """Compute SHA256 hashes of collection and normalization manifest files."""
    hashes = {}
    for name in ["collection_manifest.json", "failed_pages.json", "resume_state.json"]:
        file_path = collection_batch_dir / name
        if file_path.exists():
            hashes[name] = sha256_file(file_path)

    norm_manifest_path = normalized_input_path.parent / "normalization_manifest.json"
    if norm_manifest_path.exists():
        hashes["normalization_manifest.json"] = sha256_file(norm_manifest_path)

    return hashes


def load_current_state(catalog_root):
    """Load and validate current catalog_state.json."""
    verify_catalog_coherence(catalog_root)
    state_path = catalog_root / "current" / "catalog_state.json"
    if not state_path.exists():
        return []

    state = read_json_file(state_path)
    if not isinstance(state, list):
        raise ValueError("catalog_state.json root must be a JSON list.")

    seen = set()
    for index, entry in enumerate(state):
        if not isinstance(entry, dict):
            raise ValueError(f"Catalog state entry at index {index} must be an object.")
        free_work_id = entry.get("free_work_id")
        if free_work_id is None or str(free_work_id).strip() == "":
            raise ValueError(f"Catalog state entry at index {index} has an empty free_work_id.")
        free_work_id = str(free_work_id)
        if free_work_id in seen:
            raise ValueError(f"Duplicate catalog free_work_id refused: {free_work_id}")
        seen.add(free_work_id)
    return sorted(state, key=lambda entry: str(entry["free_work_id"]))


def make_state_entry(free_work_id, offer, content_hash, now, source_batch_id, change_type):
    """Create catalog state entry with offer, hashes, and change tracking."""
    return {
        "free_work_id": free_work_id,
        "is_active": True,
        "first_seen_at": now,
        "last_seen_at": now,
        "inactive_since": None,
        "content_hash": content_hash,
        "content_hash_version": CONTENT_HASH_VERSION,
        "source_batch_id": source_batch_id,
        "last_change_type": change_type,
        "offer": offer,
    }


def change_log_entry(
        change_type,
        free_work_id,
        now,
        previous_entry=None,
        next_entry=None,
        changed_fields=None):
    """Create change log entry with old/new hashes and changed fields."""
    previous_hash = previous_entry.get("content_hash") if previous_entry else None
    next_hash = next_entry.get("content_hash") if next_entry else None
    entry = {
        "changed_at": now,
        "change_type": change_type,
        "free_work_id": free_work_id,
        "previous_content_hash": previous_hash,
        "new_content_hash": next_hash,
    }
    if changed_fields is not None:
        entry["changed_fields"] = changed_fields
    return entry


def build_diff(previous_state, next_offers, source_batch_id, now):
    """Compute differential between previous and next catalog with change classification."""
    previous_by_id = {str(entry["free_work_id"]): entry for entry in previous_state}
    next_by_id = {str(offer["source_id"]): offer for offer in next_offers}

    next_state_by_id = {}
    buckets = {
        "NEW": [],
        "UPDATED": [],
        "UNCHANGED": [],
        "REACTIVATED": [],
        "INACTIVATED": [],
    }
    change_log = []

    for free_work_id in sorted(next_by_id):
        offer = next_by_id[free_work_id]
        next_hash = business_hash(offer)
        previous_entry = previous_by_id.get(free_work_id)

        if previous_entry is None:
            next_entry = make_state_entry(
                free_work_id, offer, next_hash, now, source_batch_id, "NEW")
            buckets["NEW"].append(next_entry)
            change_log.append(change_log_entry("NEW", free_work_id, now, next_entry=next_entry))
        else:
            previous_offer = previous_entry.get("offer", {})
            common = deepcopy(previous_entry)
            common.update(
                {
                    "is_active": True,
                    "last_seen_at": now,
                    "inactive_since": None,
                    "content_hash": next_hash,
                    "content_hash_version": CONTENT_HASH_VERSION,
                    "source_batch_id": source_batch_id,
                    "offer": offer,
                }
            )

            if not previous_entry.get("is_active", True):
                fields = changed_business_fields(previous_offer, offer)
                common["last_change_type"] = "REACTIVATED"
                common["content_changed_on_reactivation"] = bool(fields)
                if fields:
                    common["changed_fields_on_reactivation"] = fields
                buckets["REACTIVATED"].append(common)
                change_log.append(
                    change_log_entry(
                        "REACTIVATED",
                        free_work_id,
                        now,
                        previous_entry=previous_entry,
                        next_entry=common,
                        changed_fields=fields,
                    )
                )
            elif previous_entry.get("content_hash") == next_hash:
                common["last_change_type"] = "UNCHANGED"
                buckets["UNCHANGED"].append(common)
            else:
                fields = changed_business_fields(previous_offer, offer)
                common["last_change_type"] = "UPDATED"
                common["changed_fields"] = fields
                buckets["UPDATED"].append(common)
                change_log.append(
                    change_log_entry(
                        "UPDATED",
                        free_work_id,
                        now,
                        previous_entry=previous_entry,
                        next_entry=common,
                        changed_fields=fields,
                    )
                )

            next_entry = common

        next_state_by_id[free_work_id] = next_entry

    for free_work_id in sorted(previous_by_id):
        previous_entry = previous_by_id[free_work_id]
        if free_work_id in next_by_id:
            continue
        preserved = deepcopy(previous_entry)
        if previous_entry.get("is_active", True):
            preserved["is_active"] = False
            preserved["inactive_since"] = now
            preserved["last_change_type"] = "INACTIVATED"
            preserved["source_batch_id"] = source_batch_id
            buckets["INACTIVATED"].append(preserved)
            change_log.append(
                change_log_entry(
                    "INACTIVATED",
                    free_work_id,
                    now,
                    previous_entry=previous_entry,
                    next_entry=preserved))
        next_state_by_id[free_work_id] = preserved

    next_state = [next_state_by_id[key] for key in sorted(next_state_by_id)]
    return next_state, buckets, change_log


def compact_deactivation_entry(entry):
    """Extract compact deactivation record from full state entry."""
    offer = entry.get("offer") or {}
    return {
        "free_work_id": entry["free_work_id"],
        "inactive_since": entry.get("inactive_since"),
        "last_seen_at": entry.get("last_seen_at"),
        "content_hash": entry.get("content_hash"),
        "title": offer.get("title"),
        "company_name": offer.get("company_name"),
        "source_batch_id": entry.get("source_batch_id"),
    }


def validate_invariants(next_state, buckets, next_offers):
    """Validate catalog state uniqueness and bucket consistency."""
    state_ids = [entry["free_work_id"] for entry in next_state]
    if len(state_ids) != len(set(state_ids)):
        raise ValueError("Invariant failed: catalog_state contains duplicate free_work_id.")

    active_ids = [entry["free_work_id"] for entry in next_state if entry.get("is_active")]
    if len(active_ids) != len(set(active_ids)):
        raise ValueError("Invariant failed: active catalog contains duplicate free_work_id.")

    bucket_total = sum(len(rows) for rows in buckets.values())
    if bucket_total != len(next_offers) + len(buckets["INACTIVATED"]):
        raise ValueError("Invariant failed: bucket counters are inconsistent.")

    for name in buckets:
        if name not in CHANGE_TYPES:
            raise ValueError(f"Invariant failed: unexpected change type {name}.")


def write_progress(run_dir, status, stage, started_at, error=None):
    """Write sync progress status with stage and optional error."""
    payload = {
        "schema_version": SYNC_SCHEMA_VERSION,
        "status": status,
        "stage": stage,
        "started_at": started_at,
        "updated_at": utc_now_iso(),
    }
    if error:
        payload["error"] = str(error)
    write_json_atomic(run_dir / "sync_progress.json", payload)


def source_batch_id_from(collection_info, collection_batch_dir):
    """Extract source batch ID from collection manifest or directory name."""
    manifest_batch_id = collection_info["collection_manifest"].get("batch_id")
    if manifest_batch_id:
        return str(manifest_batch_id)
    return collection_batch_dir.name


def build_manifest(
    run_id,
    normalized_input,
    collection_batch_dir,
    catalog_root,
    collection_info,
    previous_state,
    next_state,
    buckets,
    started_at,
    completed_at,
    duration_seconds,
    mode,
    collection_input_hashes,
):
    """Build sync manifest with metadata, counters, and file hashes."""
    active_offers_before = sum(1 for entry in previous_state if entry.get("is_active"))
    active_offers_after = sum(1 for entry in next_state if entry.get("is_active"))
    known_offers_before = len(previous_state)
    known_offers_after = len(next_state)
    inactive_offers_after = known_offers_after - active_offers_after

    active_ids = [entry["free_work_id"] for entry in next_state if entry.get("is_active")]
    unique_active_offer_ids = len(set(active_ids))

    return {
        "sync_schema_version": SYNC_SCHEMA_VERSION,
        "schema_version": SYNC_SCHEMA_VERSION,
        "content_hash_version": CONTENT_HASH_VERSION,
        "run_id": run_id,
        "generation_id": run_id,
        "mode": mode,
        "status": "COMPLETED",
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
        "source_batch_id": source_batch_id_from(collection_info, collection_batch_dir),
        "normalized_input": str(normalized_input),
        "normalized_input_sha256": sha256_file(normalized_input),
        "collection_batch_dir": str(collection_batch_dir),
        "collection_completeness": collection_info["completeness"],
        "collection_input_hashes": collection_input_hashes,
        "catalog_root": str(catalog_root),
        "previous_catalog_entries": known_offers_before,
        "catalog_entries": known_offers_after,
        "active_offers": active_offers_after,
        "inactive_offers": inactive_offers_after,
        "counts": {name: len(buckets[name]) for name in sorted(buckets)},
        "active_offers_before": active_offers_before,
        "active_offers_after": active_offers_after,
        "known_offers_before": known_offers_before,
        "known_offers_after": known_offers_after,
        "inactive_offers_after": inactive_offers_after,
        "unique_active_offer_ids": unique_active_offer_ids,
        "offers_to_process": len(buckets["NEW"]) + len(buckets["UPDATED"]) + len(buckets["REACTIVATED"]),  # pylint: disable=line-too-long
        "offers_to_deactivate": len(buckets["INACTIVATED"]),
        "business_fields_hashed": BUSINESS_FIELDS,
        "technical_fields_excluded_from_hash": TECHNICAL_FIELDS_EXCLUDED_FROM_HASH,
    }


def write_run_artifacts(run_dir, buckets, change_log, manifest):
    """Write run artifacts (new/updated/unchanged/inactivated offers and change log)."""
    write_json_atomic(run_dir / "new_offers.json", buckets["NEW"])
    write_json_atomic(run_dir / "updated_offers.json", buckets["UPDATED"])
    write_json_atomic(run_dir / "reactivated_offers.json", buckets["REACTIVATED"])
    write_json_atomic(run_dir / "unchanged_offer_ids.json",
                      [entry["free_work_id"] for entry in buckets["UNCHANGED"]])
    write_json_atomic(run_dir / "inactivated_offers.json", buckets["INACTIVATED"])
    write_json_atomic(
        run_dir /
        "offers_to_process.json",
        buckets["NEW"] +
        buckets["UPDATED"] +
        buckets["REACTIVATED"])
    write_json_atomic(run_dir / "offers_to_deactivate.json",
                      [compact_deactivation_entry(entry) for entry in buckets["INACTIVATED"]])
    write_jsonl_atomic(run_dir / "change_log.jsonl", change_log)
    write_json_atomic(run_dir / "sync_manifest.json", manifest)


def write_current_catalog(catalog_root, run_id, next_state, manifest):
    """Promote run state as current catalog with manifest hashes."""
    current_dir = catalog_root / "current"
    active_offers = [
        deepcopy(entry["offer"])
        for entry in sorted(next_state, key=lambda item: item["free_work_id"])
        if entry.get("is_active")
    ]
    current_manifest = deepcopy(manifest)
    current_manifest["current_run_id"] = run_id
    current_manifest["catalog_state_sha256"] = sha256_payload(next_state)
    current_manifest["offers_active_sha256"] = sha256_payload(active_offers)

    write_json_atomic(current_dir / "catalog_state.json", next_state)
    write_json_atomic(current_dir / "offers_active.json", active_offers)
    current_manifest["catalog_manifest_sha256"] = sha256_payload(current_manifest)
    write_json_atomic(current_dir / "catalog_manifest.json", current_manifest)


def sync_catalog(normalized_input, collection_batch_dir, catalog_root, run_id):
    """Orchestrate full catalog sync with validation, diff, and promotion."""
    normalized_input = Path(normalized_input)
    collection_batch_dir = Path(collection_batch_dir)
    catalog_root = Path(catalog_root)
    run_dir = catalog_root / "runs" / run_id

    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError(f"Run directory already exists and is not empty: {run_dir}")

    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now_iso()
    write_progress(run_dir, "RUNNING", "started", started_at)

    start_time = time.perf_counter()

    try:
        # Determine mode before loading/creating anything
        state_path = catalog_root / "current" / "catalog_state.json"
        mode = "BOOTSTRAP" if not state_path.exists() else "INCREMENTAL"

        next_offers = load_normalized_offers(normalized_input)
        collection_info = validate_collection_complete(collection_batch_dir)
        source_batch_id = source_batch_id_from(collection_info, collection_batch_dir)
        previous_state = load_current_state(catalog_root)

        write_progress(run_dir, "RUNNING", "diff", started_at)
        now = utc_now_iso()
        next_state, buckets, change_log = build_diff(
            previous_state, next_offers, source_batch_id, now)
        validate_invariants(next_state, buckets, next_offers)

        # Confirm unique active offer ids
        active_ids = [entry["free_work_id"] for entry in next_state if entry.get("is_active")]
        if len(active_ids) != len(set(active_ids)):
            raise ValueError("Invariant failed: active catalog contains duplicate free_work_id.")

        completed_at = utc_now_iso()
        duration_seconds = time.perf_counter() - start_time
        collection_input_hashes = get_collection_input_hashes(
            collection_batch_dir, normalized_input)

        manifest = build_manifest(
            run_id=run_id,
            normalized_input=normalized_input,
            collection_batch_dir=collection_batch_dir,
            catalog_root=catalog_root,
            collection_info=collection_info,
            previous_state=previous_state,
            next_state=next_state,
            buckets=buckets,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            mode=mode,
            collection_input_hashes=collection_input_hashes,
        )

        write_progress(run_dir, "RUNNING", "write_run_artifacts", started_at)
        write_run_artifacts(run_dir, buckets, change_log, manifest)

        write_progress(run_dir, "RUNNING", "promote_current", started_at)
        write_current_catalog(catalog_root, run_id, next_state, manifest)

        write_progress(run_dir, "COMPLETED", "completed", started_at)
        return manifest
    except Exception as exc:
        write_progress(run_dir, "FAILED", "failed", started_at, error=exc)
        raise


def parse_args():
    """Parse command-line arguments for catalog sync."""
    parser = argparse.ArgumentParser(
        description="Synchronise offline a normalized Free-Work catalog snapshot with the current local catalog.")  # pylint: disable=line-too-long
    parser.add_argument("--normalized-input", required=True, type=Path)
    parser.add_argument("--collection-batch-dir", required=True, type=Path)
    parser.add_argument("--catalog-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


def main():
    """Main entry point for catalog sync."""
    args = parse_args()
    manifest = sync_catalog(
        normalized_input=args.normalized_input,
        collection_batch_dir=args.collection_batch_dir,
        catalog_root=args.catalog_root,
        run_id=args.run_id,
    )
    print(json.dumps({"status": "COMPLETED", "run_id": args.run_id,
          "counts": manifest["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
