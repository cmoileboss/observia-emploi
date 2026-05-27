"""Data models for France Travail integration."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RomeMetier:
    """Represents a ROME job code and details."""

    code_rome: str
    libelle: str
    validated: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert object to standard dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class ReferentialExport:
    """Represents the final structured export JSON schema."""

    extracted_at: str
    source: str
    count: int
    metiers: list[RomeMetier]

    def to_dict(self) -> dict[str, Any]:
        """Convert object to exportable dictionary."""
        return {
            "extracted_at": self.extracted_at,
            "source": self.source,
            "count": self.count,
            "metiers": [m.to_dict() for m in self.metiers],
        }
