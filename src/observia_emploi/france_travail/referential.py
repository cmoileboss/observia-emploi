"""France Travail ROME referential service."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from observia_emploi.france_travail.client import FranceTravailClient
from observia_emploi.france_travail.models import ReferentialExport, RomeMetier

logger = logging.getLogger(__name__)


class RomeReferentialService:
    """Service to interact with, filter, and export the ROME referential."""

    def __init__(self, client: FranceTravailClient) -> None:
        """Initialize service with client."""
        self.client = client

    def fetch_and_filter_rome(self, validated_rome_codes: set[str]) -> list[RomeMetier]:
        """Fetch all ROME métiers and filter against the validated list of codes."""
        logger.info("Fetching ROME referential...")
        raw_data = self.client.get("partenaire/rome/v1/metiers")

        filtered_metiers: list[RomeMetier] = []
        for item in raw_data:
            code = item.get("code")
            libelle = item.get("libelle", "")
            if code in validated_rome_codes:
                filtered_metiers.append(
                    RomeMetier(code_rome=code, libelle=libelle, validated=True)
                )

        logger.info(
            "Filtered %d matching ROME codes out of %d total.",
            len(filtered_metiers),
            len(raw_data),
        )
        return filtered_metiers

    def export_to_json(self, metiers: list[RomeMetier], output_path: Path) -> None:
        """Export the filtered list of ROME métiers to a clean JSON file.

        The JSON file will be compatible with the pipeline.
        """
        logger.info(f"Exporting referential to {output_path}...")

        # Ensure parent directories exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        export_data = ReferentialExport(
            extracted_at=datetime.now(UTC).isoformat(),
            source="France Travail ROME",
            count=len(metiers),
            metiers=metiers,
        )

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(export_data.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info("Export completed successfully.")
