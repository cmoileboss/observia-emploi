# -*- coding: utf-8 -*-

"""
Multi-ROME offer collection orchestrator for France Travail.

This module provides ``RomeCollectionResult`` and ``collect_offers_by_rome_codes``.

Responsibilities
----------------
1. Validate selected ROME codes against the remote referentiel (one token, one
   call to the referentiel endpoint).
2. For each validated code, paginate over the France Travail API using
   ``codeROME=<code>`` as the sole search filter, up to *max_pages* pages.
3. Write each code's raw pages to a sub-directory ``rome/<code>/`` inside a
   shared run directory created by ``FranceTravailRawStorage``.
4. Write a global run manifest ``manifest.json`` in the run root, recording
   per-code statistics, totals, and whether the run completed successfully.

Constraints
-----------
* No database access.
* No environment variable read (all configuration is injected).
* Tokens are never written to the manifest or to any log message.
* A single token is obtained once and reused for all codes.
* If the referentiel call fails or at least one code is unknown, no collection
  starts and ``FranceTravailCollectionError`` is raised.
* If a code fails mid-run, the run is closed with ``complete: false``, already-
  written pages are preserved, and ``FranceTravailCollectionError`` is raised.
* ``KeyboardInterrupt`` and ``SystemExit`` are never caught.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from services.france_travail.client import FranceTravailOffersPage
from services.france_travail.exceptions import (
    FranceTravailCollectionError,
    FranceTravailError,
    FranceTravailRomeError,
)
from services.france_travail.rome import (
    RomeReferenceEntry,
    RomeValidationResult,
    parse_rome_referentiel,
    validate_rome_codes,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Sub-directory inside a run directory where per-ROME code pages are stored.
_ROME_SUBDIR: str = "rome"

#: Fixed ``source`` field in the global manifest.
_MANIFEST_SOURCE: str = "france_travail_offres_emploi_rome"


# ---------------------------------------------------------------------------
# Protocols (keep this module independent of concrete implementations)
# ---------------------------------------------------------------------------


class _OffersClientProtocol(Protocol):
    """Minimal interface for searching offers and fetching the referentiel."""

    def search_offers_page(
        self,
        search_params: Optional[Mapping[str, Any]],
        range_start: int,
        range_end: int,
    ) -> FranceTravailOffersPage:
        """Fetch a single page of job offers."""
        ...

    def get_rome_referentiel(self) -> list[dict[str, Any]]:
        """Fetch the raw ROME referentiel payload."""
        ...


class _PaginatorProtocol(Protocol):
    """Minimal interface for the paginator."""

    def iter_pages(
        self,
        search_params: Optional[Mapping[str, Any]],
        max_pages: int,
    ) -> Any:
        """Iterate over pages of job offers."""
        ...


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RomeCodeResult:
    """Statistics for a single ROME code collection.

    Parameters
    ----------
    rome_code:
        The ROME code that was collected.
    page_count:
        Number of pages collected.
    offer_count:
        Total number of raw offers collected.
    page_paths:
        Ordered tuple of paths to the archived page files.
    error:
        Error message if this code's collection failed, ``None`` otherwise.
    """

    rome_code: str
    page_count: int
    offer_count: int
    page_paths: tuple[Path, ...]
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """True when the code was collected without error."""
        return self.error is None


@dataclass(frozen=True)
class RomeCollectionResult:
    """Global result of a multi-ROME collection run.

    Parameters
    ----------
    run_id:
        Unique identifier for the run (e.g. ``20260621T120000Z``).
    run_directory:
        Path to the run's root directory on disk.
    manifest_path:
        Path to the global ``manifest.json`` inside *run_directory*.
    codes_results:
        Ordered tuple of per-code results.
    reference_entry_count:
        Number of entries in the remote ROME referentiel.
    created_at_utc:
        ISO-8601 UTC timestamp of the run.
    complete:
        ``True`` when all codes were collected without error.
    """

    run_id: str
    run_directory: Path
    manifest_path: Path
    codes_results: tuple[RomeCodeResult, ...]
    reference_entry_count: int
    created_at_utc: str
    complete: bool

    @property
    def total_page_count(self) -> int:
        """Total pages collected across all codes."""
        return sum(r.page_count for r in self.codes_results)

    @property
    def total_offer_count(self) -> int:
        """Total raw offers collected across all codes."""
        return sum(r.offer_count for r in self.codes_results)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_run_id(now: datetime) -> str:
    """Format *now* as a run identifier string (``YYYYMMDDTHHMMSSZ``)."""
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve_run_directory(root: Path, base_id: str) -> tuple[str, Path]:
    """Return the first non-existing sub-directory name derived from *base_id*."""
    candidate = root / base_id
    if not candidate.exists():
        return base_id, candidate

    counter = 1
    while True:
        suffixed = f"{base_id}_{counter:02d}"
        candidate = root / suffixed
        if not candidate.exists():
            return suffixed, candidate
        counter += 1


def _page_filename(page_index: int, page: FranceTravailOffersPage) -> str:
    """Build the page filename from its 1-based index and range."""
    return (
        f"page_{page_index:04d}_{page.range_start:06d}-{page.range_end:06d}.json"
    )


def _write_global_manifest(
    manifest_path: Path,
    *,
    run_id: str,
    created_at_utc: str,
    requested_codes: tuple[str, ...],
    validated_codes: tuple[str, ...],
    reference_entry_count: int,
    code_results: list[RomeCodeResult],
    complete: bool,
) -> None:
    """Write the global manifest JSON to *manifest_path*.

    The manifest is written atomically (write to a ``.tmp`` sibling, then
    rename) to avoid leaving a partial file on disk.

    No token or credential is written.
    """
    per_code = []
    for r in code_results:
        per_code.append(
            {
                "rome_code": r.rome_code,
                "page_count": r.page_count,
                "offer_count": r.offer_count,
                "success": r.success,
                "error": r.error,
            }
        )

    total_pages = sum(r.page_count for r in code_results)
    total_offers = sum(r.offer_count for r in code_results)

    manifest: dict[str, Any] = {
        "source": _MANIFEST_SOURCE,
        "run_id": run_id,
        "created_at_utc": created_at_utc,
        "complete": complete,
        "reference_entry_count": reference_entry_count,
        "requested_codes": list(requested_codes),
        "validated_codes": list(validated_codes),
        "total_page_count": total_pages,
        "total_offer_count": total_offers,
        "codes": per_code,
    }

    tmp_path = manifest_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.rename(manifest_path)
    except OSError as exc:
        raise FranceTravailCollectionError(
            f"Cannot write global manifest to '{manifest_path.name}': {exc.strerror}"
        ) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_offers_by_rome_codes(
    *,
    rome_codes: Sequence[str],
    offers_client: _OffersClientProtocol,
    paginator: _PaginatorProtocol,
    output_directory: str | Path,
    max_pages: int = 10,
    now_provider: Optional[Callable[[], datetime]] = None,
) -> RomeCollectionResult:
    """Collect France Travail offers for each of the requested ROME codes.

    This function:

    1. Validates that *rome_codes* is a non-empty sequence of strings.
    2. Fetches the ROME referentiel (one call) and validates all codes.
    3. Creates a timestamped run directory under *output_directory*.
    4. For each code, paginates up to *max_pages* pages and writes them to
       ``<run_dir>/rome/<code>/page_NNNN_SSSSSS-EEEEEE.json``.
    5. After all codes are processed, writes a global ``manifest.json``.

    Parameters
    ----------
    rome_codes:
        Ordered sequence of ROME codes to collect.  Must be non-empty.
        Duplicates must have been removed by the caller.
    offers_client:
        An object implementing ``search_offers_page()`` and
        ``get_rome_referentiel()``.
    paginator:
        An object implementing ``iter_pages()``.
    output_directory:
        Root directory under which the run directory is created.
    max_pages:
        Maximum number of pages to fetch per ROME code.  Must be >= 1.
    now_provider:
        Optional callable returning the current UTC datetime.  Defaults to
        ``datetime.now(timezone.utc)``.  Inject a fixed value in tests.

    Returns
    -------
    RomeCollectionResult
        Detailed result of the completed (or partially completed) run.

    Raises
    ------
    FranceTravailCollectionError
        * Before any collection starts: unknown codes, referentiel failure.
        * After partial collection: a code's collection failed mid-run
          (partial data is preserved on disk, manifest marked incomplete).
    FranceTravailRomeError
        When *rome_codes* is a bare string or contains a non-string element.
    ValueError
        When *rome_codes* is empty or *max_pages* is invalid.
    """
    # --- Parameter validation ------------------------------------------------
    if isinstance(rome_codes, str):
        raise FranceTravailRomeError(
            "rome_codes must be a sequence of strings, not a bare string."
        )
    codes_list = list(rome_codes)
    if not codes_list:
        raise ValueError("rome_codes must not be empty.")
    for i, code in enumerate(codes_list):
        if not isinstance(code, str):
            raise FranceTravailRomeError(
                f"rome_codes element at index {i} must be a str, "
                f"got {type(code).__name__}."
            )

    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError(f"max_pages must be a positive integer, got {max_pages!r}.")

    now_fn: Callable[[], datetime] = (
        now_provider if now_provider is not None
        else lambda: datetime.now(timezone.utc)
    )

    # --- Step 1: Fetch and validate the ROME referentiel ---------------------
    logger.info("Fetching ROME referentiel for %d code(s).", len(codes_list))
    try:
        raw_ref = offers_client.get_rome_referentiel()
    except FranceTravailError as exc:
        raise FranceTravailCollectionError(
            f"Failed to fetch ROME referentiel: {type(exc).__name__}. "
            "No collection was started."
        ) from exc

    try:
        reference_entries: tuple[RomeReferenceEntry, ...] = parse_rome_referentiel(raw_ref)
    except FranceTravailRomeError as exc:
        raise FranceTravailCollectionError(
            f"Invalid ROME referentiel response: {exc}. "
            "No collection was started."
        ) from exc

    try:
        validation: RomeValidationResult = validate_rome_codes(codes_list, reference_entries)
    except FranceTravailRomeError as exc:
        raise FranceTravailCollectionError(
            f"ROME code validation error: {exc}."
        ) from exc

    if validation.unknown_codes:
        unknown_display = ", ".join(validation.unknown_codes[:10])
        raise FranceTravailCollectionError(
            f"The following ROME code(s) are not in the referentiel and cannot "
            f"be collected: {unknown_display}. No collection was started."
        )

    logger.info(
        "All %d ROME code(s) validated against %d referentiel entries.",
        len(validation.valid_codes),
        validation.reference_entry_count,
    )

    # --- Step 2: Prepare run directory ---------------------------------------
    output_root = Path(output_directory)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FranceTravailCollectionError(
            f"Cannot create output directory '{output_root}': {exc.strerror}"
        ) from exc

    now = now_fn()
    if now.tzinfo is None:
        raise FranceTravailCollectionError(
            "now_provider returned a naive datetime. Use a timezone-aware datetime."
        )
    base_id = _build_run_id(now)
    created_at_iso = now.isoformat()
    run_id, run_dir = _resolve_run_directory(output_root, base_id)

    try:
        run_dir.mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        raise FranceTravailCollectionError(
            f"Cannot create run directory '{run_dir.name}': {exc.strerror}"
        ) from exc

    manifest_path = run_dir / "manifest.json"

    # --- Step 3: Collect per-code -------------------------------------------
    code_results: list[RomeCodeResult] = []
    collection_complete = True
    failed_code: Optional[str] = None
    failure_message: Optional[str] = None

    for rome_code in validation.valid_codes:
        code_dir = run_dir / _ROME_SUBDIR / rome_code
        try:
            code_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            collection_complete = False
            failed_code = rome_code
            failure_message = (
                f"Cannot create directory for code '{rome_code}': {exc.strerror}"
            )
            code_results.append(
                RomeCodeResult(
                    rome_code=rome_code,
                    page_count=0,
                    offer_count=0,
                    page_paths=(),
                    error=failure_message,
                )
            )
            break

        logger.info("Collecting code %s (max %d page(s)).", rome_code, max_pages)

        search_params: dict[str, str] = {"codeROME": rome_code}
        page_paths: list[Path] = []
        offer_count = 0
        page_index = 0
        code_error: Optional[str] = None

        try:
            for page in paginator.iter_pages(
                search_params=search_params,
                max_pages=max_pages,
            ):
                page_index += 1
                filename = _page_filename(page_index, page)
                page_path = code_dir / filename

                page_json = json.dumps(page.payload, ensure_ascii=False, indent=2)
                page_path.write_text(page_json, encoding="utf-8")

                page_offer_count = len(page.results)
                offer_count += page_offer_count
                page_paths.append(page_path)

                logger.debug(
                    "Code %s — page %d: %d offer(s).",
                    rome_code,
                    page_index,
                    page_offer_count,
                )

        except FranceTravailError as exc:
            # Partial collection for this code: record the error, stop.
            collection_complete = False
            failed_code = rome_code
            code_error = f"{type(exc).__name__}: collection interrupted."
            failure_message = (
                f"Collection failed for code '{rome_code}': {type(exc).__name__}. "
                "Partial data preserved."
            )
            logger.warning(
                "Collection interrupted for code %s: %s.",
                rome_code,
                type(exc).__name__,
            )
        except OSError as exc:
            collection_complete = False
            failed_code = rome_code
            code_error = f"OSError writing page: {exc.strerror}."
            failure_message = (
                f"I/O error for code '{rome_code}': {exc.strerror}. "
                "Partial data preserved."
            )

        code_results.append(
            RomeCodeResult(
                rome_code=rome_code,
                page_count=len(page_paths),
                offer_count=offer_count,
                page_paths=tuple(page_paths),
                error=code_error,
            )
        )

        if not collection_complete:
            # Do not collect remaining codes.
            break

        logger.info(
            "Code %s: %d page(s), %d offer(s).",
            rome_code,
            len(page_paths),
            offer_count,
        )

    # --- Step 4: Write global manifest --------------------------------------
    try:
        _write_global_manifest(
            manifest_path,
            run_id=run_id,
            created_at_utc=created_at_iso,
            requested_codes=tuple(codes_list),
            validated_codes=validation.valid_codes,
            reference_entry_count=validation.reference_entry_count,
            code_results=code_results,
            complete=collection_complete,
        )
    except FranceTravailCollectionError:
        # Manifest write failure is critical regardless of collection success.
        raise

    result = RomeCollectionResult(
        run_id=run_id,
        run_directory=run_dir,
        manifest_path=manifest_path,
        codes_results=tuple(code_results),
        reference_entry_count=validation.reference_entry_count,
        created_at_utc=created_at_iso,
        complete=collection_complete,
    )

    if not collection_complete:
        raise FranceTravailCollectionError(
            failure_message or "Collection was interrupted. Partial data preserved."
        )

    return result
