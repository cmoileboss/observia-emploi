import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.free_work.rome_classifier import run_classification


def default_rome_reference_csv() -> Path:
    candidates = sorted((PROJECT_ROOT / "data" / "raw").glob("correspondance-rome-rncp-tech-*.csv"))
    if not candidates:
        raise FileNotFoundError("Aucun fichier data/raw/correspondance-rome-rncp-tech-*.csv trouvé.")
    return candidates[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classifie déterministiquement les offres Free-Work normalisées vers des candidats ROME."
    )
    parser.add_argument("--free-work-input", required=True, help="Chemin vers offers_normalized.json Free-Work.")
    parser.add_argument("--france-travail-input", required=True, help="Chemin vers le snapshot France Travail.")
    parser.add_argument("--triage-input", default=None, help="Chemin optionnel vers triage_decisions.jsonl.")
    parser.add_argument("--output-dir", required=True, help="Dossier de sortie des artefacts de classification.")
    parser.add_argument("--top-k", type=int, default=3, help="Nombre de candidats ROME à conserver par offre.")
    parser.add_argument(
        "--rome-reference-csv",
        default=None,
        help="Chemin vers correspondance-rome-rncp-tech-*.csv. Par défaut, premier fichier trouvé dans data/raw.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        rome_reference = Path(args.rome_reference_csv) if args.rome_reference_csv else default_rome_reference_csv()
        result = run_classification(
            free_work_input=Path(args.free_work_input),
            france_travail_input=Path(args.france_travail_input),
            triage_input=Path(args.triage_input) if args.triage_input else None,
            output_dir=Path(args.output_dir),
            top_k=args.top_k,
            rome_reference_csv=rome_reference,
        )
    except Exception as exc:
        print(f"Erreur de classification ROME : {exc}", file=sys.stderr)
        sys.exit(1)

    manifest = result["manifest"]
    benchmark = result["benchmark"]
    counters = manifest["status_counters"]
    print("Classification ROME Free-Work terminée.")
    print(f"Offres traitées : {manifest['total_offers']}")
    print(f"Codes ROME candidats : {manifest['rome_candidate_count']}")
    print(f"Compteurs : {counters}")
    loo = benchmark.get("leave_one_out", {})
    print(f"Configuration retenue : {manifest['selected_configuration']}")
    print(f"Seuil score : {manifest['scoring_parameters']['auto_score_threshold']}")
    print(f"Seuil marge : {manifest['scoring_parameters']['auto_margin_threshold']}")
    print(f"Benchmark leave-one-out : {loo.get('sample_size', 0)} cas")
    print(f"Top1 accuracy : {loo.get('top1_accuracy', 0.0)}")
    print(f"Top3 recall : {loo.get('top3_recall', 0.0)}")


if __name__ == "__main__":
    main()
