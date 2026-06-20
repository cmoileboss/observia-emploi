"""
Unit tests for services.france_travail.raw_storage.

All tests are strictly offline:
- No real HTTP calls.
- No real OAuth tokens.
- No PostgreSQL connection.
- main.py, FastAPI, and SQLAlchemy are NOT imported.
- All file I/O uses tempfile.TemporaryDirectory; no files are created in the repo.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

from services.france_travail.client import FranceTravailOffersPage
from services.france_travail.exceptions import FranceTravailStorageError
from services.france_travail.raw_storage import (
    FranceTravailRawArchive,
    FranceTravailRawStorage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_UTC = datetime(2026, 6, 20, 15, 30, 0, tzinfo=timezone.utc)
_FIXED_RUN_ID = "20260620T153000Z"


def _fixed_now() -> datetime:
    return _FIXED_UTC


def _make_page(
    results: list[dict],
    range_start: int = 0,
    range_end: int = 149,
    content_range: Optional[str] = None,
    extra_payload: Optional[dict] = None,
) -> FranceTravailOffersPage:
    payload: dict = {"resultats": results}
    if extra_payload:
        payload.update(extra_payload)
    return FranceTravailOffersPage(
        payload=payload,
        results=tuple(results),
        content_range=content_range,
        range_start=range_start,
        range_end=range_end,
    )


def _make_offers(n: int) -> list[dict]:
    return [{"id": str(i), "titre": f"Poste {i}"} for i in range(n)]


def _make_storage(tmp_path: Path, now=_fixed_now) -> FranceTravailRawStorage:
    return FranceTravailRawStorage(root_directory=tmp_path, now_provider=now)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------


class TestFranceTravailRawStorageConstruction(unittest.TestCase):

    def test_no_directory_created_on_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "archive"
            FranceTravailRawStorage(root_directory=root)
            self.assertFalse(root.exists(), "Root must not be created at construction time")

    def test_no_file_created_on_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "archive"
            FranceTravailRawStorage(root_directory=root)
            self.assertEqual(list(Path(tmp).iterdir()), [])


# ---------------------------------------------------------------------------
# 2. Valid archives
# ---------------------------------------------------------------------------


class TestFranceTravailRawStorageValidArchive(unittest.TestCase):

    def test_single_page_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            page = _make_page(_make_offers(10))
            archive = storage.archive_pages([page])
            self.assertEqual(archive.page_count, 1)
            self.assertEqual(archive.offer_count, 10)
            self.assertEqual(len(archive.page_paths), 1)

    def test_multiple_pages_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            pages = [
                _make_page(_make_offers(150), range_start=0, range_end=149),
                _make_page(_make_offers(31), range_start=150, range_end=299),
            ]
            archive = storage.archive_pages(pages)
            self.assertEqual(archive.page_count, 2)
            self.assertEqual(archive.offer_count, 181)
            self.assertEqual(len(archive.page_paths), 2)

    def test_empty_results_page_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            page = _make_page([])
            archive = storage.archive_pages([page])
            self.assertEqual(archive.page_count, 1)
            self.assertEqual(archive.offer_count, 0)
            self.assertTrue(archive.page_paths[0].exists())

    def test_page_filename_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            pages = [
                _make_page(_make_offers(150), range_start=0, range_end=149),
                _make_page(_make_offers(31), range_start=150, range_end=299),
            ]
            archive = storage.archive_pages(pages)
            names = [p.name for p in archive.page_paths]
            self.assertEqual(names[0], "page_0001_000000-000149.json")
            self.assertEqual(names[1], "page_0002_000150-000299.json")

    def test_page_content_equals_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            page = _make_page(_make_offers(5))
            archive = storage.archive_pages([page])
            written = _read_json(archive.page_paths[0])
            self.assertEqual(written, page.payload)

    def test_accented_characters_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            page = _make_page([{"titre": "Développeur Île-de-France"}])
            archive = storage.archive_pages([page])
            raw = archive.page_paths[0].read_text(encoding="utf-8")
            self.assertIn("Développeur", raw)
            self.assertIn("Île-de-France", raw)

    def test_manifest_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(5))])
            self.assertTrue(archive.manifest_path.exists())
            self.assertEqual(archive.manifest_path.name, "manifest.json")

    def test_manifest_written_last(self):
        """Manifest must be the last file written (its mtime >= page files)."""
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            pages = [
                _make_page(_make_offers(150), range_start=0, range_end=149),
                _make_page(_make_offers(31), range_start=150, range_end=299),
            ]
            archive = storage.archive_pages(pages)
            manifest_mtime = archive.manifest_path.stat().st_mtime
            for page_path in archive.page_paths:
                self.assertGreaterEqual(
                    manifest_mtime,
                    page_path.stat().st_mtime,
                    "manifest.json must not be older than any page file",
                )

    def test_manifest_page_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            pages = [_make_page(_make_offers(10)) for _ in range(3)]
            archive = storage.archive_pages(pages)
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["page_count"], 3)

    def test_manifest_offer_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            pages = [
                _make_page(_make_offers(150), range_start=0, range_end=149),
                _make_page(_make_offers(31), range_start=150, range_end=299),
            ]
            archive = storage.archive_pages(pages)
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["offer_count"], 181)

    def test_manifest_created_at_utc(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["created_at_utc"], _FIXED_UTC.isoformat())

    def test_manifest_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["run_id"], _FIXED_RUN_ID)

    def test_manifest_source_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["source"], "france_travail_offres_emploi")

    def test_manifest_search_params_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            params = {"codeROME": "M1805"}
            archive = storage.archive_pages([_make_page(_make_offers(1))], search_params=params)
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["search_params"], {"codeROME": "M1805"})

    def test_manifest_search_params_none_becomes_empty_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))], search_params=None)
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["search_params"], {})

    def test_manifest_content_range_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            page = _make_page(_make_offers(150), content_range="offres 0-149/845")
            archive = storage.archive_pages([page])
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["pages"][0]["content_range"], "offres 0-149/845")

    def test_manifest_content_range_none_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            page = _make_page(_make_offers(50), content_range=None)
            archive = storage.archive_pages([page])
            manifest = _read_json(archive.manifest_path)
            self.assertIsNone(manifest["pages"][0]["content_range"])

    def test_archive_dataclass_is_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            with self.assertRaises((AttributeError, TypeError)):
                archive.page_count = 999  # type: ignore

    def test_page_paths_is_tuple(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            self.assertIsInstance(archive.page_paths, tuple)

    def test_root_directory_created_on_first_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "deep" / "archive"
            storage = FranceTravailRawStorage(root_directory=root, now_provider=_fixed_now)
            self.assertFalse(root.exists())
            storage.archive_pages([_make_page(_make_offers(1))])
            self.assertTrue(root.exists())

    def test_archive_created_at_utc_matches_now_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            self.assertEqual(archive.created_at_utc, _FIXED_UTC.isoformat())

    def test_run_id_matches_expected_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            self.assertEqual(archive.run_id, _FIXED_RUN_ID)

    def test_directory_is_under_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = _make_storage(root)
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            self.assertEqual(archive.directory.parent, root)


# ---------------------------------------------------------------------------
# 3. Non-mutation guarantees
# ---------------------------------------------------------------------------


class TestFranceTravailRawStorageNonMutation(unittest.TestCase):

    def test_payload_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            original_payload = {"resultats": [{"id": "1"}]}
            page = FranceTravailOffersPage(
                payload=original_payload,
                results=({"id": "1"},),
                content_range=None,
                range_start=0,
                range_end=0,
            )
            storage.archive_pages([page])
            self.assertEqual(page.payload, {"resultats": [{"id": "1"}]})

    def test_search_params_not_mutated(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            params = {"codeROME": "M1805"}
            storage.archive_pages([_make_page(_make_offers(1))], search_params=params)
            self.assertEqual(params, {"codeROME": "M1805"})
            self.assertNotIn("run_id", params)


# ---------------------------------------------------------------------------
# 4. Collision handling
# ---------------------------------------------------------------------------


class TestFranceTravailRawStorageCollisions(unittest.TestCase):

    def test_first_run_has_no_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            self.assertEqual(archive.run_id, _FIXED_RUN_ID)
            self.assertEqual(archive.directory.name, _FIXED_RUN_ID)

    def test_second_run_same_second_gets_suffix_01(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            a1 = storage.archive_pages([_make_page(_make_offers(1))])
            a2 = storage.archive_pages([_make_page(_make_offers(1))])
            self.assertEqual(a1.run_id, _FIXED_RUN_ID)
            self.assertEqual(a2.run_id, f"{_FIXED_RUN_ID}_01")
            self.assertNotEqual(a1.directory, a2.directory)

    def test_third_run_same_second_gets_suffix_02(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            storage.archive_pages([_make_page(_make_offers(1))])
            storage.archive_pages([_make_page(_make_offers(1))])
            a3 = storage.archive_pages([_make_page(_make_offers(1))])
            self.assertEqual(a3.run_id, f"{_FIXED_RUN_ID}_02")

    def test_existing_archives_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            a1 = storage.archive_pages([_make_page([{"id": "first"}])])
            a2 = storage.archive_pages([_make_page([{"id": "second"}])])
            # Both archives exist independently
            self.assertTrue(a1.manifest_path.exists())
            self.assertTrue(a2.manifest_path.exists())
            m1 = _read_json(a1.manifest_path)
            m2 = _read_json(a2.manifest_path)
            self.assertNotEqual(m1["run_id"], m2["run_id"])


# ---------------------------------------------------------------------------
# 5. Failure modes and cleanup
# ---------------------------------------------------------------------------


class TestFranceTravailRawStorageFailures(unittest.TestCase):

    def test_empty_iterable_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages([])

    def test_empty_iterable_leaves_no_final_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            root = Path(tmp)
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages([])
            # No run directory should have been created
            run_dirs = [p for p in root.iterdir() if not p.name.startswith(".")]
            self.assertEqual(run_dirs, [])

    def test_naive_datetime_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            naive_now = lambda: datetime(2026, 6, 20, 15, 30, 0)  # no tzinfo
            storage = FranceTravailRawStorage(root_directory=Path(tmp), now_provider=naive_now)
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages([_make_page(_make_offers(1))])

    def test_payload_not_dict_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            bad_page = MagicMock()
            bad_page.payload = ["not", "a", "dict"]
            bad_page.results = ()
            bad_page.range_start = 0
            bad_page.range_end = 0
            bad_page.content_range = None
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages([bad_page])

    def test_payload_not_serialisable_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            bad_payload = {"resultats": [object()]}  # object() is not JSON-serialisable
            bad_page = FranceTravailOffersPage(
                payload=bad_payload,
                results=(object(),),
                content_range=None,
                range_start=0,
                range_end=0,
            )
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages([bad_page])

    def test_invalid_range_start_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            bad_page = MagicMock()
            bad_page.payload = {"resultats": []}
            bad_page.results = ()
            bad_page.range_start = "not_an_int"
            bad_page.range_end = 0
            bad_page.content_range = None
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages([bad_page])

    def test_invalid_range_end_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            bad_page = MagicMock()
            bad_page.payload = {"resultats": []}
            bad_page.results = ()
            bad_page.range_start = 0
            bad_page.range_end = None
            bad_page.content_range = None
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages([bad_page])

    def test_range_end_less_than_range_start_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            bad_page = FranceTravailOffersPage(
                payload={"resultats": []},
                results=(),
                content_range=None,
                range_start=10,
                range_end=5,  # invalid: end < start
            )
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages([bad_page])

    def test_tmp_directory_deleted_after_write_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = _make_storage(root)

            # Simulate write failure by making write_text raise OSError
            page = _make_page(_make_offers(5))
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                with self.assertRaises(FranceTravailStorageError):
                    storage.archive_pages([page])

            # No .tmp directory should remain
            tmp_dirs = list(root.glob("*.tmp"))
            self.assertEqual(tmp_dirs, [], "Temporary directory must be cleaned up after error")

    def test_no_final_directory_after_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = _make_storage(root)
            page = _make_page(_make_offers(5))

            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                with self.assertRaises(FranceTravailStorageError):
                    storage.archive_pages([page])

            final_dirs = [p for p in root.iterdir() if not p.name.startswith(".")]
            self.assertEqual(final_dirs, [], "No final directory must exist after a write error")

    def test_error_message_does_not_contain_payload_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            # range_end < range_start triggers a predictable error
            bad_page = FranceTravailOffersPage(
                payload={"resultats": [{"SECRET_OFFER_DATA": "TOP_SECRET_VALUE"}]},
                results=(),
                content_range=None,
                range_start=10,
                range_end=5,
            )
            try:
                storage.archive_pages([bad_page])
            except FranceTravailStorageError as exc:
                self.assertNotIn("TOP_SECRET_VALUE", str(exc))
                self.assertNotIn("SECRET_OFFER_DATA", str(exc))
            else:
                self.fail("Expected FranceTravailStorageError")


# ---------------------------------------------------------------------------
# 6. Sensitive key protection
# ---------------------------------------------------------------------------


class TestFranceTravailRawStorageSensitiveKeys(unittest.TestCase):

    def _assert_key_refused(self, key: str, value: str = "some_value"):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            with self.assertRaises(FranceTravailStorageError, msg=f"Key '{key}' must be refused"):
                storage.archive_pages(
                    [_make_page(_make_offers(1))],
                    search_params={key: value},
                )

    def test_authorization_refused(self):
        self._assert_key_refused("authorization")

    def test_access_token_refused(self):
        self._assert_key_refused("access_token")

    def test_token_refused(self):
        self._assert_key_refused("token")

    def test_client_secret_refused(self):
        self._assert_key_refused("client_secret")

    def test_secret_refused(self):
        self._assert_key_refused("secret")

    def test_client_id_refused(self):
        self._assert_key_refused("client_id")

    def test_password_refused(self):
        self._assert_key_refused("password")

    def test_uppercase_authorization_refused(self):
        self._assert_key_refused("Authorization")

    def test_uppercase_access_token_refused(self):
        self._assert_key_refused("ACCESS_TOKEN")

    def test_mixed_case_client_secret_refused(self):
        self._assert_key_refused("Client_Secret")

    def test_sensitive_value_absent_from_error_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            try:
                storage.archive_pages(
                    [_make_page(_make_offers(1))],
                    search_params={"access_token": "ULTRA_SECRET_TOKEN_VALUE"},
                )
            except FranceTravailStorageError as exc:
                self.assertNotIn("ULTRA_SECRET_TOKEN_VALUE", str(exc))
            else:
                self.fail("Expected FranceTravailStorageError")

    def test_sensitive_check_happens_before_any_file_creation(self):
        """No directory must be created when a sensitive key is detected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = _make_storage(root)
            with self.assertRaises(FranceTravailStorageError):
                storage.archive_pages(
                    [_make_page(_make_offers(1))],
                    search_params={"access_token": "tok"},
                )
            dirs = list(root.iterdir())
            self.assertEqual(dirs, [], "No directory must be created before sensitive-key check")

    def test_safe_keys_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            # These are legitimate API filter keys and must NOT be refused.
            safe_params = {"motsCles": "python", "romeProfessionCard": "M1805"}
            archive = storage.archive_pages(
                [_make_page(_make_offers(1))],
                search_params=safe_params,
            )
            manifest = _read_json(archive.manifest_path)
            self.assertEqual(manifest["search_params"]["motsCles"], "python")


# ---------------------------------------------------------------------------
# 7. Isolation guarantees
# ---------------------------------------------------------------------------


class TestFranceTravailRawStorageIsolation(unittest.TestCase):

    def test_requests_not_imported(self):
        import services.france_travail.raw_storage as mod
        self.assertFalse(hasattr(mod, "requests"))

    def test_fastapi_not_imported(self):
        import services.france_travail.raw_storage as mod
        self.assertFalse(hasattr(mod, "fastapi"))

    def test_sqlalchemy_not_imported(self):
        import services.france_travail.raw_storage as mod
        self.assertFalse(hasattr(mod, "sqlalchemy"))

    def test_no_files_created_outside_temp_dir(self):
        """Verify archive directory is strictly inside the TemporaryDirectory."""
        with tempfile.TemporaryDirectory() as tmp:
            storage = _make_storage(Path(tmp))
            archive = storage.archive_pages([_make_page(_make_offers(1))])
            self.assertTrue(
                str(archive.directory).startswith(tmp),
                "Archive directory must be inside the TemporaryDirectory",
            )


if __name__ == "__main__":
    unittest.main()
