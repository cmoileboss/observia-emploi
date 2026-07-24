"""Socle commun des méthodes de benchmark offre–certification."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from services.offer_certification_evaluation_sample import (
    EvaluationCompetence,
    EvaluationOfferSource,
    build_common_matching_text,
    load_evaluation_certifications,
)


SUPPORTED_SPLITS = ("development", "validation", "all")


@dataclass(frozen=True)
class BenchmarkOffer:
    """Représente une offre normalisée indépendamment de sa source."""

    source: str
    source_offer_id: str
    database_offer_id: int | None
    split: str
    title: str | None
    matching_text: str

    @property
    def offer_id(self) -> str:
        """Retourne l'identifiant stable qualifié par la source."""
        return f"{self.source}:{self.source_offer_id}"


@dataclass(frozen=True)
class BenchmarkCertification:
    """Représente une certification RNCP active et son texte commun."""

    code_rncp: str
    official_title: str | None
    matching_text: str


@dataclass(frozen=True)
class BenchmarkResult:
    """Décrit le score brut attribué à une certification pour une offre."""

    offer_id: str
    source: str
    source_offer_id: str
    database_offer_id: int | None
    code_rncp: str
    position: int
    raw_score: float
    method_name: str
    method_version: str
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Retourne le résultat sous une forme sérialisable explicite."""
        return {
            "offer_id": self.offer_id,
            "source": self.source,
            "source_offer_id": self.source_offer_id,
            "database_offer_id": self.database_offer_id,
            "code_rncp": self.code_rncp,
            "position": self.position,
            "raw_score": self.raw_score,
            "method_name": self.method_name,
            "method_version": self.method_version,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class BenchmarkOfferRanking:
    """Regroupe le classement complet et le top K d'une offre."""

    offer: BenchmarkOffer
    results: tuple[BenchmarkResult, ...]
    top_k: int

    @property
    def top_results(self) -> tuple[BenchmarkResult, ...]:
        """Retourne les premiers résultats demandés sans altérer le classement."""
        return self.results[: self.top_k]


@dataclass(frozen=True)
class BenchmarkRun:
    """Contient les classements validés et les durées d'une exécution."""

    method_name: str
    method_version: str
    split: str
    top_k: int
    certification_count: int
    rankings: tuple[BenchmarkOfferRanking, ...]
    total_duration_seconds: float

    @property
    def score_count(self) -> int:
        """Retourne le nombre total de scores du classement complet."""
        return sum(len(ranking.results) for ranking in self.rankings)

    @property
    def average_duration_seconds(self) -> float:
        """Retourne la durée murale moyenne par offre."""
        if not self.rankings:
            return 0.0
        return self.total_duration_seconds / len(self.rankings)


class BenchmarkMethod(Protocol):
    """Définit l'interface minimale commune aux méthodes de benchmark."""

    name: str
    version: str

    def rank(
        self,
        offer: BenchmarkOffer,
        certifications: Sequence[BenchmarkCertification],
        top_k: int,
    ) -> BenchmarkOfferRanking:
        """Classe les certifications communes pour une offre et un top K."""
        ...


def _clean_optional_text(value: object) -> str | None:
    """Nettoie une chaîne optionnelle et ignore les autres types."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _required_text(value: object, field_name: str) -> str:
    """Valide et retourne une chaîne obligatoire non vide."""
    cleaned = _clean_optional_text(value)
    if cleaned is None:
        raise ValueError(f"Le champ obligatoire {field_name} est absent ou vide.")
    return cleaned


def _optional_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    """Valide un objet JSON optionnel et retourne un objet vide à défaut."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"Le champ {field_name} doit être un objet JSON.")
    return value


def _load_offer_competences(raw_value: object) -> tuple[EvaluationCompetence, ...]:
    """Charge les compétences structurées utilisées dans le texte commun."""
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ValueError("Le champ champs_sources.competences doit être une liste.")
    competences: list[EvaluationCompetence] = []
    for raw_competence in raw_value:
        if not isinstance(raw_competence, Mapping):
            raise ValueError("Une compétence d'offre doit être un objet JSON.")
        competences.append(
            EvaluationCompetence(
                code=_clean_optional_text(raw_competence.get("code")),
                libelle=_clean_optional_text(raw_competence.get("libelle")),
            )
        )
    return tuple(competences)


def load_benchmark_offers(
    payload: Mapping[str, Any],
    split: str = "development",
) -> tuple[BenchmarkOffer, ...]:
    """Charge et normalise les offres du lot 5 pour le split demandé."""
    if split not in SUPPORTED_SPLITS:
        raise ValueError(
            f"Split inconnu : {split}. Valeurs attendues : {SUPPORTED_SPLITS}."
        )
    raw_offers = payload.get("offres")
    if not isinstance(raw_offers, list):
        raise ValueError("Le fichier d'offres ne contient pas de liste offres.")

    offers: list[BenchmarkOffer] = []
    seen_keys: set[tuple[str, str]] = set()
    for raw_offer in raw_offers:
        if not isinstance(raw_offer, Mapping):
            raise ValueError("Une offre d'évaluation doit être un objet JSON.")
        offer_split = _required_text(raw_offer.get("split"), "split")
        if split != "all" and offer_split != split:
            continue
        source = _required_text(raw_offer.get("source"), "source")
        source_offer_id = _required_text(
            raw_offer.get("source_offer_id"),
            "source_offer_id",
        )
        offer_key = (source, source_offer_id)
        if offer_key in seen_keys:
            raise ValueError(
                "Offre dupliquée dans les données de benchmark : "
                f"{source}/{source_offer_id}."
            )
        seen_keys.add(offer_key)

        database_offer_id = raw_offer.get("database_offer_id")
        if database_offer_id is not None and (
            not isinstance(database_offer_id, int)
            or isinstance(database_offer_id, bool)
        ):
            raise ValueError("database_offer_id doit être un entier ou null.")
        source_fields = _optional_mapping(
            raw_offer.get("champs_sources"),
            "champs_sources",
        )
        evaluation_source = EvaluationOfferSource(
            source=source,
            source_offer_id=source_offer_id,
            database_offer_id=database_offer_id,
            rome_code=_clean_optional_text(raw_offer.get("code_rome")) or "",
            title=_clean_optional_text(source_fields.get("intitule")),
            occupation_label=_clean_optional_text(
                source_fields.get("appellation")
            ),
            rome_label=_clean_optional_text(source_fields.get("libelle_rome")),
            description=_clean_optional_text(source_fields.get("description")),
            competences=_load_offer_competences(
                source_fields.get("competences")
            ),
            training_requirements=(),
        )
        matching_text = build_common_matching_text(evaluation_source)
        if not matching_text:
            raise ValueError(
                f"Le texte commun de l'offre {source}/{source_offer_id} est vide."
            )
        offers.append(
            BenchmarkOffer(
                source=source,
                source_offer_id=source_offer_id,
                database_offer_id=database_offer_id,
                split=offer_split,
                title=evaluation_source.title,
                matching_text=matching_text,
            )
        )
    if not offers:
        raise ValueError(f"Aucune offre disponible pour le split {split}.")
    return tuple(
        sorted(
            offers,
            key=lambda item: (
                item.source,
                item.source_offer_id,
                item.database_offer_id
                if item.database_offer_id is not None
                else -1,
            ),
        )
    )


def build_certification_matching_text(
    official_title: str | None,
    official_data: Mapping[str, Any],
) -> str:
    """Compose le texte commun d'une certification avec les champs officiels."""
    parts: list[str] = []

    def append(value: object) -> None:
        """Ajoute une chaîne nettoyée lorsqu'elle est renseignée."""
        cleaned = _clean_optional_text(value)
        if cleaned is not None:
            parts.append(cleaned)

    append(official_title)
    level = _optional_mapping(official_data.get("niveau"), "niveau")
    append(level.get("code"))
    append(level.get("libelle"))

    raw_rome_codes = official_data.get("codes_rome", [])
    if not isinstance(raw_rome_codes, list):
        raise ValueError("Le champ officiel codes_rome doit être une liste.")
    for raw_rome_code in raw_rome_codes:
        append(raw_rome_code)

    for field_name in (
        "activites_visees",
        "competences_attestees",
        "metiers_accessibles",
        "secteurs_activite",
    ):
        append(official_data.get(field_name))

    raw_blocks = official_data.get("blocs_competences", [])
    if raw_blocks is None:
        raw_blocks = []
    if not isinstance(raw_blocks, list):
        raise ValueError(
            "Le champ officiel blocs_competences doit être une liste."
        )
    for raw_block in raw_blocks:
        if not isinstance(raw_block, Mapping):
            raise ValueError("Un bloc de compétences doit être un objet JSON.")
        append(raw_block.get("code"))
        append(raw_block.get("libelle"))
        append(raw_block.get("competences"))

    append(official_data.get("prerequis"))
    return "\n".join(parts)


def load_active_benchmark_certifications(
    payload: Mapping[str, Any],
) -> tuple[BenchmarkCertification, ...]:
    """Charge les certifications locales actives et prépare leur texte commun."""
    active_certifications, _ = load_evaluation_certifications(payload)
    certifications = tuple(
        BenchmarkCertification(
            code_rncp=certification.code_rncp,
            official_title=certification.official_title,
            matching_text=build_certification_matching_text(
                certification.official_title,
                certification.official_data,
            ),
        )
        for certification in active_certifications
    )
    metadata = _optional_mapping(payload.get("metadata"), "metadata")
    counters = _optional_mapping(metadata.get("compteurs"), "metadata.compteurs")
    expected_count = counters.get("nombre_certifications_actives")
    if expected_count is not None and expected_count != len(certifications):
        raise ValueError(
            "Le compteur de certifications actives est incohérent : "
            f"{expected_count} annoncé pour {len(certifications)} chargé."
        )
    if not certifications:
        raise ValueError("Le catalogue ne contient aucune certification active.")
    empty_codes = [
        certification.code_rncp
        for certification in certifications
        if not certification.matching_text
    ]
    if empty_codes:
        raise ValueError(
            "Texte de certification vide pour : "
            f"{', '.join(sorted(empty_codes))}."
        )
    return certifications


def _validate_offer_ranking(
    ranking: BenchmarkOfferRanking,
    certification_codes: frozenset[str],
    method: BenchmarkMethod,
    top_k: int,
) -> None:
    """Valide la complétude et les invariants d'un classement d'offre."""
    if ranking.offer.offer_id != ranking.results[0].offer_id:
        raise ValueError("Le classement ne correspond pas à l'offre demandée.")
    if ranking.top_k != top_k:
        raise ValueError("La méthode n'a pas respecté la valeur top_k.")
    result_codes = [result.code_rncp for result in ranking.results]
    if len(result_codes) != len(certification_codes):
        raise ValueError("Le classement ne contient pas toutes les certifications.")
    if frozenset(result_codes) != certification_codes:
        raise ValueError("Le classement contient des codes RNCP invalides ou dupliqués.")
    if [result.position for result in ranking.results] != list(
        range(1, len(result_codes) + 1)
    ):
        raise ValueError("Les positions du classement ne sont pas continues.")
    for result in ranking.results:
        if result.method_name != method.name or result.method_version != method.version:
            raise ValueError("Les métadonnées de méthode sont incohérentes.")
        if not math.isfinite(result.raw_score):
            raise ValueError("Un score brut doit être fini.")
        if (
            not math.isfinite(result.duration_seconds)
            or result.duration_seconds < 0
        ):
            raise ValueError("Une durée doit être finie et positive ou nulle.")


def run_benchmark(
    method: BenchmarkMethod,
    offers: Sequence[BenchmarkOffer],
    certifications: Sequence[BenchmarkCertification],
    split: str,
    top_k: int,
    *,
    clock: Callable[[], float],
) -> BenchmarkRun:
    """Exécute une méthode sur toutes les offres puis valide les classements."""
    if not offers:
        raise ValueError("Le benchmark requiert au moins une offre.")
    if not certifications:
        raise ValueError("Le benchmark requiert au moins une certification.")
    if top_k <= 0 or top_k > len(certifications):
        raise ValueError(
            f"top_k doit être compris entre 1 et {len(certifications)}."
        )
    certification_codes = [item.code_rncp for item in certifications]
    if len(certification_codes) != len(set(certification_codes)):
        raise ValueError("Les certifications du benchmark contiennent des doublons.")

    started_at = clock()
    rankings: list[BenchmarkOfferRanking] = []
    for offer in offers:
        ranking = method.rank(offer, certifications, top_k)
        if not ranking.results:
            raise ValueError("Une méthode a retourné un classement vide.")
        _validate_offer_ranking(
            ranking,
            frozenset(certification_codes),
            method,
            top_k,
        )
        rankings.append(ranking)
    total_duration = clock() - started_at
    if not math.isfinite(total_duration) or total_duration < 0:
        raise ValueError("La durée totale du benchmark est invalide.")
    return BenchmarkRun(
        method_name=method.name,
        method_version=method.version,
        split=split,
        top_k=top_k,
        certification_count=len(certifications),
        rankings=tuple(rankings),
        total_duration_seconds=total_duration,
    )
