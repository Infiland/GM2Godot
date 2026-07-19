# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

from scripts import verify_macos_bundle_metadata as verifier
from src.version import VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = PROJECT_ROOT / "scripts" / "verify_macos_bundle_metadata.py"
SYNTHETIC_POLICY = {
    "CFBundleIdentifier": "land.infi.gm2godot",
    "CFBundleShortVersionString": "1.2.3",
    "CFBundleVersion": "1.2.3",
}


def _policy_source(expression: str) -> str:
    return (
        "from pathlib import Path\n\n"
        "def load_bundle_metadata(source_root: Path) -> dict[str, str]:\n"
        "    if not source_root.is_absolute():\n"
        "        raise ValueError('source root must be absolute')\n"
        f"    return {expression}\n"
    )


def _write_policy(source_root: Path, expression: str | None = None) -> None:
    helper = source_root.joinpath(*verifier.POLICY_COMPONENTS)
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(
        _policy_source(repr(SYNTHETIC_POLICY) if expression is None else expression),
        encoding="utf-8",
    )


def _plist_bytes(
    values: Mapping[str, object] | None = None,
    *,
    binary: bool = False,
) -> bytes:
    selected = dict(SYNTHETIC_POLICY if values is None else values)
    selected.setdefault("CFBundleExecutable", "GM2Godot")
    return plistlib.dumps(
        selected,
        fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML,
        sort_keys=True,
    )


def _write_app(root: Path, content: bytes) -> Path:
    app = root / "GM2Godot.app"
    (app / "Contents").mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Info.plist").write_bytes(content)
    return app


def _write_zip(path: Path, content: bytes) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(verifier.ZIP_PLIST_PATH, content)
        archive.writestr("unrelated/readme.txt", b"GM2Godot\n")


def _remove_fake_app(mountpoint: Path) -> None:
    plist_path = mountpoint.joinpath(*verifier.APP_PLIST_COMPONENTS)
    plist_path.unlink()
    plist_path.parent.rmdir()
    plist_path.parent.parent.rmdir()


class _TemporaryRootFactory:
    def __init__(self, parent: Path) -> None:
        self.parent = parent
        self.paths: list[Path] = []

    def __call__(self, *, prefix: str) -> str:
        path = self.parent / f"{prefix}{len(self.paths)}"
        path.mkdir(mode=0o700)
        self.paths.append(path)
        return os.fspath(path)


class _FakeHdiutil:
    def __init__(
        self,
        plist_content: bytes,
        *,
        attach_returncode: int = 0,
        attach_receipt: str = "valid",
        attach_error: bool = False,
        mount_on_attach: bool = True,
        info_returncode: int = 0,
        info_receipt: str = "valid",
        detach_returncode: int = 0,
        unmount_on_detach: bool = True,
    ) -> None:
        self.plist_content = plist_content
        self.attach_returncode = attach_returncode
        self.attach_receipt = attach_receipt
        self.attach_error = attach_error
        self.mount_on_attach = mount_on_attach
        self.info_returncode = info_returncode
        self.info_receipt = info_receipt
        self.detach_returncode = detach_returncode
        self.unmount_on_detach = unmount_on_detach
        self.device = "/dev/disk42s1"
        self.mountpoint: Path | None = None
        self.mounted = False
        self.events: list[str] = []

    def _attach_receipt_bytes(self) -> bytes:
        if self.attach_receipt == "invalid":
            return b"not a plist"
        entities: list[dict[str, str]] = []
        if self.attach_receipt == "valid" and self.mountpoint is not None:
            entities.append(
                {
                    "dev-entry": self.device,
                    "mount-point": os.fspath(self.mountpoint),
                }
            )
        return plistlib.dumps({"system-entities": entities})

    def _info_receipt_bytes(self) -> bytes:
        if self.info_receipt == "invalid":
            return b"not a plist"
        entities: list[dict[str, str]] = []
        if self.mounted and self.mountpoint is not None:
            entities.append(
                {
                    "dev-entry": self.device,
                    "mount-point": os.fspath(self.mountpoint),
                }
            )
        return plistlib.dumps({"images": [{"system-entities": entities}]})

    def __call__(self, command: object, label: str) -> verifier._CommandResult:
        parts = tuple(str(part) for part in command)  # type: ignore[arg-type]
        self.events.append(label)
        if label == "attach":
            self.mountpoint = Path(parts[parts.index("-mountpoint") + 1])
            if self.mount_on_attach:
                _write_app(self.mountpoint, self.plist_content)
                self.mounted = True
            if self.attach_error:
                raise verifier.MetadataVerificationError("attach command timed out")
            return verifier._CommandResult(
                self.attach_returncode,
                self._attach_receipt_bytes(),
                b"attach failed detail" if self.attach_returncode else b"",
            )
        if label == "info":
            return verifier._CommandResult(
                self.info_returncode,
                self._info_receipt_bytes(),
                b"info failed detail" if self.info_returncode else b"",
            )
        if label == "detach":
            if parts != (verifier.HDIUTIL_PATH, "detach", self.device):
                raise AssertionError(f"unexpected detach command: {parts!r}")
            if self.detach_returncode == 0 and self.unmount_on_detach:
                if self.mounted and self.mountpoint is not None:
                    _remove_fake_app(self.mountpoint)
                self.mounted = False
            return verifier._CommandResult(
                self.detach_returncode,
                b"",
                b"detach failed detail" if self.detach_returncode else b"",
            )
        raise AssertionError(f"unexpected hdiutil label: {label}")


class BundleMetadataFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name).resolve()
        self.source_root = self.root / "source"
        self.source_root.mkdir()
        _write_policy(self.source_root)
        self.plist_content = _plist_bytes()
        self.app_path = _write_app(self.root / "direct", self.plist_content)
        self.zip_path = self.root / "GM2Godot-macos.zip"
        _write_zip(self.zip_path, self.plist_content)
        self.dmg_path = self.root / "GM2Godot-macos.dmg"
        self.dmg_path.write_bytes(b"synthetic dmg")
        self.root_factory = _TemporaryRootFactory(self.root)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def inspect_dmg_with(self, fake: _FakeHdiutil) -> verifier.BundleMetadata:
        with (
            mock.patch.object(verifier, "_run_hdiutil_command", side_effect=fake),
            mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=self.root_factory,
            ),
        ):
            return verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)

    def verify_with(self, fake: _FakeHdiutil) -> verifier.BundleMetadata:
        with (
            mock.patch.object(verifier, "_run_hdiutil_command", side_effect=fake),
            mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=self.root_factory,
            ),
        ):
            return verifier.verify_artifacts(
                self.source_root,
                self.app_path,
                self.zip_path,
                self.dmg_path,
            )


class MacOSBundleMetadataHappyPathTests(BundleMetadataFixture):
    def test_xml_artifacts_match_and_cleanup_after_confirmed_detach(self) -> None:
        fake = _FakeHdiutil(self.plist_content)
        metadata = self.verify_with(fake)

        self.assertEqual(metadata.identifier, SYNTHETIC_POLICY["CFBundleIdentifier"])
        self.assertEqual(fake.events, ["attach", "detach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())

    def test_binary_plist_is_supported_in_all_artifacts(self) -> None:
        binary = _plist_bytes(binary=True)
        (self.app_path / "Contents" / "Info.plist").write_bytes(binary)
        _write_zip(self.zip_path, binary)

        metadata = self.verify_with(_FakeHdiutil(binary))

        self.assertEqual(metadata.plist_sha256, verifier.hashlib.sha256(binary).hexdigest())

    def test_byte_parity_rejects_semantically_equal_plists(self) -> None:
        changed = dict(SYNTHETIC_POLICY)
        changed["ExtraField"] = "different bytes"
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "Info.plist bytes are not identical",
        ):
            self.verify_with(_FakeHdiutil(_plist_bytes(changed)))


class MacOSBundleMetadataStrictValueTests(BundleMetadataFixture):
    def test_plist_missing_wrong_and_non_string_values_are_rejected(self) -> None:
        cases: dict[str, dict[str, object]] = {}
        for key in verifier.POLICY_KEYS:
            missing: dict[str, object] = dict(SYNTHETIC_POLICY)
            del missing[key]
            cases[f"missing-{key}"] = missing
            wrong: dict[str, object] = dict(SYNTHETIC_POLICY)
            wrong[key] = "wrong"
            cases[f"wrong-{key}"] = wrong
            wrong_type: dict[str, object] = dict(SYNTHETIC_POLICY)
            wrong_type[key] = 123
            cases[f"type-{key}"] = wrong_type

        for name, values in cases.items():
            with self.subTest(name=name):
                app = _write_app(self.root / name, _plist_bytes(values))
                with self.assertRaises(verifier.MetadataVerificationError):
                    verifier.inspect_app(app, SYNTHETIC_POLICY)

    def test_malformed_plist_is_rejected_cleanly(self) -> None:
        app = _write_app(self.root / "malformed", b"not a property list")

        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "unable to parse direct app Info.plist",
        ):
            verifier.inspect_app(app, SYNTHETIC_POLICY)

    def test_policy_contract_rejects_missing_extra_type_placeholder_and_mismatch(self) -> None:
        cases = {
            "missing": "{'CFBundleIdentifier': 'land.infi.gm2godot'}",
            "extra": repr({**SYNTHETIC_POLICY, "extra": "value"}),
            "type": repr({**SYNTHETIC_POLICY, "CFBundleVersion": 123}),
            "placeholder-id": repr({**SYNTHETIC_POLICY, "CFBundleIdentifier": "com.example.gm2godot"}),
            "placeholder-version": repr(
                {
                    **SYNTHETIC_POLICY,
                    "CFBundleShortVersionString": "0.0.0",
                    "CFBundleVersion": "0.0.0",
                }
            ),
            "mismatch": repr({**SYNTHETIC_POLICY, "CFBundleVersion": "1.2.4"}),
        }
        for name, expression in cases.items():
            with self.subTest(name=name):
                root = self.root / f"policy-{name}"
                root.mkdir()
                _write_policy(root, expression)
                with self.assertRaises(verifier.MetadataVerificationError):
                    verifier._load_policy(root)

    def test_repository_policy_is_tied_to_current_source_version(self) -> None:
        self.assertEqual(
            verifier._load_policy(PROJECT_ROOT),
            {
                "CFBundleIdentifier": "land.infi.gm2godot",
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": VERSION,
            },
        )

    def test_exact_policy_path_load_isolated_from_pythonpath_shadow(self) -> None:
        shadow = self.root / "shadow"
        shadow.mkdir()
        sentinel = self.root / "shadow-imported"
        (shadow / "bundle_metadata.py").write_text(
            f"from pathlib import Path\nPath({os.fspath(sentinel)!r}).touch()\n",
            encoding="utf-8",
        )
        code = (
            "import pathlib,runpy,sys;"
            "m=runpy.run_path(sys.argv[1]);"
            "print(m['_load_policy'](pathlib.Path(sys.argv[2]))['CFBundleVersion'])"
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.fspath(shadow)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                code,
                os.fspath(VERIFIER_PATH),
                os.fspath(self.source_root),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1.2.3")
        self.assertFalse(sentinel.exists())


class MacOSBundleMetadataZipTests(BundleMetadataFixture):
    def _archive_with(self, members: list[tuple[str | zipfile.ZipInfo, bytes]]) -> Path:
        path = self.root / f"case-{len(list(self.root.glob('case-*.zip')))}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in members:
                archive.writestr(name, content)
        return path

    def test_duplicate_and_target_symlink_are_rejected(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicate = self._archive_with(
                [
                    (verifier.ZIP_PLIST_PATH, self.plist_content),
                    (verifier.ZIP_PLIST_PATH, self.plist_content),
                ]
            )
        with self.assertRaises(verifier.MetadataVerificationError):
            verifier.inspect_zip(duplicate, SYNTHETIC_POLICY)

        target = zipfile.ZipInfo(verifier.ZIP_PLIST_PATH)
        target.create_system = 3
        target.external_attr = (stat.S_IFLNK | 0o777) << 16
        symlink = self._archive_with([(target, b"outside")])
        with self.assertRaisesRegex(verifier.MetadataVerificationError, "regular file"):
            verifier.inspect_zip(symlink, SYNTHETIC_POLICY)

    def test_explicit_ancestor_files_symlinks_and_aliases_are_rejected(self) -> None:
        app_link = zipfile.ZipInfo("GM2Godot.app/")
        app_link.create_system = 3
        app_link.external_attr = (stat.S_IFLNK | 0o777) << 16
        contents_link = zipfile.ZipInfo("GM2Godot.app/Contents")
        contents_link.create_system = 3
        contents_link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases: list[tuple[str | zipfile.ZipInfo, bytes]] = [
            ("GM2Godot.app", b"file"),
            (app_link, b"elsewhere"),
            ("GM2Godot.app/Contents", b"file"),
            (contents_link, b"elsewhere"),
            ("gm2godot.app/unrelated.txt", b"alias"),
            ("GM2Godot.app/contents/unrelated.txt", b"alias"),
            ("GM2Godot.app/Contentſ/unrelated.txt", b"unicode alias"),
            ("GM2Godot.app/Contents/info.plist", self.plist_content),
            ("GM2Godot.app/Contents/Info.plist/child", b"impossible child"),
            ("./GM2Godot.app/Contents/Info.plist", b"dot alias"),
            ("prefix/../GM2Godot.app/Contents/Info.plist", b"parent alias"),
            ("/GM2Godot.app/Contents/Info.plist", b"absolute alias"),
            ("C:/GM2Godot.app/Contents/Info.plist", b"drive alias"),
        ]
        for index, extra in enumerate(cases):
            with self.subTest(index=index):
                archive = self._archive_with([(verifier.ZIP_PLIST_PATH, self.plist_content), extra])
                with self.assertRaises(verifier.MetadataVerificationError):
                    verifier.inspect_zip(archive, SYNTHETIC_POLICY)

    def test_exact_directory_ancestors_are_allowed_and_unrelated_members_are_ignored(self) -> None:
        unrelated_link = zipfile.ZipInfo("unrelated/link")
        unrelated_link.create_system = 3
        unrelated_link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self._archive_with(
            [
                ("GM2Godot.app/", b""),
                ("GM2Godot.app/Contents/", b""),
                (verifier.ZIP_PLIST_PATH, self.plist_content),
                ("unrelated/readme.txt", b"ignored"),
                (unrelated_link, b"../../outside"),
            ]
        )

        metadata = verifier.inspect_zip(archive, SYNTHETIC_POLICY)

        self.assertEqual(metadata.short_version, "1.2.3")


class MacOSBundleMetadataDmgTests(BundleMetadataFixture):
    def test_nonzero_attach_preserves_status_and_stderr_then_cleans_when_unmounted(self) -> None:
        fake = _FakeHdiutil(
            self.plist_content,
            attach_returncode=7,
            attach_receipt="missing",
            mount_on_attach=False,
        )
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "status 7: attach failed detail",
        ):
            self.inspect_dmg_with(fake)
        self.assertEqual(fake.events, ["attach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())

    def test_nonzero_attach_with_exact_device_detaches_before_reporting_status(self) -> None:
        fake = _FakeHdiutil(
            self.plist_content,
            attach_returncode=7,
            attach_receipt="valid",
        )

        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "status 7: attach failed detail",
        ):
            self.inspect_dmg_with(fake)

        self.assertEqual(fake.events, ["attach", "detach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())

    def test_invalid_receipt_recovers_device_and_detaches_before_error(self) -> None:
        fake = _FakeHdiutil(self.plist_content, attach_receipt="invalid")
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "parse hdiutil attach receipt",
        ):
            self.inspect_dmg_with(fake)
        self.assertEqual(fake.events, ["attach", "info", "detach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())

    def test_attach_command_error_still_recovers_partial_mount_and_detaches(self) -> None:
        fake = _FakeHdiutil(self.plist_content, attach_error=True)
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "attach command timed out",
        ):
            self.inspect_dmg_with(fake)
        self.assertEqual(fake.events, ["attach", "info", "detach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())

    def test_unknown_mount_after_failed_recovery_retains_root(self) -> None:
        fake = _FakeHdiutil(
            self.plist_content,
            attach_receipt="invalid",
            info_receipt="invalid",
        )
        with self.assertRaisesRegex(verifier.MetadataVerificationError, "retaining"):
            self.inspect_dmg_with(fake)
        self.assertEqual(fake.events, ["attach", "info"])
        self.assertTrue(self.root_factory.paths[0].exists())

    def test_detach_failure_and_confirmation_failure_retain_root(self) -> None:
        detach_failure = _FakeHdiutil(self.plist_content, detach_returncode=9)
        with self.assertRaisesRegex(verifier.MetadataVerificationError, "status 9"):
            self.inspect_dmg_with(detach_failure)
        self.assertTrue(self.root_factory.paths[0].exists())

        confirmation_failure = _FakeHdiutil(
            self.plist_content,
            info_receipt="invalid",
        )
        with self.assertRaisesRegex(verifier.MetadataVerificationError, "retaining"):
            self.inspect_dmg_with(confirmation_failure)
        self.assertTrue(self.root_factory.paths[1].exists())

    def test_temporary_setup_and_mounted_plist_read_errors_are_clean(self) -> None:
        with (
            mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=OSError("temp unavailable"),
            ),
            self.assertRaisesRegex(
                verifier.MetadataVerificationError,
                "temp unavailable",
            ),
        ):
            verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)

        setup_root = self.root / "setup-failure"
        setup_root.mkdir(mode=0o700)
        with (
            mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                return_value=os.fspath(setup_root),
            ),
            mock.patch.object(
                verifier.Path,
                "mkdir",
                side_effect=OSError("mountpoint unavailable"),
            ),
            self.assertRaisesRegex(
                verifier.MetadataVerificationError,
                "mountpoint unavailable",
            ),
        ):
            verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
        self.assertFalse(setup_root.exists())

        fake = _FakeHdiutil(self.plist_content)
        with (
            mock.patch.object(verifier, "_run_hdiutil_command", side_effect=fake),
            mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=self.root_factory,
            ),
            mock.patch.object(verifier.os, "read", side_effect=OSError("read failed")),
            self.assertRaisesRegex(verifier.MetadataVerificationError, "read failed"),
        ):
            verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
        self.assertEqual(fake.events, ["attach", "detach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())


class MacOSBundleMetadataCliTests(BundleMetadataFixture):
    def test_main_reports_clean_validation_and_output_errors(self) -> None:
        for error in (
            verifier.MetadataVerificationError("bad metadata"),
            OSError("output unavailable"),
        ):
            with self.subTest(error=type(error).__name__):
                stderr = StringIO()
                with (
                    mock.patch.object(verifier, "verify_artifacts", side_effect=error),
                    redirect_stderr(stderr),
                ):
                    status = verifier.main(
                        [
                            "--source-root",
                            os.fspath(self.source_root),
                            "--app",
                            os.fspath(self.app_path),
                            "--zip",
                            os.fspath(self.zip_path),
                            "--dmg",
                            os.fspath(self.dmg_path),
                        ]
                    )
                self.assertEqual(status, 1)
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_main_prints_stable_success(self) -> None:
        metadata = verifier.BundleMetadata("land.infi.gm2godot", "1.2.3", "1.2.3", "a" * 64)
        stdout = StringIO()
        with (
            mock.patch.object(verifier, "verify_artifacts", return_value=metadata),
            redirect_stdout(stdout),
        ):
            status = verifier.main(
                [
                    "--source-root",
                    os.fspath(self.source_root),
                    "--app",
                    os.fspath(self.app_path),
                    "--zip",
                    os.fspath(self.zip_path),
                    "--dmg",
                    os.fspath(self.dmg_path),
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn("identifier=land.infi.gm2godot", stdout.getvalue())
        self.assertIn("plist_sha256=" + "a" * 64, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
