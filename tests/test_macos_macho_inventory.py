# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
import errno
import plistlib
from io import BytesIO
import os
from pathlib import Path
import stat
import struct
import tempfile
from typing import BinaryIO
import unittest
import unicodedata
from unittest import mock
import zipfile

from scripts import verify_macos_bundle_metadata as verifier


ZIP_POLICY = {
    "CFBundleIdentifier": "land.infi.gm2godot",
    "CFBundleShortVersionString": "1.2.3",
    "CFBundleVersion": "1.2.3",
    "LSMinimumSystemVersion": "15.0",
}


CPU_TYPES = {
    "arm64": 0x0100000C,
    "x86_64": 0x01000007,
}


def _packed_version(version: tuple[int, int, int]) -> int:
    major, minor, patch = version
    return (major << 16) | (minor << 8) | patch


def _build_version_command(
    minimum: tuple[int, int, int] = (15, 0, 0),
    *,
    platform: int = 1,
    tools: tuple[tuple[int, int], ...] = (),
) -> bytes:
    command_size = 24 + 8 * len(tools)
    content = struct.pack(
        "<IIIIII",
        0x32,
        command_size,
        platform,
        _packed_version(minimum),
        _packed_version((15, 4, 0)),
        len(tools),
    )
    return content + b"".join(struct.pack("<II", *tool) for tool in tools)


def _legacy_version_command(
    minimum: tuple[int, int, int] = (14, 5, 1),
) -> bytes:
    return struct.pack(
        "<IIII",
        0x24,
        16,
        _packed_version(minimum),
        _packed_version((15, 4, 0)),
    )


def _macho(
    architecture: str = "arm64",
    *,
    commands: bytes | None = None,
    command_count: int | None = None,
    declared_command_bytes: int | None = None,
    cpu_type: int | None = None,
    cpu_subtype: int | None = None,
    filetype: int = 2,
) -> bytes:
    selected_commands = _build_version_command() if commands is None else commands
    count = 1 if command_count is None else command_count
    command_bytes = len(selected_commands) if declared_command_bytes is None else declared_command_bytes
    header = struct.pack(
        "<IiiIIIII",
        0xFEEDFACF,
        CPU_TYPES[architecture] if cpu_type is None else cpu_type,
        (
            (0 if architecture == "arm64" else 3)
            if cpu_subtype is None
            else cpu_subtype
            if cpu_subtype < 0x80000000
            else cpu_subtype - 0x100000000
        ),
        filetype,
        count,
        command_bytes,
        0,
        0,
    )
    return header + selected_commands


def _parse_macho(
    content: bytes,
    expected_architecture: str,
) -> verifier._MachOHeader | None:
    return verifier._parse_macho_stream(
        BytesIO(content),
        len(content),
        expected_architecture,
        "Mach-O fixture",
    )


class TestMachOParser(unittest.TestCase):
    def test_argument_and_version_helpers_reject_noncanonical_values(self) -> None:
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "expected architecture must be one of",
        ):
            verifier._require_expected_architecture("universal2")
        with self.assertRaisesRegex(
            verifier.MetadataVerificationError,
            "not a canonical macOS version",
        ):
            verifier._parse_macos_version_text("15", "fixture version")
        self.assertEqual(verifier._format_macos_version((14, 5, 1)), "14.5.1")

    def test_thin_arm64_and_x86_64_deployment_commands_are_supported(self) -> None:
        for architecture in ("arm64", "x86_64"):
            for commands, minimum in (
                (_build_version_command((15, 0, 0), tools=((3, 0x90100),)), (15, 0, 0)),
                (_legacy_version_command((14, 5, 1)), (14, 5, 1)),
            ):
                with self.subTest(architecture=architecture, command=commands[:4]):
                    parsed = _parse_macho(_macho(architecture, commands=commands), architecture)
                    self.assertIsNotNone(parsed)
                    assert parsed is not None
                    self.assertEqual((parsed.architecture, parsed.minimum_macos), (architecture, minimum))
                    other = "x86_64" if architecture == "arm64" else "arm64"
                    with self.assertRaises(verifier.MetadataVerificationError):
                        _parse_macho(_macho(architecture, commands=commands), other)

    def test_non_macho_is_ignored_but_fat_and_unsupported_thin_are_rejected(self) -> None:
        self.assertIsNone(_parse_macho(b"plain text", "arm64"))

        for magic in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"):
            with (
                self.subTest(kind="fat", magic=magic),
                self.assertRaisesRegex(
                    verifier.MetadataVerificationError,
                    "universal/fat",
                ),
            ):
                _parse_macho(magic + b"\0" * 32, "arm64")
        for magic in (b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf"):
            with (
                self.subTest(kind="unsupported", magic=magic),
                self.assertRaisesRegex(
                    verifier.MetadataVerificationError,
                    "unsupported 32-bit or byte-swapped",
                ),
            ):
                _parse_macho(magic + b"\0" * 32, "arm64")

    def test_wrong_and_unknown_cpu_types_are_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.MetadataVerificationError, "x86_64; expected thin arm64"):
            _parse_macho(_macho("x86_64"), "arm64")
        with self.assertRaisesRegex(verifier.MetadataVerificationError, "unknown .* CPU type"):
            _parse_macho(
                _macho(cpu_type=0x01000063),
                "arm64",
            )

    def test_cpu_subtypes_and_capability_bits_must_be_exact_baselines(self) -> None:
        for architecture, subtype in (
            ("arm64", 2),
            ("arm64", 0x80000000),
            ("x86_64", 8),
            ("x86_64", 0x80000003),
            ("x86_64", 4),
        ):
            with (
                self.subTest(architecture=architecture, subtype=subtype),
                self.assertRaisesRegex(
                    verifier.MetadataVerificationError,
                    "CPU subtype/capability",
                ),
            ):
                _parse_macho(
                    _macho(architecture, cpu_subtype=subtype),
                    architecture,
                )

    def test_truncated_and_structurally_invalid_tables_are_rejected(self) -> None:
        invalid_cases = {
            "header": b"\xcf\xfa\xed\xfe",
            "short-header-read": (
                b"\xcf\xfa\xed\xfe",
                32,
            ),
            "declared-table": _macho(declared_command_bytes=32),
            "command-count": _macho(command_count=2),
            "count-cannot-fit": _macho(command_count=4),
            "command-exceeds-table": _macho(commands=struct.pack("<II", 1, 16)),
            "command-size": _macho(commands=struct.pack("<II", 1, 10) + b"\0\0"),
            "zero-command-size": _macho(commands=struct.pack("<II", 1, 0)),
            "zero-command-count": _macho(command_count=0),
            "unaligned-table": _macho(declared_command_bytes=25),
            "short-magic-read": (b"\xcf", 32),
            "legacy-size": _macho(
                commands=struct.pack(
                    "<IIII",
                    0x24,
                    24,
                    _packed_version((15, 0, 0)),
                    _packed_version((15, 4, 0)),
                )
                + b"\0" * 8
            ),
            "build-size": _macho(commands=struct.pack("<II", 0x32, 16) + b"\0" * 8),
            "trailing-table": _macho(
                commands=_build_version_command() + b"\0" * 8,
            ),
        }
        for label, raw_case in invalid_cases.items():
            content, file_size = raw_case if isinstance(raw_case, tuple) else (raw_case, len(raw_case))
            with self.subTest(label=label), self.assertRaises(verifier.MetadataVerificationError):
                verifier._parse_macho_stream(
                    BytesIO(content),
                    file_size,
                    "arm64",
                    "Mach-O fixture",
                )

        # One valid deployment command and 65536 valid-size unknown commands form
        # a consistent table that would parse successfully without the count cap.
        over_count_commands = _build_version_command() + struct.pack("<II", 0x7FF00000, 8) * 65536
        self.assertEqual(len(over_count_commands), 24 + 8 * 65536)
        over_count = _macho(commands=over_count_commands, command_count=65537)
        with (
            self.subTest(label="commands-limit"),
            self.assertRaisesRegex(
                verifier.MetadataVerificationError,
                r"^Mach-O fixture has 65537 load commands; limit is 65536$",
            ),
        ):
            _parse_macho(over_count, "arm64")

        class HeaderOnlyReader:
            def __init__(self, header: bytes) -> None:
                self.header = BytesIO(header)
                self.requests: list[int] = []

            def read(self, size: int = -1) -> bytes:
                self.requests.append(size)
                if size < 0 or size > 32 - self.header.tell():
                    raise AssertionError("the table-byte cap must reject before requesting load-table bytes")
                return self.header.read(size)

        # The nominal file size agrees with the declared table; only the 32-byte
        # header is materialized, and any attempted table read fails the test.
        declared_bytes = 16777217
        header_reader = HeaderOnlyReader(_macho(commands=b"", declared_command_bytes=declared_bytes))
        with (
            self.subTest(label="bytes-limit"),
            self.assertRaisesRegex(
                verifier.MetadataVerificationError,
                r"^Mach-O fixture load-command table exceeds the 16777216-byte limit$",
            ),
        ):
            verifier._parse_macho_stream(header_reader, 32 + declared_bytes, "arm64", "Mach-O fixture")
        self.assertEqual(header_reader.requests, [4, 28])
        self.assertEqual(header_reader.header.tell(), 32)

        self.assertIsNone(verifier._parse_macho_stream(BytesIO(b"abc"), 3, "arm64", "short fixture"))
        with self.assertRaisesRegex(verifier.MetadataVerificationError, "negative file size"):
            verifier._parse_macho_stream(BytesIO(), -1, "arm64", "negative fixture")

    def test_missing_duplicate_wrong_platform_and_bad_tool_tables_are_rejected(self) -> None:
        no_deployment = struct.pack("<II", 1, 8)
        duplicate = _build_version_command() + _legacy_version_command()
        bad_tool_table = bytearray(_build_version_command())
        struct.pack_into("<I", bad_tool_table, 20, 1)
        cases = {
            "missing": _macho(commands=no_deployment),
            "duplicate": _macho(commands=duplicate, command_count=2),
            "platform": _macho(commands=_build_version_command(platform=2)),
            "legacy-platform": _macho(
                commands=struct.pack(
                    "<IIII",
                    0x25,
                    16,
                    _packed_version((15, 0, 0)),
                    _packed_version((15, 4, 0)),
                )
            ),
            "tools": _macho(commands=bytes(bad_tool_table)),
            "zero": _macho(commands=_build_version_command((0, 0, 0))),
            "filetype": _macho(filetype=0),
        }
        for label, content in cases.items():
            with self.subTest(label=label), self.assertRaises(verifier.MetadataVerificationError):
                _parse_macho(content, "arm64")


class TestBundleInventory(unittest.TestCase):
    def test_directory_and_regular_file_substitutions_are_rejected(self) -> None:
        for swapped_kind in ("directory", "file"):
            with self.subTest(kind=swapped_kind), tempfile.TemporaryDirectory() as raw_root:
                app = Path(raw_root).resolve() / "GM2Godot.app"
                main = app / "Contents/MacOS/GM2Godot"
                main.parent.mkdir(parents=True)
                main.write_bytes(_macho())
                main.chmod(0o755)
                real_open = verifier.os.open
                swapped = False

                def swap_then_open(
                    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    nonlocal swapped
                    name = os.fsdecode(path)
                    trigger = "MacOS" if swapped_kind == "directory" else "GM2Godot"
                    if not swapped and name == trigger and dir_fd is not None:
                        swapped = True
                        victim = main.parent if swapped_kind == "directory" else main
                        original = victim.with_name(victim.name + "-original")
                        victim.rename(original)
                        if swapped_kind == "directory":
                            victim.mkdir()
                            replacement = victim / "GM2Godot"
                            replacement.write_bytes(_macho())
                            replacement.chmod(0o755)
                        else:
                            victim.write_bytes(_macho())
                            victim.chmod(0o755)
                    return real_open(path, flags, mode, dir_fd=dir_fd)

                with (
                    mock.patch.object(verifier.os, "open", new=swap_then_open),
                    mock.patch.object(verifier.os, "supports_dir_fd", os.supports_dir_fd | {swap_then_open}),
                    self.assertRaisesRegex(verifier.MetadataVerificationError, "changed"),
                ):
                    verifier._inspect_directory_inventory(app, "arm64", "fixture app")

    def test_symlink_substitution_during_readlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            app = Path(raw_root).resolve() / "GM2Godot.app"
            main = app / "Contents/MacOS/GM2Godot"
            link = app / "Contents" / "link"
            main.parent.mkdir(parents=True)
            main.write_bytes(_macho())
            main.chmod(0o755)
            link.symlink_to("MacOS/GM2Godot")
            real_readlink = verifier.os.readlink

            def swap_then_readlink(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes], *, dir_fd: int | None = None
            ) -> str:
                if os.fsdecode(path) == "link":
                    link.unlink()
                    link.symlink_to("MacOS/GM2Godot")
                return real_readlink(os.fsdecode(path), dir_fd=dir_fd)

            with (
                mock.patch.object(verifier.os, "readlink", side_effect=swap_then_readlink),
                self.assertRaisesRegex(verifier.MetadataVerificationError, "symlink .* changed"),
            ):
                verifier._inspect_directory_inventory(app, "arm64", "fixture app")

    def test_regular_file_mutation_during_macho_parse_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            app = Path(raw_root).resolve() / "GM2Godot.app"
            main = app / "Contents/MacOS/GM2Godot"
            main.parent.mkdir(parents=True)
            main.write_bytes(_macho())
            main.chmod(0o755)
            real_parse = verifier._parse_macho_stream
            mutated = False

            def parse_then_mutate(
                stream: BinaryIO, file_size: int, architecture: str, description: str
            ) -> verifier._MachOHeader | None:
                nonlocal mutated
                result = real_parse(stream, file_size, architecture, description)
                if not mutated:
                    mutated = True
                    with main.open("ab") as handle:
                        handle.write(b"mutation")
                return result

            with (
                mock.patch.object(verifier, "_parse_macho_stream", side_effect=parse_then_mutate),
                self.assertRaisesRegex(verifier.MetadataVerificationError, "changed during inspection"),
            ):
                verifier._inspect_directory_inventory(app, "arm64", "fixture app")

    def test_non_regular_leaf_and_raced_fifo_fail_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            app = Path(raw_root).resolve() / "GM2Godot.app"
            main = app / "Contents" / "MacOS" / "GM2Godot"
            main.parent.mkdir(parents=True)
            main.write_bytes(_macho())
            main.chmod(0o755)
            original_open = os.open
            substituted = False

            def substitute_then_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal substituted
                if not substituted and os.fsdecode(path) == "GM2Godot" and dir_fd is not None:
                    substituted = True
                    main.unlink()
                    os.mkfifo(main)
                    self.assertTrue(flags & os.O_NONBLOCK, "a raced FIFO must never be opened in blocking mode")
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(verifier.os, "open", new=substitute_then_open),
                mock.patch.object(verifier.os, "supports_dir_fd", os.supports_dir_fd | {substitute_then_open}),
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                verifier._inspect_directory_inventory(app, "arm64", "FIFO fixture")
            self.assertTrue(substituted)
            self.assertTrue(stat.S_ISFIFO(main.lstat().st_mode))
            with (
                mock.patch.object(verifier.os, "open", new=substitute_then_open),
                mock.patch.object(verifier.os, "supports_dir_fd", os.supports_dir_fd | {substitute_then_open}),
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                verifier._inspect_directory_inventory(app, "arm64", "known FIFO fixture")

    def test_missing_nofollow_capabilities_fail_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            app = Path(raw_root).resolve() / "GM2Godot.app"
            app.mkdir()
            opened = False

            def forbidden_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal opened
                opened = True
                raise AssertionError("missing no-follow capability must fail before opening")

            for kind in ("flag", "dir_fd"):
                supported = set[object](os.supports_dir_fd) if kind == "flag" else set[object]()
                if kind == "flag":
                    supported.add(forbidden_open)
                with (
                    self.subTest(kind=kind),
                    mock.patch.object(verifier.os, "open", new=forbidden_open),
                    mock.patch.object(verifier.os, "supports_dir_fd", supported),
                    mock.patch.object(verifier.os, "O_NOFOLLOW", None if kind == "flag" else os.O_NOFOLLOW),
                    self.assertRaises(verifier.MetadataVerificationError),
                ):
                    verifier._inspect_directory_inventory(app, "arm64", "missing capability fixture")
            self.assertFalse(opened)

    def test_path_aliases_and_unsafe_symlink_targets_are_rejected(self) -> None:
        normalized: dict[tuple[str, ...], str] = {}
        verifier._record_bundle_path("Contents/Frameworks/QtCore", normalized, "fixture")
        with self.assertRaisesRegex(verifier.MetadataVerificationError, "aliases"):
            verifier._record_bundle_path(
                "Contents/Frameworks/qtcore",
                normalized,
                "fixture",
            )
        for first, second in (
            ("Contents/Frameworks/One", "Contents/FRAMEWORKS/Two"),
            (
                "Contents/Framéworks/One",
                f"Contents/{unicodedata.normalize('NFD', 'Framéworks')}/Two",
            ),
        ):
            with self.subTest(first=first, second=second):
                prefixes: dict[tuple[str, ...], str] = {}
                verifier._record_bundle_path(first, prefixes, "fixture")
                with self.assertRaisesRegex(verifier.MetadataVerificationError, "aliases"):
                    verifier._record_bundle_path(second, prefixes, "fixture")

        unsafe_targets = (
            "",
            "/outside",
            "C:/outside",
            "part//child",
            "..",
            "\udcff",
            "a" * (16384 + 1),
        )
        for target in unsafe_targets:
            with self.subTest(target=target[:20]), self.assertRaises(verifier.MetadataVerificationError):
                verifier._symlink_destination("Top/link", target, "fixture")

    def test_framework_symlink_chain_resolves_to_a_physical_member(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            app = Path(raw_root).resolve() / "GM2Godot.app"
            main = app / "Contents/MacOS/GM2Godot"
            framework = app / "Contents" / "Frameworks" / "QtCore.framework"
            library = framework / "Versions" / "A" / "QtCore"
            main.parent.mkdir(parents=True)
            library.parent.mkdir(parents=True)
            main.write_bytes(_macho())
            main.chmod(0o755)
            library.write_bytes(_macho(filetype=6))
            (framework / "Versions" / "Current").symlink_to("A")
            (framework / "QtCore").symlink_to("Versions/Current/QtCore")

            inventory = verifier._inspect_directory_inventory(
                app,
                "arm64",
                "framework app",
            )

        self.assertEqual(len(inventory.mach_o_files), 2)
        self.assertEqual(len(inventory.symlinks), 2)

    def test_inventory_uses_magic_not_extensions_and_requires_executable_main(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            app = Path(raw_root).resolve() / "GM2Godot.app"
            main = app / "Contents/MacOS/GM2Godot"
            disguised = app / "Contents" / "Resources" / "native.txt"
            decoy = app / "Contents" / "Frameworks" / "not-native.dylib"
            main.parent.mkdir(parents=True)
            disguised.parent.mkdir(parents=True)
            decoy.parent.mkdir(parents=True)
            main.write_bytes(_macho())
            main.chmod(0o755)
            disguised.write_bytes(_macho(filetype=6))
            decoy.write_text("not Mach-O", encoding="utf-8")

            inventory = verifier._inspect_directory_inventory(
                app,
                "arm64",
                "fixture app",
            )

        self.assertEqual(
            tuple(item.relative_path for item in inventory.mach_o_files),
            ("Contents/MacOS/GM2Godot", "Contents/Resources/native.txt"),
        )

    def test_main_must_be_launchable_and_zip_records_reviewed_mode(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            app = Path(raw_root).resolve() / "GM2Godot.app"
            main = app / "Contents/MacOS/GM2Godot"
            main.parent.mkdir(parents=True)
            main.write_bytes(_macho())
            main.chmod(0o644)
            with self.assertRaisesRegex(verifier.MetadataVerificationError, "not executable"):
                verifier._inspect_directory_inventory(app, "arm64", "fixture app")

        archive_bytes = BytesIO()
        member = zipfile.ZipInfo("GM2Godot.app/Contents/MacOS/GM2Godot")
        member.create_system = 3
        member.external_attr = (stat.S_IFREG | 0o755) << 16
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr(member, _macho())
        archive_bytes.seek(0)
        with zipfile.ZipFile(archive_bytes) as archive:
            inventory = verifier._inspect_zip_inventory(
                archive,
                archive.infolist(),
                "arm64",
            )
        self.assertEqual(inventory.mach_o_files[0].mode, 0o755)

    def test_zip_rejects_implicit_case_and_unicode_ancestor_aliases(self) -> None:
        for first, second in (
            ("Frameworks/One/a", "FRAMEWORKS/Two/b"),
            (
                "Framéworks/One/a",
                f"{unicodedata.normalize('NFD', 'Framéworks')}/Two/b",
            ),
        ):
            content = BytesIO()
            with zipfile.ZipFile(content, "w") as archive:
                for relative, contents in ((first, b"a"), (second, b"b")):
                    member = zipfile.ZipInfo(f"GM2Godot.app/Contents/{relative}")
                    member.create_system = 3
                    member.external_attr = (stat.S_IFREG | 0o644) << 16
                    archive.writestr(member, contents)
            content.seek(0)
            with (
                zipfile.ZipFile(content) as archive,
                self.assertRaisesRegex(
                    verifier.MetadataVerificationError,
                    "aliases",
                ),
            ):
                verifier._inspect_zip_inventory(
                    archive,
                    archive.infolist(),
                    "arm64",
                )

    def test_zip_rejects_non_unix_creator_before_mode_interpretation(self) -> None:
        for creator in (0, 1, 2, 4):
            content = BytesIO()
            member = zipfile.ZipInfo("GM2Godot.app/Contents/MacOS/GM2Godot")
            member.create_system = creator
            member.external_attr = (stat.S_IFREG | 0o755) << 16
            with zipfile.ZipFile(content, "w") as archive:
                archive.writestr(member, _macho())
            content.seek(0)
            with (
                self.subTest(creator=creator),
                zipfile.ZipFile(content) as archive,
                self.assertRaisesRegex(
                    verifier.MetadataVerificationError,
                    "Unix creator metadata",
                ),
            ):
                verifier._inspect_zip_inventory(
                    archive,
                    archive.infolist(),
                    "arm64",
                )

    def test_empty_missing_main_and_wrong_main_filetype_are_rejected(self) -> None:
        cases = {
            "empty": {},
            "missing-main": {
                "Contents/Frameworks/libfixture.dylib": _macho(filetype=6),
            },
            "wrong-main": {
                "Contents/MacOS/GM2Godot": _macho(filetype=6),
            },
        }
        for label, files in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw_root:
                app = Path(raw_root).resolve() / "GM2Godot.app"
                app.mkdir()
                for relative_path, content in files.items():
                    destination = app / relative_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                    if relative_path == "Contents/MacOS/GM2Godot":
                        destination.chmod(0o755)
                with self.assertRaises(verifier.MetadataVerificationError):
                    verifier._inspect_directory_inventory(app, "arm64", "fixture app")

    def test_symlink_must_remain_inside_bundle_and_have_a_physical_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            app = Path(raw_root).resolve() / "GM2Godot.app"
            main = app / "Contents/MacOS/GM2Godot"
            main.parent.mkdir(parents=True)
            main.write_bytes(_macho())
            main.chmod(0o755)
            link = app / "Contents" / "Resources" / "escape"
            link.parent.mkdir(parents=True)
            link.symlink_to("../../../outside")

            with self.assertRaisesRegex(verifier.MetadataVerificationError, "escapes the app bundle"):
                verifier._inspect_directory_inventory(app, "arm64", "fixture app")

    def test_symlink_cycles_and_missing_chain_targets_are_rejected(self) -> None:
        for label, targets, message in (
            ("cycle", {"A": "B", "B": "A"}, "enters a cycle"),
            ("missing", {"A": "B", "B": "missing"}, "has missing target"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw_root:
                app = Path(raw_root).resolve() / "GM2Godot.app"
                main = app / "Contents/MacOS/GM2Godot"
                links = app / "Contents" / "Links"
                main.parent.mkdir(parents=True)
                links.mkdir(parents=True)
                main.write_bytes(_macho())
                main.chmod(0o755)
                for name, target in targets.items():
                    (links / name).symlink_to(target)

                with self.assertRaisesRegex(verifier.MetadataVerificationError, message):
                    verifier._inspect_directory_inventory(app, "arm64", "fixture app")


class TestZipNativeGraph(unittest.TestCase):
    def _archive(self, extra: zipfile.ZipInfo | None = None, content: bytes = b"plain") -> BytesIO:
        output = BytesIO()
        main = zipfile.ZipInfo("GM2Godot.app/Contents/MacOS/GM2Godot")
        main.create_system = 3
        main.external_attr = (stat.S_IFREG | 0o755) << 16
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(main, _macho())
            if extra is not None:
                archive.writestr(extra, content)
        output.seek(0)
        return output

    def test_archive_member_names_original_nul_and_unsafe_components_are_rejected(self) -> None:
        for name in (
            "GM2Godot.app/Contents/a//b",
            "GM2Godot.app/Contents/./a",
            "GM2Godot.app/Contents/../a",
            "GM2Godot.app/Contents/a\\b",
            "/GM2Godot.app/Contents/a",
            "C:/GM2Godot.app/Contents/a",
        ):
            member = zipfile.ZipInfo(name)
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            content = self._archive(member)
            with (
                self.subTest(name=name),
                zipfile.ZipFile(content) as archive,
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")
        original_name = b"GM2Godot.app/Contents/nulXmember"
        member = zipfile.ZipInfo(original_name.decode())
        member.create_system = 3
        member.external_attr = (stat.S_IFREG | 0o644) << 16
        raw = self._archive(member).getvalue()
        self.assertEqual(raw.count(original_name), 2)
        changed = raw.replace(original_name, original_name.replace(b"X", b"\0"))
        with zipfile.ZipFile(BytesIO(changed)) as archive:
            malformed = archive.infolist()[1]
            self.assertIn("\0", malformed.orig_filename)
            self.assertNotIn("\0", malformed.filename)
            with self.assertRaises(verifier.MetadataVerificationError):
                verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")

    def test_archive_special_missing_modes_encryption_and_symlink_parents_are_rejected(self) -> None:
        for mode in (0, stat.S_IFIFO | 0o644, stat.S_IFCHR | 0o644, stat.S_IFSOCK | 0o644):
            member = zipfile.ZipInfo("GM2Godot.app/Contents/special")
            member.create_system = 3
            member.external_attr = mode << 16
            content = self._archive(member)
            # zipfile supplies permissions if external_attr was zero; remove only this recorded field.
            if mode == 0:
                raw = bytearray(content.getvalue())
                second_header = raw.index(b"PK\x01\x02", raw.index(b"PK\x01\x02") + 4)
                struct.pack_into("<I", raw, second_header + 38, 0)
                content = BytesIO(raw)
            with (
                self.subTest(mode=mode),
                zipfile.ZipFile(content) as archive,
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")
        encrypted = bytearray(self._archive().getvalue())
        struct.pack_into("<H", encrypted, encrypted.index(b"PK\x03\x04") + 6, 1)
        struct.pack_into("<H", encrypted, encrypted.index(b"PK\x01\x02") + 8, 1)
        with zipfile.ZipFile(BytesIO(encrypted)) as archive, self.assertRaises(verifier.MetadataVerificationError):
            verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")
        for directory in ("GM2Godot.app/", "GM2Godot.app/Contents/"):
            member = zipfile.ZipInfo(directory)
            member.create_system = 3
            member.external_attr = (stat.S_IFDIR | 0o755) << 16
            positive = self._archive(member, b"")
            with self.subTest(directory=directory, kind="unencrypted"), zipfile.ZipFile(positive) as archive:
                inventory = verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")
                self.assertEqual(len(inventory.mach_o_files), 1)
            encrypted_directory = bytearray(positive.getvalue())
            first_local = encrypted_directory.index(b"PK\x03\x04")
            directory_local = encrypted_directory.index(b"PK\x03\x04", first_local + 4)
            first_central = encrypted_directory.index(b"PK\x01\x02")
            directory_central = encrypted_directory.index(b"PK\x01\x02", first_central + 4)
            struct.pack_into("<H", encrypted_directory, directory_local + 6, 1)
            struct.pack_into("<H", encrypted_directory, directory_central + 8, 1)
            with (
                self.subTest(directory=directory, kind="encrypted"),
                zipfile.ZipFile(BytesIO(encrypted_directory)) as archive,
                self.assertRaisesRegex(verifier.MetadataVerificationError, "encrypted"),
            ):
                verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")
        for kind in (stat.S_IFLNK, stat.S_IFREG):
            output = BytesIO()
            parent = zipfile.ZipInfo("GM2Godot.app/Contents/MacOS")
            parent.create_system = 3
            parent.external_attr = (kind | 0o777) << 16
            main = zipfile.ZipInfo("GM2Godot.app/Contents/MacOS/GM2Godot")
            main.create_system = 3
            main.external_attr = (stat.S_IFREG | 0o755) << 16
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr(parent, b"elsewhere")
                archive.writestr(main, _macho())
            output.seek(0)
            with (
                self.subTest(kind=kind),
                zipfile.ZipFile(output) as archive,
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")

    def test_archive_link_graph_cycles_missing_escape_and_oversize_are_rejected(self) -> None:
        for target in ("/outside", "../../../outside", "missing", "self", "a" * 16385):
            member = zipfile.ZipInfo("GM2Godot.app/Contents/self")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            content = self._archive(member, target.encode())
            with (
                self.subTest(target=target[:20]),
                zipfile.ZipFile(content) as archive,
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")

    def test_main_cannot_be_non_native_or_a_symlink_and_unrelated_resources_are_allowed(self) -> None:
        for contents, mode in ((b"plain", stat.S_IFREG | 0o755), (b"../Frameworks/library", stat.S_IFLNK | 0o777)):
            output = BytesIO()
            main = zipfile.ZipInfo("GM2Godot.app/Contents/MacOS/GM2Godot")
            main.create_system = 3
            main.external_attr = mode << 16
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr(main, contents)
            output.seek(0)
            with (
                self.subTest(mode=mode),
                zipfile.ZipFile(output) as archive,
                self.assertRaises(verifier.MetadataVerificationError),
            ):
                verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")
        output = self._archive()
        with zipfile.ZipFile(output, "a") as archive:
            archive.writestr("README.md", b"safe unrelated readme")
            archive.writestr("__MACOSX/GM2Godot.app/Contents/._Info.plist", b"resource fork")
        output.seek(0)
        with zipfile.ZipFile(output) as archive:
            inventory = verifier._inspect_zip_inventory(archive, archive.infolist(), "arm64")
        self.assertEqual(tuple(row.relative_path for row in inventory.mach_o_files), ("Contents/MacOS/GM2Godot",))


class TestRetainedBundleInputs(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.app = self.root / "ancestor" / "GM2Godot.app"
        main = self.app / "Contents" / "MacOS" / "GM2Godot"
        main.parent.mkdir(parents=True)
        main.write_bytes(_macho())
        main.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_retained_app_root_replacement_is_rejected(self) -> None:
        original_parse = verifier._parse_macho_stream
        swapped = False

        def parse_then_replace(
            stream: BinaryIO, size: int, architecture: str, description: str
        ) -> verifier._MachOHeader | None:
            nonlocal swapped
            parsed = original_parse(stream, size, architecture, description)
            if not swapped:
                swapped = True
                self.app.rename(self.app.with_name("original.app"))
                main = self.app / "Contents" / "MacOS" / "GM2Godot"
                main.parent.mkdir(parents=True)
                main.write_bytes(_macho())
                main.chmod(0o755)
            return parsed

        with (
            mock.patch.object(verifier, "_parse_macho_stream", side_effect=parse_then_replace),
            self.assertRaises(verifier.MetadataVerificationError),
        ):
            verifier._inspect_directory_inventory(self.app, "arm64", "retained fixture")
        self.assertTrue(swapped)

    def test_retained_ancestor_replacement_is_rejected(self) -> None:
        original_parse = verifier._parse_macho_stream
        swapped = False

        def parse_then_replace(
            stream: BinaryIO, size: int, architecture: str, description: str
        ) -> verifier._MachOHeader | None:
            nonlocal swapped
            parsed = original_parse(stream, size, architecture, description)
            if not swapped:
                swapped = True
                ancestor = self.app.parent
                ancestor.rename(self.root / "original-ancestor")
                main = self.app / "Contents" / "MacOS" / "GM2Godot"
                main.parent.mkdir(parents=True)
                main.write_bytes(_macho())
                main.chmod(0o755)
            return parsed

        with (
            mock.patch.object(verifier, "_parse_macho_stream", side_effect=parse_then_replace),
            self.assertRaises(verifier.MetadataVerificationError),
        ):
            verifier._inspect_directory_inventory(self.app, "arm64", "retained fixture")
        self.assertTrue(swapped)

    def test_count_limit_precedes_sorted_materialization(self) -> None:
        for index in range(10):
            (self.app / f"resource-{index}").write_bytes(b"plain")
        original_scandir = os.scandir
        observed: list[str] = []

        @contextmanager
        def counted_scandir(directory: int) -> Generator[Iterator[os.DirEntry[str]], None, None]:
            with original_scandir(directory) as entries:

                def counted_entries() -> Iterator[os.DirEntry[str]]:
                    for entry in entries:
                        observed.append(entry.name)
                        yield entry

                yield counted_entries()

        with (
            mock.patch.object(verifier, "MAX_BUNDLE_ENTRIES", 3),
            mock.patch.object(verifier.os, "scandir", side_effect=counted_scandir),
            self.assertRaisesRegex(verifier.MetadataVerificationError, "entry limit"),
        ):
            verifier._inspect_directory_inventory(self.app, "arm64", "count fixture")
        self.assertEqual(len(observed), 4)

    def test_zip_initial_size_limit_precedes_construction(self) -> None:
        path = self.root / "oversize.zip"
        with path.open("wb") as stream:
            stream.truncate(1_073_741_825)
        with (
            mock.patch.object(verifier.zipfile, "ZipFile") as constructor,
            self.assertRaises(verifier.MetadataVerificationError),
        ):
            verifier.inspect_zip(path, ZIP_POLICY)
        constructor.assert_not_called()
        self.assertEqual(path.stat().st_size, 1_073_741_825)

    def test_zip_directory_read_limit_precedes_allocation(self) -> None:
        path = self.root / "sparse-central-directory.zip"
        central_size = 33_554_433
        with path.open("wb") as stream:
            stream.seek(central_size)
            stream.write(struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1, central_size, 0, 0))
        original_pread = os.pread
        requested: list[int] = []

        def observed_pread(fd: int, size: int, offset: int) -> bytes:
            requested.append(size)
            return original_pread(fd, size, offset)

        with (
            mock.patch.object(verifier.os, "pread", side_effect=observed_pread),
            self.assertRaises(verifier.MetadataVerificationError),
        ):
            verifier.inspect_zip(path, ZIP_POLICY)
        self.assertTrue(requested)
        self.assertLessEqual(max(requested), 1_048_576)
        self.assertLess(sum(requested), 33_554_433)

    def test_zip_initial_eof_and_stat_are_bound(self) -> None:
        for mutation in ("append", "truncate", "replace"):
            with self.subTest(mutation=mutation):
                path = self.root / f"{mutation}.zip"
                member = zipfile.ZipInfo("GM2Godot.app/Contents/Info.plist")
                member.create_system = 3
                member.external_attr = (stat.S_IFREG | 0o644) << 16
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(member, plistlib.dumps(ZIP_POLICY))
                original_read = verifier._BoundedZipReader.read
                original_open = os.open
                opened: list[int] = []

                def tracked_open(
                    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    fd = original_open(path, flags, mode, dir_fd=dir_fd)
                    opened.append(fd)
                    return fd

                original_size = path.stat().st_size
                changed = False
                end_positions: list[int] = []

                def mutate_then_read(reader: verifier._BoundedZipReader, size: int = -1) -> bytes:
                    nonlocal changed
                    if not changed:
                        changed = True
                        if mutation == "append":
                            with path.open("ab") as stream:
                                stream.write(b"growth")
                        elif mutation == "truncate":
                            with path.open("r+b") as stream:
                                stream.truncate(original_size - 1)
                        else:
                            replacement = path.with_suffix(".replacement")
                            replacement.write_bytes(path.read_bytes())
                            replacement.replace(path)
                        previous = reader.tell()
                        end_positions.append(reader.seek(0, os.SEEK_END))
                        reader.seek(previous)
                    return original_read(reader, size)

                with (
                    mock.patch.object(verifier._BoundedZipReader, "read", mutate_then_read),
                    mock.patch.object(verifier.os, "open", new=tracked_open),
                    mock.patch.object(verifier.os, "supports_dir_fd", os.supports_dir_fd | {tracked_open}),
                    self.assertRaises(verifier.MetadataVerificationError),
                ):
                    verifier.inspect_zip(path, ZIP_POLICY)
                self.assertTrue(changed)
                self.assertEqual(end_positions, [original_size])
                self.assertTrue(opened)
                for fd in opened:
                    with self.assertRaises(OSError) as bad:
                        os.fstat(fd)
                    self.assertEqual(bad.exception.errno, errno.EBADF)

    def test_close_preserves_primary_and_attempts_all_fds(self) -> None:
        for primary in (
            verifier.MetadataVerificationError("inspection primary"),
            KeyboardInterrupt("inspection interrupted"),
            SystemExit(23),
            None,
        ):
            for cleanup_type in (OSError, KeyboardInterrupt, SystemExit):
                cleanup = cleanup_type("descriptor cleanup")
                original_open, original_close = os.open, os.close
                opened: list[int] = []
                closed: list[int] = []

                def tracked_open(
                    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    fd = original_open(path, flags, mode, dir_fd=dir_fd)
                    opened.append(fd)
                    return fd

                def close_then_fail(fd: int) -> None:
                    closed.append(fd)
                    original_close(fd)
                    raise cleanup

                with (
                    self.subTest(primary=type(primary).__name__, cleanup=cleanup_type.__name__),
                    mock.patch.object(verifier.os, "open", new=tracked_open),
                    mock.patch.object(verifier.os, "supports_dir_fd", os.supports_dir_fd | {tracked_open}),
                    mock.patch.object(verifier.os, "close", side_effect=close_then_fail),
                ):
                    if primary is None:
                        with self.assertRaises(cleanup_type) as raised:
                            verifier._inspect_directory_inventory(self.app, "arm64", "close fixture")
                        self.assertIs(raised.exception, cleanup)
                    else:
                        with (
                            mock.patch.object(verifier, "_parse_macho_stream", side_effect=primary),
                            self.assertRaises(type(primary)) as raised,
                        ):
                            verifier._inspect_directory_inventory(self.app, "arm64", "close fixture")
                        self.assertIs(raised.exception, primary)
                        self.assertIn("descriptor cleanup", "\n".join(getattr(primary, "__notes__", ())))
                self.assertTrue(opened)
                self.assertCountEqual(closed, opened)
                self.assertEqual(len(closed), len(set(closed)))
                for fd in opened:
                    with self.assertRaises(OSError) as bad:
                        os.fstat(fd)
                    self.assertEqual(bad.exception.errno, errno.EBADF)


if __name__ == "__main__":
    unittest.main()
