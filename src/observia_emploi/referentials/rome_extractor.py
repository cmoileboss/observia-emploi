"""Service to extract unique ROME codes and their statistics from the CSV."""

import csv
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RomeExtractedItem:
    """Represents an extracted ROME code with its calculated aggregates."""

    code_rome: str
    intitule_rome: str
    rncp_count: int
    total_entrees_formation: int
    total_sorties_realisation_partielle: int
    total_sorties_realisation_totale: int

    def to_dict(self) -> dict[str, Any]:
        """Convert object to standard dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class RomeExtractedExport:
    """Represents the final structured export schema for extracted ROME codes."""

    total_unique_rome_codes: int
    items: list[RomeExtractedItem]
    source: str = "merged_data.csv"
    dataset: str = "rome_codes_from_training_mapping"

    def to_dict(self) -> dict[str, Any]:
        """Convert object to exportable dictionary."""
        return {
            "source": self.source,
            "dataset": self.dataset,
            "total_unique_rome_codes": self.total_unique_rome_codes,
            "items": [item.to_dict() for item in self.items],
        }


class RomeExtractorService:
    """Service to extract unique ROME codes with metrics from training CSV."""

    def extract_from_csv(self, csv_path: Path) -> RomeExtractedExport:
        """Read CSV, extract unique ROME codes, and aggregate training metrics."""
        logger.info("Reading training mapping from %s...", csv_path)

        if not csv_path.exists():
            raise FileNotFoundError(f"Source CSV file not found: {csv_path}")

        # Dict mapping code_rome to its main label and accumulated stats.
        # Format: code_rome -> {"intitule_rome": str, "rncp_codes": set[str],
        # "entrees": int, "partielle": int, "totale": int}
        rome_aggregates: dict[str, dict[str, Any]] = {}

        try:
            with csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter=";")

                # Check for required headers
                headers = reader.fieldnames or []
                required = [
                    "code_rome",
                    "intitule_rome",
                    "code_rncp",
                    "entrees_formation",
                    "sorties_realisation_partielle",
                    "sorties_realisation_totale",
                ]
                for req in required:
                    if req not in headers:
                        raise ValueError(f"Missing required CSV column: {req}")

                for row in reader:
                    code_rome = row.get("code_rome", "").strip()
                    intitule_rome = row.get("intitule_rome", "").strip()

                    if not code_rome:
                        continue

                    # Safe parsing of numeric columns
                    try:
                        entrees = int(row.get("entrees_formation") or 0)
                    except ValueError:
                        entrees = 0

                    try:
                        partielle = int(row.get("sorties_realisation_partielle") or 0)
                    except ValueError:
                        partielle = 0

                    try:
                        totale = int(row.get("sorties_realisation_totale") or 0)
                    except ValueError:
                        totale = 0

                    code_rncp = row.get("code_rncp", "").strip()

                    if code_rome not in rome_aggregates:
                        rome_aggregates[code_rome] = {
                            "intitule_rome": intitule_rome,
                            "rncp_codes": set(),
                            "entrees": 0,
                            "partielle": 0,
                            "totale": 0,
                        }

                    # Keep first non-empty title if first record had none
                    if (
                        intitule_rome
                        and not rome_aggregates[code_rome]["intitule_rome"]
                    ):
                        rome_aggregates[code_rome]["intitule_rome"] = intitule_rome

                    if code_rncp:
                        rome_aggregates[code_rome]["rncp_codes"].add(code_rncp)

                    rome_aggregates[code_rome]["entrees"] += entrees
                    rome_aggregates[code_rome]["partielle"] += partielle
                    rome_aggregates[code_rome]["totale"] += totale

        except ValueError:
            # Re-raise explicit column missing errors
            raise
        except Exception as e:
            logger.error("Failed to parse CSV file: %s", e)
            raise RuntimeError(f"Failed to parse CSV file: {e}") from e

        # Convert to list of RomeExtractedItem sorted by code_rome
        items: list[RomeExtractedItem] = []
        for code in sorted(rome_aggregates.keys()):
            agg = rome_aggregates[code]
            items.append(
                RomeExtractedItem(
                    code_rome=code,
                    intitule_rome=agg["intitule_rome"],
                    rncp_count=len(agg["rncp_codes"]),
                    total_entrees_formation=agg["entrees"],
                    total_sorties_realisation_partielle=agg["partielle"],
                    total_sorties_realisation_totale=agg["totale"],
                )
            )

        logger.info("Successfully extracted %d unique ROME codes.", len(items))

        return RomeExtractedExport(
            total_unique_rome_codes=len(items),
            items=items,
        )

    def export_to_json(
        self, export_data: RomeExtractedExport, output_path: Path
    ) -> None:
        """Export the extracted ROME metrics to a lightweight UTF-8 JSON file."""
        logger.info("Saving extracted ROME reference to %s...", output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(export_data.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("Reference export completed successfully.")
        except Exception as e:
            logger.error("Failed to write reference export file: %s", e)
            raise RuntimeError(f"Failed to write export JSON: {e}") from e
