"""Service to collect detailed job offers by ROME code from France Travail API."""

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from observia_emploi.france_travail.client import FranceTravailClient
from observia_emploi.france_travail.schemas import OffreEmploiSchema

logger = logging.getLogger(__name__)


class FranceTravailOfferCollectorService:
    """Service to collect and normalize job offers from the France Travail API."""

    def __init__(self, client: FranceTravailClient) -> None:
        """Initialize with France Travail client."""
        self.client = client

    def collect_single_rome_offers(self, code_rome: str) -> list[dict[str, Any]]:
        """Collect all offers for a single ROME code with pagination."""
        offers: list[dict[str, Any]] = []
        page_size = 150
        start = 0

        logger.info("Starting detailed offer collection for ROME code: %s", code_rome)

        while True:
            end = start + page_size - 1
            range_str = f"{start}-{end}"
            endpoint = "partenaire/offresdemploi/v2/offres/search"
            params = {"codeROME": code_rome, "range": range_str}

            # Enforce 0.25s rate limit (5 req/s max)
            if not hasattr(self.client, "_is_mock_client"):
                from observia_emploi.france_travail.client import (
                    MockFranceTravailClient,
                )

                if not isinstance(self.client, MockFranceTravailClient):
                    logger.debug("Applying 250ms rate limit delay...")
                    time.sleep(0.25)

            try:
                response = self.client.get_raw(endpoint, params=params)
                status_code = response.status_code
            except Exception as e:
                logger.error(
                    "Network error during pagination %s for ROME %s: %s",
                    range_str,
                    code_rome,
                    e,
                )
                break

            # 204 No Content means we reached the end of results
            if status_code == 204:
                logger.info(
                    "Reached end of offers for ROME %s (204 No Content)", code_rome
                )
                break

            # Catch technical range limitations (e.g. 400 or 416)
            if status_code in (400, 416):
                logger.warning(
                    "Pagination limit or invalid range %s for ROME %s (Status: %s). "
                    "Passing to next ROME.",
                    range_str,
                    code_rome,
                    status_code,
                )
                break

            if status_code not in (200, 206):
                logger.error(
                    "Unexpected API status %s for ROME %s range %s. "
                    "Stopping collection for this ROME.",
                    status_code,
                    code_rome,
                    range_str,
                )
                break

            try:
                raw_json = response.json()
            except Exception:
                logger.error(
                    "Failed to decode JSON response for ROME %s range %s",
                    code_rome,
                    range_str,
                )
                break

            resultats = raw_json.get("resultats", [])
            if not resultats or not isinstance(resultats, list):
                logger.info(
                    "No resultats found in payload for ROME %s range %s",
                    code_rome,
                    range_str,
                )
                break

            # Parse and validate each offer
            parsed_count = 0
            for item in resultats:
                if not isinstance(item, dict):
                    continue
                try:
                    # Validate and clean with Pydantic
                    schema_instance = OffreEmploiSchema.model_validate(item)
                    # Exclude raw description, contact, agence
                    offers.append(
                        schema_instance.model_dump(by_alias=True, exclude_unset=True)
                    )
                    parsed_count += 1
                except Exception as e:
                    logger.warning("Failed to parse offer item: %s", e)

            logger.info(
                "Collected %d offers in range %s for ROME %s",
                parsed_count,
                range_str,
                code_rome,
            )

            # If we received less than the requested page size, we are at the end
            if len(resultats) < page_size:
                logger.info(
                    "Reached end of results (received %d < %d)",
                    len(resultats),
                    page_size,
                )
                break

            # Move to next page
            start += page_size

        return offers

    def collect_all_offers_from_file(self, referential_path: Path) -> dict[str, Any]:
        """Collect job offers for all ROME codes listed in the referential file."""
        logger.info(
            "Loading ROME codes for detailed collection from %s", referential_path
        )

        if not referential_path.exists():
            raise FileNotFoundError(
                f"ROME referential file not found: {referential_path}"
            )

        try:
            with referential_path.open("r", encoding="utf-8") as f:
                ref_data = json.load(f)
        except Exception as e:
            logger.error("Failed to parse ROME referential: %s", e)
            raise

        items = ref_data.get("items", [])
        if not items:
            logger.warning("No ROME items found in referential.")
            return self._build_export_payload([])

        all_offers: list[dict[str, Any]] = []

        for item in items:
            code = item.get("code_rome")
            if not code:
                continue
            try:
                rome_offers = self.collect_single_rome_offers(code)
                all_offers.extend(rome_offers)
            except Exception as e:
                logger.error("Error collecting offers for ROME code %s: %s", code, e)

        logger.info("Total detailed offers collected: %d", len(all_offers))
        return self._build_export_payload(all_offers)

    def _build_export_payload(self, offers: list[dict[str, Any]]) -> dict[str, Any]:
        """Wrap offers array in a standardized clean metadata payload."""
        return {
            "source": "france_travail_api",
            "dataset": "offres_emplois_detaillees",
            "collected_at": datetime.now(UTC).isoformat(),
            "offers_count": len(offers),
            "offers": offers,
        }

    def export_offers_to_json(self, payload: dict[str, Any], output_path: Path) -> None:
        """Export the consolidated offers payload to a clean UTF-8 JSON file."""
        logger.info("Saving detailed offers to %s...", output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info("Successfully exported detailed offers JSON.")
        except Exception as e:
            logger.error("Failed to write offers JSON file: %s", e)
            raise
