"""Mechanism fixtures only: these tests never create native proposal proof."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Callable, TypedDict, cast
from unittest import mock

PRODUCER_PATH = Path(__file__).resolve().parents[1] / "scripts/propose_native_wheels.py"
SOURCE_ROOT = Path(os.environ.get("GM2GODOT_PROPOSAL_SOURCE_ROOT", str(PRODUCER_PATH.parents[1]))).resolve()


def _load_producer() -> ModuleType:
    specification = importlib.util.spec_from_file_location("_native_wheel_proposal_test_subject", PRODUCER_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("producer fixture unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


PRODUCER = _load_producer()
ERROR = cast(type[ValueError], getattr(PRODUCER, "ProposalError"))


class _WheelStringCase(TypedDict, total=False):
    metadata_name: str
    wheel_tag: str
    directory: str
    tag: str


class TestNativeWheelProposals(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def _wheel(self, *, name: str = "sample-pkg", version: str = "1.0", tag: str = "py3-none-any",
               metadata_name: str | None = None, wheel_tag: str | None = None,
               directory: str = "sample_pkg-1.0.dist-info", duplicate: bool = False,
               unsafe: bool = False) -> Path:
        path = self.root / f"{name.replace('-', '_')}-{version}-{tag}.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(directory + "/METADATA", f"Metadata-Version: 2.1\nName: {metadata_name or name}\nVersion: {version}\n\n")
            archive.writestr(directory + "/WHEEL", f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: {wheel_tag or tag}\n\n")
            archive.writestr("sample_pkg/__init__.py", b"# Never executed fixture.\n")
            if duplicate:
                with self.assertWarns(UserWarning):
                    archive.writestr(directory + "/METADATA", b"Name: duplicated\n")
            if unsafe:
                archive.writestr("../outside", b"unsafe")
        return path

    def _observe(self, path: Path, native: frozenset[str] = frozenset({"py3-none-any"})) -> dict[str, object]:
        # Explicitly modeled parser for this fixed fixture, never native proof.
        # Actual observations omit the seam and use verified Packaging APIs.
        def filename(value: str) -> tuple[str, str, frozenset[str]]:
            name, version, python, abi, host = value.removesuffix(".whl").split("-")
            return name.replace("_", "-"), version, frozenset({f"{python}-{abi}-{host}"})

        def tags(value: str) -> frozenset[str]:
            return frozenset({value})

        def version(value: str) -> str:
            return value

        parser_type = cast(Callable[..., object], getattr(PRODUCER, "WheelParser"))
        parser = parser_type(filename, tags, version)
        function = cast(Callable[..., dict[str, object]], getattr(PRODUCER, "_observe_wheel"))
        return function(path, {"sample-pkg": "1.0"}, native, parser)

    def test_isolated_cli_help_starts_from_unrelated_directory_without_public_imports(self) -> None:
        completed = subprocess.run([sys.executable, "-I", "-S", str(PRODUCER_PATH), "--help"],
                                   cwd=self.root, capture_output=True, timeout=15, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(b"--work-root", completed.stdout)
        self.assertNotIn(b"--output-root", completed.stdout)
        tree = PRODUCER_PATH.read_text()
        self.assertNotIn("sys.path.", tree)
        self.assertNotIn("PYTHONPATH=", tree)

    def test_deferred_public_packaging_apis_load_explicitly_and_fail_closed(self) -> None:
        prior = sys.modules[PRODUCER.__name__]
        self.addCleanup(sys.modules.__setitem__, PRODUCER.__name__, prior)
        with mock.patch.object(PRODUCER.importlib, "import_module") as imports:
            _load_producer()
            imports.assert_not_called()
        calls: list[tuple[str, str]] = []

        def filename(value: str) -> tuple[str, str, tuple[()], frozenset[str]]:
            calls.append(("filename", value))
            return "sample-pkg", "1.0", (), frozenset({"py3-none-any"})

        def tags(value: str) -> frozenset[str]:
            calls.append(("tag", value))
            return frozenset({value})

        def version(value: str) -> str:
            calls.append(("version", value))
            return value

        modules = {name: ModuleType(name) for name in ("packaging.tags", "packaging.utils", "packaging.version")}
        setattr(modules["packaging.tags"], "parse_tag", tags)
        setattr(modules["packaging.utils"], "parse_wheel_filename", filename)
        setattr(modules["packaging.version"], "Version", version)
        source_path = self.root / "modeled-public-tags.py"
        setattr(modules["packaging.tags"], "__file__", str(source_path))
        load = cast(Callable[[], object], getattr(PRODUCER, "public_wheel_parser"))
        source = cast(Callable[[str], Path], getattr(PRODUCER, "_packaging_source_path"))
        with mock.patch.object(PRODUCER.importlib, "import_module", side_effect=modules.__getitem__) as imports:
            parser = load()
            parse_filename = cast(Callable[[str], object], getattr(parser, "filename"))
            parse_tags = cast(Callable[[str], object], getattr(parser, "tags"))
            parse_version = cast(Callable[[str], object], getattr(parser, "version"))
            self.assertEqual(parse_filename("sample_pkg-1.0-py3-none-any.whl"),
                ("sample-pkg", "1.0", frozenset({"py3-none-any"})))
            self.assertEqual(parse_tags("py3-none-any"), frozenset({"py3-none-any"}))
            self.assertEqual(parse_version("1.0"), "1.0")
            self.assertEqual(source("packaging.tags"), source_path)
            self.assertEqual([call.args[0] for call in imports.call_args_list],
                ["packaging.tags", "packaging.utils", "packaging.version", "packaging.tags"])
        self.assertEqual(calls, [("filename", "sample_pkg-1.0-py3-none-any.whl"),
            ("tag", "py3-none-any"), ("version", "1.0")])
        for failure in (ImportError("missing public Packaging"), AttributeError("missing public API")):
            with self.subTest(failure=failure), \
                 mock.patch.object(PRODUCER.importlib, "import_module", side_effect=failure):
                with self.assertRaisesRegex(ERROR, "API unavailable") as caught:
                    load()
                self.assertIs(caught.exception.__cause__, failure)
        missing = ModuleType("packaging.tags")
        with mock.patch.object(PRODUCER.importlib, "import_module", return_value=missing):
            with self.assertRaisesRegex(ERROR, "API unavailable"):
                load()
        setattr(missing, "parse_tag", None)
        with mock.patch.object(PRODUCER.importlib, "import_module", return_value=missing):
            with self.assertRaisesRegex(ERROR, "not callable"):
                load()
            for value in (None, 7, ""):
                with self.subTest(source_path=value):
                    setattr(missing, "__file__", value)
                    with self.assertRaisesRegex(ERROR, "no source path"):
                        source("packaging.tags")

    def test_cli_rejects_nonisolated_startup_and_nonpositive_provenance(self) -> None:
        for arguments, isolated in ((["--help"], False), (["--run-id", "0"], True), (["--run-attempt", "-1"], True)):
            with self.subTest(arguments=arguments):
                completed = subprocess.run([sys.executable, *(["-I"] if isolated else []), str(PRODUCER_PATH), *arguments],
                                           cwd=self.root, capture_output=True, timeout=15, check=False)
                self.assertEqual(completed.returncode, 2)
        positive = cast(Callable[[str], int], getattr(PRODUCER, "_positive_integer"))
        self.assertEqual(positive("37"), 37)
        for value in ("0", "-1", "True", "1.0", "+1", "01"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                positive(value)

    def test_native_mismatch_precedes_source_reads_or_environment_creation(self) -> None:
        produce = cast(Callable[[argparse.Namespace], int], getattr(PRODUCER, "produce"))
        observed = {"python_version": "3.14.7", "sys_platform": "darwin", "os_name": "posix", "system": "Darwin", "machine": "arm64", "implementation": "cpython"}
        with mock.patch.object(PRODUCER, "native_identity", return_value=observed), mock.patch.object(PRODUCER, "bind_source") as source:
            with self.assertRaisesRegex(ERROR, "native tuple mismatch"):
                produce(argparse.Namespace(platform="macos-arm64"))
            source.assert_not_called()

    def test_version_and_companion_parsers_reject_lossy_or_partial_pin_sets(self) -> None:
        parse = cast(Callable[[bytes], dict[str, str]], getattr(PRODUCER, "exact_pins"))
        self.assertEqual(parse(b"# canonical header\nSample_Pkg==1.0\nother==2.0 # note\n"), {"sample-pkg": "1.0", "other": "2.0"})
        for payload in (b"", b"sample==1.0\nsample_==1.0\nsample-==1.0\n", b"sample==1.0\nSample==1.0\n", b"sample>=1.0\n", b"sample @ https://example.invalid/a.whl\n", b"sample==1.0 \\\n --hash=sha256:abc\n"):
            with self.subTest(payload=payload), self.assertRaises(ERROR):
                parse(payload)
        companion = cast(Callable[[bytes], object], getattr(PRODUCER, "parse_companion"))
        for payload in (b"", b"pip==26.2.1\n", b"pip==26.2.1 --hash=sha256:" + b"a" * 64 + b"\r\n", b"pip==26.2.1 --hash=sha256:" + b"a" * 64):
            with self.subTest(payload=payload), self.assertRaises(ERROR):
                companion(payload)

    def test_companion_hashes_are_actual_fixture_bytes_and_exact_closed_projection(self) -> None:
        wheel = self._wheel()
        row = self._observe(wheel)
        companion = cast(Callable[[dict[str, str], list[dict[str, object]]], bytes], getattr(PRODUCER, "companion_bytes"))
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        self.assertEqual(row["sha256"], digest)
        self.assertEqual(row["size"], wheel.stat().st_size)
        self.assertEqual(companion({"sample-pkg": "1.0"}, [row]), f"sample-pkg==1.0 --hash=sha256:{digest}\n".encode())
        for pins, rows in (({"sample-pkg": "1.0", "transitive": "2.0"}, [row]), ({"sample-pkg": "2.0"}, [row]), ({"sample-pkg": "1.0"}, [row, row])):
            with self.subTest(pins=pins), self.assertRaises(ERROR):
                companion(pins, rows)

    def test_real_wheel_fixture_requires_metadata_directory_and_native_tag_agreement(self) -> None:
        cases: tuple[_WheelStringCase, ...] = ({"metadata_name": "other"}, {"wheel_tag": "cp312-cp312-win_amd64"}, {"directory": "other-1.0.dist-info"}, {"tag": "cp312-cp312-win_amd64"})
        for settings in cases:
            with self.subTest(settings=settings), self.assertRaises(ERROR):
                self._observe(self._wheel(metadata_name=settings.get("metadata_name"),
                    wheel_tag=settings.get("wheel_tag"), directory=settings.get("directory", "sample_pkg-1.0.dist-info"),
                    tag=settings.get("tag", "py3-none-any")))
        positive = self._observe(self._wheel())
        self.assertEqual(positive["compatible_tags"], ["py3-none-any"])

    def test_real_wheel_fixture_rejects_duplicates_traversal_and_modified_bytes(self) -> None:
        for duplicate, unsafe in ((True, False), (False, True)):
            with self.subTest(duplicate=duplicate, unsafe=unsafe), self.assertRaises(ERROR):
                self._observe(self._wheel(duplicate=duplicate, unsafe=unsafe))
        wheel = self._wheel()
        first = self._observe(wheel)
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("sample_pkg/changed.py", b"# additional fixture bytes\n")
        second = self._observe(wheel)
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(first["size"], second["size"])

    def test_retained_regular_file_guards_reject_aliases_bounds_and_reparse_targets(self) -> None:
        read = cast(Callable[[Path, int], bytes], getattr(PRODUCER, "read_regular"))
        path = self.root / "sealed"
        path.write_bytes(b"fixture")
        self.assertEqual(read(path, 7), b"fixture")
        with self.assertRaises(ERROR):
            read(path, 6)
        alias = self.root / "linked"
        os.link(path, alias)
        with self.assertRaises(ERROR):
            read(path, 7)
        alias.unlink()
        if os.name == "posix":
            alias.symlink_to(path)
            with self.assertRaises(ERROR):
                read(alias, 7)
            alias.unlink()
        # The all-host model represents lstat's symlink/reparse classification,
        # without depending on a Windows account's symlink creation privilege.
        modeled = mock.Mock(spec=os.stat_result)
        modeled.st_mode = stat.S_IFLNK | 0o777
        modeled.st_file_attributes = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
        with mock.patch.object(Path, "lstat", return_value=modeled), \
             mock.patch.object(Path, "open") as opening:
            with self.assertRaises(ERROR):
                read(alias, 7)
            opening.assert_not_called()

    def test_cross_view_stat_binding_preserves_windows_creation_identity_and_posix_ctime(self) -> None:
        compare = cast(Callable[[os.stat_result, os.stat_result], bool],
                       getattr(PRODUCER, "same_file_across_views"))
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns")
        common: dict[str, int] = {
            "st_dev": 11, "st_ino": 22, "st_mode": stat.S_IFREG | 0o644,
            "st_nlink": 1, "st_size": 7, "st_mtime_ns": 300,
        }

        def view(missing_birthtime: bool = False, /, **changes: object) -> os.stat_result:
            # Explicit path/fd metadata model, not native Windows evidence.
            values: dict[str, object] = {**common, "st_ctime_ns": 100, "st_birthtime_ns": 100}
            values.update(changes)
            if missing_birthtime:
                values.pop("st_birthtime_ns")
            return cast(os.stat_result, SimpleNamespace(**values))

        named, opened = view(), view(st_ctime_ns=200)
        with mock.patch.object(PRODUCER.sys, "platform", "win32"):
            self.assertTrue(compare(named, opened))
            for field in fields:
                with self.subTest(field=field):
                    self.assertFalse(compare(named, view(st_ctime_ns=200, **{field: common[field] + 1})))
            for birthtime in (101, None, True, False, 100.0, "100"):
                with self.subTest(birthtime=birthtime):
                    self.assertFalse(compare(named, view(st_ctime_ns=200, st_birthtime_ns=birthtime)))
                    self.assertFalse(compare(view(st_birthtime_ns=birthtime), opened))
                    if type(birthtime) is not int:
                        self.assertFalse(compare(view(st_birthtime_ns=birthtime),
                                                 view(st_ctime_ns=200, st_birthtime_ns=birthtime)))
            self.assertFalse(compare(named, view(True, st_ctime_ns=200)))
            self.assertFalse(compare(view(True), opened))
            self.assertFalse(compare(view(True),
                                     view(True, st_ctime_ns=200)))
        with mock.patch.object(PRODUCER.sys, "platform", "linux"):
            self.assertFalse(compare(named, opened))
            self.assertTrue(compare(named, view()))

    def test_owned_descriptor_seals_reject_change_time_drift_after_read(self) -> None:
        path = self.root / "retained-metadata"
        payload = b"actual retained fixture bytes"
        path.write_bytes(payload)
        original = path.lstat()
        actual_fstat = os.fstat
        binding = cast(Callable[[os.stat_result], tuple[int, ...]], getattr(PRODUCER, "file_binding"))
        functions: tuple[tuple[str, Callable[[Path, int], object], object], ...] = (
            ("read", cast(Callable[[Path, int], object], getattr(PRODUCER, "read_regular")), payload),
            ("hash", cast(Callable[[Path, int], object], getattr(PRODUCER, "hash_regular")),
             (len(payload), hashlib.sha256(payload).hexdigest())),
        )

        def view(value: os.stat_result, ctime_ns: int) -> os.stat_result:
            fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns")
            values: dict[str, object] = {field: getattr(value, field) for field in fields}
            values.update(st_ctime_ns=ctime_ns, st_birthtime_ns=100)
            return cast(os.stat_result, SimpleNamespace(**values))

        for name, function, expected in functions:
            for changed_fd in (False, True):
                with self.subTest(function=name, changed_fd=changed_fd):
                    descriptors: list[int] = []

                    def observed_fstat(descriptor: int) -> os.stat_result:
                        # Forward every call to the real retained descriptor;
                        # only its reported ChangeTime is modeled after reading.
                        observed = actual_fstat(descriptor)
                        descriptors.append(descriptor)
                        self.assertEqual((observed.st_dev, observed.st_ino),
                                         (original.st_dev, original.st_ino))
                        return view(observed, 201 if changed_fd and len(descriptors) > 1 else 200)

                    with mock.patch.object(PRODUCER.sys, "platform", "win32"), \
                         mock.patch.object(Path, "lstat", return_value=view(original, 100)), \
                         mock.patch.object(PRODUCER.os, "fstat", side_effect=observed_fstat):
                        if changed_fd:
                            with self.assertRaisesRegex(ERROR, "changed.*(?:reading|hashing)"):
                                function(path, len(payload))
                        else:
                            self.assertEqual(function(path, len(payload)), expected)
                    self.assertEqual(len(descriptors), 2)
                    self.assertEqual(descriptors[0], descriptors[1])
                    with self.assertRaises(OSError) as closed:
                        actual_fstat(descriptors[0])
                    self.assertEqual(closed.exception.errno, errno.EBADF)
                    self.assertEqual(path.read_bytes(), payload)
                    self.assertEqual(binding(path.lstat()), binding(original))

    def test_actual_git_source_binding_rejects_drift_redirects_and_oversized_blobs(self) -> None:
        source = self.root / "source-checkout"
        source.mkdir()
        files = self._source_helpers()
        roots = cast(tuple[str, ...], getattr(PRODUCER, "ROOTS"))
        for name in roots:
            files[name] = b"# source-binding fixture; never resolved\npip==26.2.1\npip-tools==7.6.1\n"
        seed = "constraints/requirements-linux-py312.lock"
        files[seed] = b"# source-binding fixture\npip==26.2.1\npip-tools==7.6.1\n"
        for relative, payload in files.items():
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        environment = cast(Callable[..., dict[str, str]], getattr(PRODUCER, "isolated_environment"))(os.environ)
        for selector in cast(frozenset[str], getattr(PRODUCER, "GIT_SELECTORS")):
            environment.pop(selector, None)
        environment.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                            "GIT_CONFIG_SYSTEM": os.devnull})
        actual_run = subprocess.run

        def git(*arguments: str) -> bytes:
            completed = actual_run(["git", "-C", str(source), *arguments], env=environment,
                stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertLess(len(completed.stdout) + len(completed.stderr), 1_048_576)
            return completed.stdout

        git("init", "-b", "main")
        git("config", "user.name", "Local source fixture")
        git("config", "user.email", "source-fixture@example.invalid")
        git("config", "core.autocrlf", "false")
        git("add", "--all")
        git("commit", "-m", "Create local source-binding fixture")
        head = git("rev-parse", "HEAD").decode().strip()
        bind = cast(Callable[..., tuple[dict[str, bytes], dict[str, str]]], getattr(PRODUCER, "bind_source"))
        fixture_producer = source / "scripts/propose_native_wheels.py"
        with mock.patch.object(PRODUCER, "__file__", str(fixture_producer)), \
             mock.patch.dict(PRODUCER.os.environ, environment, clear=True):
            observed, layout = bind(source, head, "linux-x64", "discover")
            self.assertEqual(observed, files)
            self.assertEqual(layout["linux-x64"], seed)
            (source / seed).write_bytes(files[seed] + b"# actual checkout-byte drift\n")
            with self.assertRaisesRegex(ERROR, "physical source differs") as drift:
                bind(source, head, "linux-x64", "discover")
            self.assertIn("CRLF-only difference=False", str(drift.exception))
            self.assertIn("sha256=" + hashlib.sha256(files[seed]).hexdigest(), str(drift.exception))
            (source / seed).write_bytes(files[seed].replace(b"\n", b"\r\n"))
            with self.assertRaisesRegex(ERROR, "physical source differs") as newline_drift:
                bind(source, head, "linux-x64", "discover")
            self.assertIn("CRLF-only difference=True", str(newline_drift.exception))
            (source / seed).write_bytes(files[seed])
            with self.assertRaisesRegex(ERROR, "HEAD differs"):
                bind(source, "0" * 40, "linux-x64", "discover")
            with mock.patch.dict(PRODUCER.os.environ, {"GIT_DIR": str(self.root / "redirect")}), \
                 mock.patch.object(PRODUCER.subprocess, "run", wraps=actual_run) as calls:
                with self.assertRaisesRegex(ERROR, "repository selectors"):
                    bind(source, head, "linux-x64", "discover")
                calls.assert_not_called()
            (source / "oversized-source.txt").write_bytes(b"x" * 1_048_577)
            git("add", "oversized-source.txt")
            git("commit", "-m", "Add oversized immutable fixture blob")
            oversized_head = git("rev-parse", "HEAD").decode().strip()
            bounded_git = cast(Callable[[Path, list[str]], bytes], getattr(PRODUCER, "_git"))
            with mock.patch.object(PRODUCER.subprocess, "run", wraps=actual_run) as calls:
                with self.assertRaisesRegex(ERROR, "blob type/size bound"):
                    bounded_git(source, ["cat-file", "blob", f"{oversized_head}:oversized-source.txt"])
            self.assertEqual(calls.call_count, 1)
            self.assertEqual(calls.call_args.args[0][-3:],
                ["cat-file", "-s", f"{oversized_head}:oversized-source.txt"])

    def test_hash_streaming_is_bounded_and_seals_actual_regular_bytes(self) -> None:
        path = self.root / "large-fixture"
        payload = b"actual-fixture" * 100_000
        path.write_bytes(payload)
        hash_file = cast(Callable[[Path, int], tuple[int, str]], getattr(PRODUCER, "hash_regular"))
        self.assertEqual(hash_file(path, len(payload)), (len(payload), hashlib.sha256(payload).hexdigest()))
        with self.assertRaises(ERROR):
            hash_file(path, len(payload) - 1)

    def test_committed_layout_never_falls_back_on_a_partial_split(self) -> None:
        select = cast(Callable[[Path, str], dict[str, str]], getattr(PRODUCER, "version_layout"))
        self.assertEqual(select(self.root, "discover")["macos-x64"], "constraints/requirements-macos-py312.lock")
        constraints = self.root / "constraints"
        constraints.mkdir()
        (constraints / "requirements-macos-arm64-py312.lock").write_bytes(b"fixture")
        with self.assertRaisesRegex(ERROR, "partial"):
            select(self.root, "require-committed")
        (constraints / "requirements-macos-x64-py312.lock").write_bytes(b"fixture")
        self.assertEqual(select(self.root, "require-committed")["macos-x64"], "constraints/requirements-macos-x64-py312.lock")

    def test_authenticated_snapshot_keeps_original_checkout_changes_out_of_execution(self) -> None:
        helpers = cast(tuple[str, ...], getattr(PRODUCER, "HELPERS"))
        files = {name: b"# authenticated fixture helper\n" for name in helpers}
        files["requirements-bootstrap.txt"] = b"pip==26.2.1\npip-tools==7.6.1\n"
        anchor = ModuleType("fixture-anchor")

        def identical(path: Path, payload: bytes) -> None:
            if path.exists():
                self.assertEqual(path.read_bytes(), payload)
            else:
                with path.open("xb") as stream:
                    stream.write(payload)

        setattr(anchor, "publish_identical_receipt_bytes", identical)
        prepare = cast(Callable[[Path, dict[str, bytes]], tuple[Path, Callable[[Path, bytes], None]]], getattr(PRODUCER, "prepare_snapshot"))
        with mock.patch.object(PRODUCER, "load_sibling", return_value=anchor) as load:
            export, publisher = prepare(self.root, files)
            self.assertIs(publisher, identical)
            self.assertEqual(load.call_args.args[-1], export / "scripts")
        original = self.root / "changed-checkout.py"
        original.write_bytes(files["scripts/propose_native_wheels.py"])
        original.write_bytes(b"raise RuntimeError('changed original checkout')\n")
        self.assertEqual((export / "scripts/propose_native_wheels.py").read_bytes(), b"# authenticated fixture helper\n")
        self.assertEqual((export / "requirements-bootstrap.txt").read_bytes(), files["requirements-bootstrap.txt"])

    def test_guardian_cleanup_reaps_after_signal_failure_and_preserves_control_identity(self) -> None:
        run = cast(Callable[..., dict[str, object]], getattr(PRODUCER, "run_command"))
        primary = KeyboardInterrupt("original command interruption")
        acquired = mock.MagicMock(spec=subprocess.Popen)
        acquired.pid = 111
        acquired.stdin = mock.Mock()
        acquired.stdin.close.side_effect = OSError("stdin close failure")

        def publish(path: Path, payload: bytes) -> None:
            with path.open("xb") as stream:
                stream.write(payload)

        with mock.patch.object(PRODUCER, "_require_private_guardian_ownership"), \
             mock.patch.object(PRODUCER.subprocess, "Popen", return_value=acquired), \
             mock.patch.object(PRODUCER.time, "monotonic", side_effect=primary), \
             mock.patch.object(PRODUCER.os, "killpg", create=True, side_effect=OSError("group signal failure")):
            with self.assertRaises(KeyboardInterrupt) as caught:
                run(["fixture-command"], cwd=self.root, environment={}, work=self.root,
                    label="fixture", publisher=publish, guardian_path=self.root / "captured-producer.py")
        self.assertIs(caught.exception, primary)
        acquired.wait.assert_called_once_with(timeout=15)
        acquired.stdin.close.assert_called_once_with()
        notes = "\n".join(getattr(primary, "__notes__", ()))
        if os.name == "posix":
            self.assertIn("group signal failure", notes)
        self.assertIn("stdin close failure", notes)

    def test_windows_job_setup_models_handle_width_and_fail_closed_before_child_launch(self) -> None:
        job = cast(Callable[[], object], getattr(PRODUCER, "_windows_guard_job"))
        high_handle = 0x100001234
        for failure in ("create", "configure", "assign", None):
            with self.subTest(failure=failure):
                kernel = mock.Mock()
                kernel.CreateJobObjectW.return_value = 0 if failure == "create" else high_handle
                kernel.SetInformationJobObject.return_value = 0 if failure == "configure" else 1
                kernel.AssignProcessToJobObject.return_value = 0 if failure == "assign" else 1
                kernel.GetCurrentProcess.return_value = -1
                kernel.CloseHandle.return_value = 1
                with mock.patch.object(PRODUCER.ctypes, "WinDLL", create=True, return_value=kernel) as load, \
                     mock.patch.object(PRODUCER.ctypes, "get_last_error", create=True, return_value=5):
                    if failure:
                        with self.assertRaises(OSError) as caught:
                            job()
                        self.assertEqual(caught.exception.errno, 5)
                    else:
                        self.assertEqual(job(), high_handle)
                load.assert_called_once_with("kernel32", use_last_error=True)
                self.assertIs(kernel.CreateJobObjectW.restype, ctypes.c_void_p)
                self.assertEqual(kernel.AssignProcessToJobObject.argtypes, (ctypes.c_void_p, ctypes.c_void_p))
                self.assertEqual(kernel.CloseHandle.argtypes, (ctypes.c_void_p,))
                self.assertIs(kernel.AssignProcessToJobObject.restype, ctypes.c_int32)
                if failure != "create":
                    configured = kernel.SetInformationJobObject.call_args.args
                    self.assertEqual(configured[0:2], (high_handle, 9))
                    self.assertEqual(configured[3], 144)
                    limits = getattr(configured[2], "_obj")
                    self.assertEqual(getattr(getattr(limits, "basic"), "flags"), 0x2000)
                if failure == "create":
                    kernel.CloseHandle.assert_not_called()
                    kernel.SetInformationJobObject.assert_not_called()
                elif failure in ("configure", "assign"):
                    kernel.CloseHandle.assert_called_once_with(high_handle)
                else:
                    kernel.CloseHandle.assert_not_called()
                if failure in ("create", "configure"):
                    kernel.AssignProcessToJobObject.assert_not_called()
                else:
                    kernel.AssignProcessToJobObject.assert_called_once_with(high_handle, -1)

    def test_windows_job_setup_models_preserve_primary_when_close_raises_or_returns_false(self) -> None:
        job = cast(Callable[[], object], getattr(PRODUCER, "_windows_guard_job"))
        for cleanup in (False, OSError("modeled native close error"), KeyboardInterrupt("modeled close control")):
            with self.subTest(cleanup=cleanup):
                primary = SystemExit(0)
                kernel = mock.Mock()
                kernel.CreateJobObjectW.return_value = 0x100001234
                kernel.SetInformationJobObject.side_effect = primary
                kernel.CloseHandle.side_effect = cleanup if isinstance(cleanup, BaseException) else None
                kernel.CloseHandle.return_value = cleanup
                with mock.patch.object(PRODUCER.ctypes, "WinDLL", create=True, return_value=kernel), \
                     mock.patch.object(PRODUCER.ctypes, "get_last_error", create=True, return_value=5):
                    with self.assertRaises(SystemExit) as caught:
                        job()
                self.assertIs(caught.exception, primary)
                self.assertIn("CloseHandle", "\n".join(getattr(primary, "__notes__", ())))
                kernel.AssignProcessToJobObject.assert_not_called()

    def _source_helpers(self) -> dict[str, bytes]:
        helpers = cast(tuple[str, ...], getattr(PRODUCER, "HELPERS"))
        result: dict[str, bytes] = {}
        for name in helpers:
            if not name.endswith(".py"):
                result[name] = b"# workflow fixture; never executed\n"
            elif name == "scripts/propose_native_wheels.py":
                result[name] = PRODUCER_PATH.read_bytes()
            elif name == "scripts/verify_native_wheel_proposal.py":
                result[name] = b"# independent validator fixture; never executed\n"
            else:
                result[name] = (SOURCE_ROOT / name).read_bytes()
        return result

    def test_actual_supervisor_bounds_output_timeout_and_descendant_lifetime(self) -> None:
        prepare = cast(Callable[..., tuple[Path, Callable[[Path, bytes], None]]], getattr(PRODUCER, "prepare_snapshot"))
        # A prior fixture may have loaded the same anchored module name: each
        # actual isolated CLI owns one snapshot. This test models that lifetime.
        name = "_gm2godot_native_proposal_snapshot_anchor"
        prior = sys.modules.pop(name, None)
        self.addCleanup(sys.modules.pop, name, None)
        if prior is not None:
            self.addCleanup(sys.modules.__setitem__, name, prior)
        export, publisher = prepare(self.root, self._source_helpers())
        run = cast(Callable[..., dict[str, object]], getattr(PRODUCER, "run_command"))
        environment = cast(Callable[..., dict[str, str]], getattr(PRODUCER, "isolated_environment"))(os.environ)
        options = {"cwd": self.root, "environment": environment, "work": self.root,
                   "publisher": publisher, "guardian_path": export / "scripts/propose_native_wheels.py"}
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(PRODUCER.sys, "stdout", output), mock.patch.object(PRODUCER.sys, "stderr", errors):
            positive = run([sys.executable, "-I", "-c", "print('real supervisor fixture')"], label="positive", timeout=15, **options)
        self.assertEqual(positive["returncode"], 0)
        self.assertIn("real supervisor fixture", output.getvalue())
        with mock.patch.object(PRODUCER.sys, "stdout", io.StringIO()), mock.patch.object(PRODUCER.sys, "stderr", io.StringIO()):
            with self.assertRaisesRegex(ERROR, "bound|bounded"):
                run([sys.executable, "-I", "-c", "import sys; sys.stdout.buffer.write(b'x'*2097152); sys.stdout.flush()"], label="overflow", timeout=15, **options)
        pid_file = self.root / "owned-descendant.pid"
        child_code = (
            "import subprocess,sys,time; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(60)']); "
            "Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
        )
        started = time.monotonic()
        with mock.patch.object(PRODUCER.sys, "stdout", io.StringIO()), mock.patch.object(PRODUCER.sys, "stderr", io.StringIO()):
            with self.assertRaisesRegex(ERROR, "timed out"):
                run([sys.executable, "-I", "-c", child_code, str(pid_file)], label="timeout", timeout=2, **options)
        self.assertLess(time.monotonic() - started, 18)
        self.assertTrue(pid_file.is_file(), "child must actually create a descendant before timeout")
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 10
        while True:
            if os.name == "nt":
                result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, timeout=5, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                alive = f'"{pid}"'.encode() in result.stdout
            else:
                result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, timeout=5, check=False)
                self.assertIn(result.returncode, (0, 1), result.stderr)
                state = result.stdout.strip()
                alive = bool(state) and not state.startswith(b"Z")
            if not alive:
                break
            self.assertLess(time.monotonic(), deadline, "owned command descendant remains running")
            time.sleep(0.05)

    def test_guardian_ready_directory_requires_successful_result_publication_return(self) -> None:
        guardian = cast(Callable[[Path], int], getattr(PRODUCER, "_guardian"))
        encode = cast(Callable[[object], bytes], getattr(PRODUCER, "json_bytes"))
        for publication_error in (None, OSError("modeled result publication close failure")):
            with self.subTest(publication_error=publication_error):
                work = self.root / ("success" if publication_error is None else "failure")
                work.mkdir()
                result_path = work / "result.json"
                ready_path = work / "result.ready"
                specification = work / "specification.json"
                specification.write_bytes(encode({"argv": ["modeled-command"], "cwd": str(work),
                                                   "environment": {}, "result": str(result_path)}))
                events: list[str] = []

                def publish(path: Path, payload: bytes) -> None:
                    self.assertEqual(path, result_path)
                    self.assertFalse(ready_path.exists())
                    with path.open("xb") as stream:
                        descriptor = stream.fileno()
                        stream.write(payload)
                        stream.flush()
                        os.fsync(descriptor)
                        events.append("result-visible")
                        self.assertFalse(ready_path.exists())
                    with self.assertRaises(OSError) as closed:
                        os.fstat(descriptor)
                    self.assertEqual(closed.exception.errno, errno.EBADF)
                    events.append("result-closed")
                    if publication_error is not None:
                        raise publication_error
                    events.append("publisher-returning")

                with mock.patch.object(PRODUCER, "publish_bytes", side_effect=publish), \
                     mock.patch.object(PRODUCER.subprocess, "run", return_value=subprocess.CompletedProcess(["modeled-command"], 0)), \
                     mock.patch.object(PRODUCER, "_windows_guard_job", return_value=object()), \
                     mock.patch.object(PRODUCER.os, "read", return_value=b""), \
                     mock.patch.object(PRODUCER.os, "killpg", create=True) as signal_group:
                    if publication_error is None:
                        self.assertEqual(guardian(specification), 2)
                        self.assertTrue(ready_path.is_dir())
                        self.assertEqual(events, ["result-visible", "result-closed", "publisher-returning"])
                    else:
                        with self.assertRaises(OSError) as caught:
                            guardian(specification)
                        self.assertIs(caught.exception, publication_error)
                        self.assertFalse(ready_path.exists())
                        signal_group.assert_not_called()
                self.assertEqual(json.loads(result_path.read_bytes()), {"returncode": 0, "error": None})

    def test_actual_guardian_readiness_defers_result_reads_and_preserves_fatal_failures(self) -> None:
        prepare = cast(Callable[..., tuple[Path, Callable[[Path, bytes], None]]], getattr(PRODUCER, "prepare_snapshot"))
        name = "_gm2godot_native_proposal_snapshot_anchor"
        prior_family = {key: value for key, value in sys.modules.items()
                        if key == name or key.startswith(name + "__")}

        def restore_module_family() -> None:
            for key in tuple(sys.modules):
                if key == name or key.startswith(name + "__"):
                    sys.modules.pop(key, None)
            sys.modules.update(prior_family)

        self.addCleanup(restore_module_family)
        for key in prior_family:
            sys.modules.pop(key, None)
        export, publisher = prepare(self.root, self._source_helpers())
        fixture = self.root / "readiness-guardian.py"
        fixture.write_text(textwrap.dedent(f"""
            import importlib.util, os, sys
            from pathlib import Path
            source = Path({str(export / 'scripts/propose_native_wheels.py')!r})
            specification = importlib.util.spec_from_file_location('_readiness_fixture', source)
            if specification is None or specification.loader is None:
                raise RuntimeError('exact fixture producer unavailable')
            module = importlib.util.module_from_spec(specification)
            sys.modules[specification.name] = module
            specification.loader.exec_module(module)
            mode = os.environ['GM2GODOT_READY_FIXTURE']
            def publish(path, payload):
                # A controlled publisher in a real guardian/process. This is
                # file-visibility evidence, not native NT sharing-code evidence.
                with path.open('xb') as stream:
                    split = len(payload) // 2 if mode == 'partial' else len(payload)
                    stream.write(payload[:split])
                    stream.flush()
                    os.fsync(stream.fileno())
                    path.with_name('result.visible').mkdir()
                    if mode == 'partial':
                        if os.read(0, 1) != b'r':
                            raise RuntimeError('fixture release missing')
                        stream.write(payload[split:])
                        stream.flush()
                        os.fsync(stream.fileno())
                if mode == 'withhold':
                    os.read(0, 1)
                    raise RuntimeError('fixture must be stopped before return')
                if mode == 'missing':
                    path.unlink()
            module.publish_bytes = publish
            raise SystemExit(module._guardian(Path(sys.argv[2])))
        """), encoding="utf-8")
        run = cast(Callable[..., dict[str, object]], getattr(PRODUCER, "run_command"))
        actual_read = cast(Callable[[Path, int], bytes], getattr(PRODUCER, "read_regular"))
        actual_popen = cast(Callable[..., subprocess.Popen[bytes]], subprocess.Popen)
        actual_sleep = time.sleep
        environment = cast(Callable[..., dict[str, str]], getattr(PRODUCER, "isolated_environment"))(os.environ)
        result_size = len(cast(Callable[[object], bytes], getattr(PRODUCER, "json_bytes"))({"returncode": 0, "error": None}))
        for mode in ("partial", "withhold", "missing"):
            with self.subTest(mode=mode):
                work = self.root / mode
                work.mkdir()
                acquired: list[subprocess.Popen[bytes]] = []
                command_roots: list[Path] = []
                result_reads: list[Path] = []
                released = False

                def launch(*arguments: object, **options: object) -> subprocess.Popen[bytes]:
                    process = actual_popen(*arguments, **options)
                    acquired.append(process)
                    command_roots.append(Path(cast(list[str], arguments[0])[-1]).parent)
                    return process

                def progress(delay: float) -> None:
                    nonlocal released
                    if mode == "partial" and command_roots and not released:
                        command_root = command_roots[0]
                        if (command_root / "result.visible").is_dir():
                            self.assertFalse((command_root / "result.ready").exists())
                            self.assertEqual(result_reads, [])
                            self.assertGreater((command_root / "result.json").stat().st_size, 0)
                            self.assertLess((command_root / "result.json").stat().st_size, result_size)
                            pipe = acquired[0].stdin
                            if pipe is None:
                                self.fail("real guardian stdin ownership missing")
                            pipe.write(b"r")
                            pipe.flush()
                            released = True
                    actual_sleep(delay)

                def read(path: Path, maximum: int = 1_048_576) -> bytes:
                    if path.name == "result.json":
                        result_reads.append(path)
                        self.assertTrue(path.with_name("result.ready").is_dir())
                    return actual_read(path, maximum)

                started = time.monotonic()
                with mock.patch.object(PRODUCER.subprocess, "Popen", side_effect=launch), \
                     mock.patch.object(PRODUCER.time, "sleep", side_effect=progress), \
                     mock.patch.object(PRODUCER, "read_regular", side_effect=read), \
                     mock.patch.object(PRODUCER.sys, "stdout", io.StringIO()), \
                     mock.patch.object(PRODUCER.sys, "stderr", io.StringIO()):
                    options = {"cwd": work, "environment": {**environment, "GM2GODOT_READY_FIXTURE": mode},
                               "work": work, "publisher": publisher, "guardian_path": fixture}
                    command = [sys.executable, "-I", "-c", "print('actual readiness fixture child')"]
                    if mode == "partial":
                        result = run(command, label="partial-before-ready", timeout=15, **options)
                        self.assertEqual(result["returncode"], 0)
                    elif mode == "withhold":
                        with self.assertRaisesRegex(ERROR, "timed out"):
                            run(command, label="result-without-ready", timeout=2, **options)
                    else:
                        with self.assertRaises(FileNotFoundError):
                            run(command, label="missing-after-ready", timeout=15, **options)
                self.assertEqual(len(acquired), 1)
                self.assertIsNotNone(acquired[0].returncode)
                pipe = acquired[0].stdin
                self.assertIsNotNone(pipe)
                if pipe is not None:
                    self.assertTrue(pipe.closed)
                self.assertTrue((command_roots[0] / "result.visible").is_dir())
                self.assertEqual(len(result_reads), 0 if mode == "withhold" else 1)
                if mode == "partial":
                    self.assertTrue(released)
                elif mode == "withhold":
                    self.assertLess(time.monotonic() - started, 18)
                    self.assertFalse((command_roots[0] / "result.ready").exists())
                    self.assertEqual(json.loads((command_roots[0] / "result.json").read_bytes()),
                                     {"returncode": 0, "error": None})

    def test_actual_offline_fixture_hash_install_rejects_tampering_and_direct_url(self) -> None:
        wheel = self._wheel()
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("sample_pkg-1.0.dist-info/RECORD",
                "sample_pkg/__init__.py,,\nsample_pkg-1.0.dist-info/METADATA,,\nsample_pkg-1.0.dist-info/WHEEL,,\nsample_pkg-1.0.dist-info/RECORD,,\n")
        original = wheel.read_bytes()
        requirement = self.root / "fixture.wheels.lock"
        requirement.write_text(f"sample-pkg==1.0 --hash=sha256:{hashlib.sha256(original).hexdigest()}\n")
        environment = cast(Callable[..., dict[str, str]], getattr(PRODUCER, "isolated_environment"))(os.environ)

        def command(argv: list[str], expected: int = 0) -> bytes:
            result = subprocess.run(argv, cwd=self.root, env=environment, capture_output=True, timeout=120, check=False)
            if expected == 0:
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace")[-4096:])
            else:
                self.assertNotEqual(result.returncode, 0)
            self.assertLess(len(result.stdout) + len(result.stderr), 1_048_576)
            return result.stdout

        def new_python(name: str) -> str:
            root = self.root / name
            command([sys.executable, "-I", "-m", "venv", str(root)])
            return str(root / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))

        flags = ["--isolated", "--disable-pip-version-check", "--no-input"]
        hashed = new_python("hashed-fixture")
        command([hashed, "-I", "-m", "pip", *flags, "install", "--require-hashes", "--no-index", "--find-links", str(self.root), "--only-binary=:all:", "--no-cache-dir", "-r", str(requirement)])
        report = json.loads(command([hashed, "-I", "-m", "pip", *flags, "inspect", "--local"]))
        installed = cast(list[dict[str, object]], report["installed"])
        fixture = next(row for row in installed if cast(dict[str, str], row["metadata"])["name"] == "sample-pkg")
        self.assertNotIn("direct_url", fixture)
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("sample_pkg/tampered.py", b"# byte mutation\n")
        tampered = new_python("tampered-fixture")
        command([tampered, "-I", "-m", "pip", *flags, "install", "--require-hashes", "--no-index", "--find-links", str(self.root), "--only-binary=:all:", "--no-cache-dir", "-r", str(requirement)], expected=1)
        wheel.write_bytes(original)
        direct = new_python("direct-fixture")
        command([direct, "-I", "-m", "pip", *flags, "install", "--no-index", "--no-cache-dir", str(wheel)])
        direct_report = json.loads(command([direct, "-I", "-m", "pip", *flags, "inspect", "--local"]))
        rows = cast(list[dict[str, object]], direct_report["installed"])
        direct_fixture = next(row for row in rows if cast(dict[str, str], row["metadata"])["name"] == "sample-pkg")
        self.assertIn("direct_url", direct_fixture)
        specification = importlib.util.spec_from_file_location("_fixture_dependency_verifier", SOURCE_ROOT / "scripts/verify_dependency_environment.py")
        self.assertIsNotNone(specification)
        if specification is None or specification.loader is None:
            self.fail("current exact-sibling verifier unavailable")
        verifier = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = verifier
        self.addCleanup(sys.modules.pop, specification.name, None)
        specification.loader.exec_module(verifier)
        pins = {cast(dict[str, str], row["metadata"])["name"].lower().replace("_", "-"): cast(dict[str, str], row["metadata"])["version"] for row in rows}
        policy_type = cast(Callable[..., object], getattr(verifier, "ConstraintPolicy"))
        expected_type = cast(Callable[..., object], getattr(verifier, "parse_expected_environment"))
        analyze = cast(Callable[..., object], getattr(verifier, "analyze_inspect_report"))
        observed = cast(dict[str, str], direct_report["environment"])
        policy = policy_type(self.root / "generic-fixture-policy.lock", "fixture-only", pins)
        expected = expected_type(python_full_version=observed["python_full_version"], sys_platform=observed["sys_platform"], platform_machine=observed["platform_machine"], pip_version=direct_report["pip_version"])
        analysis = analyze(direct_report, policy=policy, expected_environment=expected, mode="complete", required_names=())
        findings = cast(tuple[object, ...], getattr(analysis, "findings"))
        self.assertTrue(any("direct-url" in str(getattr(finding, "code")) for finding in findings))


if __name__ == "__main__":
    unittest.main()
