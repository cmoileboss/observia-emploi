"""France Travail ROME referential service.

Fetches the full list of ROME job codes from the France Travail API
(``/referentiel/metiers`` endpoint), then filters them against a
requested set of codes (the V1 target list: M1801, M1802, M1805,
M1806, M1810).

The resulting export contains:
- Metadata describing which codes were found / missing.
- Full items with ``code_rome``, ``libelle_rome`` and selection flags.

Historical role: this was the first Lot 1B implementation. The referential
it produces is still consumed by ``volume_measurement.py`` for the core
5-code measurement workflow.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import requests

from observia_emploi.france_travail.client import FranceTravailClient
from observia_emploi.france_travail.models import (
    NormalizedReferentialExport,
    RomeMetierItem,
    RomeSelectionMetadata,
)

logger = logging.getLogger(__name__)

TEST_ROME_CODES = ["M1801", "M1802", "M1805", "M1806", "M1810"]


class RomeReferentialService:
    """Fetch, filter, and export the ROME métiers referential from France Travail."""

    def __init__(self, client: FranceTravailClient) -> None:
        """Initialize service with client."""
        self.client = client

    def fetch_and_filter_rome(
        self, requested_codes: list[str], scope: str = "v1_test_tech_ia"
    ) -> NormalizedReferentialExport:
        """Fetch ROME métiers and filter them using selection parameters."""
        logger.info("Fetching France Travail ROME referential...")

        try:
            # Query the required partner referentiel metiers endpoint
            raw_data = self.client.get(
                "partenaire/offresdemploi/v2/referentiel/metiers"
            )
        except requests.RequestException:
            logger.error("Failed to query referentiel métiers endpoint.")
            raise

        if not isinstance(raw_data, list):
            logger.error("Unexpected response format from API: expected a list.")
            raise ValueError("Unexpected response format from API.")

        requested_set = set(requested_codes)
        found_set: set[str] = set()

        items: list[RomeMetierItem] = []
        for item in raw_data:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            libelle = item.get("libelle", "")

            if code in requested_set:
                found_set.add(code)
                items.append(
                    RomeMetierItem(
                        code_rome=code,
                        libelle_rome=libelle,
                        source_api="france_travail",
                        is_selected_for_v1=True,
                        theme="tech",
                    )
                )

        missing_codes = list(requested_set - found_set)
        # Sort for stable/predictable output ordering
        found_codes = sorted(found_set)
        missing_codes.sort()

        logger.info(
            "Found %d ROME codes out of %d requested.",
            len(found_codes),
            len(requested_codes),
        )

        metadata = RomeSelectionMetadata(
            scope=scope,
            rome_codes_requested=requested_codes,
            rome_codes_found=found_codes,
            rome_codes_missing=missing_codes,
        )

        return NormalizedReferentialExport(
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            selection=metadata,
            items=items,
        )

    def export_to_json(
        self, export_data: NormalizedReferentialExport, output_path: Path
    ) -> None:
        """Export the consolidated referential metadata to a clean JSON file."""
        logger.info("Exporting referential to %s...", output_path)

        # Ensure parent directories exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(export_data.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("Export completed successfully.")
        except Exception:
            logger.error("Failed to write ROME referential export file.")
            raise
