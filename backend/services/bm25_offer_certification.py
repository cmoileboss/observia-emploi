"""Méthode BM25 déterministe du benchmark offre–certification."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import Mapping, Sequence

from backend.services.benchmark_text_tokenization import (
    tokenize_benchmark_text,
)
from backend.services.offer_certification_benchmark import (
    BenchmarkCertification,
    BenchmarkOffer,
    BenchmarkOfferRanking,
    BenchmarkResult,
)


DEFAULT_K1 = 1.5
DEFAULT_B = 0.75


@dataclass(frozen=True)
class _Bm25Index:
    """Conserve l'index BM25 immuable des certifications actives."""

    certifications: tuple[BenchmarkCertification, ...]
    term_frequencies: tuple[Mapping[str, int], ...]
    document_lengths: tuple[int, ...]
    average_document_length: float
    inverse_document_frequencies: Mapping[str, float]


def _build_index(
    certifications: tuple[BenchmarkCertification, ...],
) -> _Bm25Index:
    """Prépare une seule fois les fréquences et IDF classiques de BM25."""
    tokenized_documents = tuple(
        tokenize_benchmark_text(certification.matching_text)
        for certification in certifications
    )
    term_frequencies = tuple(
        Counter(tokens) for tokens in tokenized_documents
    )
    document_lengths = tuple(len(tokens) for tokens in tokenized_documents)
    document_count = len(certifications)
    average_document_length = (
        sum(document_lengths) / document_count if document_count else 0.0
    )
    document_frequencies: Counter[str] = Counter()
    for frequencies in term_frequencies:
        document_frequencies.update(frequencies.keys())
    inverse_document_frequencies = {
        term: math.log(
            1.0
            + (
                document_count
                - document_frequency
                + 0.5
            )
            / (document_frequency + 0.5)
        )
        for term, document_frequency in document_frequencies.items()
    }
    return _Bm25Index(
        certifications=certifications,
        term_frequencies=term_frequencies,
        document_lengths=document_lengths,
        average_document_length=average_document_length,
        inverse_document_frequencies=inverse_document_frequencies,
    )


class Bm25BenchmarkMethod:
    """Classe les certifications avec la formule Okapi BM25 classique."""

    name = "BM25"
    version = "1.0"

    def __init__(
        self,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
    ) -> None:
        """Valide les paramètres BM25 et initialise un index vide."""
        if (
            isinstance(k1, bool)
            or not isinstance(k1, (int, float))
            or not math.isfinite(k1)
            or k1 <= 0
        ):
            raise ValueError("k1 doit être un nombre fini strictement positif.")
        if (
            isinstance(b, bool)
            or not isinstance(b, (int, float))
            or not math.isfinite(b)
            or not 0 <= b <= 1
        ):
            raise ValueError("b doit être un nombre fini compris entre 0 et 1.")
        self.k1 = float(k1)
        self.b = float(b)
        self._index: _Bm25Index | None = None

    def _get_index(
        self,
        certifications: Sequence[BenchmarkCertification],
    ) -> _Bm25Index:
        """Construit puis réutilise l'index de la collection commune."""
        ordered_certifications = tuple(
            sorted(certifications, key=lambda item: item.code_rncp)
        )
        if (
            self._index is None
            or self._index.certifications != ordered_certifications
        ):
            self._index = _build_index(ordered_certifications)
        return self._index

    def _score_document(
        self,
        query_terms: Sequence[str],
        document_frequencies: Mapping[str, int],
        document_length: int,
        index: _Bm25Index,
    ) -> float:
        """Calcule le score BM25 brut d'un document pour une requête."""
        average_length = index.average_document_length or 1.0
        length_normalization = self.k1 * (
            1.0
            - self.b
            + self.b * document_length / average_length
        )
        score = 0.0
        for term in query_terms:
            term_frequency = document_frequencies.get(term, 0)
            if term_frequency == 0:
                continue
            inverse_document_frequency = (
                index.inverse_document_frequencies.get(term)
            )
            if inverse_document_frequency is None:
                continue
            score += (
                inverse_document_frequency
                * term_frequency
                * (self.k1 + 1.0)
                / (term_frequency + length_normalization)
            )
        return score

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
        query_terms = tuple(
            sorted(set(tokenize_benchmark_text(offer.matching_text)))
        )
        scored_certifications = [
            (
                certification.code_rncp,
                self._score_document(
                    query_terms,
                    document_frequencies,
                    document_length,
                    index,
                ),
            )
            for certification, document_frequencies, document_length in zip(
                index.certifications,
                index.term_frequencies,
                index.document_lengths,
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
