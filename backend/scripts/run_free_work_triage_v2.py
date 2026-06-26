from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT

from backend.scripts.free_work_triage_v2 import (
    TRIAGE_RULESET_V2_CANDIDATE,
    TriageThresholds,
    build_france_travail_lookup,
    build_skill_statistics,
    canonical_source_id,
    candidate_score,
    count_job_postings_urls,
    import_candidate_from_record,
    make_decision_record,
    review_row_from_record,
    sha256_file,
    write_review_queue,
)
from backend.scripts.triage_free_work_matches import classify_triage, extraire_tokens


PROGRESS_FILE_NAME = "triage_progress.json"


class CounterDict(defaultdict):
    def __init__(self):
        super().__init__(int)

    def add(self, key: str) -> None:
        self[str(key)] += 1

    def to_dict(self) -> dict[str, int]:
        return dict(sorted(self.items()))


def write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp_path.write_bytes(content)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def write_json_atomic(path: Path, payload: Any) -> None:
    write_bytes_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


def load_json_file(path: Path, label: str) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"{label} introuvable : {path}")
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON invalide : {path}:{exc.lineno}:{exc.colno}") from exc


def require_list(data: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError(f"{label} doit être une liste JSON.")
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"{label}[{index}] doit être un objet JSON.")
    return data


def validate_unique(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        value = canonical_source_id(row.get(key))
        if value is None:
            raise ValueError(f"{label}[{index}] : champ obligatoire absent ou vide : {key}")
        if value in lookup:
            raise ValueError(f"{label} contient un identifiant dupliqué : {value}")
        lookup[value] = row
    return lookup


def validate_candidate_matches(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup = validate_unique(rows, "free_work_source_id", "candidate_matches")
    for source_id, row in lookup.items():
        for key in ("free_work_title", "free_work_title_normalized", "top_candidates"):
            if key not in row:
                raise ValueError(f"candidate_matches[{source_id}] : champ obligatoire absent : {key}")
        candidates = row.get("top_candidates")
        if not isinstance(candidates, list):
            raise ValueError(f"candidate_matches[{source_id}].top_candidates doit être une liste.")
    return lookup


def validate_normalized_offers(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup = validate_unique(rows, "source_id", "offers_normalized")
    for source_id, row in lookup.items():
        if "title" not in row:
            raise ValueError(f"offers_normalized[{source_id}] : champ obligatoire absent : title")
    return lookup


def validate_france_travail(rows: list[dict[str, Any]]) -> None:
    seen = set()
    for index, row in enumerate(rows):
        france_travail_id = row.get("france_travail_id")
        if france_travail_id is None or not str(france_travail_id).strip():
            raise ValueError(f"france_travail[{index}] : france_travail_id absent ou vide.")
        if str(france_travail_id) in seen:
            raise ValueError(f"france_travail contient un identifiant dupliqué : {france_travail_id}")
        seen.add(str(france_travail_id))
        for key in ("title", "description", "rome_code"):
            if key not in row:
                raise ValueError(f"france_travail[{france_travail_id}] : champ obligatoire absent : {key}")


def write_progress(output_dir: Path, stage: str, current: int, total: int, start: float, status: str = "RUNNING") -> None:
    elapsed = time.time() - start
    speed = current / elapsed if current and elapsed > 0 else 0.0
    eta = (total - current) / speed if speed else None
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
    }
    try:
        write_json_atomic(output_dir / PROGRESS_FILE_NAME, payload)
    except Exception as exc:
        print(f"Warning: impossible d'écrire le fichier de progression : {exc}", file=sys.stderr)


def ensure_output_dir_available(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Le dossier de sortie existe déjà et n'est pas vide : {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def build_triage_entry_from_match(match_entry: dict[str, Any]) -> dict[str, Any]:
    candidates = match_entry.get("top_candidates") or []
    best = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    location = match_entry.get("free_work_location") or {}
    title_normalized = str(match_entry.get("free_work_title_normalized") or "")
    description = match_entry.get("free_work_description_excerpt") or ""
    company = match_entry.get("free_work_company_normalized") or match_entry.get("free_work_company") or ""
    postal_code = str(location.get("postal_code") or "")
    department = str(location.get("department_code") or "")
    tokens = extraire_tokens(title_normalized)
    category, reason_codes = classify_triage(
        {"title": match_entry.get("free_work_title"), "description": description},
        best,
        second,
        len(candidates),
        tokens,
        description,
        company,
        postal_code,
        department,
        str(location.get("locality_normalized") or ""),
        [],
    )
    data_coverage = 45 + (25 if description else 0) + (10 if company else 0) + (15 if postal_code else 0)
    return {
        "free_work_source_id": canonical_source_id(match_entry.get("free_work_source_id")),
        "free_work_title": match_entry.get("free_work_title"),
        "free_work_company": match_entry.get("free_work_company"),
        "free_work_location": location,
        "free_work_source_url": match_entry.get("free_work_source_url") or "",
        "triage_category": category,
        "triage_reason_codes": reason_codes,
        "data_coverage": data_coverage,
        "best_candidate": {
            "france_travail_id": best.get("france_travail_id"),
            "score": candidate_score(best),
        } if best else None,
        "candidate_count": len(candidates),
        "decision_rule_version": "CONSERVATIVE_RULESET_V1_RECONSTRUCTED_FROM_CANDIDATES",
    }


def read_matching_strategy(candidate_matches_input: Path) -> dict[str, Any]:
    manifest_path = candidate_matches_input.parent / "matching_manifest.json"
    if not manifest_path.exists():
        return {"strategy": "UNKNOWN", "use_aliases": None, "manifest_found": False}
    manifest = load_json_file(manifest_path, "matching_manifest")
    if not isinstance(manifest, dict):
        return {"strategy": "UNKNOWN", "use_aliases": None, "manifest_found": False}
    return {
        "strategy": manifest.get("strategy") or "UNKNOWN",
        "use_aliases": manifest.get("use_aliases"),
        "manifest_found": True,
        "manifest_path": str(manifest_path).replace("\\", "/"),
        "manifest_sha256": sha256_file(manifest_path),
    }


def count_review_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return max(0, sum(1 for _ in csv.reader(file, delimiter=";")) - 1)


def run_fresh_triage_v2(
    free_work_input: Path,
    france_travail_input: Path,
    candidate_matches_input: Path,
    output_dir: Path,
) -> dict[str, Any]:
    start = time.time()
    ensure_output_dir_available(output_dir)
    write_progress(output_dir, "VALIDATING_INPUTS", 0, 1, start)
    try:
        free_work_rows = require_list(load_json_file(free_work_input, "offers_normalized"), "offers_normalized")
        france_travail_rows = require_list(load_json_file(france_travail_input, "france_travail_snapshot"), "france_travail_snapshot")
        candidate_matches = require_list(load_json_file(candidate_matches_input, "candidate_matches"), "candidate_matches")

        free_work_lookup = validate_normalized_offers(free_work_rows)
        validate_france_travail(france_travail_rows)
        candidate_lookup = validate_candidate_matches(candidate_matches)
        missing_in_free_work = sorted(set(candidate_lookup) - set(free_work_lookup))
        missing_in_candidates = sorted(set(free_work_lookup) - set(candidate_lookup))
        if missing_in_free_work:
            raise ValueError(f"{len(missing_in_free_work)} candidate_matches sans offre normalisée, exemple : {missing_in_free_work[:5]}")
        if missing_in_candidates:
            raise ValueError(f"{len(missing_in_candidates)} offres normalisées sans candidate_matches, exemple : {missing_in_candidates[:5]}")
        write_progress(output_dir, "VALIDATING_INPUTS", 1, 1, start)

        write_progress(output_dir, "PREPARING_TRIAGE_INPUT", 0, len(candidate_matches), start)
        triage_by_id = {}
        for index, match_entry in enumerate(candidate_matches, start=1):
            source_id = canonical_source_id(match_entry.get("free_work_source_id"))
            triage_by_id[source_id] = build_triage_entry_from_match(match_entry)
            if index % 1000 == 0 or index == len(candidate_matches):
                write_progress(output_dir, "PREPARING_TRIAGE_INPUT", index, len(candidate_matches), start)

        france_travail_lookup = build_france_travail_lookup(france_travail_input)
        counters = CounterDict()
        review_action_counters = CounterDict()
        v1_counters = CounterDict()
        integrity_counters = CounterDict()
        import_candidates = []
        review_rows = []
        decisions = []

        write_progress(output_dir, "TRIAGE_V2", 0, len(candidate_matches), start)
        for index, match_entry in enumerate(candidate_matches, start=1):
            source_id = canonical_source_id(match_entry.get("free_work_source_id"))
            free_work_details = free_work_lookup[source_id]
            best = (match_entry.get("top_candidates") or [None])[0]
            france_travail_offer = france_travail_lookup.get(str((best or {}).get("france_travail_id"))) if best else None
            triage_entry = triage_by_id[source_id]
            v1_counters.add(triage_entry.get("triage_category") or "UNKNOWN")
            record = make_decision_record(
                match_entry,
                triage_entry,
                url_resolution=NoneUrlResolution(match_entry.get("free_work_source_url")),
                thresholds=TriageThresholds(),
                free_work_details=free_work_details,
                france_travail_offer=france_travail_offer,
            )
            expected_skills = free_work_details.get("skills") if isinstance(free_work_details.get("skills"), list) else []
            if expected_skills != (record.get("free_work") or {}).get("skills"):
                integrity_counters.add("skill_propagation_failures")
            else:
                integrity_counters.add("normalized_offers_found")
            counters.add(record["decision"])
            review_action_counters.add(record["review_action"])
            decisions.append(record)
            import_candidate = import_candidate_from_record(record)
            if import_candidate:
                import_candidates.append(import_candidate)
            if record["decision"] == "UNCERTAIN" and record["review_action"] == "REVIEW_NOW":
                review_rows.append(review_row_from_record(record, match_entry.get("top_candidates") or []))
            if index % 1000 == 0 or index == len(candidate_matches):
                write_progress(output_dir, "TRIAGE_V2", index, len(candidate_matches), start)
                elapsed = time.time() - start
                speed = index / elapsed if elapsed else 0.0
                eta = (len(candidate_matches) - index) / speed if speed else 0.0
                print(f"[V2 fresh] {index}/{len(candidate_matches)} - {index / len(candidate_matches) * 100:.2f}% - {speed:.1f} offres/s - ETA {eta:.1f}s")

        write_progress(output_dir, "WRITING_ARTIFACTS", 0, 4, start)
        decisions_bytes = b"".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
            for record in decisions
        )
        write_bytes_atomic(output_dir / "triage_decisions.jsonl", decisions_bytes)
        write_progress(output_dir, "WRITING_ARTIFACTS", 1, 4, start)
        write_json_atomic(output_dir / "import_candidates.json", import_candidates)
        write_progress(output_dir, "WRITING_ARTIFACTS", 2, 4, start)
        review_tmp = output_dir / "review_queue.csv.tmp"
        write_review_queue(review_tmp, review_rows)
        review_tmp.replace(output_dir / "review_queue.csv")
        write_progress(output_dir, "WRITING_ARTIFACTS", 3, 4, start)

        write_progress(output_dir, "VALIDATING_OUTPUTS", 0, 1, start)
        unique_decision_ids = {record["free_work"]["source_id"] for record in decisions}
        if len(decisions) != len(candidate_matches):
            raise ValueError("Nombre de décisions différent du nombre de candidate_matches.")
        if len(unique_decision_ids) != len(decisions):
            raise ValueError("Identifiants de décisions dupliqués dans la sortie.")
        review_csv_rows = count_review_rows(output_dir / "review_queue.csv")
        duration = time.time() - start
        manifest = {
            "run_id": output_dir.name,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "triage_version": TRIAGE_RULESET_V2_CANDIDATE,
            "matching_observed": read_matching_strategy(candidate_matches_input),
            "input_files": {
                "free_work_input": str(free_work_input).replace("\\", "/"),
                "free_work_sha256": sha256_file(free_work_input),
                "france_travail_input": str(france_travail_input).replace("\\", "/"),
                "france_travail_sha256": sha256_file(france_travail_input),
                "candidate_matches_input": str(candidate_matches_input).replace("\\", "/"),
                "candidate_matches_sha256": sha256_file(candidate_matches_input),
            },
            "counts": {
                "free_work_offers": len(free_work_rows),
                "candidate_matches": len(candidate_matches),
                "unique_free_work_ids": len(free_work_lookup),
                "decisions": len(decisions),
                "import_candidates": len(import_candidates),
                "review_queue_rows": review_csv_rows,
            },
            "counters": {
                "total_processed": len(decisions),
                "PRESENT_IN_FT_SNAPSHOT": counters["PRESENT_IN_FT_SNAPSHOT"],
                "NOT_FOUND_IN_FT_SNAPSHOT": counters["NOT_FOUND_IN_FT_SNAPSHOT"],
                "UNCERTAIN": counters["UNCERTAIN"],
                "PROCESSING_ERROR": counters["PROCESSING_ERROR"],
                "review_actions": review_action_counters.to_dict(),
                "v1_reconstructed_categories": v1_counters.to_dict(),
            },
            "thresholds": TriageThresholds().__dict__,
            "duration_seconds": round(duration, 2),
            "status": "COMPLETED",
            "artifact_policy": {
                "main_files": ["run_manifest.json", "triage_decisions.jsonl", "import_candidates.json", "review_queue.csv"],
                "progress_file": PROGRESS_FILE_NAME,
                "overwrite_refused_by_default": True,
            },
            "skill_propagation_integrity": {
                "normalized_offers_found": integrity_counters["normalized_offers_found"],
                "skill_propagation_failures": integrity_counters["skill_propagation_failures"],
            },
        }
        write_json_atomic(output_dir / "run_manifest.json", manifest)
        write_progress(output_dir, "WRITING_ARTIFACTS", 4, 4, start)
        write_progress(output_dir, "COMPLETED", len(candidate_matches), len(candidate_matches), start, status="COMPLETED")
        return manifest
    except Exception:
        write_progress(output_dir, "FAILED", 0, 1, start, status="FAILED")
        raise


class NoneUrlResolution:
    def __init__(self, fallback_url: str | None):
        from backend.scripts.free_work_triage_v2 import resolve_free_work_url

        resolved = resolve_free_work_url(None, fallback_url)
        self.raw_url = resolved.raw_url
        self.absolute_url = resolved.absolute_url
        self.method = resolved.method


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Produit un triage Free-Work V2 complet à partir d'artefacts frais.")
    parser.add_argument("--free-work-input", required=True, help="Chemin vers offers_normalized.json.")
    parser.add_argument("--france-travail-input", required=True, help="Chemin vers france_travail_offers_snapshot.json.")
    parser.add_argument("--candidate-matches-input", required=True, help="Chemin vers candidate_matches.json.")
    parser.add_argument("--output-dir", required=True, help="Dossier de sortie du run V2 frais.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        manifest = run_fresh_triage_v2(
            free_work_input=Path(args.free_work_input),
            france_travail_input=Path(args.france_travail_input),
            candidate_matches_input=Path(args.candidate_matches_input),
            output_dir=Path(args.output_dir),
        )
    except Exception as exc:
        print(f"Erreur triage V2 frais : {exc}", file=sys.stderr)
        sys.exit(1)

    counters = manifest["counters"]
    review_actions = counters["review_actions"]
    print("Triage V2 frais terminé.")
    print(f"Total traité : {counters['total_processed']}")
    print(f"PRESENT_IN_FT_SNAPSHOT : {counters.get('PRESENT_IN_FT_SNAPSHOT', 0)}")
    print(f"NOT_FOUND_IN_FT_SNAPSHOT : {counters.get('NOT_FOUND_IN_FT_SNAPSHOT', 0)}")
    print(f"UNCERTAIN : {counters.get('UNCERTAIN', 0)}")
    print(f"PROCESSING_ERROR : {counters.get('PROCESSING_ERROR', 0)}")
    print(f"Candidats import : {manifest['counts']['import_candidates']}")
    print(f"REVIEW_NOW : {review_actions.get('REVIEW_NOW', 0)}")
    print(f"DEFER_DATA_INCOMPLETE : {review_actions.get('DEFER_DATA_INCOMPLETE', 0)}")
    print(f"NO_MANUAL_REVIEW : {review_actions.get('NO_MANUAL_REVIEW', 0)}")


if __name__ == "__main__":
    main()
