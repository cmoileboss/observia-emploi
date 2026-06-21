# -*- coding: utf-8 -*-

"""
Unit tests for services.france_travail.rome.

Coverage
--------
- read_local_rome_codes  (§14)
- parse_rome_referentiel (§15)
- validate_rome_codes    (§17)

No network call. No database. No import of main.py.
All file-based tests use only synthetic temporary files.
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path


# ---------------------------------------------------------------------------
# Isolation helpers
# ---------------------------------------------------------------------------

_MODULES_TO_CLEAN = [
    "services.france_travail.rome",
]


def _import_fresh():
    """Import the modules under test from scratch, skipping the module cache.

    Only services.france_travail.rome is purged to avoid invalidating the
    module-level imports of neighbouring test files (e.g. test_mapper.py uses
    a module-level 'from services.france_travail.exceptions import ...' which
    must remain a stable reference across the whole test run).
    """
    for name in list(sys.modules.keys()):
        if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
            sys.modules.pop(name, None)

    from services.france_travail.rome import (  # noqa: PLC0415
        DEFAULT_ROME_COLUMN,
        RomeReferenceEntry,
        RomeValidationResult,
        parse_rome_referentiel,
        read_local_rome_codes,
        validate_rome_codes,
    )
    from services.france_travail.exceptions import FranceTravailRomeError  # noqa: PLC0415

    return (
        read_local_rome_codes,
        parse_rome_referentiel,
        validate_rome_codes,
        RomeReferenceEntry,
        RomeValidationResult,
        FranceTravailRomeError,
        DEFAULT_ROME_COLUMN,
    )


# ---------------------------------------------------------------------------
# Helpers to write synthetic CSV files
# ---------------------------------------------------------------------------

_DEFAULT_COL = "code_rome"


def _write_csv(
    path: Path,
    rows: list[dict],
    fieldnames: list[str] | None = None,
    delimiter: str = ";",
    encoding: str = "utf-8",
) -> None:
    """Write a synthetic CSV to *path*."""
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else [_DEFAULT_COL]
    with path.open("w", newline="", encoding=encoding) as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# §14 — Tests of read_local_rome_codes
# ---------------------------------------------------------------------------


class TestReadLocalRomeCodes(unittest.TestCase):
    """Tests for read_local_rome_codes (§14)."""

    def setUp(self):
        (
            self.read_local_rome_codes,
            self.parse_rome_referentiel,
            self.validate_rome_codes,
            self.RomeReferenceEntry,
            self.RomeValidationResult,
            self.FranceTravailRomeError,
            self.DEFAULT_ROME_COLUMN,
        ) = _import_fresh()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules.keys()):
            if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
                sys.modules.pop(name, None)

    # --- Valid file ---

    def test_valid_file_returns_tuple(self):
        """A valid CSV returns a non-empty tuple."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "M1805"}, {_DEFAULT_COL: "A1401"}])
        result = self.read_local_rome_codes(p)
        self.assertIsInstance(result, tuple)
        self.assertEqual(result, ("M1805", "A1401"))

    def test_valid_file_path_as_string(self):
        """Accepts a str path in addition to Path."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "K2204"}])
        result = self.read_local_rome_codes(str(p))
        self.assertEqual(result, ("K2204",))

    # --- Missing path ---

    def test_absent_path_raises(self):
        """A path that does not exist raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.read_local_rome_codes(self.tmp / "nonexistent.csv")

    # --- Path is a directory, not a file ---

    def test_directory_path_raises(self):
        """Passing a directory path raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.read_local_rome_codes(self.tmp)

    # --- Missing column ---

    def test_missing_column_raises(self):
        """An absent column name raises FranceTravailRomeError."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{"autre_colonne": "M1805"}])
        with self.assertRaises(self.FranceTravailRomeError) as ctx:
            self.read_local_rome_codes(p)
        self.assertIn("code_rome", str(ctx.exception))

    # --- Empty file (no header) ---

    def test_empty_file_raises(self):
        """A completely empty file raises FranceTravailRomeError."""
        p = self.tmp / "empty.csv"
        p.write_text("", encoding="utf-8")
        with self.assertRaises(self.FranceTravailRomeError):
            self.read_local_rome_codes(p)

    # --- File with header but no data rows ---

    def test_header_only_file_raises(self):
        """A file with header only (no data rows) raises FranceTravailRomeError."""
        p = self.tmp / "header_only.csv"
        p.write_text("code_rome\n", encoding="utf-8")
        with self.assertRaises(self.FranceTravailRomeError):
            self.read_local_rome_codes(p)

    # --- Empty values are skipped ---

    def test_empty_values_skipped(self):
        """Empty string values in the column are silently skipped."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [
            {_DEFAULT_COL: "M1805"},
            {_DEFAULT_COL: ""},
            {_DEFAULT_COL: "A1401"},
        ])
        result = self.read_local_rome_codes(p)
        self.assertEqual(result, ("M1805", "A1401"))

    # --- Whitespace is stripped ---

    def test_whitespace_stripped(self):
        """Values with leading/trailing spaces are stripped before validation."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "  M1805  "}])
        result = self.read_local_rome_codes(p)
        self.assertEqual(result, ("M1805",))

    # --- Lowercase is converted to uppercase ---

    def test_lowercase_converted_to_uppercase(self):
        """Lowercase codes are converted to uppercase."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "m1805"}])
        result = self.read_local_rome_codes(p)
        self.assertEqual(result, ("M1805",))

    # --- Duplicates removed, order preserved ---

    def test_duplicates_removed_order_preserved(self):
        """Duplicate codes are deduplicated; first occurrence order is preserved."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [
            {_DEFAULT_COL: "A1401"},
            {_DEFAULT_COL: "M1805"},
            {_DEFAULT_COL: "A1401"},
        ])
        result = self.read_local_rome_codes(p)
        self.assertEqual(result, ("A1401", "M1805"))

    # --- Invalid code format raises ---

    def test_invalid_code_format_raises(self):
        """A code not matching letter+4digits raises FranceTravailRomeError."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "INVALID"}])
        with self.assertRaises(self.FranceTravailRomeError) as ctx:
            self.read_local_rome_codes(p)
        self.assertIn("INVALID", str(ctx.exception))

    def test_numeric_only_code_raises(self):
        """A code with no leading letter raises FranceTravailRomeError."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "12345"}])
        with self.assertRaises(self.FranceTravailRomeError):
            self.read_local_rome_codes(p)

    def test_too_short_code_raises(self):
        """A code shorter than 5 chars raises FranceTravailRomeError."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "M180"}])
        with self.assertRaises(self.FranceTravailRomeError):
            self.read_local_rome_codes(p)

    # --- Real separator (semicolon) ---

    def test_semicolon_separator_accepted(self):
        """CSV files using semicolon separator are read correctly."""
        p = self.tmp / "codes.csv"
        p.write_text("code_rome;autre\nM1805;x\n", encoding="utf-8")
        result = self.read_local_rome_codes(p)
        self.assertEqual(result, ("M1805",))

    # --- Encoding UTF-8 with BOM ---

    def test_utf8_bom_encoding_accepted(self):
        """Files encoded as UTF-8 with BOM (utf-8-sig) are accepted."""
        p = self.tmp / "codes_bom.csv"
        _write_csv(p, [{_DEFAULT_COL: "B1234"}], encoding="utf-8-sig")
        result = self.read_local_rome_codes(p)
        self.assertEqual(result, ("B1234",))

    # --- Source file is not modified ---

    def test_source_file_not_modified(self):
        """The source file content is identical before and after the call."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "M1805"}])
        before = p.read_bytes()
        self.read_local_rome_codes(p)
        after = p.read_bytes()
        self.assertEqual(before, after)

    # --- Custom column name ---

    def test_custom_column_name(self):
        """A custom column name is correctly used when provided."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{"rome": "C1234"}], fieldnames=["rome"])
        result = self.read_local_rome_codes(p, column="rome")
        self.assertEqual(result, ("C1234",))

    # --- No absolute path hard-coded ---

    def test_no_absolute_path_hardcoded(self):
        """The function accepts only the path passed as argument — no hardcoded path."""
        p = self.tmp / "codes.csv"
        _write_csv(p, [{_DEFAULT_COL: "D5678"}])
        # Any explicit Path object works, not just predefined paths.
        result = self.read_local_rome_codes(p)
        self.assertIn("D5678", result)


# ---------------------------------------------------------------------------
# §15 — Tests of parse_rome_referentiel
# ---------------------------------------------------------------------------


class TestParseRomeReferentiel(unittest.TestCase):
    """Tests for parse_rome_referentiel (§15)."""

    def setUp(self):
        (
            self.read_local_rome_codes,
            self.parse_rome_referentiel,
            self.validate_rome_codes,
            self.RomeReferenceEntry,
            self.RomeValidationResult,
            self.FranceTravailRomeError,
            self.DEFAULT_ROME_COLUMN,
        ) = _import_fresh()

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules.keys()):
            if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
                sys.modules.pop(name, None)

    # --- Valid response ---

    def test_valid_response_returns_tuple_of_entries(self):
        """A valid list payload returns a tuple of RomeReferenceEntry."""
        raw = [
            {"code": "M1805", "libelle": "Études et développement informatique"},
            {"code": "A1401", "libelle": "Arboriculture"},
        ]
        result = self.parse_rome_referentiel(raw)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].code, "M1805")
        self.assertEqual(result[1].code, "A1401")

    def test_empty_list_returns_empty_tuple(self):
        """An empty list payload returns an empty tuple."""
        result = self.parse_rome_referentiel([])
        self.assertEqual(result, ())

    # --- Root type validation ---

    def test_root_dict_raises(self):
        """A root dict raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel({"code": "M1805", "libelle": "test"})

    def test_root_string_raises(self):
        """A root string raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel("M1805")

    def test_root_none_raises(self):
        """None as root raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel(None)

    def test_root_int_raises(self):
        """An integer as root raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel(42)

    # --- Element validation ---

    def test_element_not_mapping_raises(self):
        """A list element that is not a mapping raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel(["M1805"])

    def test_code_absent_raises(self):
        """An element without 'code' raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel([{"libelle": "Informatique"}])

    def test_code_not_str_raises(self):
        """A non-string 'code' raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel([{"code": 1805, "libelle": "Informatique"}])

    def test_code_empty_raises(self):
        """An empty 'code' raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel([{"code": "   ", "libelle": "Informatique"}])

    def test_libelle_absent_raises(self):
        """An element without 'libelle' raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel([{"code": "M1805"}])

    def test_libelle_not_str_raises(self):
        """A non-string 'libelle' raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel([{"code": "M1805", "libelle": 42}])

    def test_libelle_empty_raises(self):
        """An empty 'libelle' raises FranceTravailRomeError."""
        with self.assertRaises(self.FranceTravailRomeError):
            self.parse_rome_referentiel([{"code": "M1805", "libelle": "  "}])

    # --- Normalisation ---

    def test_whitespace_stripped_from_code(self):
        """Leading/trailing whitespace is stripped from code."""
        result = self.parse_rome_referentiel([{"code": "  M1805  ", "libelle": "label"}])
        self.assertEqual(result[0].code, "M1805")

    def test_code_uppercased(self):
        """Code is converted to uppercase."""
        result = self.parse_rome_referentiel([{"code": "m1805", "libelle": "label"}])
        self.assertEqual(result[0].code, "M1805")

    def test_libelle_stripped(self):
        """Whitespace is stripped from libelle."""
        result = self.parse_rome_referentiel([{"code": "M1805", "libelle": "  Informatique  "}])
        self.assertEqual(result[0].label, "Informatique")

    # --- Deduplication ---

    def test_duplicate_codes_first_occurrence_kept(self):
        """Duplicate codes: first occurrence is kept, second is dropped."""
        raw = [
            {"code": "M1805", "libelle": "Premier libellé"},
            {"code": "M1805", "libelle": "Second libellé"},
        ]
        result = self.parse_rome_referentiel(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].label, "Premier libellé")

    def test_order_preserved(self):
        """Order of first-occurrence entries is preserved."""
        raw = [
            {"code": "Z9999", "libelle": "Zulu"},
            {"code": "A0001", "libelle": "Alpha"},
        ]
        result = self.parse_rome_referentiel(raw)
        self.assertEqual(result[0].code, "Z9999")
        self.assertEqual(result[1].code, "A0001")

    # --- Immutability ---

    def test_returned_entries_are_immutable(self):
        """RomeReferenceEntry instances are frozen (cannot be mutated)."""
        result = self.parse_rome_referentiel([{"code": "M1805", "libelle": "label"}])
        with self.assertRaises((AttributeError, TypeError)):
            result[0].code = "X9999"  # type: ignore[misc]

    def test_returned_tuple_is_tuple(self):
        """The returned collection is a tuple."""
        result = self.parse_rome_referentiel([{"code": "M1805", "libelle": "label"}])
        self.assertIsInstance(result, tuple)

    # --- Remote codes that don't match local format are accepted ---

    def test_non_local_format_code_accepted(self):
        """Remote codes not matching local ROME format are accepted without error."""
        result = self.parse_rome_referentiel([{"code": "01", "libelle": "label"}])
        self.assertEqual(result[0].code, "01")

    def test_extra_fields_in_entry_are_ignored(self):
        """Extra keys in entries are silently ignored."""
        raw = [{"code": "M1805", "libelle": "label", "extra": "ignored"}]
        result = self.parse_rome_referentiel(raw)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# §17 — Tests of validate_rome_codes
# ---------------------------------------------------------------------------


class TestValidateRomeCodes(unittest.TestCase):
    """Tests for validate_rome_codes (§17)."""

    def setUp(self):
        (
            self.read_local_rome_codes,
            self.parse_rome_referentiel,
            self.validate_rome_codes,
            self.RomeReferenceEntry,
            self.RomeValidationResult,
            self.FranceTravailRomeError,
            self.DEFAULT_ROME_COLUMN,
        ) = _import_fresh()

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules.keys()):
            if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
                sys.modules.pop(name, None)

    def _make_ref(self, *codes_and_labels):
        """Helper: build a tuple of RomeReferenceEntry from (code, label) pairs."""
        return tuple(
            self.RomeReferenceEntry(code=c, label=l)
            for c, l in codes_and_labels
        )

    # --- All codes recognised ---

    def test_all_codes_recognised(self):
        """When all requested codes are in the referentiel, unknown_codes is empty."""
        ref = self._make_ref(("M1805", "Informatique"), ("A1401", "Agri"))
        result = self.validate_rome_codes(["M1805", "A1401"], ref)
        self.assertEqual(result.valid_codes, ("M1805", "A1401"))
        self.assertEqual(result.unknown_codes, ())

    # --- Some codes unknown ---

    def test_some_codes_unknown(self):
        """Codes absent from the referentiel appear in unknown_codes."""
        ref = self._make_ref(("M1805", "Informatique"))
        result = self.validate_rome_codes(["M1805", "Z9999"], ref)
        self.assertIn("M1805", result.valid_codes)
        self.assertIn("Z9999", result.unknown_codes)

    # --- All unknown ---

    def test_all_codes_unknown(self):
        """When no requested code is in the referentiel, valid_codes is empty."""
        ref = self._make_ref(("M1805", "Informatique"))
        result = self.validate_rome_codes(["Z9999"], ref)
        self.assertEqual(result.valid_codes, ())
        self.assertEqual(result.unknown_codes, ("Z9999",))

    # --- Empty request ---

    def test_empty_request_returns_empty_results(self):
        """An empty iterable of requested codes returns all empty collections."""
        ref = self._make_ref(("M1805", "Informatique"))
        result = self.validate_rome_codes([], ref)
        self.assertEqual(result.requested_codes, ())
        self.assertEqual(result.valid_codes, ())
        self.assertEqual(result.unknown_codes, ())
        self.assertEqual(result.duplicate_requested_count, 0)

    # --- Whitespace and case ---

    def test_whitespace_and_case_normalised(self):
        """Requested codes are stripped and uppercased before comparison."""
        ref = self._make_ref(("M1805", "Informatique"))
        result = self.validate_rome_codes(["  m1805  "], ref)
        self.assertIn("M1805", result.valid_codes)

    # --- Duplicates ---

    def test_duplicates_are_counted_and_removed(self):
        """Duplicate requested codes are deduplicated and the count is correct."""
        ref = self._make_ref(("M1805", "Informatique"))
        result = self.validate_rome_codes(["M1805", "M1805", "M1805"], ref)
        self.assertEqual(result.requested_codes, ("M1805",))
        self.assertEqual(result.duplicate_requested_count, 2)

    # --- Order preserved ---

    def test_order_preserved_in_valid_codes(self):
        """The order of valid codes matches the order of requested_codes."""
        ref = self._make_ref(("A1401", "Agri"), ("M1805", "Info"), ("K2204", "Admin"))
        result = self.validate_rome_codes(["K2204", "A1401", "M1805"], ref)
        self.assertEqual(result.valid_codes, ("K2204", "A1401", "M1805"))

    def test_order_preserved_in_unknown_codes(self):
        """The order of unknown codes matches the order they were requested."""
        ref = self._make_ref(("M1805", "Info"))
        result = self.validate_rome_codes(["Z9999", "M1805", "X0000"], ref)
        self.assertEqual(result.unknown_codes, ("Z9999", "X0000"))

    # --- Bare string refused ---

    def test_bare_string_raises(self):
        """Passing a bare string raises FranceTravailRomeError."""
        ref = self._make_ref(("M1805", "Info"))
        with self.assertRaises(self.FranceTravailRomeError):
            self.validate_rome_codes("M1805", ref)

    # --- Non-string element refused ---

    def test_non_string_element_raises(self):
        """A non-string element in requested_codes raises FranceTravailRomeError."""
        ref = self._make_ref(("M1805", "Info"))
        with self.assertRaises(self.FranceTravailRomeError):
            self.validate_rome_codes([1805], ref)  # type: ignore[list-item]

    # --- Reference with various code formats accepted ---

    def test_referentiel_with_non_local_format_codes(self):
        """Reference entries with non-standard codes work without error."""
        ref = self._make_ref(("01", "Agriculteur"), ("M1805", "Informatique"))
        result = self.validate_rome_codes(["01", "M1805"], ref)
        self.assertEqual(result.valid_codes, ("01", "M1805"))

    # --- Exact counters ---

    def test_reference_entry_count_is_exact(self):
        """reference_entry_count matches the number of entries in the referentiel."""
        ref = self._make_ref(("M1805", "Info"), ("A1401", "Agri"), ("K2204", "Admin"))
        result = self.validate_rome_codes(["M1805"], ref)
        self.assertEqual(result.reference_entry_count, 3)

    # --- Immutable result ---

    def test_result_is_frozen(self):
        """RomeValidationResult is frozen (cannot be mutated)."""
        ref = self._make_ref(("M1805", "Info"))
        result = self.validate_rome_codes(["M1805"], ref)
        with self.assertRaises((AttributeError, TypeError)):
            result.valid_codes = ()  # type: ignore[misc]

    def test_result_collections_are_tuples(self):
        """requested_codes, valid_codes, and unknown_codes are tuples."""
        ref = self._make_ref(("M1805", "Info"))
        result = self.validate_rome_codes(["M1805", "Z9999"], ref)
        self.assertIsInstance(result.requested_codes, tuple)
        self.assertIsInstance(result.valid_codes, tuple)
        self.assertIsInstance(result.unknown_codes, tuple)

    # --- Empty code raises ---

    def test_empty_code_in_request_raises(self):
        """An empty string in the requested codes raises FranceTravailRomeError."""
        ref = self._make_ref(("M1805", "Info"))
        with self.assertRaises(self.FranceTravailRomeError):
            self.validate_rome_codes(["M1805", ""], ref)

    def test_whitespace_only_code_in_request_raises(self):
        """A whitespace-only code in the requested list raises FranceTravailRomeError."""
        ref = self._make_ref(("M1805", "Info"))
        with self.assertRaises(self.FranceTravailRomeError):
            self.validate_rome_codes(["M1805", "   "], ref)


if __name__ == "__main__":
    unittest.main()
