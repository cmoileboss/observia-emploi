"""Tests métier de la méthode BM25 du lot 7B."""

import math
from unittest.mock import patch

import pytest

import backend.services.bm25_offer_certification as bm25_module
from backend.services.bm25_offer_certification import Bm25BenchmarkMethod
from backend.services.offer_certification_benchmark import (
    BenchmarkCertification,
    BenchmarkOffer,
    load_benchmark_offers,
)


def make_offer(
    matching_text: str,
    source_offer_id: str = "OFFER-001",
) -> BenchmarkOffer:
    return BenchmarkOffer(
        source="FRANCE_TRAVAIL",
        source_offer_id=source_offer_id,
        database_offer_id=1,
        split="development",
        title="Offre de test",
        matching_text=matching_text,
    )


def make_certification(
    code_rncp: str,
    matching_text: str,
) -> BenchmarkCertification:
    return BenchmarkCertification(
        code_rncp=code_rncp,
        official_title=f"Certification {code_rncp}",
        matching_text=matching_text,
    )


def test_bm25_ranks_precise_query_document_first():
    offer = make_offer("administrer cluster kubernetes sécurité réseau")
    certifications = (
        make_certification(
            "RNCP100",
            "administrer un cluster kubernetes et sécuriser le réseau",
        ),
        make_certification(
            "RNCP200",
            "tenir la comptabilité et produire un bilan financier",
        ),
        make_certification(
            "RNCP300",
            "concevoir une interface de développement web",
        ),
    )

    ranking = Bm25BenchmarkMethod().rank(offer, certifications, top_k=2)

    assert ranking.results[0].code_rncp == "RNCP100"
    assert ranking.results[0].raw_score > ranking.results[1].raw_score


def test_bm25_ignores_repeated_query_terms():
    certifications = (
        make_certification("RNCP100", "réseau sécurité infrastructures"),
        make_certification("RNCP200", "gestion commerciale"),
    )
    single_query = Bm25BenchmarkMethod().rank(
        make_offer("réseau sécurité", "OFFER-SINGLE"),
        certifications,
        top_k=2,
    )
    repeated_query = Bm25BenchmarkMethod().rank(
        make_offer(
            "réseau sécurité réseau sécurité réseau sécurité",
            "OFFER-REPEATED",
        ),
        certifications,
        top_k=2,
    )

    assert [
        (result.code_rncp, result.position, result.raw_score)
        for result in single_query.results
    ] == [
        (result.code_rncp, result.position, result.raw_score)
        for result in repeated_query.results
    ]


def test_bm25_returns_complete_continuous_non_negative_ranking():
    offer = make_offer("python api sécurité")
    certifications = (
        make_certification("RNCP300", "maintenance industrielle"),
        make_certification("RNCP100", "développer une API Python"),
        make_certification("RNCP200", "sécurité des réseaux"),
    )

    ranking = Bm25BenchmarkMethod().rank(offer, certifications, top_k=2)

    assert len(ranking.results) == 3
    assert len(ranking.top_results) == 2
    assert [result.position for result in ranking.results] == [1, 2, 3]
    assert {result.code_rncp for result in ranking.results} == {
        "RNCP100",
        "RNCP200",
        "RNCP300",
    }
    assert all(
        math.isfinite(result.raw_score) and result.raw_score >= 0
        for result in ranking.results
    )
    assert all(result.method_name == "BM25" for result in ranking.results)
    assert all(result.method_version == "1.0" for result in ranking.results)


def test_bm25_breaks_ties_by_code_and_is_input_order_independent():
    offer = make_offer("terme absent")
    certifications = (
        make_certification("RNCP300", "cuisine"),
        make_certification("RNCP100", "comptabilité"),
        make_certification("RNCP200", "mécanique"),
    )

    first = Bm25BenchmarkMethod().rank(offer, certifications, top_k=3)
    second = Bm25BenchmarkMethod().rank(
        offer,
        tuple(reversed(certifications)),
        top_k=3,
    )

    first_stable = [
        (result.code_rncp, result.position, result.raw_score)
        for result in first.results
    ]
    second_stable = [
        (result.code_rncp, result.position, result.raw_score)
        for result in second.results
    ]
    assert first_stable == second_stable
    assert [result.code_rncp for result in first.results] == [
        "RNCP100",
        "RNCP200",
        "RNCP300",
    ]
    assert {result.raw_score for result in first.results} == {0.0}


def test_bm25_builds_index_once_for_same_certification_collection():
    certifications = (
        make_certification("RNCP100", "développement python"),
        make_certification("RNCP200", "administration réseau"),
    )
    method = Bm25BenchmarkMethod()

    with patch.object(
        bm25_module,
        "_build_index",
        wraps=bm25_module._build_index,
    ) as build_index:
        method.rank(make_offer("python", "OFFER-001"), certifications, top_k=1)
        method.rank(make_offer("réseau", "OFFER-002"), certifications, top_k=1)

    build_index.assert_called_once()


@pytest.mark.parametrize("k1", (0, -1, float("inf"), float("nan"), True))
def test_bm25_rejects_invalid_k1(k1):
    with pytest.raises(ValueError, match="k1"):
        Bm25BenchmarkMethod(k1=k1)


@pytest.mark.parametrize(
    "b",
    (-0.01, 1.01, float("inf"), float("nan"), True),
)
def test_bm25_rejects_invalid_b(b):
    with pytest.raises(ValueError, match="b"):
        Bm25BenchmarkMethod(b=b)


def test_bm25_accepts_free_work_offer_without_rome():
    payload = {
        "offres": [
            {
                "split": "development",
                "source": "FREE_WORK",
                "source_offer_id": "FW-001",
                "database_offer_id": None,
                "code_rome": "",
                "champs_sources": {
                    "intitule": "Ingénieur sécurité",
                    "appellation": None,
                    "libelle_rome": None,
                    "description": "Sécuriser des infrastructures cloud.",
                    "competences": [],
                    "exigences_france_travail": [],
                },
            }
        ]
    }
    offer = load_benchmark_offers(payload)[0]
    certifications = (
        make_certification("RNCP100", "sécurité cloud"),
        make_certification("RNCP200", "gestion commerciale"),
    )

    ranking = Bm25BenchmarkMethod().rank(offer, certifications, top_k=1)

    assert ranking.offer.offer_id == "FREE_WORK:FW-001"
    assert ranking.results[0].code_rncp == "RNCP100"
