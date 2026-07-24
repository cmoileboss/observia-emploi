"""."""
from scripts.free_work_triage_v2 import replay_triage_v2
import argparse
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"


DEFAULT_SOURCE_RUN = "run_triage_full_20260624"
DEFAULT_TARGET_RUN = "run_triage_v2_handoff_20260624"


def main():
    """Main entry point to replay triage V2 from existing candidate matches."""
    parser = argparse.ArgumentParser(
        description="Rejoue uniquement le triage V2 à partir des correspondances existantes.")
    parser.add_argument("--source-run-id", default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--target-run-id", default=DEFAULT_TARGET_RUN)
    parser.add_argument("--debug-artifacts", action="store_true")
    parser.add_argument("--legacy-artifacts", action="store_true")
    args = parser.parse_args()

    source_dir = PROCESSED_DATA_ROOT / "matching" / "free_work_vs_france_travail" / args.source_run_id  # pylint: disable=line-too-long
    target_dir = PROCESSED_DATA_ROOT / "matching" / "free_work_vs_france_travail" / args.target_run_id  # pylint: disable=line-too-long
    raw_offers_path = RAW_DATA_ROOT / "free_work" / "full_catalog" / \
        "batches" / "20260624_081715" / "offers_deduplicated.json"
    normalized_offers_path = PROCESSED_DATA_ROOT / "free_work" / \
        "full_catalog" / "20260624_081715" / "offers_normalized.json"
    france_travail_snapshot_path = PROCESSED_DATA_ROOT / "france_travail" / \
        "snapshots" / "current" / "france_travail_offers_snapshot.json"

    manifest = replay_triage_v2(
        candidate_matches_path=source_dir / "candidate_matches.json",
        triage_results_path=source_dir / "triage_results.json",
        raw_offers_path=raw_offers_path,
        normalized_offers_path=normalized_offers_path,
        france_travail_snapshot_path=france_travail_snapshot_path,
        output_dir=target_dir,
        run_id=args.target_run_id,
        debug_artifacts=args.debug_artifacts,
        legacy_artifacts=args.legacy_artifacts,
    )

    counters = manifest["counters"]
    print("Triage V2 candidat terminé.")
    print(f"Total traité : {counters['total_processed']}")
    print(f"PRESENT_IN_FT_SNAPSHOT : {counters.get('PRESENT_IN_FT_SNAPSHOT', 0)}")
    print(f"NOT_FOUND_IN_FT_SNAPSHOT : {counters.get('NOT_FOUND_IN_FT_SNAPSHOT', 0)}")
    print(f"UNCERTAIN : {counters.get('UNCERTAIN', 0)} ({counters['uncertainty_rate_percent']} %)")
    print(f"PROCESSING_ERROR : {counters.get('PROCESSING_ERROR', 0)}")
    print(f"Candidats import : {counters['import_candidates']}")
    print(f"Revue humaine (REVIEW_NOW) : {counters['human_review_required']}")
    print(f"Revue différée (DEFER_DATA_INCOMPLETE) : {counters['deferred_data_incomplete']}")
    print(f"Sans revue (NO_MANUAL_REVIEW) : {counters['no_manual_review']}")


if __name__ == "__main__":
    main()
