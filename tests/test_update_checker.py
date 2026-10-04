from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unittest
from collections.abc import Iterable, Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from src.update_checker import UpdateChecker


class TestCheckForUpdate(unittest.TestCase):
    def test_carries_github_release_digest_and_size_to_download_info(self) -> None:
        payload = b"verified release"
        digest = hashlib.sha256(payload).hexdigest()
        response = MagicMock()
        response.json.return_value = {
            "tag_name": "v9.0.0",
            "body": "notes",
            "html_url": "https://example.test/release",
            "assets": [
                {
                    "name": "GM2Godot-macos-arm64.zip",
                    "browser_download_url": "https://example.test/update.zip",
                    "digest": f"sha256:{digest.upper()}",
                    "size": len(payload),
                }
            ],
        }

        with (
            patch("src.update_checker.requests.get", return_value=response),
            patch("src.update_checker.platform.system", return_value="Darwin"),
            patch("src.update_checker.platform.machine", return_value="arm64"),
            patch("src.update_checker.get_version", return_value="1.0.0"),
        ):
            info = UpdateChecker().check_for_update()

        self.assertIsNotNone(info)
        assert info is not None
        self.assertTrue(info.available)
        self.assertEqual(info.asset_digest, f"sha256:{digest}")
        self.assertEqual(info.asset_size, len(payload))

    def test_macos_architecture_aliases_select_exact_zip_metadata(self) -> None:
        asset_names = [
            "GM2Godot-linux.zip",
            "GM2Godot-macos-arm64.dmg",
            "GM2Godot-macos-arm64.zip",
            "GM2Godot-macos-x86_64.dmg",
            "GM2Godot-macos-x86_64.zip",
            "GM2Godot-windows.zip",
            "SHA256SUMS",
        ]
        assets: list[dict[str, object]] = [
            {
                "name": name,
                "browser_download_url": f"https://example.test/releases/{name}",
                "digest": "sha256:" + hashlib.sha256(name.encode()).hexdigest().upper(),
                "size": 100 + index,
            }
            for index, name in enumerate(asset_names)
        ]
        aliases = (
            ("arm64", "arm64"),
            ("aarch64", "arm64"),
            (" ARM64 ", "arm64"),
            ("\tAaRcH64\n", "arm64"),
            ("x86_64", "x86_64"),
            ("amd64", "x86_64"),
            (" X86_64 ", "x86_64"),
            ("\tAmD64\n", "x86_64"),
        )
        for index, (machine, architecture) in enumerate(aliases):
            with self.subTest(machine=machine):
                shuffled = assets[index % len(assets):] + assets[:index % len(assets)]
                if index % 2:
                    shuffled = list(reversed(shuffled))
                response = self._release_response(shuffled)
                with (
                    patch("src.update_checker.requests.get", return_value=response),
                    patch("src.update_checker.platform.system", return_value="Darwin"),
                    patch("src.update_checker.platform.machine", return_value=machine),
                    patch("src.update_checker.get_version", return_value="1.0.0"),
                ):
                    info = UpdateChecker().check_for_update()
                self.assertIsNotNone(info)
                assert info is not None
                expected_name = f"GM2Godot-macos-{architecture}.zip"
                self.assertEqual(info.asset_name, expected_name)
                self.assertEqual(info.download_url, f"https://example.test/releases/{expected_name}")
                self.assertEqual(info.asset_digest, "sha256:" + hashlib.sha256(expected_name.encode()).hexdigest())
                self.assertEqual(info.asset_size, 100 + asset_names.index(expected_name))
                self.assertTrue(info.available)

    def test_macos_unsafe_or_ambiguous_assets_keep_release_page_fallback(self) -> None:
        selected: dict[str, object] = {
            "name": "GM2Godot-macos-arm64.zip",
            "browser_download_url": "https://example.test/releases/arm64.zip",
            "digest": "sha256:" + "a" * 64,
            "size": 123,
        }
        cases: list[tuple[str, str, list[dict[str, object]]]] = [
            ("missing", "arm64", []),
            ("opposite architecture", "arm64", [{**selected, "name": "GM2Godot-macos-x86_64.zip"}]),
            ("generic legacy", "arm64", [{**selected, "name": "GM2Godot-macOS.zip"}]),
            ("DMG only", "arm64", [{**selected, "name": "GM2Godot-macos-arm64.dmg"}]),
            ("substring bait", "arm64", [{**selected, "name": "backup-GM2Godot-macos-arm64.zip"}]),
            ("case bait", "arm64", [{**selected, "name": "GM2Godot-macos-ARM64.zip"}]),
            ("duplicate valid", "arm64", [selected, dict(selected)]),
            ("duplicate malformed second", "arm64", [selected, {**selected, "browser_download_url": None}]),
            ("missing URL", "arm64", [{key: value for key, value in selected.items() if key != "browser_download_url"}]),
        ]
        for machine in ("", "unknown", "universal", "arm64,x86_64", "x86"):
            cases.append(("unknown machine", machine, [selected]))
        for url in (
            None,
            "",
            42,
            "javascript:alert(1)",
            "file:///tmp/update.zip",
            "//example.test/update.zip",
            "https:///update.zip",
            "https://example.test/update file.zip",
            "https://example.test/\nupdate.zip",
            "https://example.test/\x00update.zip",
            "https://[broken/update.zip",
            "https://example.test:not-a-port/update.zip",
            "https://example.test:70000/update.zip",
        ):
            cases.append((f"unsafe URL {url!r}", "arm64", [{**selected, "browser_download_url": url}]))
        for label, machine, assets in cases:
            with self.subTest(case=label, machine=machine):
                response = self._release_response(assets)
                with (
                    patch("src.update_checker.requests.get", return_value=response),
                    patch("src.update_checker.platform.system", return_value="Darwin"),
                    patch("src.update_checker.platform.machine", return_value=machine),
                    patch("src.update_checker.get_version", return_value="1.0.0"),
                ):
                    info = UpdateChecker().check_for_update()
                self.assertIsNotNone(info)
                assert info is not None
                self.assertTrue(info.available)
                self.assertEqual(info.latest_version, "9.0.0")
                self.assertEqual(info.release_notes, "release notes")
                self.assertEqual(info.release_page_url, "https://example.test/release")
                self.assertEqual(
                    (info.download_url, info.asset_name, info.asset_digest, info.asset_size),
                    (None, None, None, None),
                )

    def test_non_macos_selection_never_queries_machine(self) -> None:
        for system, asset_name in (
            ("Windows", "GM2Godot-windows.zip"),
            ("Linux", "GM2Godot-linux.zip"),
        ):
            with self.subTest(system=system):
                assets: list[dict[str, object]] = [
                    {"name": "GM2Godot-macos-arm64.zip", "browser_download_url": "https://example.test/arm.zip"},
                    {"name": "GM2Godot-macos-x86_64.zip", "browser_download_url": "https://example.test/intel.zip"},
                    {
                        "name": asset_name,
                        "browser_download_url": f"https://example.test/{asset_name}",
                        "digest": "sha256:" + "b" * 64,
                        "size": 456,
                    },
                ]
                response = self._release_response(assets)
                with (
                    patch("src.update_checker.requests.get", return_value=response),
                    patch("src.update_checker.platform.system", return_value=system),
                    patch("src.update_checker.platform.machine", side_effect=AssertionError("non-Mac machine query")) as machine,
                    patch("src.update_checker.get_version", return_value="1.0.0"),
                ):
                    info = UpdateChecker().check_for_update()
                machine.assert_not_called()
                self.assertIsNotNone(info)
                assert info is not None
                self.assertEqual(info.asset_name, asset_name)
                self.assertEqual(info.download_url, f"https://example.test/{asset_name}")
                self.assertEqual(info.asset_digest, "sha256:" + "b" * 64)
                self.assertEqual(info.asset_size, 456)

    @staticmethod
    def _release_response(assets: list[dict[str, object]]) -> MagicMock:
        response = MagicMock()
        response.json.return_value = {
            "tag_name": "v9.0.0",
            "body": "release notes",
            "html_url": "https://example.test/release",
            "assets": assets,
        }
        return response



class TestDownloadUpdate(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir_context = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_context.name)
        self.destination = self.temp_dir / "GM2Godot-update.bin"

    def tearDown(self) -> None:
        self.temp_dir_context.cleanup()

    def test_success_replaces_destination_atomically_and_reports_progress(self) -> None:
        response = self._response([b"abc", b"def"], content_length=6)
        progress: list[int] = []
        real_replace = os.replace

        with (
            patch("src.update_checker.requests.get", return_value=response) as request_get,
            patch("src.update_checker.os.replace", wraps=real_replace) as replace,
        ):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
                progress.append,
            )

        self.assertTrue(success)
        self.assertEqual(self.destination.read_bytes(), b"abcdef")
        self.assertEqual(progress, [50, 100])
        request_get.assert_called_once_with(
            "https://example.test/update.bin",
            stream=True,
            timeout=60,
        )
        response.raise_for_status.assert_called_once_with()
        response.iter_content.assert_called_once_with(chunk_size=8192)
        response.close.assert_called_once_with()
        replace.assert_called_once()
        staged_path, replaced_path = replace.call_args.args
        self.assertEqual(Path(staged_path).parent, self.temp_dir)
        self.assertEqual(Path(replaced_path), self.destination)
        self.assert_no_partial_downloads()

    def test_verified_digest_accepts_matching_payload(self) -> None:
        payload = b"verified release"
        response = self._response([payload], content_length=len(payload))

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
                expected_digest="sha256:" + hashlib.sha256(payload).hexdigest(),
                expected_size=len(payload),
            )

        self.assertTrue(success)
        self.assertEqual(self.destination.read_bytes(), payload)

    def test_same_length_digest_mismatch_preserves_existing_destination(self) -> None:
        self.destination.write_bytes(b"existing release")
        expected_payload = b"expected"
        corrupt_payload = b"corrupt!"
        self.assertEqual(len(expected_payload), len(corrupt_payload))
        response = self._response([corrupt_payload], content_length=len(corrupt_payload))

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
                expected_digest="sha256:" + hashlib.sha256(expected_payload).hexdigest(),
                expected_size=len(expected_payload),
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        self.assert_no_partial_downloads()

    @unittest.skipIf(os.name == "nt", "POSIX permissions test")
    def test_replacing_existing_destination_preserves_its_mode(self) -> None:
        self.destination.write_bytes(b"existing release")
        self.destination.chmod(0o755)
        payload = b"complete"
        response = self._response([payload], content_length=len(payload))

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertTrue(success)
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o755)

    def test_truncated_download_preserves_existing_destination_and_cleans_up(self) -> None:
        self.destination.write_bytes(b"existing release")
        response = self._response([b"short"], content_length=10)

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_request_failure_preserves_existing_destination(self) -> None:
        self.destination.write_bytes(b"existing release")

        with patch(
            "src.update_checker.requests.get",
            side_effect=requests.ConnectionError("connection refused"),
        ):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        self.assert_no_partial_downloads()

    def test_iteration_failure_preserves_existing_destination_and_cleans_up(self) -> None:
        self.destination.write_bytes(b"existing release")
        response = self._response(self._failing_chunks(), content_length=12)

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_http_error_closes_response_without_creating_destination(self) -> None:
        response = self._response([], content_length=None)
        response.raise_for_status.side_effect = requests.HTTPError("not found")

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertFalse(success)
        self.assertFalse(self.destination.exists())
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_empty_chunks_are_ignored_for_progress(self) -> None:
        response = self._response([b"abc", b"", b"def"], content_length=6)
        progress: list[int] = []

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
                progress.append,
            )

        self.assertTrue(success)
        self.assertEqual(self.destination.read_bytes(), b"abcdef")
        self.assertEqual(progress, [50, 100])
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_underreported_content_length_bounds_progress_and_preserves_destination(self) -> None:
        self.destination.write_bytes(b"existing release")
        consumed: list[str] = []

        def overlong_chunks() -> Iterator[bytes]:
            consumed.append("overrun")
            yield b"too long"
            consumed.append("unnecessary tail")
            yield b"tail"

        response = self._response(overlong_chunks(), content_length=3)
        progress: list[int] = []

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
                progress.append,
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        self.assertEqual(consumed, ["overrun"])
        self.assertEqual(progress, [])
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_zero_content_length_preserves_existing_destination(self) -> None:
        self.destination.write_bytes(b"existing release")
        response = self._response([], content_length=0)

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_empty_response_without_content_length_preserves_destination(self) -> None:
        self.destination.write_bytes(b"existing release")
        response = self._response([], content_length=None)

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_missing_content_length_allows_nonempty_download(self) -> None:
        response = self._response([b"complete"], content_length=None)
        progress: list[int] = []

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
                progress.append,
            )

        self.assertTrue(success)
        self.assertEqual(self.destination.read_bytes(), b"complete")
        self.assertEqual(progress, [])
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_content_length_allows_http_optional_whitespace(self) -> None:
        response = self._response([b"complete"], content_length="\t8 ")

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertTrue(success)
        self.assertEqual(self.destination.read_bytes(), b"complete")
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_malformed_content_length_preserves_destination_and_closes_response(self) -> None:
        self.destination.write_bytes(b"existing release")

        for content_length in ("invalid", "-8", "+8", "1_0", ""):
            with self.subTest(content_length=content_length):
                response = self._response([b"complete"], content_length=content_length)
                with patch("src.update_checker.requests.get", return_value=response):
                    success = UpdateChecker.download_update(
                        "https://example.test/update.bin",
                        str(self.destination),
                    )

                self.assertFalse(success)
                self.assertEqual(self.destination.read_bytes(), b"existing release")
                response.close.assert_called_once_with()
                self.assert_no_partial_downloads()

    def test_callback_failure_preserves_destination_and_closes_response(self) -> None:
        self.destination.write_bytes(b"existing release")
        response = self._response([b"complete"], content_length=8)

        def fail_callback(_progress: int) -> None:
            raise RuntimeError("callback failed")

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
                fail_callback,
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_missing_destination_parent_closes_response(self) -> None:
        response = self._response([b"complete"], content_length=8)
        destination = self.temp_dir / "missing" / "update.bin"

        with patch("src.update_checker.requests.get", return_value=response):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(destination),
            )

        self.assertFalse(success)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.parent.exists())
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    def test_replace_failure_preserves_existing_destination_and_cleans_up(self) -> None:
        self.destination.write_bytes(b"existing release")
        response = self._response([b"complete"], content_length=8)

        with (
            patch("src.update_checker.requests.get", return_value=response),
            patch("src.update_checker.os.replace", side_effect=OSError("replace failed")),
        ):
            success = UpdateChecker.download_update(
                "https://example.test/update.bin",
                str(self.destination),
            )

        self.assertFalse(success)
        self.assertEqual(self.destination.read_bytes(), b"existing release")
        response.close.assert_called_once_with()
        self.assert_no_partial_downloads()

    @staticmethod
    def _response(chunks: Iterable[bytes], *, content_length: int | str | None) -> MagicMock:
        response = MagicMock()
        response.headers = {} if content_length is None else {"content-length": str(content_length)}
        response.iter_content.return_value = chunks
        return response

    @staticmethod
    def _failing_chunks() -> Iterator[bytes]:
        yield b"partial"
        raise requests.ConnectionError("connection dropped")

    def assert_no_partial_downloads(self) -> None:
        self.assertEqual(list(self.temp_dir.glob(f".{self.destination.name}.*.part")), [])


if __name__ == "__main__":
    unittest.main()
