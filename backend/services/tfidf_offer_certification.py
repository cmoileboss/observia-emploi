"""Méthode TF-IDF déterministe du benchmark offre–certification."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import Mapping, Sequence

from services.benchmark_text_tokenization import (
    tokenize_benchmark_text,
)
from services.offer_certification_benchmark import (
    BenchmarkCertification,
    BenchmarkOffer,
    BenchmarkOfferRanking,
    BenchmarkResult,
)


@dataclass(frozen=True)
class _TfidfIndex:
    """Conserve l'index TF-IDF immuable des certifications actives."""

    certifications: tuple[BenchmarkCertification, ...]
    inverse_document_frequencies: Mapping[str, float]
    certification_vectors: tuple[Mapping[str, float], ...]


def _build_normalized_vector(
    tokens: Sequence[str],
    inverse_document_frequencies: Mapping[str, float],
) -> dict[str, float]:
    """Construit un vecteur TF-IDF sous-linéaire normalisé en norme L2."""
    counts = Counter(
        token for token in tokens if token in inverse_document_frequencies
    )
    weights = {
        token: (1.0 + math.log(count)) * inverse_document_frequencies[token]
        for token, count in counts.items()
    }
    norm = math.sqrt(sum(weight * weight for weight in weights.values()))
    if norm == 0:
        return {}
    return {token: weight / norm for token, weight in weights.items()}


def _build_index(
    certifications: tuple[BenchmarkCertification, ...],
) -> _TfidfIndex:
    """Prépare le vocabulaire, les IDF lissés et les vecteurs RNCP."""
    tokenized_documents = tuple(
        tokenize_benchmark_text(certification.matching_text)
        for certification in certifications
    )
    document_frequencies: Counter[str] = Counter()
    for tokens in tokenized_documents:
        document_frequencies.update(set(tokens))
    document_count = len(certifications)
    inverse_document_frequencies = {
        token: math.log(
            (1.0 + document_count) / (1.0 + document_frequency)
        )
        + 1.0
        for token, document_frequency in document_frequencies.items()
    }
    vectors = tuple(
        _build_normalized_vector(tokens, inverse_document_frequencies)
        for tokens in tokenized_documents
    )
    return _TfidfIndex(
        certifications=certifications,
        inverse_document_frequencies=inverse_document_frequencies,
        certification_vectors=vectors,
    )


def _cosine_similarity(
    first: Mapping[str, float],
    second: Mapping[str, float],
) -> float:
    """Calcule le produit scalaire de deux vecteurs déjà normalisés."""
    if len(first) > len(second):
        first, second = second, first
    return sum(weight * second.get(token, 0.0) for token, weight in first.items())


class TfidfBenchmarkMethod:
    """Classe les certifications par similarité cosinus TF-IDF brute."""

    name = "TF_IDF"
    version = "1.0"

    def __init__(self) -> None:
        """Initialise une méthode sans index de certifications."""
        self._index: _TfidfIndex | None = None

    def _get_index(
        self,
        certifications: Sequence[BenchmarkCertification],
    ) -> _TfidfIndex:
        """Réutilise l'index lorsque la collection commune est inchangée."""
        ordered_certifications = tuple(
            sorted(certifications, key=lambda item: item.code_rncp)
        )
        if (
            self._index is None
            or self._index.certifications != ordered_certifications
        ):
            self._index = _build_index(ordered_certifications)
        return self._index

    def rank(
        self,
        offer: BenchmarkOffer,
        certifications: Sequence[BenchmarkCertification],
        top_k: int,
    ) -> BenchmarkOfferRanking:
        """Classe toute la collection RNCP avec un départage par code."""
        if top_k <= 0 or top_k > len(certifications):
            raise ValueError(
                f"top_k doit être compris entre 1 et {len(certifications)}."
            )
        started_at = perf_counter()
        index = self._get_index(certifications)
        offer_vector = _build_normalized_vector(
            tokenize_benchmark_text(offer.matching_text),
            index.inverse_document_frequencies,
        )
        scored_certifications = [
            (
                certification.code_rncp,
                _cosine_similarity(offer_vector, certification_vector),
            )
            for certification, certification_vector in zip(
                index.certifications,
                index.certification_vectors,
                strict=True,
            )
        ]
        scored_certifications.sort(key=lambda item: (-item[1], item[0]))
        duration = perf_counter() - started_at
        results = tuple(
            BenchmarkResult(
                offer_id=offer.offer_id,
                source=offer.source,
                source_offer_id=offer.source_offer_id,
                database_offer_id=offer.database_offer_id,
                code_rncp=code_rncp,
                position=position,
                raw_score=score,
                method_name=self.name,
                method_version=self.version,
                duration_seconds=duration,
            )
            for position, (code_rncp, score) in enumerate(
                scored_certifications,
                start=1,
            )
        )
        return BenchmarkOfferRanking(
            offer=offer,
            results=results,
            top_k=top_k,
        )
