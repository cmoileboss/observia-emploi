"""Tokenisation lexicale commune aux méthodes de benchmark."""

from __future__ import annotations

import re
import unicodedata


TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize_benchmark_text(text: str) -> tuple[str, ...]:
    """Normalise les accents et extrait des termes Unicode en minuscules."""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return tuple(TOKEN_PATTERN.findall(without_accents))
