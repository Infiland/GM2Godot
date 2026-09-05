# pyright: reportPrivateUsage=false
from __future__ import annotations

import inspect
import ntpath
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import cast
from unittest import mock

from scripts import _anchored_output as anchored

PAYLOAD = b'{"status":"verified"}\n'


def _entry_snapshot(path: Path) -> tuple[tuple[int, ...], object]:
    value = path.lstat()
    metadata = (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if path.is_symlink():
        content: object = os.readlink(path)
    elif path.is_file():
        content = path.read_bytes()
    elif path.is_dir():
        content = tuple(sorted(os.listdir(path)))
    else:
        content = None
    return metadata, content


class AnchoredReceiptContractTests(unittest.TestCase):
    def test_private_receipt_entry_points_require_caller_held_owners(self) -> None:
        posix = anchored._posix_receipt_module()
        windows = anchored._windows_receipt_module()
        required_parameters = (
            (anchored._publish_posix_receipt_bytes, "outer_lease"),
            (anchored._publish_windows_receipt_bytes, "outer_lease"),
            (anchored._read_exact_receipt, "descriptor_lease"),
            (posix._publish_posix_receipt_bytes, "publication_lease"),
            (posix._sync_posix_public_descriptor, "descriptor_lease"),
            (windows.read_windows_receipt, "publication_lease"),
            (windows.publish_windows_receipt, "publication_lease"),
        )

        for function, parameter_name in required_parameters:
            with self.subTest(function=function.__name__):
                parameter = inspect.signature(function).parameters[parameter_name]
                self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_windows_invalid_leaves_are_path_invalid_before_native_parent_open(self) -> None:
        anchored._windows_receipt_module()
        invalid_leaves = (
            "receipt.json:stream",
            "receipt.",
            "receipt ",
            "NUL.txt",
            "NUL .txt",
            "cOm¹.log",
            "lPt9.backup",
            "bad?name",
            "bad<name",
            "bad>name",
            'bad"name',
            "bad|name",
            "bad*name",
            "bad\x01name",
            "\ud800",
        )
        for leaf in invalid_leaves:
            with self.subTest(leaf=repr(leaf)):
                output = Path("receipts") / leaf
                lease = anchored._OutputParentBindingLease()
                with (
                    mock.patch.object(anchored.os, "name", "nt"),
                    mock.patch.object(anchored, "_open_rooted_windows_parent") as native_open,
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored.open_rooted_output_parent(output, lease)
                self.assertEqual(raised.exception.code, "path-invalid")
                native_open.assert_not_called()
                self.assertIsNone(lease.binding)

    def test_windows_invalid_ancestor_is_rejected_before_any_parent_mutation(self) -> None:
        anchored._windows_receipt_module()
        for invalid_component in ("bad?", "NUL"):
            with self.subTest(component=invalid_component), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                missing = root / "valid-missing"
                output = missing / invalid_component / "receipt.json"
                lease = anchored._OutputParentBindingLease()
                with (
                    mock.patch.object(anchored.os, "name", "nt"),
                    mock.patch.object(
                        anchored,
                        "_open_rooted_windows_parent",
                        side_effect=AssertionError("native Windows parent open reached"),
                    ) as native_open,
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored.open_rooted_output_parent(output, lease)

                self.assertEqual(raised.exception.code, "path-invalid")
                native_open.assert_not_called()
                self.assertFalse(missing.exists())
                self.assertIsNone(lease.binding)

    def test_windows_device_namespace_roots_are_path_invalid_before_native_parent_open(self) -> None:
        anchored._windows_receipt_module()
        invalid_paths = (
            PureWindowsPath(r"\\.\C:\parent\receipt.json"),
            PureWindowsPath(r"\\?\GLOBALROOT\Device\HarddiskVolume1\parent\receipt.json"),
        )
        for output in invalid_paths:
            with self.subTest(path=str(output)):
                lease = anchored._OutputParentBindingLease()
                with (
                    mock.patch.object(anchored.os, "name", "nt"),
                    mock.patch.object(anchored.os, "path", ntpath),
                    mock.patch.object(anchored, "Path", PureWindowsPath),
                    mock.patch.object(anchored, "_open_rooted_windows_parent") as native_open,
                    self.assertRaises(anchored.AnchoredOutputError) as raised,
                ):
                    anchored.open_rooted_output_parent(cast(Path, output), lease)

                self.assertEqual(raised.exception.code, "path-invalid")
                native_open.assert_not_called()
                self.assertIsNone(lease.binding)

    def test_posix_helper_loader_failure_preserves_primary_and_closes_binding(self) -> None:
        primary = KeyboardInterrupt("loader failure")

        class Binding:
            closed = False

            def close(self) -> tuple[BaseException, ...]:
                self.closed = True
                return (OSError("close failure"),)

        binding = Binding()
        owner = anchored._OutputParentBindingLease()
        owner.binding = cast(anchored.OutputParentBinding, binding)
        with (
            mock.patch.object(anchored, "_posix_receipt_module", side_effect=primary),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored._publish_posix_receipt_bytes(
                Path("parent/receipt.json"),
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                owner,
            )
        self.assertIs(raised.exception, primary)
        self.assertTrue(binding.closed)
        self.assertIn("close failure", "\n".join(getattr(primary, "__notes__", ())))

    def test_windows_helper_loader_failure_preserves_primary_and_closes_binding(self) -> None:
        primary = KeyboardInterrupt("loader failure")

        class Binding:
            parent = Path("parent")
            leaf = "receipt.json"
            windows_entries = ((Path("parent"), (1, 2), 3),)
            windows_api = object()
            closed = False

            def stat(self, _name: str) -> os.stat_result:
                raise FileNotFoundError

            def close(self) -> list[BaseException]:
                self.closed = True
                return []

        binding = Binding()
        owner = anchored._OutputParentBindingLease()
        owner.binding = cast(anchored.OutputParentBinding, binding)
        with (
            mock.patch.object(anchored, "_windows_receipt_module", side_effect=primary),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            anchored._publish_windows_receipt_bytes(
                Path("parent/receipt.json"),
                PAYLOAD,
                cast(anchored.OutputParentBinding, binding),
                owner,
            )
        self.assertIs(raised.exception, primary)
        self.assertTrue(binding.closed)

    def test_public_cleanup_return_gap_preserves_active_primary(self) -> None:
        primary = OSError("acquisition failure")
        cleanup_interrupt = KeyboardInterrupt("cleanup returned before assignment")

        class Binding:
            close_calls = 0
            descriptor_leases: tuple[object, ...] = ()

            @property
            def is_closed(self) -> bool:
                return self.close_calls > 0

            def close(self) -> tuple[BaseException, ...]:
                self.close_calls += 1
                return ()

        binding = Binding()

        def fail_after_retaining_binding(
            _path: Path,
            lease: anchored._OutputParentBindingLease,
        ) -> anchored.OutputParentBinding:
            lease.binding = cast(anchored.OutputParentBinding, binding)
            raise primary

        triggered = False

        real_close = anchored._OutputParentBindingLease.close

        def close_then_interrupt(lease: anchored._OutputParentBindingLease) -> tuple[BaseException, ...]:
            nonlocal triggered
            real_close(lease)
            triggered = True
            raise cleanup_interrupt

        with (
            mock.patch.object(
                anchored,
                "open_rooted_output_parent",
                side_effect=fail_after_retaining_binding,
            ),
            mock.patch.object(
                anchored._OutputParentBindingLease,
                "close",
                new=close_then_interrupt,
            ),
            self.assertRaises(OSError) as raised,
        ):
            anchored.publish_identical_receipt_bytes(Path("receipt.json"), PAYLOAD)

        self.assertTrue(triggered)
        self.assertIs(raised.exception, primary)
        self.assertEqual(binding.close_calls, 1)
        self.assertIn(str(cleanup_interrupt), "\n".join(getattr(primary, "__notes__", ())))

    def test_verifier_translation_is_stable_in_both_import_orders(self) -> None:
        for facade_first in (False, True):
            with self.subTest(facade_first=facade_first):
                if facade_first:
                    imports = """
from scripts import _anchored_output as direct
direct_helper = direct._posix_receipt_module()
from scripts import verify_dependency_environment as verifier
verifier_helper = verifier._ANCHORED_OUTPUT._posix_receipt_module()
"""
                else:
                    imports = """
from scripts import verify_dependency_environment as verifier
verifier_helper = verifier._ANCHORED_OUTPUT._posix_receipt_module()
from scripts import _anchored_output as direct
direct_helper = direct._posix_receipt_module()
"""
                source = (
                    imports
                    + """
from pathlib import Path
assert direct_helper is not verifier_helper
assert direct_helper.AnchoredOutputError is direct.AnchoredOutputError
assert verifier_helper.AnchoredOutputError is verifier._ANCHORED_OUTPUT.AnchoredOutputError
assert direct_helper.AnchoredOutputError is not verifier_helper.AnchoredOutputError
error_type = verifier_helper.AnchoredOutputError
assert error_type is verifier._ANCHORED_OUTPUT.AnchoredOutputError
def fail(_path, _payload):
    raise error_type('induced-helper-failure', 'induced')
verifier._PUBLISH_IDENTICAL_RECEIPT_BYTES = fail
try:
    verifier.atomic_write_receipt(Path('unused.json'), {'status': 'failed'})
except verifier.ReceiptOutputError as error:
    assert error.code == 'induced-helper-failure'
else:
    raise AssertionError('translation did not occur')
"""
                )
                result = subprocess.run(
                    [sys.executable, "-c", source],
                    cwd=Path(__file__).resolve().parents[1],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_publication_does_not_load_receipt_helpers(self) -> None:
        source = """
from pathlib import Path
import tempfile
from scripts import _anchored_output as anchored
assert anchored._posix_receipt_cache is None and anchored._windows_receipt_cache is None
with tempfile.TemporaryDirectory(dir='.') as raw:
    anchored.publish_new_bytes(Path(raw).resolve() / 'snapshot.json', b'bytes')
assert anchored._posix_receipt_cache is None and anchored._windows_receipt_cache is None
"""
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_exact_receipt_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory).resolve()
            previous = Path.cwd()
            os.chdir(root)
            try:
                output = root / "receipt.json"
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
                before = output.stat()
                metadata = (before.st_ino, before.st_mode, before.st_mtime_ns, before.st_ctime_ns)
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
                after = output.stat()
                self.assertEqual(
                    (after.st_ino, after.st_mode, after.st_mtime_ns, after.st_ctime_ns),
                    metadata,
                )
                self.assertEqual(output.read_bytes(), PAYLOAD)
            finally:
                os.chdir(previous)

    def test_noncanonical_existing_targets_fail_untouched(self) -> None:
        def wrong_mode(path: Path) -> None:
            path.write_bytes(PAYLOAD)
            path.chmod(0o644)

        def hardlink(path: Path) -> None:
            source = path.with_name("source")
            source.write_bytes(PAYLOAD)
            source.chmod(0o600)
            os.link(source, path)

        creators: dict[str, Callable[[Path], None]] = {
            "wrong-mode": wrong_mode,
            "directory": lambda path: path.mkdir(),
            "symlink": lambda path: path.symlink_to("missing-target"),
            "fifo": os.mkfifo,
            "hardlink": hardlink,
        }
        for label, create in creators.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw_directory:
                root = Path(raw_directory).resolve()
                output = root / "receipt.json"
                create(output)
                before = _entry_snapshot(output)
                source = output.with_name("source")
                source_before = _entry_snapshot(source) if source.exists() else None
                linked_before = source_before is not None and os.path.samefile(source, output)
                previous = Path.cwd()
                os.chdir(root)
                try:
                    with self.assertRaises(anchored.AnchoredOutputError) as raised:
                        anchored.publish_identical_receipt_bytes(output, PAYLOAD)
                finally:
                    os.chdir(previous)
                self.assertEqual(raised.exception.code, "output-existing-invalid")
                self.assertEqual(_entry_snapshot(output), before)
                if source_before is not None:
                    self.assertEqual(_entry_snapshot(source), source_before)
                    self.assertEqual(os.path.samefile(source, output), linked_before)

    def test_missing_nested_ancestors_are_created_with_canonical_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory).resolve()
            output = root / "one" / "two" / "receipt.json"
            previous = Path.cwd()
            os.chdir(root)
            try:
                anchored.publish_identical_receipt_bytes(output, PAYLOAD)
            finally:
                os.chdir(previous)
            self.assertEqual(output.read_bytes(), PAYLOAD)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_existing_different_receipt_is_rejected_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory).resolve()
            previous = Path.cwd()
            os.chdir(root)
            try:
                output = root / "receipt.json"
                output.write_bytes(b"different\n")
                output.chmod(0o600)
                before = _entry_snapshot(output)
                with self.assertRaises(anchored.AnchoredOutputError) as raised:
                    anchored.publish_identical_receipt_bytes(output, PAYLOAD)
                self.assertEqual(raised.exception.code, "output-different")
                self.assertEqual(_entry_snapshot(output), before)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
