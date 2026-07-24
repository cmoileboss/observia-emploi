"""Tests de l'orchestration et des artefacts BM25 du lot 7B."""

import json

from backend.scripts.run_bm25_offer_certification_benchmark import (
    build_bm25_benchmark_artifacts,
    export_bm25_benchmark_artifacts,
    parse_args,
    run_bm25_benchmark,
)


def write_json(path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def make_offer(source_offer_id, *, split="development"):
    return {
        "split": split,
        "source": "FRANCE_TRAVAIL",
        "source_offer_id": source_offer_id,
        "database_offer_id": 1,
        "code_rome": "M1805",
        "champs_sources": {
            "intitule": "Développeur Python",
            "appellation": "Développeur informatique",
            "libelle_rome": "Études et développement informatique",
            "description": "Développer une API Python.",
            "competences": [{"code": "C1", "libelle": "Programmer en Python"}],
            "exigences_france_travail": [],
        },
    }


def make_certification(code_rncp, *, active=True, competence="Python"):
    return {
        "donnees_locales": {"code_rncp": code_rncp},
        "donnees_officielles": {
            "intitule_officiel": f"Certification {code_rncp}",
            "actif": active,
            "niveau": {"code": "NIV6", "libelle": "Niveau 6"},
            "codes_rome": ["M1805"],
            "activites_visees": "Conception de logiciels",
            "competences_attestees": competence,
            "metiers_accessibles": "Développeur",
            "secteurs_activite": "Numérique",
            "blocs_competences": [],
            "prerequis": None,
        },
    }


def make_catalogue(*certifications):
    return {
        "metadata": {
            "compteurs": {
                "nombre_certifications_actives": sum(
                    certification["donnees_officielles"]["actif"] is True
                    for certification in certifications
                )
            }
        },
        "certifications": list(certifications),
    }


def stable_rankings(run):
    return [
        [
            (result.code_rncp, result.position, result.raw_score)
            for result in ranking.results
        ]
        for ranking in run.rankings
    ]


def prepare_inputs(tmp_path):
    offers_path = tmp_path / "evaluation_offers.json"
    catalogue_path = tmp_path / "rncp_catalogue_enrichi.json"
    write_json(
        offers_path,
        {
            "offres": [
                make_offer("FT-DEV", split="development"),
                make_offer("FT-VAL", split="validation"),
            ]
        },
    )
    write_json(
        catalogue_path,
        make_catalogue(
            make_certification("RNCP100", competence="Python API"),
            make_certification("RNCP200", competence="Réseau"),
            make_certification("RNCP300", active=False),
        ),
    )
    return offers_path, catalogue_path


def test_runs_requested_split_against_all_active_certifications(tmp_path):
    offers_path, catalogue_path = prepare_inputs(tmp_path)

    run, offers_sha256, catalogue_sha256 = run_bm25_benchmark(
        offers_path,
        catalogue_path,
        split="development",
        top_k=1,
    )

    assert [ranking.offer.source_offer_id for ranking in run.rankings] == [
        "FT-DEV"
    ]
    assert run.certification_count == 2
    assert run.score_count == 2
    assert {
        result.code_rncp
        for ranking in run.rankings
        for result in ranking.results
    } == {"RNCP100", "RNCP200"}
    assert len(offers_sha256) == 64
    assert len(catalogue_sha256) == 64


def test_bm25_rankings_and_hash_are_deterministic(tmp_path):
    offers_path, catalogue_path = prepare_inputs(tmp_path)

    first, offers_sha256, catalogue_sha256 = run_bm25_benchmark(
        offers_path,
        catalogue_path,
        top_k=2,
    )
    second, _, _ = run_bm25_benchmark(
        offers_path,
        catalogue_path,
        top_k=2,
    )
    first_artifacts = build_bm25_benchmark_artifacts(
        first,
        offers_sha256,
        catalogue_sha256,
        1.5,
        0.75,
    )
    second_artifacts = build_bm25_benchmark_artifacts(
        second,
        offers_sha256,
        catalogue_sha256,
        1.5,
        0.75,
    )
    first_manifest = json.loads(first_artifacts["benchmark_manifest.json"])
    second_manifest = json.loads(second_artifacts["benchmark_manifest.json"])

    assert stable_rankings(first) == stable_rankings(second)
    assert (
        first_manifest["resultat_deterministe_sha256"]
        == second_manifest["resultat_deterministe_sha256"]
    )


def test_exports_bm25_parameters_full_ranking_top_k_and_summary(tmp_path):
    offers_path, catalogue_path = prepare_inputs(tmp_path)
    run, offers_sha256, catalogue_sha256 = run_bm25_benchmark(
        offers_path,
        catalogue_path,
        top_k=1,
        k1=1.2,
        b=0.6,
    )
    artifacts = build_bm25_benchmark_artifacts(
        run,
        offers_sha256,
        catalogue_sha256,
        1.2,
        0.6,
    )
    output_directory = tmp_path / "output"

    export_bm25_benchmark_artifacts(artifacts, output_directory)

    assert {path.name for path in output_directory.iterdir()} == set(artifacts)
    ranking_line = json.loads(
        (output_directory / "bm25_rankings.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert len(ranking_line["classement_complet"]) == 2
    assert len(ranking_line["classement_top_k"]) == 1
    manifest = json.loads(
        (output_directory / "benchmark_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["parametres"]["k1"] == 1.2
    assert manifest["parametres"]["b"] == 0.6
    assert manifest["methode"]["score_est_un_pourcentage"] is False


def test_cli_exposes_default_bm25_parameters():
    args = parse_args(
        [
            "--offers",
            "offers.json",
            "--enriched-catalogue",
            "catalogue.json",
            "--output-dir",
            "output",
        ]
    )

    assert args.split == "development"
    assert args.top_k == 10
    assert args.k1 == 1.5
    assert args.b == 0.75
