"""Tests métier de l'échantillon figé offre–certification."""

import csv
import io
import json
from dataclasses import replace
from datetime import date

import pytest

from backend.services.france_travail_training_requirements import (
    FranceTravailTrainingRequirement,
)
from backend.services.offer_certification_evaluation_sample import (
    ANNOTATION_COLUMNS,
    CANDIDATE_REASONS,
    EvaluationCertification,
    EvaluationCompetence,
    EvaluationOfferSource,
    EvaluationSampleConfig,
    build_evaluation_artifacts,
    build_evaluation_sample,
    build_common_matching_text,
    classify_description_richness,
    export_evaluation_artifacts,
    load_evaluation_certifications,
)


def make_requirement(offer_id: int) -> FranceTravailTrainingRequirement:
    return FranceTravailTrainingRequirement(
        formation_id=1000 + offer_id,
        intitule="Diplôme en informatique",
        code_source="BAC+3",
        niveau="6",
        commentaire="Exigé",
        offre_ids=(offer_id,),
    )


def make_offer(
    offer_id: int,
    *,
    rome_code: str = "M1801",
    with_competence: bool = False,
    with_requirement: bool = False,
    description_length: int = 700,
) -> EvaluationOfferSource:
    return EvaluationOfferSource(
        source="FRANCE_TRAVAIL",
        source_offer_id=f"FT-{offer_id:03d}",
        database_offer_id=offer_id,
        rome_code=rome_code,
        title=f"Administrateur systèmes {offer_id}",
        occupation_label="Administrateur informatique",
        rome_label="Administration de systèmes d'information",
        description="D" * description_length,
        competences=(EvaluationCompetence("C1", "Administrer Linux"),)
        if with_competence
        else (),
        training_requirements=(make_requirement(offer_id),)
        if with_requirement
        else (),
    )


def make_certification(
    code: str,
    rome_codes: tuple[str, ...],
) -> EvaluationCertification:
    official_data = {
        "intitule_officiel": f"Certification {code}",
        "actif": True,
        "codes_rome": list(rome_codes),
        "competences_attestees": f"Compétences {code}",
    }
    return EvaluationCertification(
        code_rncp=code,
        official_title=f"Certification {code}",
        rome_codes=rome_codes,
        official_data=official_data,
    )


def make_certifications() -> tuple[EvaluationCertification, ...]:
    return (
        make_certification("RNCPD1", ("M1801",)),
        make_certification("RNCPD2", ("M1801",)),
        make_certification("RNCPD3", ("M1801",)),
        make_certification("RNCPN1", ("M1802",)),
        make_certification("RNCPN2", ("M1802",)),
        make_certification("RNCPN3", ("M1802",)),
        make_certification("RNCPX1", ("E1101",)),
        make_certification("RNCPX2", ("E1103",)),
        make_certification("RNCPX3", ("H1206",)),
    )


def make_config() -> EvaluationSampleConfig:
    return EvaluationSampleConfig(
        development_size=4,
        validation_size=2,
        candidate_pool_size=6,
        max_offers_per_rome=6,
    )


def build_sample(source_order: tuple[int, ...] = (1, 2, 3, 4, 5, 6)):
    offers = tuple(
        make_offer(
            offer_id,
            with_competence=offer_id % 2 == 0,
            with_requirement=offer_id % 3 == 0,
            description_length=(200, 800, 1700)[offer_id % 3],
        )
        for offer_id in source_order
    )
    certifications = make_certifications()
    return build_evaluation_sample(
        offers,
        certifications,
        frozenset(certification.code_rncp for certification in certifications),
        "catalogue-sha256",
        make_config(),
    )


def test_builds_common_text_without_france_travail_requirement():
    source = make_offer(1, with_competence=True, with_requirement=True)

    text = build_common_matching_text(source)

    assert "Administrateur systèmes" in text
    assert "Administrateur informatique" in text
    assert "Administration de systèmes" in text
    assert "Administrer Linux" in text
    assert "Diplôme en informatique" not in text
    assert "BAC+3" not in text
    assert "Exigé" not in text
    assert "entreprise" not in text.lower()
    assert "localisation" not in text.lower()
    serialized = next(
        offer.to_dict()
        for offer in build_sample().offers
        if offer.source.training_requirements
    )
    requirement = serialized["champs_sources"]["exigences_france_travail"][0]
    assert requirement["intitule"] == "Diplôme en informatique"
    assert requirement["code_source"] == "BAC+3"
    assert requirement["niveau"] == "6"
    assert requirement["commentaire"] == "Exigé"
    assert "texte_matching" not in serialized
    assert "texte_matching_commun" in serialized


@pytest.mark.parametrize(
    ("length", "expected"),
    ((499, "COURTE"), (500, "MOYENNE"), (1499, "MOYENNE"), (1500, "LONGUE")),
)
def test_classifies_description_richness_at_explicit_thresholds(length, expected):
    assert classify_description_richness("x" * length) == expected


def test_loads_only_active_local_certifications_and_ignores_external_successor():
    payload = {
        "certifications": [
            {
                "donnees_locales": {"code_rncp": "RNCP100"},
                "donnees_officielles": {
                    "actif": True,
                    "intitule_officiel": "Titre actif",
                    "codes_rome": ["M1801"],
                },
            },
            {
                "donnees_locales": {"code_rncp": "RNCP200"},
                "donnees_officielles": {
                    "actif": False,
                    "intitule_officiel": "Titre inactif",
                    "codes_rome": ["M1801"],
                },
                "succession": {
                    "successeurs_actifs_terminaux": [
                        {"code_rncp": "RNCP999", "actif": True}
                    ]
                },
            },
        ]
    }

    certifications, catalogue_codes = load_evaluation_certifications(payload)

    assert [certification.code_rncp for certification in certifications] == [
        "RNCP100"
    ]
    assert catalogue_codes == frozenset({"RNCP100", "RNCP200"})


def test_separates_splits_without_leak_and_preserves_data_richness():
    sample = build_sample()
    development_ids = {
        offer.source.source_offer_id
        for offer in sample.offers
        if offer.split == "development"
    }
    validation_ids = {
        offer.source.source_offer_id
        for offer in sample.offers
        if offer.split == "validation"
    }

    assert len(development_ids) == 4
    assert len(validation_ids) == 2
    assert development_ids.isdisjoint(validation_ids)
    assert any(offer.source.competences for offer in sample.offers)
    assert any(offer.source.training_requirements for offer in sample.offers)


def test_distributes_validation_proportionally_between_rome_codes():
    certifications = make_certifications()
    offers = tuple(
        make_offer(
            offer_id,
            rome_code="M1801" if offer_id <= 3 else "M1802",
        )
        for offer_id in range(1, 7)
    )

    sample = build_evaluation_sample(
        offers,
        certifications,
        frozenset(certification.code_rncp for certification in certifications),
        "catalogue-sha256",
        make_config(),
    )

    validation_counts = {
        code: sum(
            offer.split == "validation" and offer.source.rome_code == code
            for offer in sample.offers
        )
        for code in ("M1801", "M1802")
    }
    assert validation_counts == {"M1801": 1, "M1802": 1}


def test_stratification_and_candidate_selection_are_deterministic():
    first = build_sample()
    second = build_sample((6, 5, 4, 3, 2, 1))

    assert [offer.to_dict() for offer in first.offers] == [
        offer.to_dict() for offer in second.offers
    ]
    assert [pool.to_dict() for pool in first.candidate_pools] == [
        pool.to_dict() for pool in second.candidate_pools
    ]


def test_candidate_pools_contain_all_reasons_and_unique_active_pairs():
    sample = build_sample()
    pairs = []

    for pool in sample.candidate_pools:
        reasons = {candidate.selection_reason for candidate in pool.candidates}
        direct_count = sum(
            candidate.selection_reason == "ROME_DIRECT"
            for candidate in pool.candidates
        )
        assert reasons == set(CANDIDATE_REASONS)
        assert direct_count >= 2
        assert len(pool.candidates) == 6
        pairs.extend(
            ((pool.source, pool.source_offer_id), candidate.certification.code_rncp)
            for candidate in pool.candidates
        )

    assert len(pairs) == len(set(pairs))


def test_annotation_columns_are_empty_and_artifacts_are_identical():
    sample = build_sample()
    first = build_evaluation_artifacts(sample, date(2026, 7, 22))
    second = build_evaluation_artifacts(sample, date(2026, 7, 22))

    assert first == second
    rows = list(
        csv.DictReader(
            io.StringIO(first["annotation_template.csv"].decode("utf-8"))
        )
    )
    assert len(rows) == 36
    assert tuple(rows[0]) == ANNOTATION_COLUMNS
    assert rows[0]["source"] == "FRANCE_TRAVAIL"
    assert rows[0]["source_offer_id"].startswith("FT-")
    assert rows[0]["database_offer_id"]
    offer = sample.offers[0].to_dict()
    pool = sample.candidate_pools[0].to_dict()
    for payload in (offer, pool):
        assert payload["source"] == "FRANCE_TRAVAIL"
        assert payload["source_offer_id"].startswith("FT-")
        assert payload["database_offer_id"] is not None
    for column in ANNOTATION_COLUMNS[-6:]:
        assert all(row[column] == "" for row in rows)
    manifest = json.loads(first["sample_manifest.json"].decode("utf-8"))
    assert manifest["compteurs"]["couples_offre_certification"] == 36


def test_accepts_generic_future_provenance_without_database_identifier():
    certifications = make_certifications()
    sources = tuple(
        replace(
            make_offer(offer_id),
            source="FREE_WORK",
            source_offer_id=f"FW-{offer_id:03d}",
            database_offer_id=None,
        )
        for offer_id in range(1, 7)
    )

    sample = build_evaluation_sample(
        sources,
        certifications,
        frozenset(certification.code_rncp for certification in certifications),
        "catalogue-sha256",
        make_config(),
    )

    assert {offer.to_dict()["source"] for offer in sample.offers} == {"FREE_WORK"}
    assert {offer.to_dict()["database_offer_id"] for offer in sample.offers} == {
        None
    }
    assert {pool.to_dict()["source"] for pool in sample.candidate_pools} == {
        "FREE_WORK"
    }


def test_multi_source_same_source_id_is_order_independent():
    certifications = make_certifications()
    sources = tuple(
        replace(
            make_offer(offer_id),
            source="FRANCE_TRAVAIL" if offer_id % 2 else "FREE_WORK",
            source_offer_id="SHARED" if offer_id in (1, 2) else f"O-{offer_id}",
            database_offer_id=None,
        )
        for offer_id in range(1, 7)
    )

    def build(source_order):
        return build_evaluation_sample(
            source_order,
            certifications,
            frozenset(certification.code_rncp for certification in certifications),
            "catalogue-sha256",
            make_config(),
        )

    first = build(sources)
    second = build(tuple(reversed(sources)))

    assert [offer.to_dict() for offer in first.offers] == [
        offer.to_dict() for offer in second.offers
    ]
    assert [pool.to_dict() for pool in first.candidate_pools] == [
        pool.to_dict() for pool in second.candidate_pools
    ]


def test_exports_the_four_expected_artifacts(tmp_path):
    artifacts = build_evaluation_artifacts(build_sample(), date(2026, 7, 22))

    export_evaluation_artifacts(artifacts, tmp_path)

    assert {path.name for path in tmp_path.iterdir()} == set(artifacts)
    assert all((tmp_path / name).read_bytes() == content for name, content in artifacts.items())


def test_rejects_an_insufficient_eligible_offer_volume():
    certifications = make_certifications()

    with pytest.raises(ValueError, match="insuffisant"):
        build_evaluation_sample(
            tuple(make_offer(offer_id) for offer_id in range(1, 6)),
            certifications,
            frozenset(certification.code_rncp for certification in certifications),
            "catalogue-sha256",
            make_config(),
        )
