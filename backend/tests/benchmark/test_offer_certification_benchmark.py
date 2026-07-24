"""Tests du socle commun et de la méthode TF-IDF du lot 7A."""

import math

from backend.services.offer_certification_benchmark import (
    load_active_benchmark_certifications,
    load_benchmark_offers,
)
from backend.services.tfidf_offer_certification import TfidfBenchmarkMethod


def make_offer(
    source_offer_id: str,
    *,
    source: str = "FRANCE_TRAVAIL",
    split: str = "development",
    database_offer_id: int | None = 1,
    appellation: str | None = "Développeur informatique",
    rome_code: str = "M1805",
    rome_label: str | None = "Études et développement informatique",
) -> dict:
    return {
        "split": split,
        "source": source,
        "source_offer_id": source_offer_id,
        "database_offer_id": database_offer_id,
        "code_rome": rome_code,
        "champs_sources": {
            "intitule": "Développeur Python",
            "appellation": appellation,
            "libelle_rome": rome_label,
            "description": "Développer une API Python sécurisée.",
            "competences": [
                {"code": "C1", "libelle": "Programmer en Python"},
                {"code": "C2", "libelle": "Concevoir une API"},
            ],
            "exigences_france_travail": [
                {
                    "intitule": "EXIGENCE INTERDITE",
                    "code_source": "CODE INTERDIT",
                    "niveau": "NIVEAU INTERDIT",
                    "commentaire": "COMMENTAIRE INTERDIT",
                }
            ],
        },
        "texte_matching_commun": "Cette valeur sérialisée ne doit pas être crue.",
    }


def make_certification(
    code_rncp: str,
    *,
    active: bool = True,
    title: str | None = None,
    competence: str = "Développer des applications Python",
) -> dict:
    return {
        "donnees_locales": {
            "code_rncp": code_rncp,
            "intitule_certification": f"Titre local {code_rncp}",
        },
        "donnees_officielles": {
            "numero_fiche": code_rncp,
            "intitule_officiel": title or f"Certification {code_rncp}",
            "actif": active,
            "niveau": {"code": "NIV6", "libelle": "Niveau 6"},
            "codes_rome": ["M1805"],
            "activites_visees": "Conception de logiciels",
            "competences_attestees": competence,
            "metiers_accessibles": "Développeur",
            "secteurs_activite": "Numérique",
            "blocs_competences": [
                {
                    "code": f"{code_rncp}BC01",
                    "libelle": "Développement",
                    "competences": "Coder, tester et déployer",
                }
            ],
            "prerequis": "Bases en programmation",
        },
    }


def make_catalogue(*certifications: dict) -> dict:
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


def test_builds_source_independent_offer_text_without_training_requirement():
    payload = {"offres": [make_offer("FT-001")]}

    offer = load_benchmark_offers(payload)[0]

    assert offer.matching_text.splitlines() == [
        "Développeur Python",
        "Développeur informatique",
        "Études et développement informatique",
        "Développer une API Python sécurisée.",
        "Programmer en Python; Concevoir une API",
    ]
    assert "EXIGENCE INTERDITE" not in offer.matching_text
    assert "CODE INTERDIT" not in offer.matching_text
    assert "NIVEAU INTERDIT" not in offer.matching_text
    assert "COMMENTAIRE INTERDIT" not in offer.matching_text
    assert "Cette valeur sérialisée" not in offer.matching_text


def test_accepts_free_work_offer_without_appellation_or_rome():
    payload = {
        "offres": [
            make_offer(
                "FW-001",
                source="FREE_WORK",
                database_offer_id=None,
                appellation=None,
                rome_code="",
                rome_label=None,
            )
        ]
    }

    offer = load_benchmark_offers(payload)[0]

    assert offer.offer_id == "FREE_WORK:FW-001"
    assert offer.database_offer_id is None
    assert offer.matching_text.splitlines() == [
        "Développeur Python",
        "Développer une API Python sécurisée.",
        "Programmer en Python; Concevoir une API",
    ]


def test_loads_only_active_certifications_and_all_available_text_fields():
    payload = make_catalogue(
        make_certification("RNCP100"),
        make_certification("RNCP200", active=False),
    )

    certifications = load_active_benchmark_certifications(payload)

    assert [item.code_rncp for item in certifications] == ["RNCP100"]
    text = certifications[0].matching_text
    for expected in (
        "Certification RNCP100",
        "NIV6",
        "Niveau 6",
        "M1805",
        "Conception de logiciels",
        "Développer des applications Python",
        "Développeur",
        "Numérique",
        "RNCP100BC01",
        "Développement",
        "Coder, tester et déployer",
        "Bases en programmation",
    ):
        assert expected in text


def test_tfidf_returns_full_continuous_ranking_and_requested_top_k():
    offer = load_benchmark_offers({"offres": [make_offer("FT-001")]})[0]
    certifications = load_active_benchmark_certifications(
        make_catalogue(
            make_certification("RNCP100", competence="Python API"),
            make_certification("RNCP200", competence="Gestion comptable"),
            make_certification("RNCP300", competence="Maintenance industrielle"),
        )
    )

    ranking = TfidfBenchmarkMethod().rank(offer, certifications, top_k=2)

    assert len(ranking.results) == 3
    assert len(ranking.top_results) == 2
    assert [result.position for result in ranking.results] == [1, 2, 3]
    assert {result.code_rncp for result in ranking.results} == {
        "RNCP100",
        "RNCP200",
        "RNCP300",
    }
    assert ranking.results[0].code_rncp == "RNCP100"
    assert all(
        math.isfinite(result.raw_score) and result.raw_score >= 0
        for result in ranking.results
    )
    assert all(result.method_name == "TF_IDF" for result in ranking.results)
    assert all(result.method_version == "1.0" for result in ranking.results)


def test_tfidf_is_deterministic_and_breaks_equal_scores_by_rncp_code():
    offer = load_benchmark_offers(
        {
            "offres": [
                {
                    **make_offer("FW-001", source="FREE_WORK"),
                    "champs_sources": {
                        "intitule": "Terme totalement absent",
                        "appellation": None,
                        "libelle_rome": None,
                        "description": None,
                        "competences": [],
                        "exigences_france_travail": [],
                    },
                }
            ]
        }
    )[0]
    certifications = load_active_benchmark_certifications(
        make_catalogue(
            make_certification("RNCP300", competence="Cuisine"),
            make_certification("RNCP100", competence="Comptabilité"),
            make_certification("RNCP200", competence="Mécanique"),
        )
    )

    first = TfidfBenchmarkMethod().rank(offer, certifications, top_k=3)
    second = TfidfBenchmarkMethod().rank(
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
