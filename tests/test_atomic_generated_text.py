# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import unittest
from contextlib import ExitStack
from typing import Callable
from unittest.mock import patch

from src.conversion import atomic_generated_text as atomic_generated_text_module
from src.conversion.atomic_generated_text import (
    atomic_write_confined_generated_text,
)
from src.conversion.asset_registry import (
    ASSET_REGISTRY_RELATIVE_PATH,
    AssetRegistryConverter,
)
from src.conversion.included_file_registry import (
    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
    write_included_file_registry,
)


class TestAtomicGeneratedText(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()

    def tearDown(self) -> None:
        if os.name == "nt":
            for directory, _children, filenames in os.walk(self.root):
                for filename in filenames:
                    path = os.path.join(directory, filename)
                    try:
                        if stat.S_ISREG(os.lstat(path).st_mode):
                            os.chmod(path, stat.S_IWRITE)
                    except OSError:
                        pass
        shutil.rmtree(self.root)

    @staticmethod
    def _write(path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as output_file:
            output_file.write(content)

    @staticmethod
    def _snapshot(path: str) -> tuple[tuple[int, int], bytes, int]:
        path_stat = os.lstat(path)
        with open(path, "rb") as input_file:
            content = input_file.read()
        return (
            (path_stat.st_dev, path_stat.st_ino),
            content,
            stat.S_IMODE(path_stat.st_mode),
        )

    def _assert_snapshot(
        self,
        path: str,
        expected: tuple[tuple[int, int], bytes, int],
    ) -> None:
        identity, content, mode = self._snapshot(path)
        self.assertEqual(identity, expected[0])
        self.assertEqual(content, expected[1])
        self.assertEqual(
            bool(mode & stat.S_IWRITE),
            bool(expected[2] & stat.S_IWRITE),
        )

    def _transaction_path(self, label: str) -> str:
        return os.path.join(self.root, label, "gm2godot", "shared-output.txt")

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_readonly_transaction_replaces_shared_output(self) -> None:
        output_path = self._transaction_path("success")
        self._write(output_path, "previous output\n")
        os.chmod(output_path, stat.S_IREAD)
        previous = self._snapshot(output_path)

        atomic_write_confined_generated_text(
            output_path,
            "replacement output\n",
            confinement_root=os.path.join(self.root, "success"),
        )

        current = self._snapshot(output_path)
        self.assertNotEqual(current[0], previous[0])
        self.assertEqual(current[1], b"replacement output\n")
        self.assertFalse(current[2] & stat.S_IWRITE)
        self.assertEqual(
            os.listdir(os.path.dirname(output_path)),
            [os.path.basename(output_path)],
        )

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_readonly_transaction_failures_restore_original(self) -> None:
        failure_cases = (
            "stage-sync",
            "stage-mode",
            "quarantine",
            "publish",
            "late-validation",
            "previous-cleanup",
        )
        for failure_case in failure_cases:
            with self.subTest(failure_case=failure_case):
                output_path = self._transaction_path(failure_case)
                self._write(output_path, "previous output\n")
                os.chmod(output_path, stat.S_IREAD)
                previous = self._snapshot(output_path)
                validation_calls = 0

                def validator() -> None:
                    nonlocal validation_calls
                    validation_calls += 1
                    if (
                        failure_case == "late-validation"
                        and validation_calls == 2
                    ):
                        raise RuntimeError("late validation failed")

                def fail_rename(
                    operation: str,
                    _source: str,
                    _destination: str,
                ) -> None:
                    if operation == failure_case:
                        raise OSError(f"{failure_case} failed")

                def fail_delete(operation: str, _path: str) -> None:
                    if (
                        failure_case == "previous-cleanup"
                        and operation == "previous-output"
                    ):
                        raise OSError("previous cleanup failed")

                with ExitStack() as stack:
                    if failure_case == "stage-sync":
                        stack.enter_context(
                            patch.object(
                                atomic_generated_text_module,
                                "_sync_generated_asset_stage",
                                side_effect=OSError("stage sync failed"),
                            )
                        )
                    elif failure_case == "stage-mode":
                        stack.enter_context(
                            patch.object(
                                atomic_generated_text_module,
                                "_before_asset_readonly_transaction_mode",
                                side_effect=OSError("stage mode failed"),
                            )
                        )
                    elif failure_case in {"quarantine", "publish"}:
                        stack.enter_context(
                            patch.object(
                                atomic_generated_text_module,
                                "_before_asset_readonly_transaction_rename",
                                side_effect=fail_rename,
                            )
                        )
                    elif failure_case == "previous-cleanup":
                        stack.enter_context(
                            patch.object(
                                atomic_generated_text_module,
                                "_before_asset_readonly_transaction_delete",
                                side_effect=fail_delete,
                            )
                        )
                    with self.assertRaises((OSError, RuntimeError)):
                        atomic_write_confined_generated_text(
                            output_path,
                            "replacement output\n",
                            confinement_root=os.path.join(
                                self.root,
                                failure_case,
                            ),
                            publication_validator=validator,
                        )

                self._assert_snapshot(output_path, previous)
                self.assertEqual(
                    os.listdir(os.path.dirname(output_path)),
                    [os.path.basename(output_path)],
                )

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_readonly_transaction_preserves_unknown_publish_destination(
        self,
    ) -> None:
        output_path = self._transaction_path("unknown-publish")
        self._write(output_path, "previous output\n")
        os.chmod(output_path, stat.S_IREAD)
        previous = self._snapshot(output_path)
        unknown_snapshot: tuple[tuple[int, int], bytes, int] | None = None

        def install_unknown_destination(
            operation: str,
            _source: str,
            destination: str,
        ) -> None:
            nonlocal unknown_snapshot
            if operation != "publish" or unknown_snapshot is not None:
                return
            self._write(destination, "unknown destination\n")
            os.chmod(destination, stat.S_IREAD)
            unknown_snapshot = self._snapshot(destination)

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    atomic_generated_text_module,
                    "_before_asset_readonly_transaction_rename",
                    side_effect=install_unknown_destination,
                )
            )
            with self.assertRaises(OSError) as raised:
                atomic_write_confined_generated_text(
                    output_path,
                    "replacement output\n",
                    confinement_root=os.path.join(
                        self.root,
                        "unknown-publish",
                    ),
                )

        self.assertIsNotNone(unknown_snapshot)
        assert unknown_snapshot is not None
        self._assert_snapshot(output_path, unknown_snapshot)
        backup_names = [
            name
            for name in os.listdir(os.path.dirname(output_path))
            if name.endswith(".backup")
        ]
        self.assertEqual(len(backup_names), 1)
        backup_path = os.path.join(os.path.dirname(output_path), backup_names[0])
        self._assert_snapshot(backup_path, previous)
        self.assertIn(
            "recover",
            " ".join(getattr(raised.exception, "__notes__", ())).lower(),
        )
        self.assertFalse(
            any(
                name.endswith((".tmp", ".rollback"))
                for name in os.listdir(os.path.dirname(output_path))
            )
        )

    @unittest.skipIf(os.name == "nt", "POSIX exact-mode regression")
    def test_posix_paths_preserve_exact_readonly_mode(self) -> None:
        for force_fallback in (False, True):
            with self.subTest(force_fallback=force_fallback):
                label = "posix-fallback" if force_fallback else "posix-descriptor"
                output_path = self._transaction_path(label)
                self._write(output_path, "previous output\n")
                os.chmod(output_path, 0o450)
                stack = ExitStack()
                with stack:
                    if force_fallback:
                        stack.enter_context(
                            patch.object(
                                atomic_generated_text_module,
                                "_confined_asset_output_supported",
                                return_value=False,
                            )
                        )
                    atomic_write_confined_generated_text(
                        output_path,
                        "replacement output\n",
                        confinement_root=os.path.join(self.root, label),
                    )
                self.assertEqual(
                    stat.S_IMODE(os.lstat(output_path).st_mode),
                    0o450,
                )

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_readonly_hardlink_preserves_external_alias(
        self,
    ) -> None:
        project_path = os.path.join(self.root, "native-hardlink")
        output_path = os.path.join(
            project_path,
            "gm2godot",
            "shared-output.txt",
        )
        external_path = os.path.join(project_path, "external-output.txt")
        self._write(external_path, "external previous output\n")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        os.link(external_path, output_path)
        os.chmod(external_path, stat.S_IREAD)
        external_snapshot = self._snapshot(external_path)

        atomic_write_confined_generated_text(
            output_path,
            "replacement output\n",
            confinement_root=project_path,
        )

        self._assert_snapshot(external_path, external_snapshot)
        output_snapshot = self._snapshot(output_path)
        self.assertNotEqual(output_snapshot[0], external_snapshot[0])
        self.assertEqual(output_snapshot[1], b"replacement output\n")
        self.assertFalse(output_snapshot[2] & stat.S_IWRITE)
        self.assertEqual(
            os.listdir(os.path.dirname(output_path)),
            [os.path.basename(output_path)],
        )

    @unittest.skipUnless(os.name == "nt", "requires native Windows semantics")
    def test_native_windows_shared_registry_callers_replace_readonly_outputs(
        self,
    ) -> None:
        project_path = os.path.join(self.root, "native-callers")
        os.makedirs(project_path)
        registry_paths_and_writers: tuple[
            tuple[str, Callable[[], object]],
            ...,
        ] = (
            (
                os.path.join(project_path, ASSET_REGISTRY_RELATIVE_PATH),
                lambda: AssetRegistryConverter._atomic_write_text(
                    os.path.join(project_path, ASSET_REGISTRY_RELATIVE_PATH),
                    "replacement asset registry\n",
                ),
            ),
            (
                os.path.join(
                    project_path,
                    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
                ),
                lambda: write_included_file_registry(project_path, (), ()),
            ),
        )
        for registry_path, writer in registry_paths_and_writers:
            with self.subTest(registry_path=registry_path):
                self._write(registry_path, "previous registry\n")
                os.chmod(registry_path, stat.S_IREAD)
                previous_identity = self._snapshot(registry_path)[0]

                writer()

                current = self._snapshot(registry_path)
                self.assertNotEqual(current[0], previous_identity)
                self.assertFalse(current[2] & stat.S_IWRITE)
                self.assertNotEqual(current[1], b"previous registry\n")
                self.assertFalse(
                    any(
                        name.startswith(f".{os.path.basename(registry_path)}.")
                        for name in os.listdir(os.path.dirname(registry_path))
                    )
                )


if __name__ == "__main__":
    unittest.main()
