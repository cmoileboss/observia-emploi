"""
Local raw-archive storage for France Travail job-offer pages.

This module provides ``FranceTravailRawStorage``, which receives
``FranceTravailOffersPage`` objects produced by the paginator and writes:

* one JSON file per page (the raw payload, untouched);
* a ``manifest.json`` summarising the collection run.

All files are first written to a hidden temporary directory inside
``root_directory``.  The directory is atomically renamed to its final,
timestamped name only when every write has succeeded.  If any error occurs,
the temporary directory is deleted and ``FranceTravailStorageError`` is raised.

No network call is made.  No environment variable is read.  No PostgreSQL
connection is opened.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from services.france_travail.client import FranceTravailOffersPage
from services.france_travail.exceptions import FranceTravailStorageError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sensitive key guard
# ---------------------------------------------------------------------------

#: Lower-cased key names that must never appear in ``search_params``.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "access_token",
        "token",
        "client_secret",
        "secret",
        "client_id",
        "password",
    }
)


def _check_sensitive_keys(params: Mapping[str, Any]) -> None:
    """Raise ``FranceTravailStorageError`` if *params* contains a sensitive key.

    The comparison is case-insensitive.  The sensitive value is never included
    in the exception message.

    Parameters
    ----------
    params:
        The search-parameter mapping to inspect.

    Raises
    ------
    FranceTravailStorageError
        When at least one key matches a forbidden name.
    """
    for key in params:
        if key.lower() in _SENSITIVE_KEYS:
            raise FranceTravailStorageError(
                f"search_params contains a sensitive key that must not be "
                f"persisted: '{key}'. Remove it before archiving."
            )


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FranceTravailRawArchive:
    """Immutable description of a completed raw-archive run.

    Parameters
    ----------
    run_id:
        Unique identifier for this collection run (e.g. ``20260620T153000Z``).
    directory:
        Absolute path to the final archive directory.
    manifest_path:
        Absolute path to ``manifest.json`` inside *directory*.
    page_paths:
        Ordered tuple of absolute paths to the page JSON files.
    page_count:
        Number of pages archived.
    offer_count:
        Total number of offers across all pages.
    created_at_utc:
        ISO-8601 UTC timestamp of the run (e.g. ``2026-06-20T15:30:00+00:00``).
    """

    run_id: str
    directory: Path
    manifest_path: Path
    page_paths: tuple[Path, ...]
    page_count: int
    offer_count: int
    created_at_utc: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_run_id(now: datetime) -> str:
    """Format *now* as a Windows-safe, file-system-safe run identifier.

    Parameters
    ----------
    now:
        A timezone-aware UTC datetime.

    Returns
    -------
    str
        A string of the form ``YYYYMMDDTHHMMSSZ``.
    """
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve_run_directory(root: Path, base_id: str) -> tuple[str, Path]:
    """Find the first non-existing directory name derived from *base_id*.

    Tries ``base_id``, then ``base_id_01``, ``base_id_02``, … until a name
    that does not yet exist inside *root* is found.

    Parameters
    ----------
    root:
        The root directory that will contain the run directory.
    base_id:
        The base run identifier (e.g. ``20260620T153000Z``).

    Returns
    -------
    tuple[str, Path]
        The chosen ``run_id`` string and the corresponding absolute ``Path``.
    """
    candidate = root / base_id
    if not candidate.exists():
        return base_id, candidate

    counter = 1
    while True:
        suffixed_id = f"{base_id}_{counter:02d}"
        candidate = root / suffixed_id
        if not candidate.exists():
            return suffixed_id, candidate
        counter += 1


def _page_filename(page_index: int, page: FranceTravailOffersPage) -> str:
    """Build the JSON filename for a single page.

    Parameters
    ----------
    page_index:
        1-based page number.
    page:
        The page whose ``range_start`` and ``range_end`` are used.

    Returns
    -------
    str
        A name such as ``page_0001_000000-000149.json``.
    """
    return (
        f"page_{page_index:04d}_{page.range_start:06d}-{page.range_end:06d}.json"
    )


def _validate_page(page: Any, index: int) -> None:
    """Validate a single page before writing.

    Parameters
    ----------
    page:
        The object to validate.
    index:
        0-based position in the iterable, used in error messages.

    Raises
    ------
    FranceTravailStorageError
        When the page does not meet the minimum structural requirements.
    """
    if not isinstance(getattr(page, "payload", None), dict):
        raise FranceTravailStorageError(
            f"Page at index {index} has a non-dict payload and cannot be archived."
        )

    range_start = getattr(page, "range_start", None)
    range_end = getattr(page, "range_end", None)

    if not isinstance(range_start, int) or isinstance(range_start, bool):
        raise FranceTravailStorageError(
            f"Page at index {index} has an invalid range_start: {range_start!r}."
        )
    if not isinstance(range_end, int) or isinstance(range_end, bool):
        raise FranceTravailStorageError(
            f"Page at index {index} has an invalid range_end: {range_end!r}."
        )
    if range_end < range_start:
        raise FranceTravailStorageError(
            f"Page at index {index} has range_end ({range_end}) < range_start ({range_start})."
        )

    # Verify JSON serialisability without logging the content.
    try:
        json.dumps(page.payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise FranceTravailStorageError(
            f"Page at index {index} has a payload that cannot be serialised to JSON: "
            f"{type(exc).__name__}."
        ) from exc


# ---------------------------------------------------------------------------
# Main storage class
# ---------------------------------------------------------------------------


class FranceTravailRawStorage:
    """Saves raw France Travail offer pages to a timestamped local directory.

    Parameters
    ----------
    root_directory:
        Base directory under which run-specific sub-directories are created.
        It is created with ``parents=True, exist_ok=True`` on first use.
    now_provider:
        Optional callable returning the current UTC datetime.  Defaults to
        ``datetime.now(timezone.utc)``.  Must return a timezone-aware datetime.
        Inject a fixed value in tests to make runs deterministic.

    Example
    -------
    ::

        storage = FranceTravailRawStorage(root_directory=Path("/data/raw"))
        archive = storage.archive_pages(
            pages=paginator.iter_pages(search_params={"codeROME": "M1805"}),
            search_params={"codeROME": "M1805"},
        )
        print(archive.manifest_path)
    """

    def __init__(
        self,
        root_directory: str | Path,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._root = Path(root_directory)
        self._now_provider: Callable[[], datetime] = (
            now_provider if now_provider is not None
            else lambda: datetime.now(timezone.utc)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def archive_pages(
        self,
        pages: Iterable[FranceTravailOffersPage],
        search_params: Optional[Mapping[str, Any]] = None,
    ) -> FranceTravailRawArchive:
        """Archive an iterable of offer pages to a timestamped directory.

        Parameters
        ----------
        pages:
            An iterable (typically the generator from
            ``FranceTravailOffersPaginator.iter_pages()``) of
            ``FranceTravailOffersPage`` objects.  Must not be empty.
        search_params:
            The search filters used to produce *pages*.  A shallow copy is
            stored in the manifest.  Must not contain sensitive keys.  The
            caller's mapping is never modified.

        Returns
        -------
        FranceTravailRawArchive
            Description of the completed archive.

        Raises
        ------
        FranceTravailStorageError
            On any storage failure, sensitive key, empty iterable, invalid
            page, or naive datetime from ``now_provider``.
        """
        # --- Validate search_params before any I/O ---
        params_copy: dict[str, Any] = {}
        if search_params is not None:
            _check_sensitive_keys(search_params)
            params_copy = dict(search_params)

        # --- Validate the timestamp ---
        now = self._now_provider()
        if now.tzinfo is None:
            raise FranceTravailStorageError(
                "now_provider returned a naive datetime (no timezone info). "
                "Use a timezone-aware datetime, e.g. datetime.now(timezone.utc)."
            )

        base_id = _build_run_id(now)
        created_at_iso = now.isoformat()

        # --- Ensure root directory exists ---
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FranceTravailStorageError(
                f"Cannot create root archive directory '{self._root}': {exc.strerror}."
            ) from exc

        # --- Determine the final run directory ---
        run_id, final_dir = _resolve_run_directory(self._root, base_id)
        tmp_dir = self._root / f".{run_id}.tmp"

        # --- Consume and validate pages before writing ---
        page_list: list[FranceTravailOffersPage] = list(pages)

        if not page_list:
            raise FranceTravailStorageError(
                "archive_pages received an empty iterable: nothing to archive."
            )

        for i, page in enumerate(page_list):
            _validate_page(page, i)

        # --- Write everything inside the temporary directory ---
        try:
            tmp_dir.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            raise FranceTravailStorageError(
                f"Cannot create temporary archive directory: {exc.strerror}."
            ) from exc

        page_paths: list[Path] = []
        page_manifest_entries: list[dict[str, Any]] = []
        offer_count = 0

        try:
            for page_index, page in enumerate(page_list, start=1):
                filename = _page_filename(page_index, page)
                page_path = tmp_dir / filename

                try:
                    page_json = json.dumps(
                        page.payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                except (TypeError, ValueError) as exc:
                    raise FranceTravailStorageError(
                        f"Cannot serialise page {page_index} to JSON: {type(exc).__name__}."
                    ) from exc

                try:
                    page_path.write_text(page_json, encoding="utf-8")
                except OSError as exc:
                    raise FranceTravailStorageError(
                        f"Cannot write page file '{filename}': {exc.strerror}."
                    ) from exc

                result_count = len(page.results)
                offer_count += result_count
                page_paths.append(page_path)
                page_manifest_entries.append(
                    {
                        "index": page_index,
                        "file": filename,
                        "range_start": page.range_start,
                        "range_end": page.range_end,
                        "content_range": page.content_range,
                        "result_count": result_count,
                    }
                )

            # Write manifest last so that its presence signals a complete run.
            manifest_data: dict[str, Any] = {
                "source": "france_travail_offres_emploi",
                "run_id": run_id,
                "created_at_utc": created_at_iso,
                "page_count": len(page_list),
                "offer_count": offer_count,
                "search_params": params_copy,
                "pages": page_manifest_entries,
            }

            manifest_path_tmp = tmp_dir / "manifest.json"
            try:
                manifest_path_tmp.write_text(
                    json.dumps(manifest_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                raise FranceTravailStorageError(
                    f"Cannot write manifest.json: {exc.strerror}."
                ) from exc

            # --- Atomic rename: tmp → final ---
            try:
                tmp_dir.rename(final_dir)
            except OSError as exc:
                raise FranceTravailStorageError(
                    f"Cannot rename temporary directory to '{final_dir.name}': "
                    f"{exc.strerror}."
                ) from exc

        except FranceTravailStorageError:
            # Clean up the temporary directory on any storage failure.
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        # Remap page paths to the final directory.
        final_page_paths = tuple(final_dir / p.name for p in page_paths)
        final_manifest_path = final_dir / "manifest.json"

        logger.info(
            "Archived %d page(s) (%d offer(s)) to '%s'.",
            len(page_list),
            offer_count,
            final_dir,
        )

        return FranceTravailRawArchive(
            run_id=run_id,
            directory=final_dir,
            manifest_path=final_manifest_path,
            page_paths=final_page_paths,
            page_count=len(page_list),
            offer_count=offer_count,
            created_at_utc=created_at_iso,
        )
