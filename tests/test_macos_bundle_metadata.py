# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
import errno
from io import StringIO
import os
from pathlib import Path
import plistlib
import shutil
import stat
import struct
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
    "LSMinimumSystemVersion": "15.0",
}


def _packed_version(major: int, minor: int, patch: int = 0) -> int:
    return (major << 16) | (minor << 8) | patch


def _macho_bytes(
    architecture: str = "arm64",
    *,
    minimum: tuple[int, int, int] = (15, 0, 0),
    filetype: int = 2,
) -> bytes:
    cpu_type = {"arm64": 0x0100000C, "x86_64": 0x01000007}[architecture]
    packed_minimum = _packed_version(*minimum)
    command = struct.pack(
        "<IIIIII",
        0x32,
        24,
        1,
        packed_minimum,
        packed_minimum,
        0,
    )
    header = struct.pack(
        "<IiiIIIII",
        0xFEEDFACF,
        cpu_type,
        0 if architecture == "arm64" else 3,
        filetype,
        1,
        len(command),
        0,
        0,
    )
    return header + command


DEFAULT_MACHO_FILES = {"Contents/MacOS/GM2Godot": _macho_bytes()}


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


def _write_app(
    root: Path,
    content: bytes,
    macho_files: Mapping[str, bytes] | None = None,
    symlinks: Mapping[str, str] | None = None,
) -> Path:
    app = root / "GM2Godot.app"
    (app / "Contents").mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Info.plist").write_bytes(content)
    for relative_path, macho_content in (DEFAULT_MACHO_FILES if macho_files is None else macho_files).items():
        destination = app / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(macho_content)
        destination.chmod(0o755 if relative_path == "Contents/MacOS/GM2Godot" else 0o644)
    selected_symlinks: Mapping[str, str] = {} if symlinks is None else symlinks
    for relative_path, target in selected_symlinks.items():
        destination = app / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(target)
    return app


def _write_zip(
    path: Path,
    content: bytes,
    macho_files: Mapping[str, bytes] | None = None,
    symlinks: Mapping[str, str] | None = None,
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        plist_member = zipfile.ZipInfo("GM2Godot.app/Contents/Info.plist")
        plist_member.create_system = 3
        plist_member.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(plist_member, content)
        for relative_path, macho_content in (DEFAULT_MACHO_FILES if macho_files is None else macho_files).items():
            member = zipfile.ZipInfo(f"GM2Godot.app/{relative_path}")
            member.create_system = 3
            member.external_attr = (
                stat.S_IFREG | (0o755 if relative_path == "Contents/MacOS/GM2Godot" else 0o644)
            ) << 16
            archive.writestr(member, macho_content)
        selected_symlinks: Mapping[str, str] = {} if symlinks is None else symlinks
        for relative_path, target in selected_symlinks.items():
            member = zipfile.ZipInfo(f"GM2Godot.app/{relative_path}")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, target.encode("utf-8"))
        archive.writestr("unrelated/readme.txt", b"GM2Godot\n")


def _remove_fake_app(mountpoint: Path) -> None:
    shutil.rmtree(mountpoint / verifier.APP_PLIST_COMPONENTS[0])


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
        macho_files: Mapping[str, bytes] | None = None,
        symlinks: Mapping[str, str] | None = None,
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
        self.macho_files = macho_files
        self.symlinks = symlinks
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

    def __call__(self, command: Sequence[str], label: str) -> verifier._CommandResult:
        parts = tuple(command)
        self.events.append(label)
        if label == "attach":
            if len(parts) != 8 or parts[:6] != (
                "/usr/bin/hdiutil",
                "attach",
                "-readonly",
                "-nobrowse",
                "-plist",
                "-mountpoint",
            ):
                raise AssertionError(f"unexpected read-only attach recipe: {parts!r}")
            copied = Path(parts[-1])
            if copied.name != "source.dmg" or stat.S_IMODE(copied.stat().st_mode) != 0o600:
                raise AssertionError("attach must receive the checked private 0600 copy")
            self.mountpoint = Path(parts[parts.index("-mountpoint") + 1])
            if self.mount_on_attach:
                _write_app(
                    self.mountpoint,
                    self.plist_content,
                    self.macho_files,
                    self.symlinks,
                )
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
            if parts != ("/usr/bin/hdiutil", "detach", self.device):
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

    def inspect_dmg_inventory_with(
        self,
        fake: _FakeHdiutil,
    ) -> tuple[verifier.BundleMetadata, verifier.BundleInventory | None]:
        with (
            mock.patch.object(verifier, "_run_hdiutil_command", side_effect=fake),
            mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=self.root_factory,
            ),
        ):
            return verifier._inspect_dmg_contents(
                self.dmg_path,
                SYNTHETIC_POLICY,
                "arm64",
            )

    def verify_with(
        self,
        fake: _FakeHdiutil,
        expected_architecture: str = "arm64",
    ) -> verifier.VerificationReceipt:
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
                expected_architecture,
            )


class MacOSBundleMetadataHappyPathTests(BundleMetadataFixture):
    def test_public_zip_and_extracted_app_inspections_retain_native_checks(self) -> None:
        expected = verifier.load_source_policy(self.source_root)
        archive = verifier.inspect_zip_bundle(self.zip_path, expected, "arm64")
        physical = verifier.inspect_app_bundle(self.app_path, expected, "arm64")
        self.assertEqual(archive, physical)
        self.assertEqual(archive.inventory.mach_o_files[0].relative_path, "Contents/MacOS/GM2Godot")
        self.assertEqual(archive.inventory.mach_o_files[0].minimum_macos, (15, 0, 0))
        for inspect, path in ((verifier.inspect_zip_bundle, self.zip_path), (verifier.inspect_app_bundle, self.app_path)):
            with self.subTest(path=path):
                with self.assertRaises(verifier.MetadataVerificationError):
                    inspect(path, expected, "x86_64")
        over_minimum = {"Contents/MacOS/GM2Godot": _macho_bytes(minimum=(16, 0, 0))}
        _write_zip(self.zip_path, self.plist_content, over_minimum)
        _write_app(self.app_path.parent, self.plist_content, over_minimum)
        for inspect, path in ((verifier.inspect_zip_bundle, self.zip_path), (verifier.inspect_app_bundle, self.app_path)):
            with self.subTest(over_minimum=path):
                with self.assertRaisesRegex(verifier.MetadataVerificationError, "below native Mach-O requirement 16.0"):
                    inspect(path, expected, "arm64")

    def test_executable_mode_drift_between_app_zip_and_dmg_is_rejected(self) -> None:
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            plist_member = zipfile.ZipInfo("GM2Godot.app/Contents/Info.plist")
            plist_member.create_system = 3
            plist_member.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(plist_member, self.plist_content)
            member = zipfile.ZipInfo("GM2Godot.app/Contents/MacOS/GM2Godot")
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o744) << 16
            archive.writestr(member, DEFAULT_MACHO_FILES["Contents/MacOS/GM2Godot"])
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "Mach-O inventories are not identical",
        ):
            self.verify_with(_FakeHdiutil(self.plist_content))

    def test_xml_artifacts_match_and_cleanup_after_confirmed_detach(self) -> None:
        fake = _FakeHdiutil(self.plist_content)
        receipt = self.verify_with(fake)

        self.assertEqual(
            receipt.metadata.identifier,
            SYNTHETIC_POLICY["CFBundleIdentifier"],
        )
        self.assertEqual(receipt.architecture, "arm64")
        self.assertEqual(receipt.macho_count, 1)
        self.assertEqual(receipt.maximum_macos, (15, 0, 0))
        self.assertEqual(fake.events, ["attach", "detach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())

    def test_dmg_path_substitution_after_copy_cannot_change_attached_bytes(self) -> None:
        fake = _FakeHdiutil(self.plist_content)
        original = self.dmg_path.read_bytes()

        def substitute_then_run(command: Sequence[str], label: str) -> verifier._CommandResult:
            parts = tuple(command)
            if label == "attach":
                private_path = Path(parts[-1])
                self.assertNotEqual(private_path, self.dmg_path)
                self.assertEqual(private_path.read_bytes(), original)
                replacement = self.dmg_path.with_suffix(".replacement")
                replacement.write_bytes(b"attacker replacement")
                replacement.replace(self.dmg_path)
                self.assertEqual(private_path.read_bytes(), original)
            return fake(command, label)

        with (
            mock.patch.object(
                verifier,
                "_run_hdiutil_command",
                side_effect=substitute_then_run,
            ),
            mock.patch.object(verifier.tempfile, "mkdtemp", side_effect=self.root_factory),
        ):
            metadata = verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
        self.assertEqual(metadata.identifier, SYNTHETIC_POLICY["CFBundleIdentifier"])
        self.assertFalse(self.root_factory.paths[0].exists())

    def test_binary_plist_is_supported_in_all_artifacts(self) -> None:
        binary = _plist_bytes(binary=True)
        (self.app_path / "Contents" / "Info.plist").write_bytes(binary)
        _write_zip(self.zip_path, binary)

        receipt = self.verify_with(_FakeHdiutil(binary))

        self.assertEqual(
            receipt.metadata.plist_sha256,
            verifier.hashlib.sha256(binary).hexdigest(),
        )

    def test_byte_parity_rejects_semantically_equal_plists(self) -> None:
        changed = dict(SYNTHETIC_POLICY)
        changed["ExtraField"] = "different bytes"
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "Info.plist bytes are not identical",
        ):
            self.verify_with(_FakeHdiutil(_plist_bytes(changed)))

    def test_x86_64_artifacts_use_the_same_parameterized_verifier(self) -> None:
        macho_files = {
            "Contents/MacOS/GM2Godot": _macho_bytes("x86_64"),
        }
        _write_app(self.app_path.parent, self.plist_content, macho_files)
        _write_zip(self.zip_path, self.plist_content, macho_files)

        receipt = self.verify_with(
            _FakeHdiutil(self.plist_content, macho_files=macho_files),
            "x86_64",
        )

        self.assertEqual(receipt.architecture, "x86_64")
        self.assertEqual(receipt.macho_count, 1)

    def test_matching_bundle_internal_symlinks_are_preserved(self) -> None:
        macho_files = {
            "Contents/MacOS/GM2Godot": _macho_bytes(minimum=(14, 0, 0)),
            "Contents/Frameworks/QtCore.framework/Versions/A/QtCore": (_macho_bytes(filetype=6)),
        }
        symlinks = {
            "Contents/Frameworks/QtCore.framework/Versions/Current": "A",
            "Contents/Frameworks/QtCore.framework/QtCore": ("Versions/Current/QtCore"),
        }
        _write_app(self.app_path.parent, self.plist_content, macho_files, symlinks)
        _write_zip(self.zip_path, self.plist_content, macho_files, symlinks)

        receipt = self.verify_with(
            _FakeHdiutil(
                self.plist_content,
                macho_files=macho_files,
                symlinks=symlinks,
            )
        )

        self.assertEqual(receipt.macho_count, 2)
        self.assertEqual(receipt.symlink_count, 2)
        self.assertEqual(receipt.maximum_macos, (15, 0, 0))

    def test_macho_and_symlink_inventory_drift_are_rejected(self) -> None:
        macho_files = {
            "Contents/MacOS/GM2Godot": _macho_bytes(),
            "Contents/Frameworks/libfixture.dylib": _macho_bytes(filetype=6),
        }
        _write_app(self.app_path.parent, self.plist_content, macho_files)
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "Mach-O inventories are not identical",
        ):
            self.verify_with(_FakeHdiutil(self.plist_content))

        symlinks = {
            "Contents/Resources/libfixture.dylib": "../Frameworks/libfixture.dylib",
        }
        _write_app(self.app_path.parent, self.plist_content, macho_files, symlinks)
        _write_zip(self.zip_path, self.plist_content, macho_files)
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "symlink inventories are not identical",
        ):
            self.verify_with(
                _FakeHdiutil(
                    self.plist_content,
                    macho_files=macho_files,
                    symlinks=symlinks,
                )
            )

    def test_native_minimum_above_reviewed_plist_target_is_rejected(self) -> None:
        for minimum, rendered in (((15, 0, 1), "15.0.1"), ((15, 1, 0), "15.1"), ((16, 0, 0), "16.0")):
            macho_files = {"Contents/MacOS/GM2Godot": _macho_bytes(minimum=minimum)}
            _write_app(self.app_path.parent, self.plist_content, macho_files)
            _write_zip(self.zip_path, self.plist_content, macho_files)
            with (
                self.subTest(minimum=minimum),
                self.assertRaisesRegex(
                    verifier.MetadataVerificationError,
                    "below native Mach-O requirement " + rendered.replace(".", r"\."),
                ),
            ):
                self.verify_with(_FakeHdiutil(self.plist_content, macho_files=macho_files))

    def test_exact_reviewed_minimum_allows_lower_and_equal_native_requirements(self) -> None:
        for minimum in ((14, 5, 1), (15, 0, 0)):
            files = {"Contents/MacOS/GM2Godot": _macho_bytes(minimum=minimum)}
            _write_app(self.app_path.parent, self.plist_content, files)
            _write_zip(self.zip_path, self.plist_content, files)
            with self.subTest(minimum=minimum):
                receipt = self.verify_with(_FakeHdiutil(self.plist_content, macho_files=files))
            self.assertEqual(receipt.maximum_macos, minimum)
            self.assertEqual(receipt.metadata.minimum_system_version, "15.0")

    def test_architecture_and_deployment_target_drift_are_rejected(self) -> None:
        mixed_files = {
            "Contents/MacOS/GM2Godot": _macho_bytes(),
            "Contents/Frameworks/libintel.dylib": _macho_bytes(
                "x86_64",
                filetype=6,
            ),
        }
        _write_app(self.app_path.parent, self.plist_content, mixed_files)
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "x86_64; expected thin arm64",
        ):
            self.verify_with(_FakeHdiutil(self.plist_content))

        source_files = {
            "Contents/MacOS/GM2Godot": _macho_bytes(minimum=(14, 0, 0)),
        }
        packaged_files = {
            "Contents/MacOS/GM2Godot": _macho_bytes(minimum=(15, 0, 0)),
        }
        shutil.rmtree(self.app_path)
        _write_app(self.app_path.parent, self.plist_content, source_files)
        _write_zip(self.zip_path, self.plist_content, packaged_files)
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "Mach-O inventories are not identical",
        ):
            self.verify_with(_FakeHdiutil(self.plist_content, macho_files=packaged_files))


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
            "minimum-format": repr({**SYNTHETIC_POLICY, "LSMinimumSystemVersion": "15.0.0"}),
            "minimum-unreviewed": repr({**SYNTHETIC_POLICY, "LSMinimumSystemVersion": "14.0"}),
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
                "LSMinimumSystemVersion": "15.0",
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
                if isinstance(name, str):
                    member = zipfile.ZipInfo(name)
                    member.create_system = 3
                    member.external_attr = (
                        (stat.S_IFDIR | 0o755) if name.endswith("/") else (stat.S_IFREG | 0o644)
                    ) << 16
                else:
                    member = name
                archive.writestr(member, content)
        return path

    def test_duplicate_and_target_symlink_are_rejected(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicate = self._archive_with(
                [
                    ("GM2Godot.app/Contents/Info.plist", self.plist_content),
                    ("GM2Godot.app/Contents/Info.plist", self.plist_content),
                ]
            )
        with self.assertRaises(verifier.MetadataVerificationError):
            verifier.inspect_zip(duplicate, SYNTHETIC_POLICY)

        target = zipfile.ZipInfo("GM2Godot.app/Contents/Info.plist")
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
                archive = self._archive_with([("GM2Godot.app/Contents/Info.plist", self.plist_content), extra])
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
                ("GM2Godot.app/Contents/Info.plist", self.plist_content),
                ("unrelated/readme.txt", b"ignored"),
                (unrelated_link, b"../../outside"),
            ]
        )

        metadata = verifier.inspect_zip(archive, SYNTHETIC_POLICY)

        self.assertEqual(metadata.short_version, "1.2.3")


class MacOSBundleMetadataDmgTests(BundleMetadataFixture):
    def test_detach_cleanup_preserves_active_base_exception_cross_product(self) -> None:
        for phase in ("detach", "info"):
            for primary_type in (OSError, KeyboardInterrupt, SystemExit):
                for cleanup_type in (OSError, KeyboardInterrupt, SystemExit):
                    primary = primary_type("inventory primary")
                    cleanup = cleanup_type(f"{phase} cleanup")
                    fake = _FakeHdiutil(self.plist_content)

                    def run(command: Sequence[str], label: str) -> verifier._CommandResult:
                        if label == phase:
                            raise cleanup
                        return fake(command, label)

                    with (
                        self.subTest(phase=phase, primary=primary_type.__name__, cleanup=cleanup_type.__name__),
                        mock.patch.object(verifier, "_run_hdiutil_command", side_effect=run),
                        mock.patch.object(verifier.tempfile, "mkdtemp", side_effect=self.root_factory),
                        mock.patch.object(verifier, "_read_regular_at", side_effect=primary),
                        self.assertRaises(primary_type) as raised,
                    ):
                        verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
                    self.assertIs(raised.exception, primary)
                    self.assertIn(str(cleanup), "\n".join(getattr(primary, "__notes__", ())))

    def test_detach_cleanup_without_primary_propagates_exact_base_exception(self) -> None:
        for phase in ("detach", "info"):
            for cleanup_type in (OSError, KeyboardInterrupt, SystemExit):
                cleanup = cleanup_type(f"{phase} cleanup")
                fake = _FakeHdiutil(self.plist_content)

                def run(command: Sequence[str], label: str) -> verifier._CommandResult:
                    if label == phase:
                        raise cleanup
                    return fake(command, label)

                with (
                    self.subTest(phase=phase, cleanup=cleanup_type.__name__),
                    mock.patch.object(verifier, "_run_hdiutil_command", side_effect=run),
                    mock.patch.object(verifier.tempfile, "mkdtemp", side_effect=self.root_factory),
                    self.assertRaises(cleanup_type) as raised,
                ):
                    verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
                self.assertIs(raised.exception, cleanup)

    def test_private_dmg_copy_preserves_primary_base_exception_and_cleanup_note(self) -> None:
        for primary in (KeyboardInterrupt("copy interrupted"), SystemExit(29)):
            with self.subTest(primary=type(primary).__name__):
                root = self.root / f"copy-{type(primary).__name__}"
                root.mkdir(mode=0o700)
                real_close, real_open = os.close, os.open
                closed: list[int] = []
                opened: list[int] = []

                def tracked_open(
                    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    fd = real_open(path, flags, mode, dir_fd=dir_fd)
                    opened.append(fd)
                    return fd

                def close_then_fail(descriptor: int) -> None:
                    closed.append(descriptor)
                    real_close(descriptor)
                    raise OSError("injected copy close failure")

                with (
                    mock.patch.object(verifier.os, "read", side_effect=primary),
                    mock.patch.object(verifier.os, "open", new=tracked_open),
                    mock.patch.object(verifier.os, "supports_dir_fd", os.supports_dir_fd | {tracked_open}),
                    mock.patch.object(verifier.os, "close", side_effect=close_then_fail),
                    self.assertRaises(type(primary)) as raised,
                ):
                    verifier._copy_bound_dmg(self.dmg_path, root)
                self.assertIs(raised.exception, primary)
                self.assertIn(
                    "injected copy close failure",
                    "\n".join(getattr(primary, "__notes__", ())),
                )
                self.assertTrue(opened)
                self.assertCountEqual(closed, opened)
                for fd in opened:
                    with self.assertRaises(OSError) as bad:
                        os.fstat(fd)
                    self.assertEqual(bad.exception.errno, errno.EBADF)

    def test_private_dmg_copy_attempts_both_closes_without_operation_primary(self) -> None:
        for cleanup_type in (OSError, KeyboardInterrupt, SystemExit):
            root = self.root / f"close-{cleanup_type.__name__}"
            root.mkdir(mode=0o700)
            real_close, real_open = os.close, os.open
            closed: list[int] = []
            opened: list[int] = []

            def tracked_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                fd = real_open(path, flags, mode, dir_fd=dir_fd)
                opened.append(fd)
                return fd

            def close_then_fail(descriptor: int) -> None:
                closed.append(descriptor)
                real_close(descriptor)
                raise cleanup_type("injected close failure")

            with (
                self.subTest(cleanup=cleanup_type.__name__),
                mock.patch.object(verifier.os, "open", new=tracked_open),
                mock.patch.object(verifier.os, "supports_dir_fd", os.supports_dir_fd | {tracked_open}),
                mock.patch.object(verifier.os, "close", side_effect=close_then_fail),
                self.assertRaises(cleanup_type) as raised,
            ):
                verifier._copy_bound_dmg(self.dmg_path, root)
            self.assertTrue(opened)
            self.assertCountEqual(closed, opened)
            for fd in opened:
                with self.assertRaises(OSError) as bad:
                    os.fstat(fd)
                self.assertEqual(bad.exception.errno, errno.EBADF)
            self.assertIn(
                "injected close failure",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )

    def test_private_dmg_cleanup_preserves_primary_and_control_flow(self) -> None:
        for cleanup_type in (OSError, KeyboardInterrupt, SystemExit):
            cleanup = cleanup_type("injected private cleanup failure")
            real_unlink = os.unlink

            def fail_copy_unlink(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes], *, dir_fd: int | None = None
            ) -> None:
                if os.fsdecode(path).endswith("source.dmg"):
                    raise cleanup
                real_unlink(path, dir_fd=dir_fd)

            fake = _FakeHdiutil(self.plist_content, attach_returncode=9)
            with (
                self.subTest(kind="primary", cleanup=cleanup_type.__name__),
                mock.patch.object(verifier, "_run_hdiutil_command", side_effect=fake),
                mock.patch.object(verifier.tempfile, "mkdtemp", side_effect=self.root_factory),
                mock.patch.object(verifier.os, "unlink", side_effect=fail_copy_unlink),
                self.assertRaises(verifier.MetadataVerificationError) as raised,
            ):
                verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
            self.assertIn(
                "injected private cleanup failure",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )
            self.assertTrue(self.root_factory.paths[-1].exists())
            self.assertEqual(
                (self.root_factory.paths[-1] / "source.dmg").read_bytes(),
                self.dmg_path.read_bytes(),
            )

            cleanup_without_primary = cleanup_type("injected sole cleanup failure")

            def fail_sole_copy_unlink(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes], *, dir_fd: int | None = None
            ) -> None:
                if os.fsdecode(path).endswith("source.dmg"):
                    raise cleanup_without_primary
                real_unlink(path, dir_fd=dir_fd)

            fake = _FakeHdiutil(self.plist_content)
            with (
                self.subTest(kind="sole", cleanup=cleanup_type.__name__),
                mock.patch.object(verifier, "_run_hdiutil_command", side_effect=fake),
                mock.patch.object(verifier.tempfile, "mkdtemp", side_effect=self.root_factory),
                mock.patch.object(
                    verifier.os,
                    "unlink",
                    side_effect=fail_sole_copy_unlink,
                ),
                self.assertRaises(cleanup_type) as raised_cleanup,
            ):
                verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
            self.assertIs(raised_cleanup.exception, cleanup_without_primary)
            self.assertTrue(self.root_factory.paths[-1].exists())

    def test_mount_and_root_rmdir_failures_report_removed_private_copy(self) -> None:
        for target in ("mount", "root"):
            for cleanup_type in (OSError, KeyboardInterrupt, SystemExit):
                cleanup = cleanup_type(f"injected {target} rmdir failure")
                real_rmdir = os.rmdir

                def selective_rmdir(
                    path: str | bytes | os.PathLike[str] | os.PathLike[bytes], *, dir_fd: int | None = None
                ) -> None:
                    name = os.path.basename(os.fsdecode(path))
                    if (target == "mount" and name == "mount") or (
                        target == "root" and name in {item.name for item in self.root_factory.paths}
                    ):
                        raise cleanup
                    real_rmdir(path, dir_fd=dir_fd)

                for has_primary in (False, True):
                    fake = _FakeHdiutil(
                        self.plist_content,
                        attach_returncode=9 if has_primary else 0,
                    )
                    with (
                        self.subTest(
                            target=target,
                            cleanup=cleanup_type.__name__,
                            primary=has_primary,
                        ),
                        mock.patch.object(verifier, "_run_hdiutil_command", side_effect=fake),
                        mock.patch.object(
                            verifier.tempfile,
                            "mkdtemp",
                            side_effect=self.root_factory,
                        ),
                        mock.patch.object(verifier.os, "rmdir", selective_rmdir),
                    ):
                        if has_primary:
                            with self.assertRaises(verifier.MetadataVerificationError) as raised:
                                verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
                            self.assertIn("attach failed with status 9", str(raised.exception))
                            self.assertIn(
                                str(cleanup),
                                "\n".join(getattr(raised.exception, "__notes__", ())),
                            )
                        else:
                            with self.assertRaises(cleanup_type) as raised:
                                verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
                            self.assertIs(raised.exception, cleanup)
                    retained_root = self.root_factory.paths[-1]
                    self.assertTrue(retained_root.exists())
                    self.assertFalse((retained_root / "source.dmg").exists())
                    notes = "\n".join(getattr(raised.exception, "__notes__", ()))
                    self.assertIn("private DMG copy was already removed", notes)

    def test_private_cleanup_preserves_first_failure_and_orders_later_notes(self) -> None:
        root = self.root / "ordered-cleanup"
        mountpoint = root / "mount"
        private_dmg = root / "source.dmg"
        mountpoint.mkdir(parents=True)
        private_dmg.write_bytes(b"evidence")
        private_dmg.chmod(0o600)
        first = KeyboardInterrupt("unlink first")
        later = SystemExit("mountpoint second")
        with (
            mock.patch.object(verifier.os, "unlink", side_effect=first),
            mock.patch.object(verifier.os, "rmdir", side_effect=later),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            verifier._remove_private_dmg_root(root, mountpoint, private_dmg)
        self.assertIs(raised.exception, first)
        notes = list(getattr(first, "__notes__", ()))
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0], "additional private cleanup failure: mountpoint second")
        self.assertIn("private DMG copy remains", notes[1])
        self.assertIn(os.fspath(root), notes[1])
        self.assertEqual(private_dmg.read_bytes(), b"evidence")

    def test_mounted_macho_failure_still_detaches_and_cleans_up(self) -> None:
        wrong_architecture = {
            "Contents/MacOS/GM2Godot": _macho_bytes("x86_64"),
        }
        fake = _FakeHdiutil(
            self.plist_content,
            macho_files=wrong_architecture,
        )

        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "x86_64; expected thin arm64",
        ):
            self.inspect_dmg_inventory_with(fake)

        self.assertEqual(fake.events, ["attach", "detach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())

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
        with self.assertRaises(verifier.MetadataVerificationError) as raised:
            self.inspect_dmg_with(fake)
        self.assertRegex("\n".join((str(raised.exception), *getattr(raised.exception, "__notes__", ()))), "retaining")
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
        with self.assertRaises(verifier.MetadataVerificationError) as raised:
            self.inspect_dmg_with(confirmation_failure)
        self.assertIn("unable to parse hdiutil info receipt", str(raised.exception))
        self.assertRegex("\n".join((str(raised.exception), *getattr(raised.exception, "__notes__", ()))), "retaining")
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
                verifier.os,
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
        original_read = os.read

        def fail_only_mounted_read(fd: int, size: int) -> bytes:
            if fake.mounted:
                raise OSError("read failed")
            return original_read(fd, size)

        with (
            mock.patch.object(verifier, "_run_hdiutil_command", side_effect=fake),
            mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=self.root_factory,
            ),
            mock.patch.object(verifier.os, "read", side_effect=fail_only_mounted_read),
            self.assertRaisesRegex(verifier.MetadataVerificationError, "read failed"),
        ):
            verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
        self.assertEqual(fake.events, ["attach", "detach", "info"])
        self.assertFalse(self.root_factory.paths[0].exists())


class MacOSBundleRetainedInputTests(BundleMetadataFixture):
    def test_absolute_symlink_ancestor_is_rejected(self) -> None:
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(self.app_path.parent, target_is_directory=True)
        copied_zip = self.app_path.parent / "GM2Godot.zip"
        copied_dmg = self.app_path.parent / "GM2Godot.dmg"
        copied_zip.write_bytes(self.zip_path.read_bytes())
        copied_dmg.write_bytes(self.dmg_path.read_bytes())
        for kind in ("app", "zip", "dmg"):
            with (
                self.subTest(kind=kind),
                mock.patch.object(verifier, "_run_hdiutil_command") as mount_command,
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                if kind == "app":
                    verifier.inspect_app(linked_parent / "GM2Godot.app", SYNTHETIC_POLICY)
                elif kind == "zip":
                    verifier.inspect_zip(linked_parent / "GM2Godot.zip", SYNTHETIC_POLICY)
                else:
                    verifier.inspect_dmg(linked_parent / "GM2Godot.dmg", SYNTHETIC_POLICY)
            mount_command.assert_not_called()

    def test_plist_and_inventory_share_one_app_root(self) -> None:
        original_read = verifier._read_regular_at
        original_inventory = verifier._inspect_directory_inventory_at
        root_fd: int | None = None
        inventory_fd: int | None = None
        swapped = False

        def read_then_replace(fd: int, components: Sequence[str], maximum_bytes: int, description: str) -> bytes:
            nonlocal root_fd, swapped
            result = original_read(fd, components, maximum_bytes, description)
            if not swapped and "direct app" in description:
                root_fd = fd
                swapped = True
                self.app_path.rename(self.app_path.with_name("original.app"))
                _write_app(self.app_path.parent, self.plist_content)
            return result

        def borrowed_inventory(fd: int, architecture: str, description: str) -> verifier.BundleInventory:
            nonlocal inventory_fd
            if "direct app" in description:
                inventory_fd = fd
            return original_inventory(fd, architecture, description)

        with (
            mock.patch.object(verifier, "_read_regular_at", side_effect=read_then_replace),
            mock.patch.object(verifier, "_inspect_directory_inventory_at", side_effect=borrowed_inventory),
            self.assertRaises(verifier.MetadataVerificationError),
        ):
            self.verify_with(_FakeHdiutil(self.plist_content))
        self.assertTrue(swapped)
        self.assertIsNotNone(root_fd)
        self.assertEqual(inventory_fd, root_fd)
        assert root_fd is not None
        with self.assertRaises(OSError) as bad:
            os.fstat(root_fd)
        self.assertEqual(bad.exception.errno, errno.EBADF)

    def test_dmg_initial_size_copy_rejects_shrink_growth_and_oversize(self) -> None:
        for kind in ("shrink", "growth", "oversize", "short-write"):
            source = self.root / f"{kind}.dmg"
            original = b"0123456789"
            source.write_bytes(original)
            destination_root = self.root / f"{kind}-private"
            destination_root.mkdir(mode=0o700)
            if kind == "oversize":
                with source.open("r+b") as stream:
                    stream.truncate(1_073_741_825)
            original_read, original_write = os.read, os.write
            requests: list[int] = []
            actual_read_sizes: list[int] = []
            written_sizes: list[int] = []
            altered = False

            def mutate_read(fd: int, amount: int) -> bytes:
                nonlocal altered
                requests.append(amount)
                if kind == "shrink" and not altered:
                    altered = True
                    with source.open("r+b") as stream:
                        stream.truncate(5)
                data = original_read(fd, amount)
                actual_read_sizes.append(len(data))
                if kind == "growth" and not altered:
                    altered = True
                    with source.open("ab") as stream:
                        stream.write(b"growth")
                return data

            def short_write(fd: int, data: bytes | bytearray | memoryview) -> int:
                actual = original_write(fd, data[:2])
                written_sizes.append(actual)
                return actual

            with (
                self.subTest(kind=kind),
                mock.patch.object(verifier.os, "read", side_effect=mutate_read),
                mock.patch.object(verifier.os, "write", side_effect=short_write),
                mock.patch.object(verifier, "_run_hdiutil_command") as mount_command,
            ):
                if kind == "short-write":
                    copied = verifier._copy_bound_dmg(source, destination_root)
                    self.assertEqual(copied.read_bytes(), original)
                    self.assertGreater(len(written_sizes), 1)
                else:
                    with self.assertRaises(verifier.MetadataVerificationError):
                        verifier._copy_bound_dmg(source, destination_root)
                mount_command.assert_not_called()
            if kind == "oversize":
                self.assertEqual(requests, [])
                self.assertFalse((destination_root / "source.dmg").exists())
            else:
                self.assertLessEqual(max(requests), len(original))
                self.assertLessEqual(sum(written_sizes), len(original))
                self.assertLessEqual(sum(actual_read_sizes), len(original) + 1)
                self.assertLessEqual(len(requests), 3)
                if kind != "short-write":
                    self.assertTrue(altered)

    def test_dmg_snapshot_and_private_ancestry_remain_bound(self) -> None:
        for kind in ("ancestor", "copy"):
            fake = _FakeHdiutil(self.plist_content)
            changed = False
            replacement_sentinel: Path | None = None

            def substitute_then_run(command: Sequence[str], label: str) -> verifier._CommandResult:
                nonlocal changed, replacement_sentinel
                result = fake(command, label)
                if label == "attach" and not changed:
                    changed = True
                    root = self.root_factory.paths[-1]
                    if kind == "ancestor":
                        original_root = root.with_name(root.name + "-original")
                        root.rename(original_root)
                        fake.mountpoint = original_root / "mount"
                        root.mkdir(mode=0o700)
                        replacement_sentinel = root / "source.dmg"
                        replacement_sentinel.write_bytes(b"replacement must remain")
                        (root / "mount").mkdir()
                    else:
                        copied = root / "source.dmg"
                        replacement = root / "replacement.dmg"
                        replacement.write_bytes(b"replacement must remain")
                        replacement.replace(copied)
                        replacement_sentinel = copied
                return result

            with (
                self.subTest(kind=kind),
                mock.patch.object(verifier, "_run_hdiutil_command", side_effect=substitute_then_run),
                mock.patch.object(verifier.tempfile, "mkdtemp", side_effect=self.root_factory),
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                verifier.inspect_dmg(self.dmg_path, SYNTHETIC_POLICY)
            self.assertTrue(changed)
            assert replacement_sentinel is not None
            self.assertEqual(replacement_sentinel.read_bytes(), b"replacement must remain")
            self.assertEqual(self.dmg_path.read_bytes(), b"synthetic dmg")

        for kind in ("ctime-only", "content"):
            fake = _FakeHdiutil(self.plist_content)
            observations: list[tuple[os.stat_result, os.stat_result]] = []

            def mutate_copy_then_run(command: Sequence[str], label: str) -> verifier._CommandResult:
                result = fake(command, label)
                if label == "attach":
                    self.assertEqual(observations, [])
                    copied = Path(command[-1])
                    before = copied.stat()
                    original = copied.read_bytes()
                    self.assertEqual(original, b"synthetic dmg")
                    if kind == "content":
                        altered = bytes([original[0] ^ 1]) + original[1:]
                        with copied.open("r+b") as stream:
                            self.assertEqual(stream.write(altered), len(original))
                    os.utime(copied, ns=(before.st_atime_ns, before.st_mtime_ns))
                    after = copied.stat()
                    for field in ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns"):
                        self.assertEqual(getattr(before, field), getattr(after, field), field)
                    self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)
                    if kind == "ctime-only":
                        self.assertEqual(copied.read_bytes(), original)
                    else:
                        self.assertNotEqual(copied.read_bytes(), original)
                    observations.append((before, after))
                return result

            with (
                self.subTest(kind=kind),
                mock.patch.object(verifier, "_run_hdiutil_command", side_effect=mutate_copy_then_run),
                mock.patch.object(verifier.tempfile, "mkdtemp", side_effect=self.root_factory),
            ):
                if kind == "ctime-only":
                    receipt = verifier.verify_artifacts(
                        self.source_root, self.app_path, self.zip_path, self.dmg_path, "arm64"
                    )
                    self.assertEqual(receipt.architecture, "arm64")
                    self.assertEqual(receipt.macho_count, 1)
                    self.assertEqual(receipt.metadata.short_version, SYNTHETIC_POLICY["CFBundleShortVersionString"])
                else:
                    with self.assertRaisesRegex(
                        verifier.MetadataVerificationError,
                        "^private DMG copy content changed after readonly attach$",
                    ):
                        verifier.verify_artifacts(
                            self.source_root, self.app_path, self.zip_path, self.dmg_path, "arm64"
                        )
            self.assertEqual(len(observations), 1)
            self.assertEqual(fake.events, ["attach", "detach", "info"])
            self.assertFalse(fake.mounted)
            self.assertFalse(self.root_factory.paths[-1].exists())
            self.assertEqual(self.dmg_path.read_bytes(), b"synthetic dmg")

    def test_mounted_descriptors_close_before_detach(self) -> None:
        fake = _FakeHdiutil(self.plist_content)
        original_open = os.open
        mounted_fds: list[int] = []
        private_fds: list[int] = []
        checked_detach = False

        def tracked_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            fd = original_open(path, flags, mode, dir_fd=dir_fd)
            name = os.path.basename(os.fsdecode(path))
            if fake.mounted and name in {"mount", "GM2Godot.app", "Contents", "MacOS", "Info.plist", "GM2Godot"}:
                mounted_fds.append(fd)
            elif name in {item.name for item in self.root_factory.paths}:
                private_fds.append(fd)
            return fd

        def check_then_run(command: Sequence[str], label: str) -> verifier._CommandResult:
            nonlocal checked_detach
            if label == "detach":
                checked_detach = True
                self.assertTrue(mounted_fds)
                for fd in mounted_fds:
                    with self.assertRaises(OSError) as bad:
                        os.fstat(fd)
                    self.assertEqual(bad.exception.errno, errno.EBADF)
                self.assertTrue(any(self._descriptor_is_open(fd) for fd in private_fds))
            return fake(command, label)

        with (
            mock.patch.object(verifier.os, "open", new=tracked_open),
            mock.patch.object(verifier.os, "supports_dir_fd", os.supports_dir_fd | {tracked_open}),
            mock.patch.object(verifier, "_run_hdiutil_command", side_effect=check_then_run),
            mock.patch.object(verifier.tempfile, "mkdtemp", side_effect=self.root_factory),
        ):
            verifier._inspect_dmg_contents(self.dmg_path, SYNTHETIC_POLICY, "arm64")
        self.assertTrue(checked_detach)
        self.assertEqual(fake.events, ["attach", "detach", "info"])
        self.assertFalse(self.root_factory.paths[-1].exists())

    @staticmethod
    def _descriptor_is_open(fd: int) -> bool:
        try:
            os.fstat(fd)
        except OSError as error:
            if error.errno != errno.EBADF:
                raise
            return False
        return True


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
                            "--expected-architecture",
                            "arm64",
                        ]
                    )
                self.assertEqual(status, 1)
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_main_prints_stable_success(self) -> None:
        metadata = verifier.BundleMetadata(
            "land.infi.gm2godot",
            "1.2.3",
            "1.2.3",
            "15.0",
            "a" * 64,
        )
        receipt = verifier.VerificationReceipt(
            metadata,
            "arm64",
            2,
            20,
            (15, 0, 0),
        )
        stdout = StringIO()
        with (
            mock.patch.object(verifier, "verify_artifacts", return_value=receipt),
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
                    "--expected-architecture",
                    "arm64",
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn("identifier=land.infi.gm2godot", stdout.getvalue())
        self.assertIn("architecture=arm64", stdout.getvalue())
        self.assertIn("macho_count=2", stdout.getvalue())
        self.assertIn("maximum_native_minimum=15.0", stdout.getvalue())
        self.assertIn("plist_sha256=" + "a" * 64, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
