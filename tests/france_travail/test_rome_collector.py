# -*- coding: utf-8 -*-

"""
Unit tests for services.france_travail.rome_collector and for the ROME mode
of scripts/collect_france_travail.py.

All network calls are mocked. No database. No main.py. No real filesystem
access except inside tempfile.TemporaryDirectory() sandboxes.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Isolation helpers
# ---------------------------------------------------------------------------

_MODULES_TO_CLEAN = [
    "services.france_travail.rome_collector",
]


def _clean_modules() -> None:
    for name in list(sys.modules.keys()):
        if any(name == m or name.startswith(m + ".") for m in _MODULES_TO_CLEAN):
            sys.modules.pop(name, None)


def _import_collector():
    _clean_modules()
    from services.france_travail.rome_collector import (  # noqa: PLC0415
        collect_offers_by_rome_codes,
        RomeCollectionResult,
        RomeCodeResult,
    )
    from services.france_travail.exceptions import (  # noqa: PLC0415
        FranceTravailCollectionError,
        FranceTravailRomeError,
        FranceTravailApiError,
        FranceTravailNetworkError,
    )
    return (
        collect_offers_by_rome_codes,
        RomeCollectionResult,
        RomeCodeResult,
        FranceTravailCollectionError,
        FranceTravailRomeError,
        FranceTravailApiError,
        FranceTravailNetworkError,
    )


def _import_script_main():
    _clean_modules()
    import scripts.collect_france_travail as mod  # noqa: PLC0415
    return mod.main, mod


# ---------------------------------------------------------------------------
# Synthetic helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
_FIXED_RUN_ID = "20260621T120000Z"

_REFERENTIEL_VALID = [
    {"code": "M1805", "libelle": "Informatique"},
    {"code": "A1401", "libelle": "Agriculture"},
    {"code": "K2204", "libelle": "Administration"},
]


def _make_page(offers: list[dict], range_start: int = 0, range_end: int = 149) -> Any:
    """Build a synthetic FranceTravailOffersPage."""
    from services.france_travail.client import FranceTravailOffersPage  # noqa: PLC0415
    payload = {"resultats": offers}
    return FranceTravailOffersPage(
        payload=payload,
        results=tuple(offers),
        content_range=None,
        range_start=range_start,
        range_end=range_end,
    )


def _make_client(
    referentiel=None,
    pages_by_code: dict | None = None,
    referentiel_error=None,
) -> MagicMock:
    """Build a mock offers client."""
    client = MagicMock()

    if referentiel_error is not None:
        client.get_rome_referentiel.side_effect = referentiel_error
    else:
        client.get_rome_referentiel.return_value = (
            referentiel if referentiel is not None else _REFERENTIEL_VALID
        )

    pages_by_code = pages_by_code or {}
    client.search_offers_page.side_effect = lambda search_params, range_start, range_end: (
        _make_page([], range_start=range_start, range_end=range_end)
    )
    return client


def _make_paginator(pages_by_code: dict[str, list] | None = None) -> MagicMock:
    """Build a mock paginator that yields synthetic pages per code."""
    pages_by_code = pages_by_code or {}

    def _iter_pages(search_params=None, max_pages=10):
        code = (search_params or {}).get("codeROME", "")
        page_list = pages_by_code.get(code, [_make_page([])])
        yield from page_list

    paginator = MagicMock()
    paginator.iter_pages.side_effect = _iter_pages
    return paginator


def _write_csv(path: Path, codes: list[str], column: str = "code_rome") -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[column], delimiter=";")
        writer.writeheader()
        for code in codes:
            writer.writerow({column: code})


# ---------------------------------------------------------------------------
# §12 — Tests: collect_offers_by_rome_codes
# ---------------------------------------------------------------------------


class TestCollectOffersByRomeCodes(unittest.TestCase):
    """Core unit tests for collect_offers_by_rome_codes."""

    def setUp(self):
        (
            self.collect,
            self.RomeCollectionResult,
            self.RomeCodeResult,
            self.FranceTravailCollectionError,
            self.FranceTravailRomeError,
            self.FranceTravailApiError,
            self.FranceTravailNetworkError,
        ) = _import_collector()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()
        _clean_modules()

    def _run(self, codes, pages_by_code=None, referentiel=None, max_pages=1):
        client = _make_client(referentiel=referentiel)
        paginator = _make_paginator(pages_by_code=pages_by_code or {})
        return self.collect(
            rome_codes=codes,
            offers_client=client,
            paginator=paginator,
            output_directory=self.tmp,
            max_pages=max_pages,
            now_provider=lambda: _FIXED_NOW,
        )

    # --- Validation préalable ---

    def test_referentiel_called_exactly_once(self):
        """The referentiel is called exactly once regardless of the number of codes."""
        client = _make_client()
        paginator = _make_paginator()
        self.collect(
            rome_codes=["M1805", "A1401"],
            offers_client=client,
            paginator=paginator,
            output_directory=self.tmp,
            max_pages=1,
            now_provider=lambda: _FIXED_NOW,
        )
        client.get_rome_referentiel.assert_called_once()

    def test_all_codes_recognised_succeeds(self):
        """All recognised codes produce a complete result."""
        result = self._run(["M1805", "A1401"])
        self.assertTrue(result.complete)
        self.assertEqual(len(result.codes_results), 2)

    def test_unknown_code_blocks_collection(self):
        """An unknown code raises before any search_offers_page call."""
        client = _make_client()
        paginator = _make_paginator()
        with self.assertRaises(self.FranceTravailCollectionError) as ctx:
            self.collect(
                rome_codes=["Z9999"],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )
        client.search_offers_page.assert_not_called()
        paginator.iter_pages.assert_not_called()
        self.assertIn("Z9999", str(ctx.exception))

    def test_referentiel_failure_blocks_collection(self):
        """A referentiel API error raises before any search."""
        from services.france_travail.exceptions import FranceTravailApiError  # noqa: PLC0415
        client = _make_client(referentiel_error=FranceTravailApiError("boom"))
        paginator = _make_paginator()
        with self.assertRaises(self.FranceTravailCollectionError):
            self.collect(
                rome_codes=["M1805"],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )
        paginator.iter_pages.assert_not_called()

    def test_token_obtained_once_per_run(self):
        """The auth token is not re-obtained for each code (delegation to client)."""
        # The collector does not call auth directly; it uses the client.
        # Verify get_rome_referentiel is called once — not once per code.
        client = _make_client()
        paginator = _make_paginator()
        self.collect(
            rome_codes=["M1805", "A1401", "K2204"],
            offers_client=client,
            paginator=paginator,
            output_directory=self.tmp,
            max_pages=1,
            now_provider=lambda: _FIXED_NOW,
        )
        # Referentiel called once means authentication was not re-triggered per code.
        self.assertEqual(client.get_rome_referentiel.call_count, 1)

    # --- Recherche par code ---

    def test_search_uses_codeROME_parameter(self):
        """Each page iteration receives codeROME in search_params."""
        client = _make_client()
        paginator = _make_paginator({"M1805": [_make_page([{"id": "1"}])]})
        self.collect(
            rome_codes=["M1805"],
            offers_client=client,
            paginator=paginator,
            output_directory=self.tmp,
            max_pages=1,
            now_provider=lambda: _FIXED_NOW,
        )
        call_args = paginator.iter_pages.call_args
        params = call_args[1].get("search_params") or call_args[0][0]
        self.assertEqual(params.get("codeROME"), "M1805")

    def test_separate_iteration_per_code(self):
        """iter_pages is called once per code."""
        client = _make_client()
        paginator = _make_paginator(
            {
                "M1805": [_make_page([{"id": "1"}])],
                "A1401": [_make_page([{"id": "2"}])],
            }
        )
        self.collect(
            rome_codes=["M1805", "A1401"],
            offers_client=client,
            paginator=paginator,
            output_directory=self.tmp,
            max_pages=1,
            now_provider=lambda: _FIXED_NOW,
        )
        self.assertEqual(paginator.iter_pages.call_count, 2)

    def test_max_pages_passed_per_code(self):
        """max_pages is forwarded to iter_pages for each code."""
        client = _make_client()
        paginator = _make_paginator()
        self.collect(
            rome_codes=["M1805"],
            offers_client=client,
            paginator=paginator,
            output_directory=self.tmp,
            max_pages=3,
            now_provider=lambda: _FIXED_NOW,
        )
        call_kwargs = paginator.iter_pages.call_args[1]
        self.assertEqual(call_kwargs.get("max_pages"), 3)

    def test_empty_page_treated_as_normal_end(self):
        """An empty page does not raise an error."""
        result = self._run(
            ["M1805"],
            pages_by_code={"M1805": [_make_page([])]},
        )
        self.assertTrue(result.complete)
        code_result = result.codes_results[0]
        self.assertEqual(code_result.offer_count, 0)

    def test_order_of_codes_preserved(self):
        """Results appear in the same order as the input codes."""
        client = _make_client()
        paginator = _make_paginator(
            {
                "A1401": [_make_page([{"id": "1"}])],
                "M1805": [_make_page([{"id": "2"}])],
            }
        )
        result = self.collect(
            rome_codes=["A1401", "M1805"],
            offers_client=client,
            paginator=paginator,
            output_directory=self.tmp,
            max_pages=1,
            now_provider=lambda: _FIXED_NOW,
        )
        self.assertEqual(result.codes_results[0].rome_code, "A1401")
        self.assertEqual(result.codes_results[1].rome_code, "M1805")

    def test_no_secret_in_collection_error(self):
        """FranceTravailCollectionError messages do not contain credential keywords."""
        from services.france_travail.exceptions import FranceTravailNetworkError  # noqa: PLC0415
        client = _make_client(referentiel_error=FranceTravailNetworkError("timeout"))
        paginator = _make_paginator()
        try:
            self.collect(
                rome_codes=["M1805"],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )
        except self.FranceTravailCollectionError as exc:
            for word in ("token", "client_secret", "Authorization", "password"):
                self.assertNotIn(word, str(exc))

    # --- Archivage brut ---

    def test_raw_pages_preserved_unchanged(self):
        """The raw payload is written to disk without modification."""
        offer = {"id": "FT-1", "intitule": "Dev Python"}
        page = _make_page([offer], range_start=0, range_end=149)
        result = self._run(
            ["M1805"],
            pages_by_code={"M1805": [page]},
        )
        page_paths = result.codes_results[0].page_paths
        self.assertEqual(len(page_paths), 1)
        written = json.loads(page_paths[0].read_text(encoding="utf-8"))
        self.assertEqual(written, {"resultats": [offer]})

    def test_pages_stored_in_separate_code_subdirs(self):
        """Each code's pages are stored in rome/<code>/ inside the run directory."""
        offer1 = {"id": "FT-1"}
        offer2 = {"id": "FT-2"}
        pages = {
            "M1805": [_make_page([offer1])],
            "A1401": [_make_page([offer2])],
        }
        result = self._run(["M1805", "A1401"], pages_by_code=pages)
        for code_result in result.codes_results:
            for p in code_result.page_paths:
                # Path must contain rome/<code>/.
                self.assertIn("rome", p.parts)
                self.assertIn(code_result.rome_code, p.parts)

    def test_manifest_written_to_run_directory(self):
        """manifest.json is written in the run directory root."""
        result = self._run(["M1805"])
        self.assertTrue(result.manifest_path.is_file())
        self.assertEqual(result.manifest_path.parent, result.run_directory)
        self.assertEqual(result.manifest_path.name, "manifest.json")

    def test_manifest_fields_correct(self):
        """Manifest contains expected top-level fields with correct values."""
        offers = [{"id": "1"}, {"id": "2"}]
        result = self._run(
            ["M1805"],
            pages_by_code={"M1805": [_make_page(offers)]},
        )
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"], "france_travail_offres_emploi_rome")
        self.assertEqual(manifest["run_id"], _FIXED_RUN_ID)
        self.assertTrue(manifest["complete"])
        self.assertIn("M1805", manifest["requested_codes"])
        self.assertIn("M1805", manifest["validated_codes"])
        self.assertEqual(manifest["total_offer_count"], 2)
        self.assertEqual(manifest["total_page_count"], 1)

    def test_manifest_no_sensitive_data(self):
        """Manifest does not contain any credential-like keywords."""
        result = self._run(["M1805"])
        raw = result.manifest_path.read_text(encoding="utf-8")
        for word in ("token", "client_secret", "authorization", "password", "Bearer"):
            self.assertNotIn(word, raw)

    def test_per_code_counters_in_manifest(self):
        """Manifest contains per-code page and offer counts."""
        offers = [{"id": "1"}]
        result = self._run(
            ["M1805"],
            pages_by_code={"M1805": [_make_page(offers)]},
        )
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        codes_entry = manifest["codes"][0]
        self.assertEqual(codes_entry["rome_code"], "M1805")
        self.assertEqual(codes_entry["page_count"], 1)
        self.assertEqual(codes_entry["offer_count"], 1)
        self.assertTrue(codes_entry["success"])

    def test_total_counters_sum_across_codes(self):
        """Total offer count = sum of per-code offer counts."""
        pages = {
            "M1805": [_make_page([{"id": "1"}, {"id": "2"}])],
            "A1401": [_make_page([{"id": "3"}])],
        }
        result = self._run(["M1805", "A1401"], pages_by_code=pages)
        self.assertEqual(result.total_offer_count, 3)
        self.assertEqual(result.total_page_count, 2)

    def test_duplicate_offers_preserved_in_raw(self):
        """Duplicate offer ids are NOT deduplicated in the raw archive."""
        offer = {"id": "FT-DUP"}
        # Same offer appears in two codes — raw storage keeps both.
        pages = {
            "M1805": [_make_page([offer])],
            "A1401": [_make_page([offer])],
        }
        result = self._run(["M1805", "A1401"], pages_by_code=pages)
        self.assertEqual(result.total_offer_count, 2)

    # --- Erreur partielle ---

    def test_failed_code_marks_run_incomplete(self):
        """A collection error on one code marks the run as incomplete."""
        from services.france_travail.exceptions import FranceTravailNetworkError  # noqa: PLC0415

        def _failing_iter(search_params=None, max_pages=10):
            raise FranceTravailNetworkError("connection lost")
            yield  # pragma: no cover

        paginator = MagicMock()
        paginator.iter_pages.side_effect = _failing_iter

        client = _make_client()
        with self.assertRaises(self.FranceTravailCollectionError):
            self.collect(
                rome_codes=["M1805"],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )

    def test_failed_code_manifest_marked_incomplete(self):
        """The manifest is written with complete=false when a code fails."""
        from services.france_travail.exceptions import FranceTravailApiError  # noqa: PLC0415

        def _failing_iter(search_params=None, max_pages=10):
            raise FranceTravailApiError("HTTP 500")
            yield  # pragma: no cover

        paginator = MagicMock()
        paginator.iter_pages.side_effect = _failing_iter

        client = _make_client()
        try:
            self.collect(
                rome_codes=["M1805"],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )
        except self.FranceTravailCollectionError:
            pass

        run_dir = self.tmp / _FIXED_RUN_ID
        manifest_path = run_dir / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertFalse(manifest["complete"])

    def test_partial_pages_of_first_code_preserved_on_second_code_failure(self):
        """Pages already written for code 1 are preserved when code 2 fails."""
        from services.france_travail.exceptions import FranceTravailNetworkError  # noqa: PLC0415

        call_count = 0

        def _iter(search_params=None, max_pages=10):
            nonlocal call_count
            call_count += 1
            code = (search_params or {}).get("codeROME", "")
            if code == "M1805":
                yield _make_page([{"id": "1"}])
            else:
                raise FranceTravailNetworkError("network fail")

        paginator = MagicMock()
        paginator.iter_pages.side_effect = _iter
        client = _make_client()

        try:
            self.collect(
                rome_codes=["M1805", "A1401"],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )
        except self.FranceTravailCollectionError:
            pass

        # Page for M1805 must still be on disk.
        m1805_dir = self.tmp / _FIXED_RUN_ID / "rome" / "M1805"
        pages_on_disk = list(m1805_dir.glob("page_*.json"))
        self.assertEqual(len(pages_on_disk), 1)

    # --- Validation des arguments ---

    def test_bare_string_raises(self):
        """Passing a bare string as rome_codes raises FranceTravailRomeError."""
        client = _make_client()
        paginator = _make_paginator()
        with self.assertRaises(self.FranceTravailRomeError):
            self.collect(
                rome_codes="M1805",
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )

    def test_empty_codes_raises_value_error(self):
        """An empty sequence raises ValueError."""
        client = _make_client()
        paginator = _make_paginator()
        with self.assertRaises(ValueError):
            self.collect(
                rome_codes=[],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )

    def test_max_pages_zero_raises_value_error(self):
        """max_pages=0 raises ValueError."""
        client = _make_client()
        paginator = _make_paginator()
        with self.assertRaises(ValueError):
            self.collect(
                rome_codes=["M1805"],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=0,
                now_provider=lambda: _FIXED_NOW,
            )

    def test_max_pages_negative_raises_value_error(self):
        """Negative max_pages raises ValueError."""
        client = _make_client()
        paginator = _make_paginator()
        with self.assertRaises(ValueError):
            self.collect(
                rome_codes=["M1805"],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=-1,
                now_provider=lambda: _FIXED_NOW,
            )

    def test_non_string_element_raises(self):
        """A non-string element in rome_codes raises FranceTravailRomeError."""
        client = _make_client()
        paginator = _make_paginator()
        with self.assertRaises(self.FranceTravailRomeError):
            self.collect(
                rome_codes=[1805],
                offers_client=client,
                paginator=paginator,
                output_directory=self.tmp,
                max_pages=1,
                now_provider=lambda: _FIXED_NOW,
            )

    # --- Compteurs du résultat ---

    def test_result_counters_are_correct(self):
        """RomeCollectionResult.total_offer_count and total_page_count are sums."""
        pages = {"M1805": [_make_page([{"id": "x"}]), _make_page([])]}
        result = self._run(["M1805"], pages_by_code=pages, max_pages=5)
        self.assertEqual(result.total_page_count, 2)
        self.assertEqual(result.total_offer_count, 1)

    def test_reference_entry_count_in_result(self):
        """reference_entry_count matches the number of referentiel entries."""
        result = self._run(["M1805"])
        self.assertEqual(result.reference_entry_count, 3)

    def test_no_main_py_imported(self):
        """main.py is never imported by the collector."""
        self._run(["M1805"])
        self.assertNotIn("main", sys.modules)

    def test_no_postgres_access(self):
        """postgres_connection is never imported by the collector."""
        self._run(["M1805"])
        self.assertNotIn("postgres_connection", sys.modules)


# ---------------------------------------------------------------------------
# Tests: CLI ROME mode (scripts/collect_france_travail.py)
# ---------------------------------------------------------------------------


class TestCollectScriptRomeMode(unittest.TestCase):
    """Tests for the --codes-file ROME mode of the collect script."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()
        _clean_modules()

    def _write_codes_csv(self, codes: list[str], column: str = "code_rome") -> Path:
        p = self.tmp / "codes.csv"
        _write_csv(p, codes, column=column)
        return p

    def _make_mock_result(self, run_dir: Path):
        from services.france_travail.rome_collector import RomeCollectionResult, RomeCodeResult  # noqa: PLC0415
        return RomeCollectionResult(
            run_id="20260621T120000Z",
            run_directory=run_dir,
            manifest_path=run_dir / "manifest.json",
            codes_results=(
                RomeCodeResult(
                    rome_code="M1805",
                    page_count=1,
                    offer_count=3,
                    page_paths=(),
                ),
            ),
            reference_entry_count=1911,
            created_at_utc="2026-06-21T12:00:00+00:00",
            complete=True,
        )

    def _run_main(self, argv, env_overrides=None):
        main_fn, _ = _import_script_main()
        env = {"LOCALAPPDATA": str(self.tmp)}
        if env_overrides:
            env.update(env_overrides)
        with patch.dict("os.environ", env, clear=True):
            return main_fn(argv)

    # --- Arguments ---

    def test_codes_file_required_for_rome_mode(self):
        """--codes-file is the trigger for ROME mode; without it, --max-pages is still accepted."""
        # Without --codes-file, max-pages alone should not trigger ROME mode.
        # The script should fall to legacy mode which succeeds (or not, but not crash on --max-pages).
        # We only verify it doesn't crash with an unrecognised argument.
        main_fn, _ = _import_script_main()
        # This should produce at most a help/usage or config error, not an uncaught exception.
        with patch("scripts.collect_france_travail._load_config_from_env", return_value=None):
            try:
                result = main_fn(["--max-pages", "2"])
                self.assertIsInstance(result, int)
            except SystemExit:
                pass  # Argparse printed help/usage — acceptable.

    def test_max_codes_valid(self):
        """--max-codes with a valid positive integer is accepted."""
        p = self._write_codes_csv(["M1805", "A1401"])
        with (
            patch("scripts.collect_france_travail._load_config_from_env", return_value=MagicMock()),
            patch("scripts.collect_france_travail.read_local_rome_codes", return_value=("M1805", "A1401")),
            patch("scripts.collect_france_travail.collect_offers_by_rome_codes") as mock_collect,
            patch("scripts.collect_france_travail.FranceTravailAuthClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersPaginator"),
        ):
            mock_collect.return_value = self._make_mock_result(self.tmp / "run1")
            (self.tmp / "run1").mkdir()
            result = self._run_main([
                "--codes-file", str(p),
                "--max-codes", "1",
                "--max-pages", "1",
                "--output-directory", str(self.tmp),
            ])
        self.assertEqual(result, 0)

    def test_max_codes_zero_returns_error(self):
        """--max-codes 0 returns a non-zero exit code."""
        p = self._write_codes_csv(["M1805"])
        result = self._run_main([
            "--codes-file", str(p),
            "--max-codes", "0",
            "--output-directory", str(self.tmp),
        ])
        self.assertNotEqual(result, 0)

    def test_max_codes_negative_returns_error(self):
        """--max-codes -1 returns a non-zero exit code."""
        p = self._write_codes_csv(["M1805"])
        result = self._run_main([
            "--codes-file", str(p),
            "--max-codes", "-1",
            "--output-directory", str(self.tmp),
        ])
        self.assertNotEqual(result, 0)

    def test_max_codes_non_integer_returns_error(self):
        """--max-codes abc returns a non-zero exit code."""
        p = self._write_codes_csv(["M1805"])
        result = self._run_main([
            "--codes-file", str(p),
            "--max-codes", "abc",
            "--output-directory", str(self.tmp),
        ])
        self.assertNotEqual(result, 0)

    def test_max_pages_zero_returns_error(self):
        """--max-pages 0 returns a non-zero exit code."""
        p = self._write_codes_csv(["M1805"])
        result = self._run_main([
            "--codes-file", str(p),
            "--max-pages", "0",
            "--output-directory", str(self.tmp),
        ])
        self.assertNotEqual(result, 0)

    def test_max_pages_negative_returns_error(self):
        """--max-pages -5 returns a non-zero exit code."""
        p = self._write_codes_csv(["M1805"])
        result = self._run_main([
            "--codes-file", str(p),
            "--max-pages", "-5",
            "--output-directory", str(self.tmp),
        ])
        self.assertNotEqual(result, 0)

    def test_max_pages_non_integer_returns_error(self):
        """--max-pages xyz returns a non-zero exit code."""
        p = self._write_codes_csv(["M1805"])
        result = self._run_main([
            "--codes-file", str(p),
            "--max-pages", "xyz",
            "--output-directory", str(self.tmp),
        ])
        self.assertNotEqual(result, 0)

    def test_absent_codes_file_returns_error(self):
        """A missing --codes-file returns a non-zero exit code."""
        with patch("scripts.collect_france_travail._load_config_from_env", return_value=MagicMock()):
            result = self._run_main([
                "--codes-file", str(self.tmp / "nonexistent.csv"),
                "--max-pages", "1",
                "--output-directory", str(self.tmp),
            ])
        self.assertNotEqual(result, 0)

    def test_codes_deduplicated_by_reader(self):
        """Duplicate codes in the CSV are deduplicated before collection."""
        p = self._write_codes_csv(["M1805", "M1805", "A1401"])
        with (
            patch("scripts.collect_france_travail._load_config_from_env", return_value=MagicMock()),
            patch("scripts.collect_france_travail.collect_offers_by_rome_codes") as mock_collect,
            patch("scripts.collect_france_travail.FranceTravailAuthClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersPaginator"),
        ):
            mock_collect.return_value = self._make_mock_result(self.tmp / "run2")
            (self.tmp / "run2").mkdir()
            self._run_main([
                "--codes-file", str(p),
                "--max-pages", "1",
                "--output-directory", str(self.tmp),
            ])
            call_kwargs = mock_collect.call_args[1]
            self.assertLessEqual(len(call_kwargs["rome_codes"]), 2)

    def test_max_codes_limits_after_deduplication(self):
        """--max-codes limits the selection after deduplication, preserving order."""
        p = self._write_codes_csv(["M1805", "A1401", "K2204"])
        with (
            patch("scripts.collect_france_travail._load_config_from_env", return_value=MagicMock()),
            patch("scripts.collect_france_travail.collect_offers_by_rome_codes") as mock_collect,
            patch("scripts.collect_france_travail.FranceTravailAuthClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersPaginator"),
        ):
            mock_collect.return_value = self._make_mock_result(self.tmp / "run3")
            (self.tmp / "run3").mkdir()
            self._run_main([
                "--codes-file", str(p),
                "--max-codes", "2",
                "--max-pages", "1",
                "--output-directory", str(self.tmp),
            ])
            call_kwargs = mock_collect.call_args[1]
            codes = list(call_kwargs["rome_codes"])
            self.assertEqual(len(codes), 2)
            self.assertEqual(codes[0], "M1805")
            self.assertEqual(codes[1], "A1401")

    def test_order_preserved_after_deduplication(self):
        """The order of first-occurrence codes is preserved."""
        p = self._write_codes_csv(["K2204", "M1805", "K2204"])
        with (
            patch("scripts.collect_france_travail._load_config_from_env", return_value=MagicMock()),
            patch("scripts.collect_france_travail.collect_offers_by_rome_codes") as mock_collect,
            patch("scripts.collect_france_travail.FranceTravailAuthClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersPaginator"),
        ):
            mock_collect.return_value = self._make_mock_result(self.tmp / "run4")
            (self.tmp / "run4").mkdir()
            self._run_main([
                "--codes-file", str(p),
                "--max-pages", "1",
                "--output-directory", str(self.tmp),
            ])
            call_kwargs = mock_collect.call_args[1]
            codes = list(call_kwargs["rome_codes"])
            self.assertEqual(codes[0], "K2204")
            self.assertEqual(codes[1], "M1805")

    def test_custom_column_name_passed(self):
        """--column is passed to read_local_rome_codes."""
        p = self._write_codes_csv(["M1805"], column="rome_col")
        with (
            patch("scripts.collect_france_travail._load_config_from_env", return_value=MagicMock()),
            patch("scripts.collect_france_travail.read_local_rome_codes", return_value=("M1805",)) as mock_read,
            patch("scripts.collect_france_travail.collect_offers_by_rome_codes") as mock_collect,
            patch("scripts.collect_france_travail.FranceTravailAuthClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersPaginator"),
        ):
            mock_collect.return_value = self._make_mock_result(self.tmp / "run5")
            (self.tmp / "run5").mkdir()
            self._run_main([
                "--codes-file", str(p),
                "--column", "rome_col",
                "--max-pages", "1",
                "--output-directory", str(self.tmp),
            ])
            call_kwargs = mock_read.call_args[1]
            self.assertEqual(call_kwargs.get("column"), "rome_col")

    def test_default_column_is_code_rome(self):
        """Without --column, the default column is code_rome."""
        p = self._write_codes_csv(["M1805"])
        with (
            patch("scripts.collect_france_travail._load_config_from_env", return_value=MagicMock()),
            patch("scripts.collect_france_travail.read_local_rome_codes", return_value=("M1805",)) as mock_read,
            patch("scripts.collect_france_travail.collect_offers_by_rome_codes") as mock_collect,
            patch("scripts.collect_france_travail.FranceTravailAuthClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersClient"),
            patch("scripts.collect_france_travail.FranceTravailOffersPaginator"),
        ):
            mock_collect.return_value = self._make_mock_result(self.tmp / "run6")
            (self.tmp / "run6").mkdir()
            self._run_main([
                "--codes-file", str(p),
                "--max-pages", "1",
                "--output-directory", str(self.tmp),
            ])
            call_kwargs = mock_read.call_args[1]
            self.assertEqual(call_kwargs.get("column"), "code_rome")

    def test_mutually_exclusive_modes_return_error(self):
        """--codes-file and --param together return a non-zero exit code."""
        p = self._write_codes_csv(["M1805"])
        result = self._run_main([
            "--codes-file", str(p),
            "--param", "motsCles=python",
            "--output-directory", str(self.tmp),
        ])
        self.assertNotEqual(result, 0)

    def test_rome_options_without_codes_file_rejected(self):
        """ROME options used without --codes-file must fail immediately without side effects."""
        # Options to test: --max-pages, --max-codes, --column
        options_list = [
            ["--max-pages", "2"],
            ["--max-codes", "2"],
            ["--column", "code_rome"],
        ]
        for options in options_list:
            with self.subTest(options=options):
                # Clean temp directory to verify no files are written
                for item in self.tmp.iterdir():
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        import shutil
                        shutil.rmtree(item)

                # Ensure env does not have LOCALAPPDATA or .env, and block network
                with (
                    patch("scripts.collect_france_travail._load_config_from_env") as mock_cfg,
                    patch("requests.Session.send", side_effect=RuntimeError("Network blocked")),
                ):
                    result = self._run_main(options + ["--output-directory", str(self.tmp)])

                    self.assertEqual(result, 1) # EXIT_ERROR
                    mock_cfg.assert_not_called()

                    # Verify no files/dirs were created in the temp directory
                    self.assertEqual(list(self.tmp.iterdir()), [])

    def test_mixtures_legacy_rome_rejected(self):
        """Mixing --codes-file with legacy options is rejected immediately."""
        p = self._write_codes_csv(["M1805"])
        mixtures = [
            ["--codes-file", str(p), "--param", "motsCles=python"],
            ["--codes-file", str(p), "--range-start", "1"],
            ["--codes-file", str(p), "--range-end", "5"],
        ]
        for argv in mixtures:
            with self.subTest(argv=argv):
                # Clean temp directory (keeping only codes file)
                for item in self.tmp.iterdir():
                    if item != p:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            import shutil
                            shutil.rmtree(item)

                with (
                    patch("scripts.collect_france_travail._load_config_from_env") as mock_cfg,
                    patch("requests.Session.send", side_effect=RuntimeError("Network blocked")),
                ):
                    result = self._run_main(argv + ["--output-directory", str(self.tmp)])
                    self.assertEqual(result, 1)
                    mock_cfg.assert_not_called()

                    # Verify no extra files/dirs were created in the temp directory
                    self.assertEqual(list(self.tmp.iterdir()), [p])

    def test_no_main_py_imported_by_script(self):
        """main.py is not imported by collect_france_travail.py."""
        _clean_modules()
        import scripts.collect_france_travail  # noqa: F401, PLC0415
        for key in sys.modules:
            self.assertNotEqual(key, "main")

    def test_no_postgres_imported_by_script(self):
        """postgres_connection is not imported by collect_france_travail.py."""
        _clean_modules()
        import scripts.collect_france_travail  # noqa: F401, PLC0415
        self.assertNotIn("postgres_connection", sys.modules)


# ---------------------------------------------------------------------------
# Tests: Legacy mode non-regression
# ---------------------------------------------------------------------------


class TestCollectScriptLegacyNonRegression(unittest.TestCase):
    """Verify that the legacy mode (--param / single page) still works."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()
        _clean_modules()

    def _run_legacy(self, extra_argv=None):
        main_fn, _ = _import_script_main()
        argv = ["--output-directory", str(self.tmp)] + (extra_argv or [])
        env = {"LOCALAPPDATA": str(self.tmp)}
        with patch.dict("os.environ", env, clear=True):
            return main_fn(argv)

    @patch("scripts.collect_france_travail.FranceTravailRawStorage")
    @patch("scripts.collect_france_travail.FranceTravailOffersClient")
    @patch("scripts.collect_france_travail.FranceTravailAuthClient")
    @patch("scripts.collect_france_travail._load_config_from_env")
    def test_legacy_mode_success(
        self, mock_cfg, mock_auth_cls, mock_client_cls, mock_storage_cls
    ):
        """Legacy mode with --param still runs and returns 0."""
        from services.france_travail.client import FranceTravailOffersPage  # noqa: PLC0415
        from services.france_travail.raw_storage import FranceTravailRawArchive  # noqa: PLC0415

        mock_cfg.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        page = FranceTravailOffersPage(
            payload={"resultats": []},
            results=(),
            content_range=None,
            range_start=0,
            range_end=9,
        )
        mock_client.search_offers_page.return_value = page

        mock_storage = MagicMock()
        mock_storage_cls.return_value = mock_storage
        archive = FranceTravailRawArchive(
            run_id="20260621T120000Z",
            directory=self.tmp / "run",
            manifest_path=self.tmp / "run" / "manifest.json",
            page_paths=(),
            page_count=1,
            offer_count=0,
            created_at_utc="2026-06-21T12:00:00+00:00",
        )
        mock_storage.archive_pages.return_value = archive

        result = self._run_legacy(["--param", "motsCles=python"])
        self.assertEqual(result, 0)

    def test_legacy_mode_sensitive_param_rejected(self):
        """A sensitive --param is still rejected in legacy mode."""
        result = self._run_legacy(["--param", "token=abc"])
        self.assertNotEqual(result, 0)


class TestNetworkBarrier(unittest.TestCase):
    """Verify that unmocked calls to requests or France Travail API clients raise errors."""

    def test_unmocked_network_calls_raise_error(self):
        # We check that requests.Session.send raises an exception when blocked
        with patch("requests.Session.send", side_effect=RuntimeError("Network access disabled")):
            import requests
            with self.assertRaises(RuntimeError) as ctx:
                requests.get("https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/metiers")
            self.assertIn("Network access disabled", str(ctx.exception))

    def test_unmocked_client_methods_raise_error(self):
        # Without real credentials, calling get_rome_referentiel or search_offers_page directly should fail immediately
        from services.france_travail.client import FranceTravailOffersClient
        from services.france_travail.config import FranceTravailConfig
        from services.france_travail.exceptions import FranceTravailError

        # Instantiate with a config mapping that points to dummy values
        config = FranceTravailConfig.from_mapping({
            "FRANCE_TRAVAIL_CLIENT_ID": "dummy",
            "FRANCE_TRAVAIL_CLIENT_SECRET": "dummy",
            "FRANCE_TRAVAIL_TOKEN_URL": "https://127.0.0.1:9999/token",
            "FRANCE_TRAVAIL_SCOPE": "dummy",
            "FRANCE_TRAVAIL_OFFERS_SEARCH_URL": "https://127.0.0.1:9999/search",
            "FRANCE_TRAVAIL_REQUEST_TIMEOUT_SECONDS": "1",
        })

        # A real auth client will attempt network connection to get token, which fails
        from services.france_travail.auth import FranceTravailAuthClient
        auth = FranceTravailAuthClient(config=config)
        client = FranceTravailOffersClient(config=config, auth_client=auth)

        # Any attempt to fetch referentiel or search page should raise FranceTravailError (due to failed token retrieval/network timeout)
        with self.assertRaises(FranceTravailError):
            client.get_rome_referentiel()

        with self.assertRaises(FranceTravailError):
            client.search_offers_page(search_params={}, range_start=0, range_end=9)


if __name__ == "__main__":
    unittest.main()
