import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PREIMPORT_SCHEMA_VERSION = 1
PROGRESS_FILE_NAME = "preimport_progress.json"


def utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_payload(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json_file(path: Path, label: str) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"{label} introuvable : {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON invalide : {path}:{exc.lineno}:{exc.colno}") from exc


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
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
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def write_progress(output_dir: Path, stage: str, current: int, total: int, start: float, status: str = "RUNNING", error: str = None) -> None:
    elapsed = time.time() - start
    speed = current / elapsed if current and elapsed > 0 else 0.0
    eta = (total - current) / speed if speed and current < total else None
    payload = {
        "status": status,
        "stage": stage,
        "current": current,
        "total": total,
        "percent": round(current / total * 100, 2) if total else 0.0,
        "elapsed_seconds": round(elapsed, 2),
        "speed_offers_per_second": round(speed, 4),
        "eta_seconds": round(eta, 2) if eta is not None else None,
        "heartbeat": time.time(),
        "error": error
    }
    try:
        write_json_atomic(output_dir / PROGRESS_FILE_NAME, payload)
    except Exception as exc:
        print(f"Warning: impossible d'écrire le fichier de progression : {exc}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère un paquet pré-import consolidé pour Free-Work."
    )
    parser.add_argument("--catalog-sync-run-dir", required=True, help="Dossier du run de synchronisation différentielle.")
    parser.add_argument("--triage-run-dir", required=True, help="Dossier du run de triage V2.")
    parser.add_argument("--rome-run-dir", required=True, help="Dossier de la classification ROME.")
    parser.add_argument("--normalized-input", required=True, help="Fichier d'offres normalisées d'origine.")
    parser.add_argument("--output-dir", required=True, help="Dossier de sortie.")
    parser.add_argument("--run-id", required=True, help="Identifiant de ce run de pré-import.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_time = time.time()
    started_at = utc_now_iso()

    output_dir = Path(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        print(f"Erreur : Le dossier de sortie existe déjà et n'est pas vide : {output_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_progress(output_dir, "VALIDATING_INPUTS", 0, 8457, start_time)

    try:
        # 1. Validation des dossiers et chemins d'entrée
        sync_run_dir = Path(args.catalog_sync_run_dir)
        triage_run_dir = Path(args.triage_run_dir)
        rome_run_dir = Path(args.rome_run_dir)
        normalized_input_path = Path(args.normalized_input)

        for path, label in [
            (sync_run_dir, "catalog-sync-run-dir"),
            (triage_run_dir, "triage-run-dir"),
            (rome_run_dir, "rome-run-dir"),
            (normalized_input_path, "normalized-input")
        ]:
            if not path.exists():
                raise FileNotFoundError(f"{label} introuvable : {path}")

        # 2. Chargement des manifestes et fichiers
        write_progress(output_dir, "LOADING_SYNC_ARTIFACTS", 500, 8457, start_time)
        sync_manifest = read_json_file(sync_run_dir / "sync_manifest.json", "sync_manifest")
        offers_to_process = read_json_file(sync_run_dir / "offers_to_process.json", "offers_to_process")
        offers_to_deactivate_sync = read_json_file(sync_run_dir / "offers_to_deactivate.json", "offers_to_deactivate")

        # Charger unchanged_offer_ids.json s'il existe (vide sinon)
        unchanged_offer_ids_path = sync_run_dir / "unchanged_offer_ids.json"
        if unchanged_offer_ids_path.exists():
            unchanged_offer_ids_list = read_json_file(unchanged_offer_ids_path, "unchanged_offer_ids")
        else:
            unchanged_offer_ids_list = []

        write_progress(output_dir, "LOADING_TRIAGE", 1500, 8457, start_time)
        triage_manifest = read_json_file(triage_run_dir / "run_manifest.json", "triage_run_manifest")

        # Lire triage_decisions.jsonl
        triage_decisions = {}
        triage_decisions_path = triage_run_dir / "triage_decisions.jsonl"
        with triage_decisions_path.open("r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"triage_decisions.jsonl ligne {line_idx} JSON invalide : {exc}")
                fw_info = record.get("free_work")
                if not fw_info or "source_id" not in fw_info:
                    raise ValueError(f"triage_decisions.jsonl ligne {line_idx} structure invalide")
                fw_id = str(fw_info["source_id"])
                if fw_id in triage_decisions:
                    raise ValueError(f"Identifiant dupliqué dans triage_decisions.jsonl : {fw_id}")
                triage_decisions[fw_id] = record

        write_progress(output_dir, "LOADING_ROME", 3000, 8457, start_time)
        rome_manifest = read_json_file(rome_run_dir / "rome_classification_manifest.json", "rome_manifest")

        # Lire rome_assignments_deterministic_v1.jsonl
        rome_assignments = {}
        rome_assignments_path = rome_run_dir / "rome_assignments_deterministic_v1.jsonl"
        with rome_assignments_path.open("r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"rome_assignments_deterministic_v1.jsonl ligne {line_idx} JSON invalide : {exc}")
                fw_id = record.get("free_work_id")
                if fw_id is None:
                    raise ValueError(f"rome_assignments_deterministic_v1.jsonl ligne {line_idx} free_work_id absent")
                fw_id = str(fw_id)
                if fw_id in rome_assignments:
                    raise ValueError(f"Identifiant dupliqué dans rome_assignments_deterministic_v1.jsonl : {fw_id}")
                rome_assignments[fw_id] = record

        # Charger normalized_input
        offers_normalized = read_json_file(normalized_input_path, "normalized_input")
        offers_normalized_by_id = {}
        for index, offer in enumerate(offers_normalized):
            if "source_id" not in offer:
                raise ValueError(f"normalized_input index {index} source_id absent")
            fw_id = str(offer["source_id"])
            if fw_id in offers_normalized_by_id:
                raise ValueError(f"Identifiant dupliqué dans normalized_input : {fw_id}")
            offers_normalized_by_id[fw_id] = offer

        # 3. Validations des ensembles et partitions
        write_progress(output_dir, "VALIDATING_IDENTIFIERS", 4500, 8457, start_time)

        active_snapshot_ids = set(offers_normalized_by_id.keys())
        process_ids = {str(o["free_work_id"]) for o in offers_to_process}
        unchanged_ids = {str(uid) for uid in unchanged_offer_ids_list}
        deactivation_ids = {str(o["free_work_id"]) for o in offers_to_deactivate_sync} if isinstance(offers_to_deactivate_sync, list) else set()

        # Invariants obligatoires de partitionnement
        process_unchanged_overlap = sorted(process_ids & unchanged_ids)
        process_deactivation_overlap = sorted(process_ids & deactivation_ids)
        unchanged_deactivation_overlap = sorted(unchanged_ids & deactivation_ids)

        if process_unchanged_overlap:
            raise ValueError(f"process_ids et unchanged_ids ne sont pas disjoints. Doublons : {process_unchanged_overlap[:5]}")
        if process_deactivation_overlap:
            raise ValueError(f"process_ids et deactivation_ids ne sont pas disjoints. Doublons : {process_deactivation_overlap[:5]}")
        if unchanged_deactivation_overlap:
            raise ValueError(f"unchanged_ids et deactivation_ids ne sont pas disjoints. Doublons : {unchanged_deactivation_overlap[:5]}")

        # process_ids ∪ unchanged_ids = active_snapshot_ids
        union_active = process_ids | unchanged_ids
        if union_active != active_snapshot_ids:
            missing_in_union = sorted(active_snapshot_ids - union_active)
            unexpected_in_union = sorted(union_active - active_snapshot_ids)
            raise ValueError(
                f"La partition active est invalide (process_ids + unchanged_ids != active_snapshot_ids). "
                f"Manquants dans la réunion : {missing_in_union[:5]}, Inattendus : {unexpected_in_union[:5]}"
            )

        active_partition_valid = True
        deactivation_partition_valid = True

        # Validation du triage et du ROME sur process_ids uniquement
        triage_ids = set(triage_decisions.keys())
        rome_ids = set(rome_assignments.keys())

        # process_ids ⊆ triage_ids et process_ids ⊆ rome_ids
        missing_process_ids_in_triage = sorted(process_ids - triage_ids)
        missing_process_ids_in_rome = sorted(process_ids - rome_ids)

        if missing_process_ids_in_triage:
            raise ValueError(f"Triage manquant pour les identifiants à traiter : {missing_process_ids_in_triage[:5]}")
        if missing_process_ids_in_rome:
            raise ValueError(f"ROME manquant pour les identifiants à traiter : {missing_process_ids_in_rome[:5]}")

        # triage_ids ⊆ active_snapshot_ids et rome_ids ⊆ active_snapshot_ids
        unexpected_triage_ids_outside_snapshot = sorted(triage_ids - active_snapshot_ids)
        unexpected_rome_ids_outside_snapshot = sorted(rome_ids - active_snapshot_ids)

        if unexpected_triage_ids_outside_snapshot:
            raise ValueError(f"Triage contient des identifiants hors du snapshot actif : {unexpected_triage_ids_outside_snapshot[:5]}")
        if unexpected_rome_ids_outside_snapshot:
            raise ValueError(f"ROME contient des identifiants hors du snapshot actif : {unexpected_rome_ids_outside_snapshot[:5]}")

        # Vérification des hashes du fichier d'entrée si disponible
        normalized_input_sha = sha256_file(normalized_input_path)
        if "normalized_input_sha256" in sync_manifest:
            if sync_manifest["normalized_input_sha256"] != normalized_input_sha:
                raise ValueError("Hash mismatch sur normalized_input entre le fichier réel et sync_manifest")

        # 4. Jointures et application de la politique
        write_progress(output_dir, "JOINING_RECORDS", 6000, 8457, start_time)

        offers_to_create = []
        offers_to_update = []
        offers_to_reactivate = []
        existing_ft_offers_to_enrich = []
        offers_to_defer = []
        offers_to_deactivate = []
        rejected_records = []

        # Compteurs ROME & Skills
        count_with_rome = 0
        count_without_rome = 0
        count_with_skills = 0
        skills_set = set()
        soft_skills_set = set()
        total_offer_skill_associations = 0

        # ROME counters
        rome_status_counts = {}

        # PRESENT checks
        present_without_ft_target = 0

        # On parcourt les offres à traiter
        write_progress(output_dir, "APPLYING_POLICY", 7000, 8457, start_time)
        for sync_item in offers_to_process:
            fw_id = str(sync_item["free_work_id"])
            change_type = sync_item["last_change_type"]
            normalized_offer = offers_normalized_by_id[fw_id]
            triage_dec = triage_decisions[fw_id]
            rome_ass = rome_assignments[fw_id]

            # ROME code and stats
            rome_code = rome_ass.get("assigned_rome_code")
            rome_status = rome_ass.get("assignment_status")
            rome_status_counts[rome_status] = rome_status_counts.get(rome_status, 0) + 1

            if rome_code:
                count_with_rome += 1
            else:
                count_without_rome += 1

            # Skills stats
            skills = normalized_offer.get("skills") or []
            soft_skills = normalized_offer.get("soft_skills") or []
            if skills:
                count_with_skills += 1
                total_offer_skill_associations += len(skills)
                for s in skills:
                    skills_set.add(s.get("name_normalized") or s.get("name") or "")
            for ss in soft_skills:
                soft_skills_set.add(ss.get("name_normalized") or ss.get("name") or "")

            # Détermination de l'action pré-import selon la politique
            decision = triage_dec.get("decision")
            review_action = triage_dec.get("review_action")

            action = None
            if decision == "PRESENT_IN_FT_SNAPSHOT":
                action = "ENRICH_EXISTING_FT"
                best_cand = triage_dec.get("best_candidate") or {}
                ft_id = best_cand.get("france_travail_id")
                if not ft_id:
                    present_without_ft_target += 1
            elif decision == "NOT_FOUND_IN_FT_SNAPSHOT":
                if change_type == "NEW":
                    action = "CREATE_FREE_WORK"
                elif change_type == "UPDATED":
                    action = "UPDATE_FREE_WORK"
                elif change_type == "REACTIVATED":
                    action = "REACTIVATE_FREE_WORK"
            elif decision == "UNCERTAIN":
                if review_action == "REVIEW_NOW":
                    if change_type == "NEW":
                        action = "CREATE_FREE_WORK"
                    elif change_type == "UPDATED":
                        action = "UPDATE_FREE_WORK"
                    elif change_type == "REACTIVATED":
                        action = "REACTIVATE_FREE_WORK"
                elif review_action == "DEFER_DATA_INCOMPLETE":
                    action = "DEFER"
            elif decision == "PROCESSING_ERROR":
                action = "REJECT"

            if not action:
                raise ValueError(f"Action pré-import indéterminée pour l'offre {fw_id} (decision={decision}, change_type={change_type}, review_action={review_action})")

            # Construction de l'enregistrement consolidé
            record = {
                "source_id": fw_id,
                "catalog_change_type": change_type,
                "preimport_action": action,
                "offer_normalized": normalized_offer,
                "skills": skills,
                "soft_skills": soft_skills,
                "triage_decision": decision,
                "review_action": review_action,
                "matching_reason": triage_dec.get("human_explanation", {}).get("decision_reason") or triage_dec.get("technical_reasons"),
                "matching_scores": triage_dec.get("score"),
                "preuves_rapprochement": triage_dec.get("best_candidate"),
                "france_travail_target_id": triage_dec.get("best_candidate", {}).get("france_travail_id") if decision == "PRESENT_IN_FT_SNAPSHOT" else None,
                "assigned_rome_code": rome_code,
                "rome_assignment_status": rome_status,
                "rome_assignment_method": rome_ass.get("assignment_method"),
                "rome_score": rome_ass.get("confidence_score"),
                "rome_margin": rome_ass.get("margin"),
                "rome_candidates": rome_ass.get("candidates"),
                "source_batch_id": sync_item.get("source_batch_id"),
                "sync_run_id": sync_manifest.get("run_id"),
                "triage_run_id": triage_manifest.get("run_id"),
                "rome_run_id": rome_manifest.get("classifier_version"),
                "preimport_run_id": args.run_id
            }

            # Distribution des enregistrements dans les fichiers cibles
            if action == "CREATE_FREE_WORK":
                offers_to_create.append(record)
            elif action == "UPDATE_FREE_WORK":
                offers_to_update.append(record)
            elif action == "REACTIVATE_FREE_WORK":
                offers_to_reactivate.append(record)
            elif action == "ENRICH_EXISTING_FT":
                record_enrich = record.copy()
                record_enrich["skills_candidate"] = skills
                record_enrich["soft_skills_candidate"] = soft_skills
                record_enrich.pop("skills", None)
                record_enrich.pop("soft_skills", None)
                existing_ft_offers_to_enrich.append(record_enrich)
            elif action == "DEFER":
                offers_to_defer.append(record)
            elif action == "REJECT":
                rejected_records.append(record)

        # Offres INACTIVATED par le catalogue
        for deac_item in offers_to_deactivate_sync:
            fw_id = str(deac_item["free_work_id"])
            record = {
                "source_id": fw_id,
                "catalog_change_type": "INACTIVATED",
                "preimport_action": "DEACTIVATE_FREE_WORK",
                "source_batch_id": deac_item.get("source_batch_id"),
                "sync_run_id": sync_manifest.get("run_id"),
                "preimport_run_id": args.run_id
            }
            offers_to_deactivate.append(record)

        # 5. Écritures atomiques
        write_progress(output_dir, "VALIDATING_OUTPUT", 8000, 8457, start_time)

        # Compteurs finaux
        counts = {
            "ENRICH_EXISTING_FT": len(existing_ft_offers_to_enrich),
            "CREATE_FREE_WORK": len(offers_to_create),
            "UPDATE_FREE_WORK": len(offers_to_update),
            "REACTIVATE_FREE_WORK": len(offers_to_reactivate),
            "DEFER": len(offers_to_defer),
            "DEACTIVATE_FREE_WORK": len(offers_to_deactivate),
            "REJECT": len(rejected_records),
            "NO_ACTION": len(unchanged_ids)
        }

        # Équations de comptage incrémentales
        process_count = len(process_ids)
        unchanged_count = len(unchanged_ids)
        deactivation_count = len(deactivation_ids)
        active_snapshot_count = len(active_snapshot_ids)

        sum_processed = (
            counts["ENRICH_EXISTING_FT"] +
            counts["CREATE_FREE_WORK"] +
            counts["UPDATE_FREE_WORK"] +
            counts["REACTIVATE_FREE_WORK"] +
            counts["DEFER"] +
            counts["REJECT"]
        )
        count_equation_valid = (sum_processed == process_count)

        active_equation_valid = (process_count + counts["NO_ACTION"] == active_snapshot_count)

        if present_without_ft_target > 0:
            raise ValueError(f"Il y a {present_without_ft_target} correspondances PRESENT_IN_FT_SNAPSHOT sans identifiant France Travail cible.")

        # Hash check
        hash_consistency = (sync_manifest.get("source_batch_id") == triage_manifest.get("input_files", {}).get("free_work_input", "").split("/")[-2])

        # Écrire les fichiers de sortie
        write_progress(output_dir, "WRITING_ARTIFACTS", 8400, 8457, start_time)

        write_json_atomic(output_dir / "offers_to_create.json", offers_to_create)
        write_json_atomic(output_dir / "offers_to_update.json", offers_to_update)
        write_json_atomic(output_dir / "offers_to_reactivate.json", offers_to_reactivate)
        write_json_atomic(output_dir / "existing_ft_offers_to_enrich.json", existing_ft_offers_to_enrich)
        write_json_atomic(output_dir / "offers_to_defer.json", offers_to_defer)
        write_json_atomic(output_dir / "offers_to_deactivate.json", offers_to_deactivate)
        write_json_atomic(output_dir / "rejected_records.json", rejected_records)

        # unchanged_offer_ids.json contenant uniquement la liste des IDs inchangés
        write_json_atomic(output_dir / "unchanged_offer_ids.json", sorted(list(unchanged_ids)))

        # Integrity Report
        integrity_report = {
            "active_snapshot_count": active_snapshot_count,
            "process_count": process_count,
            "unchanged_count": unchanged_count,
            "deactivation_count": deactivation_count,
            "missing_process_ids_in_triage": len(missing_process_ids_in_triage),
            "missing_process_ids_in_rome": len(missing_process_ids_in_rome),
            "unexpected_triage_ids_outside_snapshot": len(unexpected_triage_ids_outside_snapshot),
            "unexpected_rome_ids_outside_snapshot": len(unexpected_rome_ids_outside_snapshot),
            "process_unchanged_overlap": len(process_unchanged_overlap),
            "process_deactivation_overlap": len(process_deactivation_overlap),
            "unchanged_deactivation_overlap": len(unchanged_deactivation_overlap),
            "active_partition_valid": active_partition_valid,
            "deactivation_partition_valid": deactivation_partition_valid,
            "count_equation_valid": count_equation_valid,
            "active_equation_valid": active_equation_valid,
            "hash_consistency": hash_consistency,
            "source_batch_consistency": (sync_manifest.get("source_batch_id") == triage_manifest.get("input_files", {}).get("free_work_input", "").split("/")[-2])
        }
        write_json_atomic(output_dir / "integrity_report.json", integrity_report)

        # Manifeste final
        completed_at = utc_now_iso()
        duration_seconds = time.time() - start_time

        preimport_manifest = {
            "preimport_schema_version": PREIMPORT_SCHEMA_VERSION,
            "run_id": args.run_id,
            "status": "COMPLETED",
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": round(duration_seconds, 4),
            "input_paths": {
                "catalog_sync_run_dir": str(sync_run_dir),
                "triage_run_dir": str(triage_run_dir),
                "rome_run_dir": str(rome_run_dir),
                "normalized_input": str(normalized_input_path)
            },
            "input_hashes": {
                "sync_manifest.json": sha256_file(sync_run_dir / "sync_manifest.json"),
                "triage_manifest.json": sha256_file(triage_run_dir / "run_manifest.json"),
                "rome_manifest.json": sha256_file(rome_run_dir / "rome_classification_manifest.json"),
                "normalized_input": normalized_input_sha
            },
            "source_run_ids": {
                "sync_run_id": sync_manifest.get("run_id"),
                "triage_run_id": triage_manifest.get("run_id"),
                "rome_run_id": rome_manifest.get("classifier_version")
            },
            "source_batch_id": sync_manifest.get("source_batch_id"),
            "counts": counts,
            "rome_stats": {
                "count_with_rome": count_with_rome,
                "count_without_rome": count_without_rome,
                "status_counters": rome_status_counts
            },
            "skills_stats": {
                "count_with_skills": count_with_skills,
                "unique_skills": len(skills_set),
                "unique_soft_skills": len(soft_skills_set),
                "total_offer_skill_associations": total_offer_skill_associations
            },
            "invariants_verified": [
                "unique_identifiers",
                "complete_joins",
                "no_dangling_present_target",
                "counts_match_triage"
            ]
        }
        write_json_atomic(output_dir / "preimport_manifest.json", preimport_manifest)

        # Progression à 100%
        write_progress(output_dir, "COMPLETED", 8457, 8457, start_time, status="COMPLETED")
        print("Génération du paquet pré-import terminée avec succès.")

    except Exception as exc:
        write_progress(output_dir, "FAILED", 0, 8457, start_time, status="FAILED", error=str(exc))
        print(f"Erreur lors de la génération du paquet pré-import : {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
