"""Construction d'un échantillon figé offre–certification sans matching."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from services.france_travail_training_requirements import (
    FranceTravailTrainingRequirement,
)


EVALUATION_SEED = "observia-offre-formation-evaluation-v1"
FORMAT_VERSION = "observia-offre-certification-sample-v1"
DESCRIPTION_SHORT_LIMIT = 500
DESCRIPTION_LONG_LIMIT = 1500
DEFAULT_POOL_SIZE = 12
DEFAULT_MAX_OFFERS_PER_ROME = 10
DEFAULT_TECH_ROME_PREFIXES = ("M18",)

CANDIDATE_REASON_DIRECT = "ROME_DIRECT"
CANDIDATE_REASON_NEAR = "ROME_PROCHE"
CANDIDATE_REASON_NEGATIVE = "NEGATIF_CONTROLE"
CANDIDATE_REASONS = (
    CANDIDATE_REASON_DIRECT,
    CANDIDATE_REASON_NEAR,
    CANDIDATE_REASON_NEGATIVE,
)

ANNOTATION_COLUMNS = (
    "split",
    "source",
    "source_offer_id",
    "database_offer_id",
    "code_rome",
    "intitule_offre",
    "code_rncp",
    "intitule_officiel_certification",
    "raison_selection_candidat",
    "score_annotateur_1",
    "justification_annotateur_1",
    "score_annotateur_2",
    "justification_annotateur_2",
    "score_final",
    "commentaire_arbitrage",
)


@dataclass(frozen=True)
class EvaluationSampleConfig:
    """Regroupe les paramètres explicites et reproductibles de l'échantillon."""

    development_size: int = 40
    validation_size: int = 20
    candidate_pool_size: int = DEFAULT_POOL_SIZE
    max_offers_per_rome: int = DEFAULT_MAX_OFFERS_PER_ROME
    tech_rome_prefixes: tuple[str, ...] = DEFAULT_TECH_ROME_PREFIXES
    seed: str = EVALUATION_SEED

    @property
    def total_size(self) -> int:
        """Retourne le nombre total d'offres attendu."""
        return self.development_size + self.validation_size


@dataclass(frozen=True)
class EvaluationCompetence:
    """Conserve une compétence structurée associée à une offre."""

    code: str | None
    libelle: str | None

    def to_dict(self) -> dict[str, str | None]:
        """Retourne la représentation sérialisable de la compétence."""
        return {"code": self.code, "libelle": self.libelle}


@dataclass(frozen=True)
class EvaluationOfferSource:
    """Contient les champs sources autorisés pour une offre d'évaluation."""

    source: str
    source_offer_id: str
    database_offer_id: int | None
    rome_code: str
    title: str | None
    occupation_label: str | None
    rome_label: str | None
    description: str | None
    competences: tuple[EvaluationCompetence, ...]
    training_requirements: tuple[FranceTravailTrainingRequirement, ...]


@dataclass(frozen=True)
class EvaluationCertification:
    """Représente une certification locale active candidate à l'évaluation."""

    code_rncp: str
    official_title: str | None
    rome_codes: tuple[str, ...]
    official_data: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Retourne les données officielles conservées pour le futur benchmark."""
        return {
            "code_rncp": self.code_rncp,
            "intitule_officiel": self.official_title,
            "codes_rome": list(self.rome_codes),
            "donnees_officielles": dict(self.official_data),
        }


@dataclass(frozen=True)
class SelectedEvaluationOffer:
    """Associe une offre sélectionnée à son split et à sa strate."""

    source: EvaluationOfferSource
    split: str
    description_richness: str
    common_matching_text: str

    def to_dict(self) -> dict[str, Any]:
        """Sérialise l'offre sans entreprise ni localisation."""
        return {
            "split": self.split,
            "source": self.source.source,
            "source_offer_id": self.source.source_offer_id,
            "database_offer_id": self.source.database_offer_id,
            "code_rome": self.source.rome_code,
            "champs_sources": {
                "intitule": self.source.title,
                "appellation": self.source.occupation_label,
                "libelle_rome": self.source.rome_label,
                "description": self.source.description,
                "competences": [
                    competence.to_dict() for competence in self.source.competences
                ],
                "exigences_france_travail": [
                    _requirement_to_dict(requirement)
                    for requirement in self.source.training_requirements
                ],
            },
            "richesse": {
                "description": self.description_richness,
                "competences_structurees": bool(self.source.competences),
                "exigence_france_travail": bool(
                    self.source.training_requirements
                ),
            },
            "texte_matching_commun": self.common_matching_text,
        }


@dataclass(frozen=True)
class EvaluationCandidate:
    """Associe une certification à la raison structurelle de sa sélection."""

    certification: EvaluationCertification
    selection_reason: str

    def to_dict(self) -> dict[str, Any]:
        """Sérialise le candidat et sa raison sans score de pertinence."""
        payload = self.certification.to_dict()
        payload["raison_selection"] = self.selection_reason
        return payload


@dataclass(frozen=True)
class EvaluationCandidatePool:
    """Regroupe les certifications candidates d'une offre sélectionnée."""

    source: str
    source_offer_id: str
    database_offer_id: int | None
    split: str
    rome_code: str
    candidates: tuple[EvaluationCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        """Retourne une ligne JSONL de pool de candidats."""
        return {
            "split": self.split,
            "source": self.source,
            "source_offer_id": self.source_offer_id,
            "database_offer_id": self.database_offer_id,
            "code_rome": self.rome_code,
            "candidats": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class EvaluationSample:
    """Contient l'échantillon validé et ses pools de candidats."""

    offers: tuple[SelectedEvaluationOffer, ...]
    candidate_pools: tuple[EvaluationCandidatePool, ...]
    catalogue_sha256: str
    catalogue_codes: frozenset[str]
    active_catalogue_codes: frozenset[str]
    config: EvaluationSampleConfig


def _clean_optional_text(value: str | None) -> str | None:
    """Supprime les espaces extérieurs et convertit le vide en valeur nulle."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _stable_hash(seed: str, *parts: object) -> str:
    """Calcule une clé SHA-256 stable à partir de valeurs textuelles."""
    serialized = "\x1f".join(str(part) for part in (seed, *parts))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _offer_key(source: EvaluationOfferSource) -> tuple[str, str]:
    """Retourne l'identifiant stable d'une offre dans sa source d'origine."""
    source_name = _clean_optional_text(source.source)
    source_offer_id = _clean_optional_text(source.source_offer_id)
    if source_name is None or source_offer_id is None:
        raise ValueError("La provenance de l'offre est incomplète.")
    return source_name, source_offer_id


def _offer_hash_key(
    seed: str,
    phase: str,
    source: EvaluationOfferSource,
) -> tuple[str, str]:
    """Construit une clé legacy puis un départage explicitement multi-source."""
    return (
        _stable_hash(
            seed,
            phase,
            source.database_offer_id,
            source.source_offer_id,
        ),
        _stable_hash(
            seed,
            phase,
            source.source,
            source.source_offer_id,
            source.database_offer_id,
        ),
    )


def _requirement_to_dict(
    requirement: FranceTravailTrainingRequirement,
) -> dict[str, Any]:
    """Sérialise une exigence France Travail distincte d'un candidat RNCP."""
    return {
        "source_formation_id": requirement.formation_id,
        "intitule": requirement.intitule,
        "code_source": requirement.code_source,
        "niveau": requirement.niveau,
        "commentaire": requirement.commentaire,
    }


def classify_description_richness(description: str | None) -> str:
    """Classe une description selon les seuils documentés du lot 5."""
    length = len(_clean_optional_text(description) or "")
    if length < DESCRIPTION_SHORT_LIMIT:
        return "COURTE"
    if length < DESCRIPTION_LONG_LIMIT:
        return "MOYENNE"
    return "LONGUE"


def build_common_matching_text(source: EvaluationOfferSource) -> str:
    """Compose le texte commun aux sources à partir des champs métier partagés."""
    parts = [
        _clean_optional_text(source.title),
        _clean_optional_text(source.occupation_label),
        _clean_optional_text(source.rome_label),
        _clean_optional_text(source.description),
    ]
    competence_text = "; ".join(
        value
        for competence in source.competences
        for value in (_clean_optional_text(competence.libelle),)
        if value is not None
    )
    parts.append(competence_text or None)
    return "\n".join(part for part in parts if part is not None)


def load_evaluation_certifications(
    catalogue_payload: Mapping[str, Any],
) -> tuple[tuple[EvaluationCertification, ...], frozenset[str]]:
    """Charge uniquement les certifications locales officiellement actives."""
    raw_certifications = catalogue_payload.get("certifications")
    if not isinstance(raw_certifications, list):
        raise ValueError("Le catalogue enrichi ne contient pas de certifications.")

    all_codes: set[str] = set()
    active_certifications: list[EvaluationCertification] = []
    for raw_certification in raw_certifications:
        local_data = raw_certification.get("donnees_locales", {})
        official_data = raw_certification.get("donnees_officielles", {})
        code = _clean_optional_text(local_data.get("code_rncp"))
        if code is None:
            raise ValueError("Une certification locale ne possède pas de code RNCP.")
        if code in all_codes:
            raise ValueError(f"Code RNCP local dupliqué dans le catalogue : {code}.")
        all_codes.add(code)
        if official_data.get("actif") is not True:
            continue
        rome_codes = tuple(
            sorted(
                {
                    cleaned
                    for raw_code in official_data.get("codes_rome", [])
                    if (cleaned := _clean_optional_text(raw_code)) is not None
                }
            )
        )
        active_certifications.append(
            EvaluationCertification(
                code_rncp=code,
                official_title=_clean_optional_text(
                    official_data.get("intitule_officiel")
                ),
                rome_codes=rome_codes,
                official_data=official_data,
            )
        )
    return (
        tuple(sorted(active_certifications, key=lambda item: item.code_rncp)),
        frozenset(all_codes),
    )


def _candidate_groups(
    rome_code: str,
    certifications: Iterable[EvaluationCertification],
) -> dict[str, tuple[EvaluationCertification, ...]]:
    """Classe les candidats par ROME direct, proche ou négatif contrôlé."""
    rome_family = rome_code[:3]
    grouped: dict[str, list[EvaluationCertification]] = {
        reason: [] for reason in CANDIDATE_REASONS
    }
    for certification in certifications:
        if rome_code in certification.rome_codes:
            reason = CANDIDATE_REASON_DIRECT
        elif any(code.startswith(rome_family) for code in certification.rome_codes):
            reason = CANDIDATE_REASON_NEAR
        else:
            reason = CANDIDATE_REASON_NEGATIVE
        grouped[reason].append(certification)
    return {
        reason: tuple(sorted(items, key=lambda item: item.code_rncp))
        for reason, items in grouped.items()
    }


def _eligible_rome_codes(
    certifications: tuple[EvaluationCertification, ...],
    config: EvaluationSampleConfig,
) -> frozenset[str]:
    """Identifie les ROME Tech disposant des trois catégories de candidats."""
    known_codes = {
        code
        for certification in certifications
        for code in certification.rome_codes
        if any(code.startswith(prefix) for prefix in config.tech_rome_prefixes)
    }
    eligible_codes: set[str] = set()
    for code in known_codes:
        groups = _candidate_groups(code, certifications)
        if (
            len(groups[CANDIDATE_REASON_DIRECT]) >= 2
            and groups[CANDIDATE_REASON_NEAR]
            and groups[CANDIDATE_REASON_NEGATIVE]
        ):
            eligible_codes.add(code)
    return frozenset(eligible_codes)


def _offer_stratum(source: EvaluationOfferSource) -> tuple[str, bool, bool, str]:
    """Retourne la strate ROME, compétences, exigence et richesse descriptive."""
    return (
        source.rome_code,
        bool(source.competences),
        bool(source.training_requirements),
        classify_description_richness(source.description),
    )


def _select_offer_sources(
    sources: Iterable[EvaluationOfferSource],
    eligible_rome_codes: frozenset[str],
    config: EvaluationSampleConfig,
) -> tuple[EvaluationOfferSource, ...]:
    """Sélectionne les offres par parcours déterministe des strates."""
    if config.total_size <= 0 or config.max_offers_per_rome <= 0:
        raise ValueError("Les tailles de l'échantillon doivent être positives.")
    grouped: dict[
        tuple[str, bool, bool, str], list[EvaluationOfferSource]
    ] = defaultdict(list)
    seen_offer_keys: set[tuple[str, str]] = set()
    for source in sources:
        offer_key = _offer_key(source)
        if offer_key in seen_offer_keys:
            raise ValueError(f"Offre source dupliquée : {offer_key}.")
        seen_offer_keys.add(offer_key)
        if source.rome_code in eligible_rome_codes:
            grouped[_offer_stratum(source)].append(source)

    queues: dict[
        tuple[str, bool, bool, str], deque[EvaluationOfferSource]
    ] = {}
    for stratum, stratum_sources in grouped.items():
        queues[stratum] = deque(
            sorted(
                stratum_sources,
                key=lambda item: _offer_hash_key(config.seed, "offre", item),
            )
        )
    ordered_strata = sorted(
        queues,
        key=lambda stratum: _stable_hash(config.seed, "strate", *stratum),
    )

    selected: list[EvaluationOfferSource] = []
    counts_by_rome: Counter[str] = Counter()
    while len(selected) < config.total_size:
        progress = False
        for stratum in ordered_strata:
            queue = queues[stratum]
            rome_code = stratum[0]
            if not queue or counts_by_rome[rome_code] >= config.max_offers_per_rome:
                continue
            selected.append(queue.popleft())
            counts_by_rome[rome_code] += 1
            progress = True
            if len(selected) == config.total_size:
                break
        if not progress:
            break

    if len(selected) != config.total_size:
        raise ValueError(
            "Volume d'offres éligibles insuffisant : "
            f"{len(selected)} sélectionnées pour {config.total_size} attendues."
        )
    return tuple(selected)


def _assign_splits(
    sources: tuple[EvaluationOfferSource, ...],
    config: EvaluationSampleConfig,
) -> tuple[SelectedEvaluationOffer, ...]:
    """Répartit exactement les offres entre development et validation."""
    sources_by_rome: dict[str, list[EvaluationOfferSource]] = defaultdict(list)
    for source in sources:
        sources_by_rome[source.rome_code].append(source)

    validation_quotas = {
        code: (len(code_sources) * config.validation_size) // len(sources)
        for code, code_sources in sources_by_rome.items()
    }
    remaining_validation = config.validation_size - sum(validation_quotas.values())
    quota_priority = sorted(
        sources_by_rome,
        key=lambda code: (
            -(
                (len(sources_by_rome[code]) * config.validation_size)
                % len(sources)
            ),
            _stable_hash(config.seed, "quota-validation", code),
        ),
    )
    for code in quota_priority[:remaining_validation]:
        validation_quotas[code] += 1

    validation_offer_keys: set[tuple[str, str]] = set()
    for code in sorted(sources_by_rome):
        strata: dict[
            tuple[str, bool, bool, str], deque[EvaluationOfferSource]
        ] = defaultdict(deque)
        for source in sorted(
            sources_by_rome[code],
            key=lambda item: _offer_hash_key(config.seed, "validation", item),
        ):
            strata[_offer_stratum(source)].append(source)
        ordered_strata = sorted(
            strata,
            key=lambda stratum: _stable_hash(
                config.seed, "strate-validation", *stratum
            ),
        )
        selected_for_code = 0
        while selected_for_code < validation_quotas[code]:
            for stratum in ordered_strata:
                if not strata[stratum]:
                    continue
                validation_offer_keys.add(_offer_key(strata[stratum].popleft()))
                selected_for_code += 1
                if selected_for_code == validation_quotas[code]:
                    break

    selected: list[SelectedEvaluationOffer] = []
    for source in sources:
        split = (
            "validation"
            if _offer_key(source) in validation_offer_keys
            else "development"
        )
        selected.append(
            SelectedEvaluationOffer(
                source=source,
                split=split,
                description_richness=classify_description_richness(source.description),
                common_matching_text=build_common_matching_text(source),
            )
        )
    return tuple(selected)


def _select_candidate_pool(
    offer: SelectedEvaluationOffer,
    certifications: tuple[EvaluationCertification, ...],
    config: EvaluationSampleConfig,
) -> EvaluationCandidatePool:
    """Construit un pool sans score en équilibrant les trois raisons ROME."""
    if config.candidate_pool_size < 4:
        raise ValueError("Un pool de candidats doit contenir au moins quatre éléments.")
    grouped = _candidate_groups(offer.source.rome_code, certifications)
    if len(grouped[CANDIDATE_REASON_DIRECT]) < 2:
        raise ValueError(
            f"Moins de deux candidats ROME directs pour {offer.source.rome_code}."
        )
    if not grouped[CANDIDATE_REASON_NEAR] or not grouped[CANDIDATE_REASON_NEGATIVE]:
        raise ValueError(f"Pool incomplet pour le code ROME {offer.source.rome_code}.")

    base_quota = config.candidate_pool_size // 3
    direct_quota = max(2, base_quota)
    near_quota = max(1, base_quota)
    quotas = {
        CANDIDATE_REASON_DIRECT: direct_quota,
        CANDIDATE_REASON_NEAR: near_quota,
        CANDIDATE_REASON_NEGATIVE: max(
            1, config.candidate_pool_size - direct_quota - near_quota
        ),
    }
    ranked = {
        reason: sorted(
            items,
            key=lambda item: _stable_hash(
                config.seed,
                offer.source.source,
                offer.source.database_offer_id,
                offer.source.source_offer_id,
                reason,
                item.code_rncp,
            ),
        )
        for reason, items in grouped.items()
    }
    selected: list[EvaluationCandidate] = []
    selected_codes: set[str] = set()
    for reason in CANDIDATE_REASONS:
        for certification in ranked[reason][: quotas[reason]]:
            selected.append(EvaluationCandidate(certification, reason))
            selected_codes.add(certification.code_rncp)

    remaining = [
        EvaluationCandidate(certification, reason)
        for reason in CANDIDATE_REASONS
        for certification in ranked[reason]
        if certification.code_rncp not in selected_codes
    ]
    remaining.sort(
        key=lambda candidate: _stable_hash(
            config.seed,
            offer.source.source,
            offer.source.database_offer_id,
            offer.source.source_offer_id,
            "complement",
            candidate.certification.code_rncp,
        )
    )
    selected.extend(remaining[: config.candidate_pool_size - len(selected)])
    selected = selected[: config.candidate_pool_size]
    if len(selected) != config.candidate_pool_size:
        raise ValueError(
            "Candidats insuffisants pour l'offre "
            f"{offer.source.source}:{offer.source.source_offer_id}."
        )
    return EvaluationCandidatePool(
        source=offer.source.source,
        source_offer_id=offer.source.source_offer_id,
        database_offer_id=offer.source.database_offer_id,
        split=offer.split,
        rome_code=offer.source.rome_code,
        candidates=tuple(selected),
    )


def _validate_sample(sample: EvaluationSample) -> None:
    """Vérifie les tailles, l'unicité et l'intégrité des candidats."""
    split_counts = Counter(offer.split for offer in sample.offers)
    expected_splits = Counter(
        {
            "development": sample.config.development_size,
            "validation": sample.config.validation_size,
        }
    )
    if split_counts != expected_splits:
        raise ValueError(f"Tailles de splits invalides : {dict(split_counts)}.")
    offer_keys = [_offer_key(offer.source) for offer in sample.offers]
    if len(offer_keys) != len(set(offer_keys)):
        raise ValueError("Une offre appartient à plusieurs splits.")
    if len(sample.candidate_pools) != len(sample.offers):
        raise ValueError("Une offre ne possède pas exactement un pool de candidats.")

    pairs: set[tuple[tuple[str, str], str]] = set()
    for pool in sample.candidate_pools:
        if len(pool.candidates) < 2:
            raise ValueError(
                "L'offre "
                f"{pool.source}:{pool.source_offer_id} ne possède pas plusieurs candidats."
            )
        if len(pool.candidates) > sample.config.candidate_pool_size:
            raise ValueError(
                "Le pool de l'offre "
                f"{pool.source}:{pool.source_offer_id} dépasse la limite."
            )
        reasons = {candidate.selection_reason for candidate in pool.candidates}
        if reasons != set(CANDIDATE_REASONS):
            raise ValueError(
                "Le pool de l'offre "
                f"{pool.source}:{pool.source_offer_id} est incomplet."
            )
        for candidate in pool.candidates:
            code = candidate.certification.code_rncp
            if code not in sample.catalogue_codes:
                raise ValueError(f"Successeur externe présent dans les candidats : {code}.")
            if code not in sample.active_catalogue_codes:
                raise ValueError(f"Certification inactive présente : {code}.")
            pair = ((pool.source, pool.source_offer_id), code)
            if pair in pairs:
                raise ValueError(f"Couple offre–certification dupliqué : {pair}.")
            pairs.add(pair)


def build_evaluation_sample(
    sources: Iterable[EvaluationOfferSource],
    certifications: tuple[EvaluationCertification, ...],
    catalogue_codes: frozenset[str],
    catalogue_sha256: str,
    config: EvaluationSampleConfig | None = None,
) -> EvaluationSample:
    """Construit et valide l'échantillon figé à partir des sources fournies."""
    effective_config = config or EvaluationSampleConfig()
    eligible_codes = _eligible_rome_codes(certifications, effective_config)
    if not eligible_codes:
        raise ValueError("Aucun code ROME Tech ne possède assez de candidats actifs.")
    selected_sources = _select_offer_sources(
        sources, eligible_codes, effective_config
    )
    offers = _assign_splits(selected_sources, effective_config)
    candidate_pools = tuple(
        _select_candidate_pool(offer, certifications, effective_config)
        for offer in offers
    )
    sample = EvaluationSample(
        offers=offers,
        candidate_pools=candidate_pools,
        catalogue_sha256=catalogue_sha256,
        catalogue_codes=catalogue_codes,
        active_catalogue_codes=frozenset(
            certification.code_rncp for certification in certifications
        ),
        config=effective_config,
    )
    _validate_sample(sample)
    return sample


def _manifest_dict(sample: EvaluationSample, run_date: date) -> dict[str, Any]:
    """Construit le manifeste agrégé et reproductible du run."""
    split_counts = Counter(offer.split for offer in sample.offers)
    code_distribution: dict[str, dict[str, int]] = {}
    for code in sorted({offer.source.rome_code for offer in sample.offers}):
        code_offers = [offer for offer in sample.offers if offer.source.rome_code == code]
        code_distribution[code] = {
            "development": sum(offer.split == "development" for offer in code_offers),
            "validation": sum(offer.split == "validation" for offer in code_offers),
            "total": len(code_offers),
        }
    pool_sizes = Counter(len(pool.candidates) for pool in sample.candidate_pools)
    return {
        "format_version": FORMAT_VERSION,
        "graine": sample.config.seed,
        "date_run": run_date.isoformat(),
        "hash_catalogue_rncp_enrichi_sha256": sample.catalogue_sha256,
        "parametres": {
            "development_size": sample.config.development_size,
            "validation_size": sample.config.validation_size,
            "candidate_pool_size": sample.config.candidate_pool_size,
            "max_offers_per_rome": sample.config.max_offers_per_rome,
            "tech_rome_prefixes": list(sample.config.tech_rome_prefixes),
            "seuil_description_courte_exclusif": DESCRIPTION_SHORT_LIMIT,
            "seuil_description_longue_inclusif": DESCRIPTION_LONG_LIMIT,
        },
        "compteurs": {
            "offres": len(sample.offers),
            "certifications_actives_disponibles": len(sample.active_catalogue_codes),
            "couples_offre_certification": sum(
                len(pool.candidates) for pool in sample.candidate_pools
            ),
        },
        "distributions": {
            "par_split": dict(sorted(split_counts.items())),
            "par_code_rome": code_distribution,
            "richesse_description": dict(
                sorted(Counter(offer.description_richness for offer in sample.offers).items())
            ),
            "presence_competences": {
                "avec": sum(bool(offer.source.competences) for offer in sample.offers),
                "sans": sum(not offer.source.competences for offer in sample.offers),
            },
            "presence_exigence_france_travail": {
                "avec": sum(
                    bool(offer.source.training_requirements) for offer in sample.offers
                ),
                "sans": sum(
                    not offer.source.training_requirements for offer in sample.offers
                ),
            },
            "taille_pools": {
                str(size): count for size, count in sorted(pool_sizes.items())
            },
        },
    }


def build_evaluation_artifacts(
    sample: EvaluationSample,
    run_date: date,
) -> dict[str, bytes]:
    """Produit en mémoire les quatre artefacts aux octets déterministes."""
    manifest = _manifest_dict(sample, run_date)
    offers_payload = {
        "format_version": FORMAT_VERSION,
        "offres": [offer.to_dict() for offer in sample.offers],
    }
    json_options = {"ensure_ascii": False, "indent": 2, "sort_keys": True}
    candidate_lines = [
        json.dumps(
            pool.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for pool in sample.candidate_pools
    ]

    annotation_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        annotation_buffer,
        fieldnames=ANNOTATION_COLUMNS,
        lineterminator="\n",
    )
    writer.writeheader()
    offers_by_key = {
        _offer_key(offer.source): offer
        for offer in sample.offers
    }
    for pool in sample.candidate_pools:
        offer = offers_by_key[(pool.source, pool.source_offer_id)]
        for candidate in pool.candidates:
            writer.writerow(
                {
                    "split": pool.split,
                    "source": pool.source,
                    "source_offer_id": pool.source_offer_id,
                    "database_offer_id": pool.database_offer_id,
                    "code_rome": pool.rome_code,
                    "intitule_offre": offer.source.title or "",
                    "code_rncp": candidate.certification.code_rncp,
                    "intitule_officiel_certification": (
                        candidate.certification.official_title or ""
                    ),
                    "raison_selection_candidat": candidate.selection_reason,
                    "score_annotateur_1": "",
                    "justification_annotateur_1": "",
                    "score_annotateur_2": "",
                    "justification_annotateur_2": "",
                    "score_final": "",
                    "commentaire_arbitrage": "",
                }
            )
    return {
        "sample_manifest.json": (
            json.dumps(manifest, **json_options).encode("utf-8") + b"\n"
        ),
        "evaluation_offers.json": (
            json.dumps(offers_payload, **json_options).encode("utf-8") + b"\n"
        ),
        "candidate_pools.jsonl": (
            ("\n".join(candidate_lines) + "\n").encode("utf-8")
        ),
        "annotation_template.csv": annotation_buffer.getvalue().encode("utf-8"),
    }


def export_evaluation_artifacts(
    artifacts: Mapping[str, bytes],
    output_directory: Path,
) -> None:
    """Écrit les artefacts préalablement construits dans le dossier demandé."""
    expected_names = {
        "sample_manifest.json",
        "evaluation_offers.json",
        "candidate_pools.jsonl",
        "annotation_template.csv",
    }
    if set(artifacts) != expected_names:
        raise ValueError("La collection d'artefacts est incomplète.")
    output_directory.mkdir(parents=True, exist_ok=True)
    for name in sorted(artifacts):
        (output_directory / name).write_bytes(artifacts[name])
