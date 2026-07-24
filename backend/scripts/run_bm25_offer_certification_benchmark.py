"""Exécute le benchmark BM25 hors base et exporte ses résultats."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from backend.services.bm25_offer_certification import (
    DEFAULT_B,
    DEFAULT_K1,
    Bm25BenchmarkMethod,
)
from backend.services.offer_certification_benchmark import (
    BenchmarkRun,
    load_active_benchmark_certifications,
    load_benchmark_offers,
    run_benchmark,
)


FORMAT_VERSION = "observia-offer-certification-benchmark-v1"
DEFAULT_TOP_K = 10
OUTPUT_FILENAMES = (
    "benchmark_manifest.json",
    "bm25_rankings.jsonl",
    "benchmark_summary.json",
)


def _read_json_object(
    path: Path,
    description: str,
) -> tuple[Mapping[str, Any], bytes]:
    """Lit un objet JSON UTF-8 et conserve ses octets pour le hash."""
    content = path.read_bytes()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} n'est pas un JSON UTF-8 valide.") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{description} doit contenir un objet JSON.")
    return payload, content


def run_bm25_benchmark(
    offers_path: Path,
    catalogue_path: Path,
    split: str = "development",
    top_k: int = DEFAULT_TOP_K,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> tuple[BenchmarkRun, str, str]:
    """Charge les artefacts communs puis exécute BM25 sur le split demandé."""
    method = Bm25BenchmarkMethod(k1=k1, b=b)
    offers_payload, offers_content = _read_json_object(
        offers_path,
        "Le fichier d'offres",
    )
    catalogue_payload, catalogue_content = _read_json_object(
        catalogue_path,
        "Le catalogue RNCP enrichi",
    )
    offers = load_benchmark_offers(offers_payload, split)
    certifications = load_active_benchmark_certifications(catalogue_payload)
    run = run_benchmark(
        method,
        offers,
        certifications,
        split,
        top_k,
        clock=perf_counter,
    )
    return (
        run,
        hashlib.sha256(offers_content).hexdigest(),
        hashlib.sha256(catalogue_content).hexdigest(),
    )


def _deterministic_result_hash(run: BenchmarkRun) -> str:
    """Calcule le hash des rangs et scores en excluant les durées variables."""
    deterministic_results = [
        {
            "offer_id": result.offer_id,
            "code_rncp": result.code_rncp,
            "position": result.position,
            "raw_score": result.raw_score,
            "method_name": result.method_name,
            "method_version": result.method_version,
        }
        for ranking in run.rankings
        for result in ranking.results
    ]
    serialized = json.dumps(
        deterministic_results,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def build_bm25_benchmark_artifacts(
    run: BenchmarkRun,
    offers_sha256: str,
    catalogue_sha256: str,
    k1: float,
    b: float,
) -> dict[str, bytes]:
    """Construit le manifeste, les classements JSONL et le résumé BM25."""
    deterministic_hash = _deterministic_result_hash(run)
    manifest = {
        "format_version": FORMAT_VERSION,
        "methode": {
            "nom": run.method_name,
            "version": run.method_version,
            "score": "score_bm25_brut",
            "score_est_un_pourcentage": False,
        },
        "parametres": {
            "split": run.split,
            "top_k": run.top_k,
            "classement_complet": True,
            "k1": k1,
            "b": b,
        },
        "entrees": {
            "evaluation_offers_sha256": offers_sha256,
            "catalogue_rncp_enrichi_sha256": catalogue_sha256,
        },
        "compteurs": {
            "offres": len(run.rankings),
            "certifications_actives": run.certification_count,
            "scores_classement_complet": run.score_count,
        },
        "resultat_deterministe_sha256": deterministic_hash,
        "artefacts": {
            "classements": "bm25_rankings.jsonl",
            "resume": "benchmark_summary.json",
        },
    }
    ranking_lines = [
        json.dumps(
            {
                "offer_id": ranking.offer.offer_id,
                "source": ranking.offer.source,
                "source_offer_id": ranking.offer.source_offer_id,
                "database_offer_id": ranking.offer.database_offer_id,
                "split": ranking.offer.split,
                "top_k": run.top_k,
                "classement_complet": [
                    result.to_dict() for result in ranking.results
                ],
                "classement_top_k": [
                    result.to_dict() for result in ranking.top_results
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for ranking in run.rankings
    ]
    summary = {
        "methode": run.method_name,
        "version": run.method_version,
        "parametres": {"k1": k1, "b": b},
        "split": run.split,
        "nombre_offres": len(run.rankings),
        "nombre_certifications_actives": run.certification_count,
        "nombre_scores": run.score_count,
        "duree_totale_secondes": run.total_duration_seconds,
        "duree_moyenne_par_offre_secondes": run.average_duration_seconds,
        "resultat_deterministe_sha256": deterministic_hash,
    }
    json_options = {
        "ensure_ascii": False,
        "indent": 2,
        "sort_keys": True,
    }
    return {
        "benchmark_manifest.json": (
            json.dumps(manifest, **json_options).encode("utf-8") + b"\n"
        ),
        "bm25_rankings.jsonl": (
            ("\n".join(ranking_lines) + "\n").encode("utf-8")
        ),
        "benchmark_summary.json": (
            json.dumps(summary, **json_options).encode("utf-8") + b"\n"
        ),
    }


def export_bm25_benchmark_artifacts(
    artifacts: Mapping[str, bytes],
    output_directory: Path,
) -> None:
    """Écrit les trois artefacts sans remplacer silencieusement un fichier."""
    if set(artifacts) != set(OUTPUT_FILENAMES):
        raise ValueError("La liste des artefacts BM25 est incomplète.")
    existing_paths = [
        output_directory / filename
        for filename in OUTPUT_FILENAMES
        if (output_directory / filename).exists()
    ]
    if existing_paths:
        raise FileExistsError(
            "Des artefacts BM25 existent déjà : "
            + ", ".join(str(path) for path in existing_paths)
        )
    output_directory.mkdir(parents=True, exist_ok=True)
    for filename in OUTPUT_FILENAMES:
        (output_directory / filename).write_bytes(artifacts[filename])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Analyse les chemins, le split, le top K et les paramètres BM25."""
    parser = argparse.ArgumentParser(
        description="Classe toutes les certifications RNCP actives par BM25."
    )
    parser.add_argument(
        "--offers",
        type=Path,
        required=True,
        help="Chemin de evaluation_offers.json produit par le lot 5.",
    )
    parser.add_argument(
        "--enriched-catalogue",
        type=Path,
        required=True,
        help="Chemin du catalogue RNCP enrichi produit par le lot 4.",
    )
    parser.add_argument(
        "--split",
        choices=("development", "validation", "all"),
        default="development",
        help="Split à traiter, development par défaut.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Nombre de premiers résultats exposés dans le top K.",
    )
    parser.add_argument(
        "--k1",
        type=float,
        default=DEFAULT_K1,
        help="Saturation de fréquence des termes, 1.5 par défaut.",
    )
    parser.add_argument(
        "--b",
        type=float,
        default=DEFAULT_B,
        help="Normalisation de longueur entre 0 et 1, 0.75 par défaut.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Dossier de sortie des artefacts BM25.",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Exécute BM25, exporte les artefacts et affiche le résumé."""
    args = parse_args()
    try:
        run, offers_sha256, catalogue_sha256 = run_bm25_benchmark(
            args.offers,
            args.enriched_catalogue,
            args.split,
            args.top_k,
            args.k1,
            args.b,
        )
        artifacts = build_bm25_benchmark_artifacts(
            run,
            offers_sha256,
            catalogue_sha256,
            args.k1,
            args.b,
        )
        export_bm25_benchmark_artifacts(artifacts, args.output_dir)
    except Exception as exc:
        print(f"Erreur du benchmark BM25 : {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Offres traitées : {len(run.rankings)}")
    print(f"Certifications actives : {run.certification_count}")
    print(f"Scores calculés : {run.score_count}")
    print(f"Durée totale : {run.total_duration_seconds:.6f} s")
    print(
        "Durée moyenne par offre : "
        f"{run.average_duration_seconds:.6f} s"
    )
    print(f"Artefacts exportés : {args.output_dir}")


if __name__ == "__main__":
    main()
