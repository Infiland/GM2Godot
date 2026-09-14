"""Setup failure paths preserve credentials, installations and filesystem boundaries."""
from __future__ import annotations

import hashlib
import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.deep.credentials import credential_environment, save_credential
from src.deep.install import extract_package, platform_key
from src.deep.opencode import install_opencode
from src.deep.settings import DeepSettings


class CredentialBoundaryTests(unittest.TestCase):
    def test_environment_auth_wins_without_opening_keyring(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}), patch("src.deep.credentials._backend") as backend:
            self.assertEqual(credential_environment("openai"), {"OPENAI_API_KEY": "test-only"})
            backend.assert_not_called()

    def test_keyring_auth_is_only_exported_for_its_provider(self) -> None:
        backend = MagicMock()
        backend.get_password.return_value = "test-only"
        with patch.dict("os.environ", {}, clear=True), patch("src.deep.credentials._backend", return_value=backend):
            self.assertEqual(credential_environment("anthropic"), {"ANTHROPIC_API_KEY": "test-only"})
            backend.get_password.assert_called_once_with("GM2Godot Deep", "anthropic")
            self.assertEqual(credential_environment("unknown"), {})

    def test_unavailable_or_empty_keyring_does_not_break_existing_agent_login(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("src.deep.credentials._backend", side_effect=RuntimeError("No backend")):
                self.assertEqual(credential_environment("openai"), {})
            backend = MagicMock()
            backend.get_password.return_value = None
            with patch("src.deep.credentials._backend", return_value=backend):
                self.assertEqual(credential_environment("openai"), {})

    def test_save_and_remove_only_the_selected_provider_secret(self) -> None:
        backend = MagicMock()
        with patch("src.deep.credentials._backend", return_value=backend):
            save_credential("openai", "test-only")
            backend.set_password.assert_called_once_with("GM2Godot Deep", "openai", "test-only")
            backend.get_password.return_value = "test-only"
            save_credential("openai", "")
            backend.delete_password.assert_called_once_with("GM2Godot Deep", "openai")
            backend.get_password.return_value = None
            save_credential("openai", "")
            self.assertEqual(backend.delete_password.call_count, 1)
            with self.assertRaises(ValueError):
                save_credential("unrecognized", "test-only")


class DependencyInstallationSafetyTests(unittest.TestCase):
    def test_supported_platforms_and_unknown_platform(self) -> None:
        for system, machine, expected in (("Darwin", "arm64", "darwin-arm64"), ("Windows", "AMD64", "win-x64"), ("Linux", "x86_64", "linux-x64")):
            with self.subTest(system=system), patch("platform.system", return_value=system), patch("platform.machine", return_value=machine):
                self.assertEqual(platform_key(), expected)
        with patch("platform.system", return_value="Linux"), patch("platform.machine", return_value="arm64"):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                platform_key()

    def test_tar_regular_files_extract_but_links_cannot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.tar"
            with tarfile.open(archive, "w") as bundle:
                folder = tarfile.TarInfo("bin")
                folder.type = tarfile.DIRTYPE
                bundle.addfile(folder)
                item = tarfile.TarInfo("bin/runtime")
                item.size = 4
                item.mode = 0o755
                bundle.addfile(item, io.BytesIO(b"test"))
            extract_package(archive, root / "out")
            self.assertEqual((root / "out/bin/runtime").read_bytes(), b"test")
            with tarfile.open(archive, "w") as bundle:
                link = tarfile.TarInfo("escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "../outside"
                bundle.addfile(link)
            with self.assertRaisesRegex(ValueError, "links and special"):
                extract_package(archive, root / "out")
            self.assertFalse((root / "outside").exists())

    def test_existing_opencode_is_reused_without_downloading(self) -> None:
        with patch("src.deep.opencode.opencode_path", return_value="/existing/opencode"), patch("src.deep.opencode.download_verified_transport") as download:
            self.assertEqual(install_opencode(), "/existing/opencode")
            download.assert_not_called()

    def test_managed_opencode_rejects_bad_bytes_before_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("opencode.exe" if os.name == "nt" else "opencode", b"synthetic executable")
            payload = archive.getvalue()
            digest = hashlib.sha256(payload).hexdigest()
            def download(_url: str, destination: Path) -> None:
                destination.write_bytes(payload)
            with patch("src.deep.opencode.opencode_path", return_value=None), patch("src.deep.opencode.platform_key", return_value="test-platform"), patch("src.deep.opencode.download_verified_transport", side_effect=download), patch("src.deep.opencode._ASSETS", {"test-platform": ("test.zip", "0" * 64)}):
                with self.assertRaisesRegex(ValueError, "checksum"):
                    install_opencode(root)
                self.assertFalse((root / "opencode").exists())
            with patch("src.deep.opencode.opencode_path", return_value=None), patch("src.deep.opencode.platform_key", return_value="test-platform"), patch("src.deep.opencode.download_verified_transport", side_effect=download), patch("src.deep.opencode._ASSETS", {"test-platform": ("test.zip", digest)}):
                installed = install_opencode(root)
                self.assertEqual(Path(installed).read_bytes(), b"synthetic executable")

    def test_invalid_settings_cannot_dispatch_or_enable_paid_helpers(self) -> None:
        for changes in ({"analysisWorkers": 0}, {"freeProviderConcurrency": 33}, {"runtime": "unknown"}, {"model": " "}, {"budgets": {"maxTokens": -1}}, {"roleOverrides": {"reviewer": {"runtime": "pi", "provider": "openai"}}}):
            with self.subTest(changes=changes):
                settings = DeepSettings()
                for key, value in changes.items():
                    setattr(settings, key, value)
                with self.assertRaises(ValueError):
                    settings.validate()
