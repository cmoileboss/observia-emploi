"""Data models for France Travail integration."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RomeSelectionMetadata:
    """Represents the filtering metadata selection block."""

    scope: str
    rome_codes_requested: list[str]
    rome_codes_found: list[str]
    rome_codes_missing: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert object to standard dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class RomeMetierItem:
    """Represents a single normalized ROME job code item in the selection."""

    code_rome: str
    libelle_rome: str
    source_api: str = "france_travail"
    is_selected_for_v1: bool = True
    theme: str = "tech"

    def to_dict(self) -> dict[str, Any]:
        """Convert object to standard dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class NormalizedReferentialExport:
    """Represents the final structured export JSON schema."""

    generated_at: str
    selection: RomeSelectionMetadata
    items: list[RomeMetierItem]
    source: str = "france_travail_api"
    dataset: str = "referentiel_metiers_rome"

    def to_dict(self) -> dict[str, Any]:
        """Convert object to exportable dictionary."""
        return {
            "source": self.source,
            "dataset": self.dataset,
            "generated_at": self.generated_at,
            "selection": self.selection.to_dict(),
            "items": [item.to_dict() for item in self.items],
        }
