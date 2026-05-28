"""Service to measure the volume and aggregations of job offers by ROME code."""

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from observia_emploi.france_travail.client import FranceTravailClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RomeVolumeMeasure:
    """Consolidated measurement metrics for a single ROME code."""

    code_rome: str
    libelle_rome: str
    total_offres_disponibles: int
    http_status: int
    content_range: str | None
    contract_aggregations: dict[str, int] = field(default_factory=dict)
    experience_aggregations: dict[str, int] = field(default_factory=dict)
    qualification_aggregations: dict[str, int] = field(default_factory=dict)
    nature_contract_aggregations: dict[str, int] = field(default_factory=dict)
    first_result_rome_code: str | None = None
    first_result_id: str | None = None
    collected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert structure to standard dictionary representation."""
        return asdict(self)


@dataclass(frozen=True)
class VolumeReport:
    """Synthesis report of volume measurements for all targeted ROME codes."""

    source: str = "france_travail_api"
    dataset: str = "offres_volumes_rome"
    collected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    measures: list[RomeVolumeMeasure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to standard dictionary representation."""
        return {
            "source": self.source,
            "dataset": self.dataset,
            "collected_at": self.collected_at,
            "measures": [m.to_dict() for m in self.measures],
        }


class RomeVolumeMeasurementService:
    """Service to query, parse, and export job offers metrics.

    Queries the France Travail API search endpoint.
    """

    def __init__(self, client: FranceTravailClient) -> None:
        """Initialize with France Travail client."""
        self.client = client

    def parse_content_range(self, content_range_str: str | None) -> int:
        """Parse HTTP Content-Range header to extract total items count.

        Example: "offres 0-0/4152" -> 4152
        """
        if not content_range_str:
            return 0

        # Matches format: 'offres 0-0/4152' or 'offres 0-149/1500' or similar
        match = re.search(r"offres\s+\d+-\d+/(\d+)", content_range_str)
        if match:
            return int(match.group(1))

        # Fallback to any trailing number slash pattern
        match_slash = re.search(r"/(\d+)", content_range_str)
        if match_slash:
            return int(match_slash.group(1))

        return 0

    def extract_aggregations(
        self, raw_data: dict[str, Any], filter_name: str
    ) -> dict[str, int]:
        """Extract a specific aggregation dictionary from filtresPossibles list."""
        aggregations: dict[str, int] = {}
        filtres = raw_data.get("filtresPossibles")
        if not filtres or not isinstance(filtres, list):
            return aggregations

        for f in filtres:
            if isinstance(f, dict) and f.get("filtre") == filter_name:
                valeurs = f.get("valeurs", [])
                if isinstance(valeurs, list):
                    for item in valeurs:
                        if isinstance(item, dict) and "valeur" in item and "nb" in item:
                            aggregations[str(item["valeur"])] = int(item["nb"])

        return aggregations

    def measure_single_rome(
        self, code_rome: str, libelle_rome: str
    ) -> RomeVolumeMeasure:
        """Query and build volume measurement metrics for a single ROME code."""
        logger.info("Measuring volume for ROME code: %s (%s)", code_rome, libelle_rome)

        endpoint = "partenaire/offresdemploi/v2/offres/search"
        params = {"codeROME": code_rome, "range": "0-0"}

        try:
            response = self.client.get_raw(endpoint, params=params)
            status_code = response.status_code
        except Exception as e:
            logger.error(
                "Failed to perform volume API call for ROME %s: %s", code_rome, e
            )
            return RomeVolumeMeasure(
                code_rome=code_rome,
                libelle_rome=libelle_rome,
                total_offres_disponibles=0,
                http_status=500,
                content_range=None,
            )

        content_range_val = response.headers.get("Content-Range")
        total_offers = self.parse_content_range(content_range_val)

        # Handle API responses indicating no results or other status
        if status_code in (204, 404):
            return RomeVolumeMeasure(
                code_rome=code_rome,
                libelle_rome=libelle_rome,
                total_offres_disponibles=0,
                http_status=status_code,
                content_range=content_range_val,
            )

        # Attempt to parse json body for 200 or 206 statuses
        raw_json: dict[str, Any] = {}
        if status_code in (200, 206):
            try:
                raw_json = response.json()
            except Exception:
                logger.warning("Failed to decode JSON response for ROME %s", code_rome)

        # Extract first offer details if present to assert API codeROME accuracy
        first_rome_code: str | None = None
        first_id: str | None = None
        results = raw_json.get("resultats", [])
        if results and isinstance(results, list):
            first_offer = results[0]
            if isinstance(first_offer, dict):
                first_rome_code = first_offer.get("romeCode")
                first_id = first_offer.get("id")

        # Extract aggregations
        contracts = self.extract_aggregations(raw_json, "typeContrat")
        experience = self.extract_aggregations(raw_json, "experience")
        qualification = self.extract_aggregations(raw_json, "qualification")
        natures = self.extract_aggregations(raw_json, "natureContrat")

        return RomeVolumeMeasure(
            code_rome=code_rome,
            libelle_rome=libelle_rome,
            total_offres_disponibles=total_offers,
            http_status=status_code,
            content_range=content_range_val,
            contract_aggregations=contracts,
            experience_aggregations=experience,
            qualification_aggregations=qualification,
            nature_contract_aggregations=natures,
            first_result_rome_code=first_rome_code,
            first_result_id=first_id,
        )

    def measure_rome_volumes(self, referential_path: Path) -> VolumeReport:
        """Measure all job offers metrics for targeted ROME codes.

        Ensures all 5 core V1 ROME codes are measured.
        """
        logger.info("Loading ROME referential from %s", referential_path)

        # Core target V1 ROME codes that must always be measured
        target_codes = ["M1801", "M1802", "M1805", "M1806", "M1810"]
        items_dict: dict[str, str] = {}

        # 1. Read existing referential if available
        if referential_path.exists():
            try:
                with referential_path.open("r", encoding="utf-8") as f:
                    ref_data = json.load(f)
                items = ref_data.get("items", [])
                for item in items:
                    code = item.get("code_rome")
                    libelle = item.get("libelle_rome")
                    if code:
                        items_dict[code] = libelle or ""
            except Exception as e:
                logger.warning(
                    "Failed to parse ROME referential JSON: %s. Using targets.",
                    e,
                )

        # 2. Build complete list of items to measure (guarantee all targets are present)
        final_items: list[dict[str, str]] = []
        # Fallback default names for core targets
        default_names = {
            "M1801": "Administration de systèmes d'information",
            "M1802": "Expertise et support technique en SI",
            "M1805": "Études et développement informatique",
            "M1806": "Conseil et maîtrise d'ouvrage en SI",
            "M1810": "Production et exploitation de systèmes d'information",
        }

        for code in target_codes:
            libelle = items_dict.get(code) or default_names.get(
                code, "Métier ROME inconnu"
            )
            final_items.append({"code_rome": code, "libelle_rome": libelle})

        measures: list[RomeVolumeMeasure] = []

        for index, item in enumerate(final_items):
            # Enforce 3 req/s sequential delay on real client (0.35s delay)
            if index > 0 and not hasattr(self.client, "_is_mock_client"):
                from observia_emploi.france_travail.client import (
                    MockFranceTravailClient,
                )

                if not isinstance(self.client, MockFranceTravailClient):
                    logger.debug("Applying 350ms rate limit delay...")
                    time.sleep(0.35)

            code = item["code_rome"]
            libelle = item["libelle_rome"]
            measure = self.measure_single_rome(code, libelle)
            measures.append(measure)

        return VolumeReport(measures=measures)

    def measure_all_rome_from_file(self, referential_path: Path) -> VolumeReport:
        """Measure job offers metrics for all ROME codes present in the JSON file.

        Reads the merged referential JSON and queries France Travail for
        every ROME code. Enforces a 0.25s delay between requests to respect
        the 5 req/s limit.
        """
        logger.info("Loading extracted ROME referential from %s", referential_path)

        if not referential_path.exists():
            logger.error("Referential file not found: %s", referential_path)
            raise FileNotFoundError(f"Referential file missing: {referential_path}")

        try:
            with referential_path.open("r", encoding="utf-8") as f:
                ref_data = json.load(f)
        except Exception as e:
            logger.error("Failed to parse ROME referential JSON: %s", e)
            raise

        items = ref_data.get("items", [])
        if not items:
            logger.warning("No items found in the referential file.")
            return VolumeReport(measures=[])

        measures: list[RomeVolumeMeasure] = []

        for index, item in enumerate(items):
            code = item.get("code_rome")
            # The new format uses 'intitule_rome', fallback to 'libelle_rome' if needed
            libelle = item.get("intitule_rome") or item.get("libelle_rome") or "Inconnu"

            if not code:
                continue

            # Enforce 0.25s sequential delay on real client (max 5 req/s)
            if index > 0 and not hasattr(self.client, "_is_mock_client"):
                from observia_emploi.france_travail.client import (
                    MockFranceTravailClient,
                )

                if not isinstance(self.client, MockFranceTravailClient):
                    logger.debug("Applying 250ms rate limit delay...")
                    time.sleep(0.25)

            measure = self.measure_single_rome(code, libelle)
            measures.append(measure)

        return VolumeReport(measures=measures)

    def export_report_to_json(self, report: VolumeReport, output_path: Path) -> None:
        """Export the compiled volume report to a clean, UTF-8 JSON file."""
        logger.info("Exporting volume report to %s...", output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("Volume report export completed successfully.")
        except Exception as e:
            logger.error("Failed to write ROME volume report file: %s", e)
            raise
