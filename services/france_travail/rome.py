# -*- coding: utf-8 -*-

"""
ROME referentiel utilities for the France Travail pipeline.

Responsibilities
----------------
- Define immutable structures for ROME reference entries and validation results.
- Read and validate local ROME codes from a project CSV file.
- Parse the remote referentiel response into immutable structures.
- Cross-validate a set of requested codes against a reference collection.

Design constraints
------------------
- No network calls are made anywhere in this module.
- No database access.
- No file I/O except in ``read_local_rome_codes``, which requires an explicit path.
- No absolute paths are hard-coded.
- No pandas dependency: the standard library ``csv`` module is used.
- All public structures are frozen dataclasses with slots.
- Collections are exposed as tuples (immutable sequences).
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.france_travail.exceptions import FranceTravailRomeError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Local ROME code format: one uppercase letter followed by exactly 4 digits.
# Example: M1805, A1401, K2204.
# This pattern is used ONLY for local file validation.
# The remote referentiel endpoint format is treated as opaque until a live call
# confirms it.
_LOCAL_ROME_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z]\d{4}$")

# Default column name expected in the local CSV file.
# The caller may override it if the project file uses a different header.
DEFAULT_ROME_COLUMN: str = "code_rome"


# ---------------------------------------------------------------------------
# Immutable data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RomeReferenceEntry:
    """Immutable representation of a single entry from the ROME referentiel.

    Parameters
    ----------
    code:
        Normalised ROME code (stripped, uppercased).
    label:
        Human-readable occupation label (stripped).
    """

    code: str
    label: str


@dataclass(frozen=True, slots=True)
class RomeValidationResult:
    """Immutable result of a ROME code cross-validation.

    Parameters
    ----------
    requested_codes:
        Deduplicated ordered tuple of the requested codes (normalised).
    valid_codes:
        Ordered tuple of codes recognised in the referentiel (order preserved
        from ``requested_codes``).
    unknown_codes:
        Ordered tuple of codes NOT found in the referentiel (order preserved
        from ``requested_codes``).
    duplicate_requested_count:
        Number of duplicate entries removed from the original request.
    reference_entry_count:
        Total number of entries in the referentiel used for comparison.
    """

    requested_codes: tuple[str, ...]
    valid_codes: tuple[str, ...]
    unknown_codes: tuple[str, ...]
    duplicate_requested_count: int
    reference_entry_count: int


# ---------------------------------------------------------------------------
# Local CSV reader
# ---------------------------------------------------------------------------


def read_local_rome_codes(
    file_path: Path | str,
    column: str = DEFAULT_ROME_COLUMN,
) -> tuple[str, ...]:
    """Read and validate ROME codes from a local CSV file.

    The function enforces the following normalisation steps in order:

    1. Strip leading/trailing whitespace.
    2. Convert to uppercase.
    3. Skip empty values.
    4. Deduplicate while preserving insertion order.
    5. Validate each code against the local ROME format (letter + 4 digits).

    Parameters
    ----------
    file_path:
        Path to the CSV file.  May be a ``pathlib.Path`` or any ``str``
        accepted by ``Path()``.  Must be a regular file that exists.
    column:
        Name of the CSV column that contains the ROME codes.
        Defaults to ``DEFAULT_ROME_COLUMN``.

    Returns
    -------
    tuple[str, ...]
        Deduplicated, normalised, validated ROME codes in the order they
        first appear in the file.

    Raises
    ------
    FranceTravailRomeError
        If the path does not exist, is not a regular file, the expected column
        is absent from the header, no non-empty code is found in the file, or
        any code does not match the expected format.
    """
    path = Path(file_path)

    if not path.exists():
        raise FranceTravailRomeError(
            f"ROME codes file not found: {path.name}"
        )
    if not path.is_file():
        raise FranceTravailRomeError(
            f"ROME codes path is not a regular file: {path.name}"
        )

    codes: list[str] = []
    seen: set[str] = set()

    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh, delimiter=";")

            if reader.fieldnames is None:
                # DictReader sets fieldnames to None for completely empty files.
                raise FranceTravailRomeError(
                    f"ROME codes file is empty (no header row): {path.name}"
                )

            # Normalise fieldnames for comparison (strip whitespace only — keep case).
            normalised_fieldnames = [
                f.strip() if f is not None else "" for f in reader.fieldnames
            ]

            if column not in normalised_fieldnames:
                raise FranceTravailRomeError(
                    f"Column '{column}' not found in ROME codes file '{path.name}'. "
                    f"Available columns: {normalised_fieldnames!r}"
                )

            for row in reader:
                raw = row.get(column)
                if raw is None:
                    # Column is declared in header but absent from this row — skip.
                    continue

                if not isinstance(raw, str):
                    # DictReader always returns strings; guard for safety.
                    raise FranceTravailRomeError(
                        f"Non-string value found in column '{column}': "
                        f"type={type(raw).__name__}"
                    )

                cleaned = raw.strip().upper()
                if not cleaned:
                    continue

                if not _LOCAL_ROME_PATTERN.match(cleaned):
                    raise FranceTravailRomeError(
                        f"Invalid ROME code format in column '{column}': "
                        f"'{cleaned}' does not match expected pattern "
                        f"(one uppercase letter followed by 4 digits)."
                    )

                if cleaned not in seen:
                    seen.add(cleaned)
                    codes.append(cleaned)

    except FranceTravailRomeError:
        raise
    except OSError as exc:
        raise FranceTravailRomeError(
            f"Cannot read ROME codes file '{path.name}': {exc.strerror}"
        ) from exc
    except csv.Error as exc:
        raise FranceTravailRomeError(
            f"CSV parsing error in ROME codes file '{path.name}': {exc}"
        ) from exc

    if not codes:
        raise FranceTravailRomeError(
            f"ROME codes file '{path.name}' contains no valid non-empty codes "
            f"in column '{column}'."
        )

    return tuple(codes)


# ---------------------------------------------------------------------------
# Remote referentiel parser
# ---------------------------------------------------------------------------


def parse_rome_referentiel(raw: Any) -> tuple[RomeReferenceEntry, ...]:
    """Parse the decoded JSON payload from the ROME referentiel endpoint.

    The endpoint is expected to return a JSON array of objects, each with at
    least the keys ``code`` and ``libelle``.

    This function is pure: no network call, no file I/O, no database access.

    Parameters
    ----------
    raw:
        The Python object obtained by decoding the JSON response body.
        Must be a list at the root level.

    Returns
    -------
    tuple[RomeReferenceEntry, ...]
        Deduplicated, ordered tuple of parsed entries (first occurrence wins
        for duplicate codes).

    Raises
    ------
    FranceTravailRomeError
        If the root is not a list, if any element is not a mapping, or if
        ``code`` / ``libelle`` fields are missing, not strings, or empty.

    Notes
    -----
    The format of remote codes is NOT validated against the local pattern
    (letter + 4 digits).  The real format of the endpoint response is still
    to be confirmed by a live call.  Entries with codes that do not match the
    local pattern are accepted and preserved as-is.
    """
    if not isinstance(raw, list):
        raise FranceTravailRomeError(
            f"ROME referentiel response must be a JSON array; "
            f"got {type(raw).__name__}."
        )

    entries: list[RomeReferenceEntry] = []
    seen_codes: set[str] = set()

    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise FranceTravailRomeError(
                f"ROME referentiel entry at index {i} must be a JSON object; "
                f"got {type(item).__name__}."
            )

        # --- code ---
        if "code" not in item:
            raise FranceTravailRomeError(
                f"ROME referentiel entry at index {i} is missing the 'code' field."
            )
        code_raw = item["code"]
        if not isinstance(code_raw, str):
            raise FranceTravailRomeError(
                f"ROME referentiel entry at index {i}: 'code' must be a string; "
                f"got {type(code_raw).__name__}."
            )
        code = code_raw.strip().upper()
        if not code:
            raise FranceTravailRomeError(
                f"ROME referentiel entry at index {i}: 'code' must not be empty."
            )

        # --- libelle ---
        if "libelle" not in item:
            raise FranceTravailRomeError(
                f"ROME referentiel entry at index {i} is missing the 'libelle' field."
            )
        libelle_raw = item["libelle"]
        if not isinstance(libelle_raw, str):
            raise FranceTravailRomeError(
                f"ROME referentiel entry at index {i}: 'libelle' must be a string; "
                f"got {type(libelle_raw).__name__}."
            )
        label = libelle_raw.strip()
        if not label:
            raise FranceTravailRomeError(
                f"ROME referentiel entry at index {i}: 'libelle' must not be empty."
            )

        # Deduplicate — first occurrence wins.
        if code not in seen_codes:
            seen_codes.add(code)
            entries.append(RomeReferenceEntry(code=code, label=label))

    return tuple(entries)


# ---------------------------------------------------------------------------
# Cross-validation
# ---------------------------------------------------------------------------


def validate_rome_codes(
    requested_codes: Iterable[str],
    reference_entries: Iterable[RomeReferenceEntry],
) -> RomeValidationResult:
    """Cross-validate a set of requested codes against a ROME referentiel.

    This function is pure: no network call, no file I/O, no database access.

    Parameters
    ----------
    requested_codes:
        An iterable of ROME code strings to validate.  Must NOT be a bare
        string (which would be silently iterated character by character).
    reference_entries:
        An iterable of ``RomeReferenceEntry`` instances representing the
        known referentiel.

    Returns
    -------
    RomeValidationResult
        Immutable validation result containing deduplicated codes, valid
        codes, unknown codes, duplicate count, and referentiel size.

    Raises
    ------
    FranceTravailRomeError
        If ``requested_codes`` is a plain string (accidental iteration guard),
        if any element is not a string, or if an element is empty after
        stripping.
    """
    # Guard against accidental string iteration.
    if isinstance(requested_codes, str):
        raise FranceTravailRomeError(
            "validate_rome_codes expects an iterable of strings, not a bare string. "
            "Wrap the single code in a list: [code]."
        )

    # Build the referentiel lookup set (codes only, already normalised by parser).
    reference_set: set[str] = {entry.code for entry in reference_entries}
    reference_count = len(reference_set)

    # Normalise and deduplicate requested codes.
    deduplicated: list[str] = []
    seen: set[str] = set()
    original_count: int = 0

    for item in requested_codes:
        original_count += 1

        if not isinstance(item, str):
            raise FranceTravailRomeError(
                f"All requested ROME codes must be strings; "
                f"got {type(item).__name__}."
            )

        cleaned = item.strip().upper()
        if not cleaned:
            raise FranceTravailRomeError(
                "An empty or whitespace-only code was found in the requested codes list."
            )

        if cleaned not in seen:
            seen.add(cleaned)
            deduplicated.append(cleaned)

    duplicate_count = original_count - len(deduplicated)

    valid: list[str] = []
    unknown: list[str] = []

    for code in deduplicated:
        if code in reference_set:
            valid.append(code)
        else:
            unknown.append(code)

    return RomeValidationResult(
        requested_codes=tuple(deduplicated),
        valid_codes=tuple(valid),
        unknown_codes=tuple(unknown),
        duplicate_requested_count=duplicate_count,
        reference_entry_count=reference_count,
    )
